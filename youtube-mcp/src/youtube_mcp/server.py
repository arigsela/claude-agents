"""YouTube Transcript MCP Server."""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

# Load environment
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Configuration
SUMMARIES_DIR = Path(os.getenv("YT_SUMMARIES_DIR", "~/.yt-summaries")).expanduser()
INCLUDE_TIMESTAMPS = os.getenv("YT_INCLUDE_TIMESTAMPS", "false").lower() == "true"
PREFERRED_LANGUAGE = os.getenv("YT_PREFERRED_LANGUAGE", "en")

# Ensure summaries directory exists
SUMMARIES_DIR.mkdir(parents=True, exist_ok=True)

logger.info(f"YouTube MCP Server starting...")
logger.info(f"Summaries directory: {SUMMARIES_DIR}")
logger.info(f"Default timestamps: {INCLUDE_TIMESTAMPS}")
logger.info(f"Preferred language: {PREFERRED_LANGUAGE}")

# Create FastMCP server
mcp = FastMCP(
    name="YouTube Transcript Server",
)


def register_all_tools():
    """Register all tools with the MCP server."""
    from youtube_mcp.tools.transcript import register_transcript_tools
    from youtube_mcp.tools.storage import register_storage_tools
    from youtube_mcp.tools.playlist import register_playlist_tools

    register_transcript_tools(mcp, PREFERRED_LANGUAGE, INCLUDE_TIMESTAMPS)
    register_storage_tools(mcp, SUMMARIES_DIR)
    register_playlist_tools(mcp, PREFERRED_LANGUAGE)
    logger.info("All tools registered successfully")


def main():
    """Run the MCP server."""
    register_all_tools()
    logger.info("Starting MCP server...")
    mcp.run()


if __name__ == "__main__":
    main()
