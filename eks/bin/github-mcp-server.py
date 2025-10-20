#!/usr/bin/env python3
"""
Minimal GitHub MCP Server using low-level Server API
Provides basic GitHub operations (demonstration)
"""
import asyncio
import json
from mcp.server.stdio import stdio_server
from mcp.server import Server
from mcp.types import Tool, TextContent

# Create server
app = Server("github-mcp")

@app.list_tools()
async def list_tools() -> list[Tool]:
    """List available GitHub tools"""
    return [
        Tool(
            name="github_get_repo",
            description="Get repository information",
            inputSchema={
                "type": "object",
                "properties": {
                    "owner": {"type": "string"},
                    "repo": {"type": "string"}
                },
                "required": ["owner", "repo"]
            }
        )
    ]

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Execute GitHub operations"""

    # Demonstration placeholder
    message = json.dumps({
        "message": "GitHub MCP Server - demonstration",
        "tool": name,
        "arguments": arguments,
        "note": "This is a minimal demonstration server. Full implementation would use PyGithub."
    }, indent=2)

    return [TextContent(type="text", text=message)]

async def main():
    """Run the MCP server"""
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())
