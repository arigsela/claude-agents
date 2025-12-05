"""Transcript retrieval tools."""

import logging
import re
from typing import Annotated

from mcp.types import TextContent
from pydantic import Field
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    NoTranscriptFound,
    TranscriptsDisabled,
    VideoUnavailable,
)

logger = logging.getLogger(__name__)

# Create API instance (new v1.x API)
_api = YouTubeTranscriptApi()


def extract_video_id(url_or_id: str) -> str:
    """Extract video ID from YouTube URL or return as-is if already an ID.

    Supports:
    - https://www.youtube.com/watch?v=VIDEO_ID
    - https://youtu.be/VIDEO_ID
    - https://youtube.com/embed/VIDEO_ID
    - https://www.youtube.com/v/VIDEO_ID
    - Direct VIDEO_ID (11 characters)
    """
    # Common YouTube URL patterns
    patterns = [
        r"(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/|youtube\.com/v/)([a-zA-Z0-9_-]{11})",
        r"^([a-zA-Z0-9_-]{11})$",  # Direct video ID
    ]
    for pattern in patterns:
        match = re.search(pattern, url_or_id)
        if match:
            return match.group(1)
    raise ValueError(f"Could not extract video ID from: {url_or_id}")


def register_transcript_tools(
    server, preferred_language: str, default_include_timestamps: bool
):
    """Register transcript-related tools with the MCP server."""

    @server.tool(
        name="get_transcript",
        description="""Fetch the transcript of a YouTube video.
        Accepts either a full YouTube URL or just the video ID.
        Returns the full transcript text, optionally with timestamps.

        Examples:
        - get_transcript("https://youtube.com/watch?v=dQw4w9WgXcQ")
        - get_transcript("dQw4w9WgXcQ", include_timestamps=True)
        """,
    )
    async def get_transcript(
        video_url_or_id: Annotated[
            str,
            Field(
                description="YouTube URL or video ID (e.g., 'dQw4w9WgXcQ' or 'https://youtube.com/watch?v=dQw4w9WgXcQ')"
            ),
        ],
        include_timestamps: Annotated[
            bool, Field(description="Include timestamps in output", default=False)
        ] = False,
        language: Annotated[
            str | None,
            Field(description="Preferred language code (e.g., 'en', 'es')", default=None),
        ] = None,
    ) -> list[TextContent]:
        """Fetch YouTube video transcript."""
        try:
            video_id = extract_video_id(video_url_or_id)
            lang = language or preferred_language
            logger.info(f"Fetching transcript for video: {video_id}, language: {lang}")

            # Use new v1.x API
            actual_language = lang
            try:
                # Try to list available transcripts first
                transcript_list = _api.list(video_id)

                # Find best matching transcript
                selected_transcript = None
                for t in transcript_list:
                    if t.language_code == lang:
                        selected_transcript = t
                        break

                # Fallback to English
                if not selected_transcript:
                    for t in transcript_list:
                        if t.language_code == "en":
                            selected_transcript = t
                            break

                # Use first available if no match
                if not selected_transcript and transcript_list:
                    selected_transcript = transcript_list[0]

                if selected_transcript:
                    segments = selected_transcript.fetch()
                    actual_language = selected_transcript.language_code
                    logger.info(f"Found transcript in language: {actual_language}")
                else:
                    raise NoTranscriptFound(video_id, [], None)

            except Exception as e:
                # Direct fetch as fallback
                logger.info(f"Using direct fetch: {e}")
                segments = _api.fetch(video_id, languages=[lang, "en"])
                actual_language = lang

            # Format output - segments are now FetchedTranscriptSnippet objects
            if include_timestamps or default_include_timestamps:
                lines = []
                for seg in segments:
                    # Access attributes directly (new API uses objects, not dicts)
                    start = getattr(seg, 'start', seg.get('start', 0) if hasattr(seg, 'get') else 0)
                    text = getattr(seg, 'text', seg.get('text', '') if hasattr(seg, 'get') else '')
                    minutes = int(start // 60)
                    seconds = int(start % 60)
                    lines.append(f"[{minutes:02d}:{seconds:02d}] {text}")
                result = "\n".join(lines)
            else:
                texts = []
                for seg in segments:
                    text = getattr(seg, 'text', seg.get('text', '') if hasattr(seg, 'get') else '')
                    texts.append(text)
                result = " ".join(texts)

            # Calculate stats
            total_duration = 0
            for seg in segments:
                duration = getattr(seg, 'duration', seg.get('duration', 0) if hasattr(seg, 'get') else 0)
                total_duration += duration
            duration_mins = int(total_duration // 60)
            word_count = len(result.split())

            header = f"""**Video ID:** {video_id}
**Language:** {actual_language}
**Duration:** ~{duration_mins} minutes
**Word count:** ~{word_count} words

---

"""
            return [TextContent(type="text", text=header + result)]

        except TranscriptsDisabled:
            msg = f"Transcripts are disabled for video: {video_url_or_id}"
            logger.warning(msg)
            return [TextContent(type="text", text=f"Error: {msg}")]
        except NoTranscriptFound:
            msg = f"No transcript found for video: {video_url_or_id}"
            logger.warning(msg)
            return [TextContent(type="text", text=f"Error: {msg}")]
        except VideoUnavailable:
            msg = f"Video is unavailable: {video_url_or_id}"
            logger.warning(msg)
            return [TextContent(type="text", text=f"Error: {msg}")]
        except ValueError as e:
            logger.error(f"Invalid video ID: {e}")
            return [TextContent(type="text", text=f"Error: {str(e)}")]
        except Exception as e:
            logger.error(f"Unexpected error fetching transcript: {e}")
            return [TextContent(type="text", text=f"Error fetching transcript: {str(e)}")]

    @server.tool(
        name="get_video_info",
        description="""Get metadata about a YouTube video (title, channel, duration).
        Note: Requires yt-dlp to be installed for full metadata.
        Without yt-dlp, returns basic video info only.

        Install yt-dlp with: pip install yt-dlp
        """,
    )
    async def get_video_info(
        video_url_or_id: Annotated[
            str, Field(description="YouTube URL or video ID")
        ],
    ) -> list[TextContent]:
        """Get YouTube video metadata."""
        try:
            video_id = extract_video_id(video_url_or_id)
            url = f"https://www.youtube.com/watch?v={video_id}"
            logger.info(f"Fetching video info for: {video_id}")

            # Try yt-dlp for full metadata
            try:
                import yt_dlp

                ydl_opts = {
                    "quiet": True,
                    "no_warnings": True,
                    "extract_flat": False,
                    "skip_download": True,
                }
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    title = info.get("title", "Unknown")
                    channel = info.get("channel", info.get("uploader", "Unknown"))
                    duration = info.get("duration", 0)
                    view_count = info.get("view_count", 0)
                    upload_date = info.get("upload_date", "Unknown")
                    description = info.get("description", "")[:500]  # First 500 chars

                    if duration:
                        hours = duration // 3600
                        minutes = (duration % 3600) // 60
                        seconds = duration % 60
                        if hours:
                            duration_str = f"{hours}:{minutes:02d}:{seconds:02d}"
                        else:
                            duration_str = f"{minutes}:{seconds:02d}"
                    else:
                        duration_str = "Unknown"

                    # Format upload date
                    if upload_date and upload_date != "Unknown":
                        upload_date = f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:8]}"

                    result = f"""## Video Information

- **Title:** {title}
- **Channel:** {channel}
- **Duration:** {duration_str}
- **Views:** {view_count:,}
- **Uploaded:** {upload_date}
- **URL:** {url}
- **Video ID:** {video_id}

### Description (preview)
{description}{"..." if len(info.get("description", "")) > 500 else ""}
"""

            except ImportError:
                logger.info("yt-dlp not installed, returning basic info")
                result = f"""## Video Information (Basic)

- **URL:** {url}
- **Video ID:** {video_id}

> To get full metadata (title, channel, duration), install yt-dlp:
> `pip install yt-dlp` or `uv add yt-dlp`
"""

            return [TextContent(type="text", text=result)]

        except ValueError as e:
            logger.error(f"Invalid video ID: {e}")
            return [TextContent(type="text", text=f"Error: {str(e)}")]
        except Exception as e:
            logger.error(f"Error getting video info: {e}")
            return [TextContent(type="text", text=f"Error: {str(e)}")]

    logger.info("Registered transcript tools: get_transcript, get_video_info")
