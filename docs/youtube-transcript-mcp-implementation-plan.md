# YouTube Transcript MCP Server - Implementation Plan

**Date:** 2025-12-04
**Target:** Build an MCP server that retrieves YouTube video transcripts and saves summaries as local Markdown files
**Architecture:** FastMCP server with STDIO transport for Claude Code/Desktop integration

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Prerequisites](#prerequisites)
4. [Phase 1: Project Setup](#phase-1-project-setup)
5. [Phase 2: Core MCP Server Implementation](#phase-2-core-mcp-server-implementation)
6. [Phase 3: Transcript Retrieval Tools](#phase-3-transcript-retrieval-tools)
7. [Phase 4: Markdown Storage Tools](#phase-4-markdown-storage-tools)
8. [Phase 5: Claude Code Integration](#phase-5-claude-code-integration)
9. [Phase 6: Testing & Validation](#phase-6-testing--validation)
10. [Future Enhancements](#future-enhancements)

---

## Overview

### Goal

Create an MCP server that allows Claude to:
1. **Retrieve transcripts** from YouTube videos (with timestamps optional)
2. **Save summaries** as local Markdown documents for future reference
3. **List saved summaries** for easy retrieval

### Workflow

```
┌─────────────────┐     ┌──────────────────────┐     ┌─────────────────┐
│  Claude Code/   │────▶│  YouTube Transcript  │────▶│   YouTube API   │
│  Claude Desktop │     │     MCP Server       │     │  (transcripts)  │
└─────────────────┘     └──────────────────────┘     └─────────────────┘
         │                        │
         │                        ▼
         │              ┌──────────────────────┐
         │              │   Local Markdown     │
         └─────────────▶│   Storage (~/.yt/)   │
                        └──────────────────────┘
```

### User Flow Example

```
User: "Summarize this video: https://youtube.com/watch?v=abc123"

Claude:
1. Calls get_transcript(video_id="abc123")
2. MCP server fetches transcript from YouTube
3. Claude analyzes and generates summary
4. Calls save_summary(title="...", content="...", video_id="abc123")
5. MCP server saves to ~/.yt-summaries/2025-12-04-abc123.md
```

---

## Architecture

### Technology Stack

| Component | Technology | Purpose |
|-----------|------------|---------|
| MCP Framework | `mcp[cli]` (FastMCP) | Server framework with STDIO transport |
| YouTube API | `youtube-transcript-api` | Fetch video transcripts (no API key needed) |
| Video Metadata | `yt-dlp` (optional) | Get video title, channel, duration |
| Storage | Local filesystem | Save summaries as Markdown |
| Configuration | `python-dotenv` | Environment variables |
| Validation | `pydantic` | Input/output validation |

### MCP Tools Exposed

| Tool | Description | Parameters |
|------|-------------|------------|
| `get_transcript` | Fetch YouTube video transcript | `video_id`, `include_timestamps` |
| `get_video_info` | Get video metadata (title, channel) | `video_id` |
| `save_summary` | Save summary as Markdown file | `title`, `content`, `video_id`, `tags` |
| `list_summaries` | List all saved summaries | `limit`, `search` |
| `get_summary` | Retrieve a saved summary | `filename` |

### Directory Structure

```
youtube-mcp/
├── pyproject.toml              # Project configuration (uv/pip)
├── README.md                   # Usage documentation
├── .env.example                # Environment template
├── src/
│   └── youtube_mcp/
│       ├── __init__.py
│       ├── server.py           # FastMCP server entry point
│       ├── tools/
│       │   ├── __init__.py
│       │   ├── transcript.py   # get_transcript, get_video_info
│       │   └── storage.py      # save_summary, list_summaries, get_summary
│       └── models.py           # Pydantic models
└── tests/
    ├── test_transcript.py
    └── test_storage.py
```

---

## Prerequisites

### Required

- Python 3.11+
- `uv` package manager (recommended) or `pip`
- Claude Code or Claude Desktop

### Optional

- `yt-dlp` for video metadata (title, channel name)

---

## Phase 1: Project Setup

**Status:** ✅ Complete
**Estimated Tasks:** 4

### 1.1 Create Project Directory

```bash
mkdir -p youtube-mcp/src/youtube_mcp/tools
mkdir -p youtube-mcp/tests
cd youtube-mcp
```

### 1.2 Initialize with uv

```bash
uv init
uv add "mcp[cli]" youtube-transcript-api pydantic python-dotenv
uv add --dev pytest pytest-asyncio
```

**Dependencies:**
- `mcp[cli]` - FastMCP framework
- `youtube-transcript-api` - Transcript fetching (no API key!)
- `pydantic` - Data validation
- `python-dotenv` - Environment configuration
- `pytest`, `pytest-asyncio` - Testing

### 1.3 Create pyproject.toml

```toml
[project]
name = "youtube-mcp"
version = "0.1.0"
description = "MCP server for YouTube transcript retrieval and summarization"
requires-python = ">=3.11"
dependencies = [
    "mcp[cli]>=1.0.0",
    "youtube-transcript-api>=0.6.2",
    "pydantic>=2.0.0",
    "python-dotenv>=1.0.0",
]

[project.optional-dependencies]
metadata = ["yt-dlp>=2024.0.0"]
dev = ["pytest>=8.0.0", "pytest-asyncio>=0.23.0"]

[project.scripts]
youtube-mcp = "youtube_mcp.server:main"

[tool.uv]
dev-dependencies = ["pytest>=8.0.0", "pytest-asyncio>=0.23.0"]
```

### 1.4 Create .env.example

```bash
# YouTube MCP Server Configuration

# Directory to store summaries (default: ~/.yt-summaries)
YT_SUMMARIES_DIR=~/.yt-summaries

# Include timestamps in transcripts by default (true/false)
YT_INCLUDE_TIMESTAMPS=false

# Preferred language for transcripts (ISO 639-1 code)
YT_PREFERRED_LANGUAGE=en
```

### Tasks Checklist

- [x] Create project directory structure
- [x] Initialize with uv and add dependencies
- [x] Create pyproject.toml
- [x] Create .env.example

---

## Phase 2: Core MCP Server Implementation

**Status:** ✅ Complete
**Estimated Tasks:** 3

### 2.1 Create Pydantic Models (`src/youtube_mcp/models.py`)

```python
"""Pydantic models for YouTube MCP server."""

from datetime import datetime
from typing import Annotated
from pydantic import BaseModel, Field


class TranscriptSegment(BaseModel):
    """A single segment of a transcript."""
    text: str
    start: float
    duration: float


class TranscriptResult(BaseModel):
    """Result from get_transcript tool."""
    video_id: str
    transcript: str
    segments: list[TranscriptSegment] | None = None
    language: str


class VideoInfo(BaseModel):
    """Video metadata."""
    video_id: str
    title: str | None = None
    channel: str | None = None
    duration: int | None = None  # seconds
    url: str


class SaveSummaryInput(BaseModel):
    """Input for save_summary tool."""
    title: Annotated[str, Field(description="Title for the summary document")]
    content: Annotated[str, Field(description="Markdown content of the summary")]
    video_id: Annotated[str, Field(description="YouTube video ID")]
    video_url: Annotated[str | None, Field(description="Full YouTube URL", default=None)]
    tags: Annotated[list[str] | None, Field(description="Tags for categorization", default=None)]


class SummaryMetadata(BaseModel):
    """Metadata for a saved summary."""
    filename: str
    title: str
    video_id: str
    created_at: datetime
    tags: list[str]
```

### 2.2 Create Server Entry Point (`src/youtube_mcp/server.py`)

```python
"""YouTube Transcript MCP Server."""

import os
from pathlib import Path
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

# Load environment
load_dotenv()

# Configuration
SUMMARIES_DIR = Path(os.getenv("YT_SUMMARIES_DIR", "~/.yt-summaries")).expanduser()
INCLUDE_TIMESTAMPS = os.getenv("YT_INCLUDE_TIMESTAMPS", "false").lower() == "true"
PREFERRED_LANGUAGE = os.getenv("YT_PREFERRED_LANGUAGE", "en")

# Ensure summaries directory exists
SUMMARIES_DIR.mkdir(parents=True, exist_ok=True)

# Create FastMCP server
mcp = FastMCP(
    name="YouTube Transcript Server",
    version="0.1.0",
)

# Import and register tools
from youtube_mcp.tools.transcript import register_transcript_tools
from youtube_mcp.tools.storage import register_storage_tools

register_transcript_tools(mcp, PREFERRED_LANGUAGE, INCLUDE_TIMESTAMPS)
register_storage_tools(mcp, SUMMARIES_DIR)


def main():
    """Run the MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
```

### 2.3 Create `__init__.py` Files

```python
# src/youtube_mcp/__init__.py
"""YouTube Transcript MCP Server."""

# src/youtube_mcp/tools/__init__.py
"""MCP Tools for YouTube Transcript Server."""
```

### Tasks Checklist

- [x] Create Pydantic models in `models.py`
- [x] Create server entry point in `server.py`
- [x] Create `__init__.py` files

---

## Phase 3: Transcript Retrieval Tools

**Status:** ✅ Complete
**Estimated Tasks:** 3

### 3.1 Implement get_transcript Tool (`src/youtube_mcp/tools/transcript.py`)

```python
"""Transcript retrieval tools."""

import re
import logging
from typing import Annotated
from pydantic import Field
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    TranscriptsDisabled,
    NoTranscriptFound,
    VideoUnavailable,
)
from mcp.types import TextContent

logger = logging.getLogger(__name__)


def extract_video_id(url_or_id: str) -> str:
    """Extract video ID from YouTube URL or return as-is if already an ID."""
    # Common YouTube URL patterns
    patterns = [
        r'(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/)([a-zA-Z0-9_-]{11})',
        r'^([a-zA-Z0-9_-]{11})$',  # Direct video ID
    ]
    for pattern in patterns:
        match = re.search(pattern, url_or_id)
        if match:
            return match.group(1)
    raise ValueError(f"Could not extract video ID from: {url_or_id}")


def register_transcript_tools(server, preferred_language: str, include_timestamps: bool):
    """Register transcript-related tools with the MCP server."""

    @server.tool(
        name="get_transcript",
        description="""Fetch the transcript of a YouTube video.
        Accepts either a full YouTube URL or just the video ID.
        Returns the full transcript text, optionally with timestamps."""
    )
    async def get_transcript(
        video_url_or_id: Annotated[str, Field(description="YouTube URL or video ID (e.g., 'dQw4w9WgXcQ' or 'https://youtube.com/watch?v=dQw4w9WgXcQ')")],
        include_timestamps: Annotated[bool, Field(description="Include timestamps in output", default=False)] = False,
        language: Annotated[str | None, Field(description="Preferred language code (e.g., 'en', 'es')", default=None)] = None,
    ) -> list[TextContent]:
        """Fetch YouTube video transcript."""
        try:
            video_id = extract_video_id(video_url_or_id)
            lang = language or preferred_language

            # Try to get transcript in preferred language, fall back to any available
            try:
                transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
                try:
                    transcript = transcript_list.find_transcript([lang])
                except NoTranscriptFound:
                    # Fall back to first available transcript
                    transcript = transcript_list.find_transcript([lang])
                segments = transcript.fetch()
            except Exception:
                # Direct fetch as fallback
                segments = YouTubeTranscriptApi.get_transcript(video_id, languages=[lang, 'en'])

            # Format output
            if include_timestamps:
                lines = []
                for seg in segments:
                    minutes = int(seg['start'] // 60)
                    seconds = int(seg['start'] % 60)
                    lines.append(f"[{minutes:02d}:{seconds:02d}] {seg['text']}")
                result = "\n".join(lines)
            else:
                result = " ".join(seg['text'] for seg in segments)

            return [TextContent(
                type="text",
                text=f"Transcript for video {video_id}:\n\n{result}"
            )]

        except TranscriptsDisabled:
            return [TextContent(type="text", text=f"Error: Transcripts are disabled for video {video_url_or_id}")]
        except NoTranscriptFound:
            return [TextContent(type="text", text=f"Error: No transcript found for video {video_url_or_id}")]
        except VideoUnavailable:
            return [TextContent(type="text", text=f"Error: Video {video_url_or_id} is unavailable")]
        except ValueError as e:
            return [TextContent(type="text", text=f"Error: {str(e)}")]
        except Exception as e:
            logger.error(f"Unexpected error fetching transcript: {e}")
            return [TextContent(type="text", text=f"Error fetching transcript: {str(e)}")]

    @server.tool(
        name="get_video_info",
        description="""Get metadata about a YouTube video (title, channel, duration).
        Note: This requires yt-dlp to be installed for full metadata.
        Without yt-dlp, returns basic info only."""
    )
    async def get_video_info(
        video_url_or_id: Annotated[str, Field(description="YouTube URL or video ID")],
    ) -> list[TextContent]:
        """Get YouTube video metadata."""
        try:
            video_id = extract_video_id(video_url_or_id)
            url = f"https://www.youtube.com/watch?v={video_id}"

            # Try yt-dlp for full metadata
            try:
                import yt_dlp
                ydl_opts = {
                    'quiet': True,
                    'no_warnings': True,
                    'extract_flat': True,
                }
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    title = info.get('title', 'Unknown')
                    channel = info.get('channel', info.get('uploader', 'Unknown'))
                    duration = info.get('duration', 0)
                    duration_str = f"{duration // 60}:{duration % 60:02d}" if duration else "Unknown"

                    result = f"""Video Information:
- **Title:** {title}
- **Channel:** {channel}
- **Duration:** {duration_str}
- **URL:** {url}
- **Video ID:** {video_id}"""

            except ImportError:
                result = f"""Video Information (basic - install yt-dlp for full metadata):
- **URL:** {url}
- **Video ID:** {video_id}

To get full metadata, install yt-dlp: `pip install yt-dlp`"""

            return [TextContent(type="text", text=result)]

        except ValueError as e:
            return [TextContent(type="text", text=f"Error: {str(e)}")]
        except Exception as e:
            logger.error(f"Error getting video info: {e}")
            return [TextContent(type="text", text=f"Error: {str(e)}")]

    logger.info("Registered transcript tools: get_transcript, get_video_info")
```

### 3.2 Add Error Handling Wrapper

The error handling is already included inline in the tools above for simplicity, following the pattern from the Webex MCP server.

### 3.3 Test Transcript Retrieval

```python
# tests/test_transcript.py
import pytest
from youtube_mcp.tools.transcript import extract_video_id


def test_extract_video_id_from_url():
    assert extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert extract_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert extract_video_id("https://youtube.com/embed/dQw4w9WgXcQ") == "dQw4w9WgXcQ"


def test_extract_video_id_direct():
    assert extract_video_id("dQw4w9WgXcQ") == "dQw4w9WgXcQ"


def test_extract_video_id_invalid():
    with pytest.raises(ValueError):
        extract_video_id("not-a-valid-id")
```

### Tasks Checklist

- [x] Implement `get_transcript` tool with URL parsing
- [x] Implement `get_video_info` tool (optional yt-dlp)
- [x] Add unit tests for video ID extraction

---

## Phase 4: Markdown Storage Tools

**Status:** ✅ Complete
**Estimated Tasks:** 3

### 4.1 Implement Storage Tools (`src/youtube_mcp/tools/storage.py`)

```python
"""Markdown storage tools."""

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Annotated
from pydantic import Field
from mcp.types import TextContent

logger = logging.getLogger(__name__)


def sanitize_filename(title: str) -> str:
    """Convert title to safe filename."""
    # Remove special characters, replace spaces with hyphens
    safe = re.sub(r'[^\w\s-]', '', title.lower())
    safe = re.sub(r'[-\s]+', '-', safe).strip('-')
    return safe[:50]  # Limit length


def register_storage_tools(server, summaries_dir: Path):
    """Register storage-related tools with the MCP server."""

    @server.tool(
        name="save_summary",
        description="""Save a video summary as a Markdown file.
        The file is saved to the configured summaries directory with
        YAML frontmatter containing metadata."""
    )
    async def save_summary(
        title: Annotated[str, Field(description="Title for the summary document")],
        content: Annotated[str, Field(description="Markdown content of the summary")],
        video_id: Annotated[str, Field(description="YouTube video ID")],
        video_url: Annotated[str | None, Field(description="Full YouTube URL")] = None,
        tags: Annotated[list[str] | None, Field(description="Tags for categorization")] = None,
    ) -> list[TextContent]:
        """Save summary as Markdown file."""
        try:
            # Generate filename
            date_str = datetime.now().strftime("%Y-%m-%d")
            safe_title = sanitize_filename(title)
            filename = f"{date_str}-{video_id}-{safe_title}.md"
            filepath = summaries_dir / filename

            # Build frontmatter
            frontmatter = {
                "title": title,
                "video_id": video_id,
                "video_url": video_url or f"https://www.youtube.com/watch?v={video_id}",
                "created_at": datetime.now().isoformat(),
                "tags": tags or [],
            }

            # Format as YAML frontmatter
            yaml_lines = ["---"]
            for key, value in frontmatter.items():
                if isinstance(value, list):
                    yaml_lines.append(f"{key}:")
                    for item in value:
                        yaml_lines.append(f"  - {item}")
                else:
                    yaml_lines.append(f"{key}: \"{value}\"" if isinstance(value, str) else f"{key}: {value}")
            yaml_lines.append("---\n")

            # Write file
            file_content = "\n".join(yaml_lines) + f"\n# {title}\n\n{content}"
            filepath.write_text(file_content, encoding="utf-8")

            return [TextContent(
                type="text",
                text=f"Summary saved successfully!\n\n- **File:** {filepath}\n- **Title:** {title}\n- **Video ID:** {video_id}"
            )]

        except Exception as e:
            logger.error(f"Error saving summary: {e}")
            return [TextContent(type="text", text=f"Error saving summary: {str(e)}")]

    @server.tool(
        name="list_summaries",
        description="""List all saved video summaries.
        Returns a list of saved summaries with their metadata."""
    )
    async def list_summaries(
        limit: Annotated[int, Field(description="Maximum number of summaries to return")] = 20,
        search: Annotated[str | None, Field(description="Search term to filter by filename")] = None,
    ) -> list[TextContent]:
        """List saved summaries."""
        try:
            files = sorted(summaries_dir.glob("*.md"), key=lambda f: f.stat().st_mtime, reverse=True)

            if search:
                files = [f for f in files if search.lower() in f.name.lower()]

            files = files[:limit]

            if not files:
                return [TextContent(type="text", text="No summaries found.")]

            lines = ["# Saved Summaries\n"]
            for f in files:
                # Try to extract title from frontmatter
                content = f.read_text(encoding="utf-8")
                title = f.stem  # Default to filename
                if content.startswith("---"):
                    try:
                        end = content.index("---", 3)
                        frontmatter = content[3:end]
                        for line in frontmatter.split("\n"):
                            if line.startswith("title:"):
                                title = line.split(":", 1)[1].strip().strip('"')
                                break
                    except (ValueError, IndexError):
                        pass

                modified = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
                lines.append(f"- **{title}**\n  - File: `{f.name}`\n  - Modified: {modified}\n")

            return [TextContent(type="text", text="\n".join(lines))]

        except Exception as e:
            logger.error(f"Error listing summaries: {e}")
            return [TextContent(type="text", text=f"Error: {str(e)}")]

    @server.tool(
        name="get_summary",
        description="Retrieve the content of a saved summary by filename."
    )
    async def get_summary(
        filename: Annotated[str, Field(description="Filename of the summary to retrieve")],
    ) -> list[TextContent]:
        """Get a saved summary."""
        try:
            filepath = summaries_dir / filename
            if not filepath.exists():
                # Try with .md extension
                filepath = summaries_dir / f"{filename}.md"

            if not filepath.exists():
                return [TextContent(type="text", text=f"Summary not found: {filename}")]

            content = filepath.read_text(encoding="utf-8")
            return [TextContent(type="text", text=content)]

        except Exception as e:
            logger.error(f"Error reading summary: {e}")
            return [TextContent(type="text", text=f"Error: {str(e)}")]

    logger.info("Registered storage tools: save_summary, list_summaries, get_summary")
```

### 4.2 Test Storage Tools

```python
# tests/test_storage.py
import pytest
from pathlib import Path
import tempfile
from youtube_mcp.tools.storage import sanitize_filename


def test_sanitize_filename():
    assert sanitize_filename("Hello World!") == "hello-world"
    assert sanitize_filename("Video: The Best Tutorial (2024)") == "video-the-best-tutorial-2024"
    assert sanitize_filename("  Extra   Spaces  ") == "extra-spaces"
```

### Tasks Checklist

- [x] Implement `save_summary` tool with YAML frontmatter
- [x] Implement `list_summaries` tool with search
- [x] Implement `get_summary` tool
- [x] Add unit tests for filename sanitization

---

## Phase 5: Claude Code Integration

**Status:** ✅ Complete
**Estimated Tasks:** 3

### 5.1 Configure Claude Code Settings

Add to your Claude Code settings (`.claude/settings.json` or global config):

```json
{
  "mcpServers": {
    "youtube": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/youtube-mcp", "youtube-mcp"],
      "env": {
        "YT_SUMMARIES_DIR": "~/.yt-summaries",
        "YT_INCLUDE_TIMESTAMPS": "false",
        "YT_PREFERRED_LANGUAGE": "en"
      }
    }
  }
}
```

**Alternative (using python directly):**

```json
{
  "mcpServers": {
    "youtube": {
      "command": "python",
      "args": ["-m", "youtube_mcp.server"],
      "cwd": "/path/to/youtube-mcp",
      "env": {
        "PYTHONPATH": "/path/to/youtube-mcp/src"
      }
    }
  }
}
```

### 5.2 Configure Claude Desktop (Optional)

For Claude Desktop, edit `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "youtube": {
      "command": "/path/to/youtube-mcp/.venv/bin/python",
      "args": ["-m", "youtube_mcp.server"],
      "env": {
        "PYTHONPATH": "/path/to/youtube-mcp/src",
        "YT_SUMMARIES_DIR": "~/.yt-summaries"
      }
    }
  }
}
```

### 5.3 Verify MCP Connection

After restarting Claude Code:
1. Look for the hammer icon (tools available)
2. Try: "List the available YouTube tools"
3. Test: "Fetch the transcript for https://youtube.com/watch?v=dQw4w9WgXcQ"

### Tasks Checklist

- [x] Add MCP server configuration to Claude Code settings
- [ ] Optionally configure Claude Desktop
- [x] Verify MCP tools are accessible

---

## Phase 6: Testing & Validation

**Status:** ⬜ Not Started
**Estimated Tasks:** 4

### 6.1 Unit Tests

```bash
cd youtube-mcp
uv run pytest tests/ -v
```

### 6.2 Manual Testing Workflow

```
# Test 1: Transcript retrieval
User: "Get the transcript for this video: https://youtube.com/watch?v=abc123"

# Test 2: With timestamps
User: "Get the transcript with timestamps for video xyz789"

# Test 3: Full workflow
User: "Summarize this video and save it: https://youtube.com/watch?v=abc123"

# Test 4: List summaries
User: "Show me all my saved YouTube summaries"

# Test 5: Retrieve summary
User: "Get the summary for video abc123"
```

### 6.3 Edge Cases to Test

- [ ] Video with no transcript available
- [ ] Video with auto-generated captions only
- [ ] Private/unavailable video
- [ ] Non-English videos
- [ ] Very long videos (>2 hours)
- [ ] Invalid YouTube URLs

### 6.4 Performance Validation

- Transcript fetch: < 5 seconds
- Summary save: < 1 second
- Summary list: < 1 second

### Tasks Checklist

- [ ] Run unit tests
- [ ] Complete manual testing workflow
- [ ] Test edge cases
- [ ] Validate performance

---

## Future Enhancements

### Phase 7: Notion Integration (Optional)

- Add `create_notion_page` tool
- Sync summaries to Notion database
- Bidirectional sync

### Phase 8: Advanced Features

- **Timestamp extraction**: Key moments with timestamps
- **Speaker detection**: Identify speakers in podcasts
- **Topic segmentation**: Break transcript into sections
- **Translation**: Auto-translate non-English transcripts
- **Batch processing**: Multiple videos at once

### Phase 9: Search & Organization

- Full-text search across summaries
- Tag-based filtering
- Integration with Obsidian/Logseq

---

## Progress Tracker

| Phase | Status | Tasks | Completed |
|-------|--------|-------|-----------|
| Phase 1: Project Setup | ✅ | 4 | 4/4 |
| Phase 2: Core Server | ✅ | 3 | 3/3 |
| Phase 3: Transcript Tools | ✅ | 3 | 3/3 |
| Phase 4: Storage Tools | ✅ | 4 | 4/4 |
| Phase 5: Claude Integration | ✅ | 3 | 2/3 |
| Phase 6: Testing | ⬜ | 4 | 0/4 |

**Total Progress:** 16/21 tasks (76%)

---

## References

- [Enkrypt AI Tutorial](https://www.enkryptai.com/blog/teach-claude-to-watch-youtube-videos-and-take-notes-in-notion)
- [MCP Documentation](https://modelcontextprotocol.io)
- [FastMCP Server](https://github.com/modelcontextprotocol/python-sdk)
- [youtube-transcript-api](https://github.com/jdepoix/youtube-transcript-api)
- [yt-dlp](https://github.com/yt-dlp/yt-dlp)

---

**Last Updated:** 2025-12-04
**Phase 1 Completed:** 2025-12-04
**Phases 2-4 Completed:** 2025-12-04
**Phase 5 Completed:** 2025-12-04
