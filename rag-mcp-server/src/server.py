"""RAG MCP Server - Main entry point.

Provides MCP tools for semantic search and document storage
using Qdrant vector database and FastEmbed embeddings.

Usage:
    # stdio mode (default - for Claude Desktop, claude-code)
    python -m src.server

    # http mode (for web integrations)
    RAG_MCP_MODE=http python -m src.server

    # With custom settings
    RAG_QDRANT_URL=http://qdrant:6333 python -m src.server
"""

import asyncio
import logging
import sys
from typing import Any, Dict, List, Optional

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from src.config import get_settings
from src.tools import (
    rag_search,
    rag_store,
    rag_store_batch,
    rag_list_collections,
    rag_collection_stats,
    rag_delete_collection,
)

# Configure logging
settings = get_settings()
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
)
logger = logging.getLogger(__name__)

# Create MCP server
server = Server("rag-mcp-server")


# Tool definitions
TOOLS = [
    Tool(
        name="rag_search",
        description="""Search for relevant documents using semantic similarity.

Performs vector similarity search in Qdrant to find documents
semantically related to the query. Use this to find playbooks,
runbooks, documentation, or any indexed content.

Returns matching documents with relevance scores.""",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural language search query",
                },
                "collection": {
                    "type": "string",
                    "description": "Collection name to search (default: configured default)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum results to return (default: 5)",
                    "default": 5,
                },
                "score_threshold": {
                    "type": "number",
                    "description": "Minimum similarity score 0.0-1.0 (default: from config)",
                },
                "filter_source": {
                    "type": "string",
                    "description": "Filter by source path/name",
                },
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="rag_store",
        description="""Store a document in the vector database for semantic search.

Indexes document content with embeddings. Supports deduplication
via content hashing - identical content won't be stored twice.

Use this to add playbooks, runbooks, or documentation to the knowledge base.""",
        inputSchema={
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "Text content to store",
                },
                "collection": {
                    "type": "string",
                    "description": "Collection name (default: configured default)",
                },
                "source": {
                    "type": "string",
                    "description": "Source identifier (file path, URL, etc.)",
                },
                "title": {
                    "type": "string",
                    "description": "Document title",
                },
                "chunk_index": {
                    "type": "integer",
                    "description": "Index if part of chunked document",
                    "default": 0,
                },
                "metadata": {
                    "type": "object",
                    "description": "Additional metadata to store",
                },
                "deduplicate": {
                    "type": "boolean",
                    "description": "Skip if identical content exists (default: true)",
                    "default": True,
                },
            },
            "required": ["content"],
        },
    ),
    Tool(
        name="rag_store_batch",
        description="""Store multiple documents in batch for efficient bulk indexing.

More efficient than individual rag_store calls. Each document
should have 'content' and optionally 'source', 'title', 'metadata'.""",
        inputSchema={
            "type": "object",
            "properties": {
                "documents": {
                    "type": "array",
                    "description": "List of documents to store",
                    "items": {
                        "type": "object",
                        "properties": {
                            "content": {"type": "string"},
                            "source": {"type": "string"},
                            "title": {"type": "string"},
                            "metadata": {"type": "object"},
                        },
                        "required": ["content"],
                    },
                },
                "collection": {
                    "type": "string",
                    "description": "Collection name (default: configured default)",
                },
                "deduplicate": {
                    "type": "boolean",
                    "description": "Skip identical content (default: true)",
                    "default": True,
                },
            },
            "required": ["documents"],
        },
    ),
    Tool(
        name="rag_list_collections",
        description="""List all available collections in the vector database.

Returns collection names and count. Use this to discover
what knowledge bases are available for search.""",
        inputSchema={
            "type": "object",
            "properties": {},
        },
    ),
    Tool(
        name="rag_collection_stats",
        description="""Get statistics for a collection or all collections.

Returns document counts, vector configuration, and status.
Useful for monitoring knowledge base health and size.""",
        inputSchema={
            "type": "object",
            "properties": {
                "collection": {
                    "type": "string",
                    "description": "Collection name (omit for all collections)",
                },
            },
        },
    ),
    Tool(
        name="rag_delete_collection",
        description="""Delete a collection from the vector database.

WARNING: This permanently deletes all documents in the collection.
Requires confirm=true for safety.""",
        inputSchema={
            "type": "object",
            "properties": {
                "collection": {
                    "type": "string",
                    "description": "Collection name to delete",
                },
                "confirm": {
                    "type": "boolean",
                    "description": "Must be true to delete (safety flag)",
                    "default": False,
                },
            },
            "required": ["collection"],
        },
    ),
]


@server.list_tools()
async def list_tools() -> List[Tool]:
    """Return list of available RAG tools."""
    return TOOLS


@server.call_tool()
async def call_tool(name: str, arguments: Dict[str, Any]) -> List[TextContent]:
    """Execute a RAG tool and return results."""
    import json

    logger.info(f"Tool call: {name} with args: {arguments}")

    try:
        if name == "rag_search":
            result = await rag_search(
                query=arguments["query"],
                collection=arguments.get("collection"),
                limit=arguments.get("limit", 5),
                score_threshold=arguments.get("score_threshold"),
                filter_source=arguments.get("filter_source"),
            )

        elif name == "rag_store":
            result = await rag_store(
                content=arguments["content"],
                collection=arguments.get("collection"),
                source=arguments.get("source"),
                title=arguments.get("title"),
                chunk_index=arguments.get("chunk_index", 0),
                metadata=arguments.get("metadata"),
                deduplicate=arguments.get("deduplicate", True),
            )

        elif name == "rag_store_batch":
            result = await rag_store_batch(
                documents=arguments["documents"],
                collection=arguments.get("collection"),
                deduplicate=arguments.get("deduplicate", True),
            )

        elif name == "rag_list_collections":
            result = await rag_list_collections()

        elif name == "rag_collection_stats":
            result = await rag_collection_stats(
                collection=arguments.get("collection"),
            )

        elif name == "rag_delete_collection":
            result = await rag_delete_collection(
                collection=arguments["collection"],
                confirm=arguments.get("confirm", False),
            )

        else:
            result = {"error": f"Unknown tool: {name}"}

        logger.info(f"Tool result: success={result.get('success', 'N/A')}")

        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    except Exception as e:
        logger.error(f"Tool error: {e}", exc_info=True)
        error_result = {"success": False, "error": str(e)}
        return [TextContent(type="text", text=json.dumps(error_result, indent=2))]


async def run_stdio_server():
    """Run the MCP server in stdio mode."""
    logger.info("Starting RAG MCP Server (stdio mode)")
    logger.info(f"Qdrant URL: {settings.qdrant_url}")
    logger.info(f"Embedding model: {settings.embedding_model}")
    logger.info(f"Default collection: {settings.default_collection}")

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def run_http_server():
    """Run the MCP server in HTTP/SSE mode."""
    from mcp.server.sse import SseServerTransport
    from starlette.applications import Starlette
    from starlette.routing import Route, Mount
    from starlette.responses import JSONResponse, Response
    import uvicorn

    # Create SSE transport - path must match the mount point for POST messages
    sse = SseServerTransport("/messages/")

    async def handle_sse(request):
        """Handle SSE connections.

        Uses connect_sse context manager to establish SSE stream,
        runs the MCP server, then returns an empty Response.
        """
        async with sse.connect_sse(
            request.scope, request.receive, request._send
        ) as streams:
            await server.run(
                streams[0],
                streams[1],
                server.create_initialization_options(),
            )
        # Must return Response to avoid TypeError on disconnect
        return Response()

    async def health_check(request):
        """Health check endpoint."""
        return JSONResponse({"status": "healthy", "service": "rag-mcp-server"})

    async def list_tools_http(request):
        """List available tools (for debugging)."""
        tools = [{"name": t.name, "description": t.description} for t in TOOLS]
        return JSONResponse({"tools": tools, "count": len(tools)})

    # Create Starlette app
    # Note: handle_post_message is an ASGI app, use Mount not Route
    app = Starlette(
        debug=settings.log_level.upper() == "DEBUG",
        routes=[
            Route("/health", health_check, methods=["GET"]),
            Route("/tools", list_tools_http, methods=["GET"]),
            Route("/sse", handle_sse, methods=["GET"]),
            # Mount the message handler as ASGI app (handles its own routing)
            Mount("/messages", app=sse.handle_post_message),
        ],
    )

    logger.info("Starting RAG MCP Server (HTTP/SSE mode)")
    logger.info(f"Qdrant URL: {settings.qdrant_url}")
    logger.info(f"Embedding model: {settings.embedding_model}")
    logger.info(f"Default collection: {settings.default_collection}")
    logger.info(f"Listening on http://{settings.mcp_host}:{settings.mcp_port}")

    uvicorn.run(
        app,
        host=settings.mcp_host,
        port=settings.mcp_port,
        log_level=settings.log_level.lower(),
    )


def main():
    """Main entry point."""
    try:
        if settings.mcp_mode.lower() == "http":
            run_http_server()
        else:
            asyncio.run(run_stdio_server())
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.error(f"Server error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
