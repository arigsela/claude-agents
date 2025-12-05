"""Playlist retrieval tools."""

import logging
import re
from typing import Annotated

import yt_dlp
from mcp.types import TextContent
from pydantic import Field
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    NoTranscriptFound,
    TranscriptsDisabled,
    VideoUnavailable,
)

logger = logging.getLogger(__name__)

# Create API instance (v1.x API)
_api = YouTubeTranscriptApi()


def extract_playlist_id(url_or_id: str) -> str:
    """Extract playlist ID from YouTube URL or return as-is if already an ID.

    Supports:
    - https://www.youtube.com/playlist?list=PLxxxxxxx
    - https://www.youtube.com/watch?v=xxx&list=PLxxxxxxx
    - https://youtube.com/playlist?list=PLxxxxxxx
    - Direct playlist ID (starts with PL, UU, LL, etc.)
    """
    # URL patterns
    patterns = [
        r"[?&]list=([a-zA-Z0-9_-]+)",  # URL with list parameter
        r"^(PL[a-zA-Z0-9_-]+)$",  # Direct playlist ID (public)
        r"^(UU[a-zA-Z0-9_-]+)$",  # Uploads playlist
        r"^(LL[a-zA-Z0-9_-]+)$",  # Liked videos
        r"^(FL[a-zA-Z0-9_-]+)$",  # Favorites
        r"^(OL[a-zA-Z0-9_-]+)$",  # Other lists
    ]
    for pattern in patterns:
        match = re.search(pattern, url_or_id)
        if match:
            return match.group(1)
    raise ValueError(f"Could not extract playlist ID from: {url_or_id}")


def get_playlist_videos(playlist_id: str, max_videos: int = 50) -> list[dict]:
    """Extract video information from a playlist using yt-dlp.

    Returns list of dicts with: id, title, duration, channel
    """
    playlist_url = f"https://www.youtube.com/playlist?list={playlist_id}"

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,  # Don't download, just get metadata
        "playlistend": max_videos,
    }

    videos = []
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        result = ydl.extract_info(playlist_url, download=False)

        if not result:
            raise ValueError(f"Could not fetch playlist: {playlist_id}")

        playlist_title = result.get("title", "Unknown Playlist")
        entries = result.get("entries", [])

        for entry in entries:
            if entry:  # Some entries might be None (deleted videos)
                videos.append({
                    "id": entry.get("id"),
                    "title": entry.get("title", "Unknown"),
                    "duration": entry.get("duration", 0),
                    "channel": entry.get("channel", entry.get("uploader", "Unknown")),
                    "url": f"https://www.youtube.com/watch?v={entry.get('id')}",
                })

    return videos, playlist_title


def fetch_transcript_for_video(video_id: str, languages: list[str]) -> tuple[str, str, bool]:
    """Fetch transcript for a single video.

    Returns: (transcript_text, language, success)
    """
    try:
        # Try to list available transcripts
        transcript_list = _api.list(video_id)

        # Find best matching transcript
        selected = None
        for lang in languages:
            for t in transcript_list:
                if t.language_code == lang:
                    selected = t
                    break
            if selected:
                break

        # Use first available if no match
        if not selected and transcript_list:
            selected = transcript_list[0]

        if selected:
            segments = selected.fetch()
            text = " ".join(seg.text for seg in segments)
            return text, selected.language_code, True

        return "", "", False

    except (TranscriptsDisabled, NoTranscriptFound, VideoUnavailable) as e:
        logger.warning(f"Transcript unavailable for {video_id}: {e}")
        return "", "", False
    except Exception as e:
        logger.error(f"Error fetching transcript for {video_id}: {e}")
        return "", "", False


def register_playlist_tools(server, preferred_language: str):
    """Register playlist-related tools with the MCP server."""

    @server.tool(
        name="get_playlist_transcripts",
        description="""Fetch transcripts for all videos in a YouTube playlist.
        Returns combined transcripts with video separators.

        Accepts playlist URL or ID:
        - https://www.youtube.com/playlist?list=PLxxxxxxx
        - https://www.youtube.com/watch?v=xxx&list=PLxxxxxxx
        - PLxxxxxxx (direct playlist ID)

        Examples:
        - get_playlist_transcripts("https://youtube.com/playlist?list=PLrAXtmErZgOeiKm4sgNOknGvNjby9efdf")
        - get_playlist_transcripts("PLrAXtmErZgOeiKm4sgNOknGvNjby9efdf", max_videos=10)
        """,
    )
    async def get_playlist_transcripts(
        playlist_url_or_id: Annotated[
            str,
            Field(
                description="YouTube playlist URL or ID (e.g., 'PLxxxxxxx' or 'https://youtube.com/playlist?list=PLxxxxxxx')"
            ),
        ],
        max_videos: Annotated[
            int,
            Field(
                description="Maximum number of videos to process (default: 25, max: 100)",
                ge=1,
                le=100,
            ),
        ] = 25,
        language: Annotated[
            str | None,
            Field(description="Preferred language code (e.g., 'en', 'es')", default=None),
        ] = None,
    ) -> list[TextContent]:
        """Fetch transcripts for all videos in a playlist."""
        try:
            playlist_id = extract_playlist_id(playlist_url_or_id)
            lang = language or preferred_language
            logger.info(f"Fetching playlist: {playlist_id}, max_videos: {max_videos}")

            # Get video list from playlist
            try:
                videos, playlist_title = get_playlist_videos(playlist_id, max_videos)
            except Exception as e:
                logger.error(f"Error fetching playlist: {e}")
                return [TextContent(
                    type="text",
                    text=f"Error fetching playlist: {str(e)}"
                )]

            if not videos:
                return [TextContent(
                    type="text",
                    text=f"No videos found in playlist: {playlist_id}"
                )]

            logger.info(f"Found {len(videos)} videos in playlist '{playlist_title}'")

            # Fetch transcripts for each video
            results = []
            successful = 0
            failed = 0
            total_words = 0

            for i, video in enumerate(videos, 1):
                video_id = video["id"]
                video_title = video["title"]
                logger.info(f"Processing {i}/{len(videos)}: {video_title}")

                transcript, actual_lang, success = fetch_transcript_for_video(
                    video_id, [lang, "en"]
                )

                if success:
                    successful += 1
                    word_count = len(transcript.split())
                    total_words += word_count

                    # Format video section
                    duration = video.get("duration", 0)
                    duration_str = f"{duration // 60}:{duration % 60:02d}" if duration else "Unknown"

                    video_section = f"""
---

## {i}. {video_title}

**Video ID:** {video_id}
**Channel:** {video["channel"]}
**Duration:** {duration_str}
**Language:** {actual_lang}
**Words:** {word_count}
**URL:** {video["url"]}

### Transcript

{transcript}
"""
                    results.append(video_section)
                else:
                    failed += 1
                    results.append(f"""
---

## {i}. {video_title}

**Video ID:** {video_id}
**Status:** ⚠️ Transcript unavailable
**URL:** {video["url"]}
""")

            # Build header
            header = f"""# Playlist: {playlist_title}

**Playlist ID:** {playlist_id}
**Videos processed:** {len(videos)}
**Transcripts retrieved:** {successful}/{len(videos)}
**Failed:** {failed}
**Total words:** ~{total_words:,}

"""
            combined = header + "\n".join(results)

            return [TextContent(type="text", text=combined)]

        except ValueError as e:
            logger.error(f"Invalid playlist ID: {e}")
            return [TextContent(type="text", text=f"Error: {str(e)}")]
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            return [TextContent(type="text", text=f"Error: {str(e)}")]

    @server.tool(
        name="get_playlist_info",
        description="""Get information about a YouTube playlist without fetching transcripts.
        Returns list of videos with titles, durations, and channels.
        """,
    )
    async def get_playlist_info(
        playlist_url_or_id: Annotated[
            str,
            Field(description="YouTube playlist URL or ID"),
        ],
        max_videos: Annotated[
            int,
            Field(description="Maximum number of videos to list", ge=1, le=200),
        ] = 50,
    ) -> list[TextContent]:
        """Get playlist metadata without transcripts."""
        try:
            playlist_id = extract_playlist_id(playlist_url_or_id)
            logger.info(f"Fetching playlist info: {playlist_id}")

            videos, playlist_title = get_playlist_videos(playlist_id, max_videos)

            if not videos:
                return [TextContent(
                    type="text",
                    text=f"No videos found in playlist: {playlist_id}"
                )]

            # Calculate total duration
            total_seconds = sum(v.get("duration", 0) for v in videos)
            total_hours = total_seconds // 3600
            total_mins = (total_seconds % 3600) // 60

            # Build video list
            lines = [
                f"# Playlist: {playlist_title}\n",
                f"**Playlist ID:** {playlist_id}",
                f"**Videos:** {len(videos)}",
                f"**Total Duration:** {total_hours}h {total_mins}m\n",
                "## Videos\n",
            ]

            for i, video in enumerate(videos, 1):
                duration = video.get("duration", 0)
                duration_str = f"{duration // 60}:{duration % 60:02d}" if duration else "?"
                lines.append(
                    f"{i}. **{video['title']}** ({duration_str}) - {video['channel']}"
                )
                lines.append(f"   - ID: `{video['id']}`")

            return [TextContent(type="text", text="\n".join(lines))]

        except ValueError as e:
            logger.error(f"Invalid playlist ID: {e}")
            return [TextContent(type="text", text=f"Error: {str(e)}")]
        except Exception as e:
            logger.error(f"Error: {e}")
            return [TextContent(type="text", text=f"Error: {str(e)}")]

    logger.info("Registered playlist tools: get_playlist_transcripts, get_playlist_info")
