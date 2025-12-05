# YouTube Transcript MCP Server

An MCP (Model Context Protocol) server that enables Claude to fetch YouTube video transcripts and save summaries as local Markdown files.

## Features

- **get_transcript** - Fetch video transcripts (with optional timestamps)
- **get_video_info** - Get video metadata (title, channel, duration)
- **save_summary** - Save summaries as Markdown with YAML frontmatter
- **list_summaries** - Browse saved summaries
- **get_summary** - Retrieve a specific summary

## Installation

```bash
cd youtube-mcp
uv sync
```

## Usage with Claude Code

Add to your Claude Code settings:

```json
{
  "mcpServers": {
    "youtube": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/youtube-mcp", "youtube-mcp"]
    }
  }
}
```

## Configuration

Environment variables (optional):

- `YT_SUMMARIES_DIR` - Directory to store summaries (default: `~/.yt-summaries`)
- `YT_INCLUDE_TIMESTAMPS` - Include timestamps by default (default: `false`)
- `YT_PREFERRED_LANGUAGE` - Preferred transcript language (default: `en`)

## License

MIT
