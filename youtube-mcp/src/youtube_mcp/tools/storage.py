"""Markdown storage tools."""

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Annotated

from mcp.types import TextContent
from pydantic import Field

logger = logging.getLogger(__name__)


def sanitize_filename(title: str) -> str:
    """Convert title to safe filename.

    - Removes special characters
    - Replaces spaces with hyphens
    - Converts to lowercase
    - Limits length to 50 characters
    """
    # Remove special characters, keep alphanumeric, spaces, hyphens
    safe = re.sub(r"[^\w\s-]", "", title.lower())
    # Replace whitespace with single hyphen
    safe = re.sub(r"[-\s]+", "-", safe).strip("-")
    return safe[:50]


def register_storage_tools(server, summaries_dir: Path):
    """Register storage-related tools with the MCP server."""

    @server.tool(
        name="save_summary",
        description="""Save a video summary as a Markdown file.
        The file is saved to the configured summaries directory with
        YAML frontmatter containing metadata (title, video_id, tags, created_at).

        The filename format is: YYYY-MM-DD-VIDEO_ID-title-slug.md
        """,
    )
    async def save_summary(
        title: Annotated[str, Field(description="Title for the summary document")],
        content: Annotated[str, Field(description="Markdown content of the summary")],
        video_id: Annotated[str, Field(description="YouTube video ID")],
        video_url: Annotated[
            str | None, Field(description="Full YouTube URL")
        ] = None,
        tags: Annotated[
            list[str] | None, Field(description="Tags for categorization")
        ] = None,
    ) -> list[TextContent]:
        """Save summary as Markdown file."""
        try:
            # Generate filename
            date_str = datetime.now().strftime("%Y-%m-%d")
            safe_title = sanitize_filename(title)
            filename = f"{date_str}-{video_id}-{safe_title}.md"
            filepath = summaries_dir / filename

            logger.info(f"Saving summary to: {filepath}")

            # Build frontmatter
            frontmatter_lines = ["---"]
            frontmatter_lines.append(f'title: "{title}"')
            frontmatter_lines.append(f'video_id: "{video_id}"')
            frontmatter_lines.append(
                f'video_url: "{video_url or f"https://www.youtube.com/watch?v={video_id}"}"'
            )
            frontmatter_lines.append(f'created_at: "{datetime.now().isoformat()}"')

            if tags:
                frontmatter_lines.append("tags:")
                for tag in tags:
                    frontmatter_lines.append(f"  - {tag}")
            else:
                frontmatter_lines.append("tags: []")

            frontmatter_lines.append("---")

            # Compose full content
            file_content = "\n".join(frontmatter_lines)
            file_content += f"\n\n# {title}\n\n{content}"

            # Write file
            filepath.write_text(file_content, encoding="utf-8")

            result = f"""Summary saved successfully!

- **File:** `{filepath}`
- **Title:** {title}
- **Video ID:** {video_id}
- **Tags:** {", ".join(tags) if tags else "none"}

You can retrieve this summary later using `list_summaries` or `get_summary`.
"""
            return [TextContent(type="text", text=result)]

        except Exception as e:
            logger.error(f"Error saving summary: {e}")
            return [TextContent(type="text", text=f"Error saving summary: {str(e)}")]

    @server.tool(
        name="list_summaries",
        description="""List all saved video summaries.
        Returns a list of saved summaries sorted by modification date (newest first).
        Optionally filter by search term in filename.
        """,
    )
    async def list_summaries(
        limit: Annotated[
            int, Field(description="Maximum number of summaries to return")
        ] = 20,
        search: Annotated[
            str | None, Field(description="Search term to filter by filename")
        ] = None,
    ) -> list[TextContent]:
        """List saved summaries."""
        try:
            # Get all markdown files sorted by modification time
            files = sorted(
                summaries_dir.glob("*.md"),
                key=lambda f: f.stat().st_mtime,
                reverse=True,
            )

            # Filter by search term if provided
            if search:
                search_lower = search.lower()
                files = [f for f in files if search_lower in f.name.lower()]

            # Limit results
            files = files[:limit]

            if not files:
                return [
                    TextContent(
                        type="text",
                        text=f"No summaries found in `{summaries_dir}`."
                        + (f"\nSearch term: '{search}'" if search else ""),
                    )
                ]

            lines = [f"# Saved Summaries ({len(files)} files)\n"]
            lines.append(f"Directory: `{summaries_dir}`\n")

            for f in files:
                # Try to extract title from frontmatter
                title = f.stem  # Default to filename without extension
                video_id = "unknown"
                tags = []

                try:
                    content = f.read_text(encoding="utf-8")
                    if content.startswith("---"):
                        end_idx = content.index("---", 3)
                        frontmatter = content[3:end_idx]

                        for line in frontmatter.split("\n"):
                            line = line.strip()
                            if line.startswith("title:"):
                                title = line.split(":", 1)[1].strip().strip('"')
                            elif line.startswith("video_id:"):
                                video_id = line.split(":", 1)[1].strip().strip('"')
                            elif line.startswith("  - "):
                                tags.append(line[4:].strip())
                except (ValueError, IndexError, UnicodeDecodeError):
                    pass

                modified = datetime.fromtimestamp(f.stat().st_mtime).strftime(
                    "%Y-%m-%d %H:%M"
                )
                tags_str = f" [{', '.join(tags)}]" if tags else ""

                lines.append(f"### {title}{tags_str}")
                lines.append(f"- **File:** `{f.name}`")
                lines.append(f"- **Video ID:** {video_id}")
                lines.append(f"- **Modified:** {modified}")
                lines.append("")

            return [TextContent(type="text", text="\n".join(lines))]

        except Exception as e:
            logger.error(f"Error listing summaries: {e}")
            return [TextContent(type="text", text=f"Error: {str(e)}")]

    @server.tool(
        name="get_summary",
        description="""Retrieve the content of a saved summary by filename.
        You can provide just the filename or the full path.
        The .md extension is optional.
        """,
    )
    async def get_summary(
        filename: Annotated[
            str, Field(description="Filename of the summary to retrieve")
        ],
    ) -> list[TextContent]:
        """Get a saved summary."""
        try:
            # Handle different input formats
            filepath = summaries_dir / filename

            # Try with .md extension if not provided
            if not filepath.exists() and not filename.endswith(".md"):
                filepath = summaries_dir / f"{filename}.md"

            if not filepath.exists():
                # Try searching by video_id
                matches = list(summaries_dir.glob(f"*{filename}*.md"))
                if matches:
                    filepath = matches[0]
                    logger.info(f"Found match by search: {filepath}")
                else:
                    return [
                        TextContent(
                            type="text",
                            text=f"Summary not found: `{filename}`\n\nUse `list_summaries` to see available files.",
                        )
                    ]

            content = filepath.read_text(encoding="utf-8")
            logger.info(f"Retrieved summary: {filepath}")

            return [TextContent(type="text", text=content)]

        except Exception as e:
            logger.error(f"Error reading summary: {e}")
            return [TextContent(type="text", text=f"Error: {str(e)}")]

    @server.tool(
        name="delete_summary",
        description="""Delete a saved summary by filename.
        Use with caution - this action cannot be undone.
        """,
    )
    async def delete_summary(
        filename: Annotated[
            str, Field(description="Filename of the summary to delete")
        ],
    ) -> list[TextContent]:
        """Delete a saved summary."""
        try:
            filepath = summaries_dir / filename

            # Try with .md extension if not provided
            if not filepath.exists() and not filename.endswith(".md"):
                filepath = summaries_dir / f"{filename}.md"

            if not filepath.exists():
                return [
                    TextContent(
                        type="text",
                        text=f"Summary not found: `{filename}`",
                    )
                ]

            filepath.unlink()
            logger.info(f"Deleted summary: {filepath}")

            return [
                TextContent(
                    type="text",
                    text=f"Summary deleted: `{filepath.name}`",
                )
            ]

        except Exception as e:
            logger.error(f"Error deleting summary: {e}")
            return [TextContent(type="text", text=f"Error: {str(e)}")]

    logger.info(
        "Registered storage tools: save_summary, list_summaries, get_summary, delete_summary"
    )
