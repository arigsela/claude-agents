"""MCP tools behind AgentCore Gateway, called without mcp's output-schema check.

GitHub's hosted MCP server lists output schemas for its tools but answers with text
content only (no ``structuredContent``). mcp's ``ClientSession.call_tool`` (1.30.0)
then raises "has an output schema but did not return structured content" before the
result is seen. The tool belt only ever reads text content, so each call here goes
through the session's public ``send_request`` with the same ``tools/call`` request
``call_tool`` sends, minus that check. Everything else is langchain-mcp-adapters' own
conversion: an ``isError`` result still raises (``handle_tool_errors=False``), so it
is never mistaken for a successful read.
"""

from __future__ import annotations

from typing import Any

from langchain_mcp_adapters.sessions import create_session
from langchain_mcp_adapters.tools import convert_mcp_tool_to_langchain_tool
from mcp import types


class GatewaySession:
    """What the adapter's tools call: one fresh MCP session per tool call."""

    def __init__(self, connection: dict[str, Any]):
        self._connection = connection

    async def call_tool(
        self, name: str, arguments: dict[str, Any] | None = None, **_: Any
    ) -> types.CallToolResult:
        async with create_session(self._connection) as session:
            await session.initialize()
            request = types.ClientRequest(
                types.CallToolRequest(
                    params=types.CallToolRequestParams(name=name, arguments=arguments)
                )
            )
            return await session.send_request(request, types.CallToolResult)


async def load_gateway_tools(server_name: str, connection: dict[str, Any]) -> list[Any]:
    async with create_session(connection) as session:
        await session.initialize()
        listed = await session.list_tools()
    calls = GatewaySession(connection)
    return [
        convert_mcp_tool_to_langchain_tool(
            calls, tool, server_name=server_name, handle_tool_errors=False
        )
        for tool in listed.tools
    ]
