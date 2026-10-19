"""Gateway tools: GitHub's MCP server declares output schemas but answers with text
only, which mcp's ClientSession.call_tool refuses. The Gateway session calls tools
without that check and the belt reads the text, as it does for every server."""

from contextlib import asynccontextmanager

import pytest
from mcp import types

from docs_checker import gateway_tools
from docs_checker.gate import RecordingGate
from docs_checker.tools import ToolBelt
from tests.fakes import fixture
from tests.test_tools import IN_REPO

SCHEMA = fixture("tools_list")["tools"]["get_file_contents"]


class FakeSession:
    def __init__(self, log):
        self.log = log

    async def initialize(self):
        self.log.append("initialize")

    async def list_tools(self):
        tool = types.Tool.model_validate(
            {**SCHEMA, "name": "github___get_file_contents", "outputSchema": {"type": "object"}}
        )
        return types.ListToolsResult(tools=[tool])

    async def call_tool(self, *args, **kwargs):
        raise RuntimeError("Tool has an output schema but did not return structured content")

    async def send_request(self, request, result_type):
        params = request.root.params
        self.log.append(("call", params.name, params.arguments))
        return types.CallToolResult(content=[types.TextContent(type="text", text="chart: vault")])


@pytest.fixture
def sessions(monkeypatch):
    log: list = []

    @asynccontextmanager
    async def create_session(connection, **_):
        log.append(("connect", connection["url"]))
        yield FakeSession(log)

    monkeypatch.setattr(gateway_tools, "create_session", create_session)
    return log


async def test_gateway_tool_reads_text_without_structured_content(sessions):
    connection = {"transport": "streamable_http", "url": "https://gw.example/mcp"}
    tools = await gateway_tools.load_gateway_tools("github", connection)
    assert [t.name for t in tools] == ["github___get_file_contents"]
    belt = ToolBelt({"github": tools}, RecordingGate(), bindings={"github": ("get_file_contents",)})
    result, event = await belt.call("get_file_contents", IN_REPO, node="load", intent="i")
    assert result.ok and "chart: vault" in result.text and event["server"] == "github"
    calls = [entry for entry in sessions if entry[0] == "call"]
    assert calls == [("call", "github___get_file_contents", dict(IN_REPO))]


async def test_an_error_result_still_raises(sessions, monkeypatch):
    async def failing(self, request, result_type):
        return types.CallToolResult(
            content=[types.TextContent(type="text", text="404 Not Found")], isError=True
        )

    monkeypatch.setattr(FakeSession, "send_request", failing)
    connection = {"transport": "streamable_http", "url": "https://gw.example/mcp"}
    (tool,) = await gateway_tools.load_gateway_tools("github", connection)
    belt = ToolBelt(
        {"github": [tool]}, RecordingGate(), bindings={"github": ("get_file_contents",)}
    )
    result, _ = await belt.call("get_file_contents", IN_REPO, node="load", intent="i")
    assert not result.ok  # never a successful read; the status comes from the text
