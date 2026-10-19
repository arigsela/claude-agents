"""Test doubles: scripted chat models with usage metadata, fake MCP tools.

No network, no API key. The scripted model mimics what ChatAnthropic returns:
an ``AIMessage`` whose ``usage_metadata`` follows langchain-anthropic's
convention (``input_tokens`` is the whole prompt, cache tokens included).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.tools import StructuredTool
from langchain_mcp_adapters.tools import convert_mcp_tool_to_langchain_tool
from mcp.types import CallToolResult, Tool

# Captured github-mcp-server answers (Task 5), redacted.
FIXTURES = Path(__file__).parent / "fixtures" / "mcp"


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


def usage(uncached: int, read: int = 0, write_5m: int = 0, output: int = 50) -> dict:
    return {
        "input_tokens": uncached + read + write_5m,
        "output_tokens": output,
        "total_tokens": uncached + read + write_5m + output,
        "input_token_details": {
            "cache_read": read,
            "cache_creation": 0,
            "ephemeral_5m_input_tokens": write_5m,
            "ephemeral_1h_input_tokens": 0,
        },
    }


def reply(text: str = "", tool_calls: list | None = None, **usage_kwargs: Any) -> AIMessage:
    return AIMessage(
        content=text,
        tool_calls=tool_calls or [],
        usage_metadata=usage(**usage_kwargs) if usage_kwargs else usage(100),
        response_metadata={"id": f"msg_{abs(hash(text)) % 10**8}", "stop_reason": "end_turn"},
    )


def tool_call(name: str, args: dict, call_id: str = "toolu_1") -> dict:
    return {"name": name, "args": args, "id": call_id, "type": "tool_call"}


class ScriptedModel:
    """Returns the scripted replies in order; raises scripted exceptions."""

    def __init__(self, replies: list[Any]):
        self.replies = list(replies)
        self.calls: list[list[Any]] = []
        self.bound_tools: list[str] | None = None

    def bind_tools(self, tools: list[Any], **_: Any) -> ScriptedModel:
        self.bound_tools = [t.name for t in tools]
        return self

    async def ainvoke(self, messages: list[Any], *_: Any, **__: Any) -> Any:
        self.calls.append(list(messages))
        if not self.replies:
            raise AssertionError("ScriptedModel ran out of replies")
        item = self.replies.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


class KeyedModel(ScriptedModel):
    """Serves each branch from its own script (keyed by its node), so parallel
    Sends are deterministic."""

    def __init__(self, scripts: dict[str, list]):
        super().__init__([])
        self.scripts = {k: list(v) for k, v in scripts.items()}

    async def ainvoke(self, messages, *_, **__):
        self.calls.append(list(messages))
        task = json.loads(messages[1].content)
        return self.scripts[task["node"]].pop(0)


class FakeModels:
    def __init__(self, **by_node: ScriptedModel):
        self.by_node = by_node

    def get(self, node: str) -> ScriptedModel:
        return self.by_node[node]

    def name(self, node: str) -> str:
        return "claude-sonnet-5-5"


class TransientError(Exception):
    status_code = 529


class BadRequestError(Exception):
    status_code = 400


def fake_tools(calls: list | None = None) -> list[StructuredTool]:
    calls = calls if calls is not None else []

    async def get_file_contents(owner: str, repo: str, path: str, sha: str = "") -> str:
        calls.append(("get_file_contents", path))
        return f"# {path}\nchart: vault\nversion: 0.30.1\n" + "x" * 10_000

    async def search_code(query: str) -> str:
        calls.append(("search_code", query))
        return "base-apps/vault/values.yaml"

    async def list_commits(owner: str, repo: str, path: str = "", sha: str = "") -> str:
        calls.append(("list_commits", path))
        return json.dumps([{"sha": FAKE_COMMIT}])

    async def get_commit(owner: str, repo: str, sha: str) -> str:
        calls.append(("get_commit", sha))
        return json.dumps({"sha": FAKE_COMMIT})

    async def delete_file(path: str) -> str:  # a write tool a server might also expose
        calls.append(("delete_file", path))
        return "deleted"

    return [
        StructuredTool.from_function(coroutine=fn, name=fn.__name__, description=fn.__name__)
        for fn in (get_file_contents, search_code, list_commits, get_commit, delete_file)
    ]


FAKE_COMMIT = "c0ffee" + "0" * 34
DOCS_SERVER = "agent-docs-mcp"

# What the AgentTemplate binds. delete_file is bound on purpose: the code
# allowlist must refuse it even when a binding wrongly lists it.
FAKE_BINDINGS: dict[str, tuple[str, ...]] = {
    DOCS_SERVER: (
        "delete_file",
        "get_commit",
        "get_file_contents",
        "list_commits",
        "search_code",
    ),
}


def fake_tools_by_server(calls: list | None = None) -> dict[str, list[StructuredTool]]:
    """The fake tools grouped by the server that advertises them."""
    return {DOCS_SERVER: fake_tools(calls)}


class FixtureSession:
    """Stands in for an MCP ClientSession: answers every call with one captured result."""

    def __init__(self, result: dict):
        self.result = CallToolResult.model_validate(result)
        self.calls: list[tuple[str, dict]] = []

    async def call_tool(self, name, arguments=None, progress_callback=None, **_):
        self.calls.append((name, arguments))
        return self.result


def adapter_tool(tool: str, result: dict, *, handle_tool_errors: bool = False):
    """The real langchain-mcp-adapters tool for the captured schema of ``tool``.

    ``handle_tool_errors=False`` is what ``server.load_mcp_tools`` uses (an isError
    result raises a ToolException); True returns it as a ToolMessage with
    status "error". The belt must read both.
    """
    schema = Tool.model_validate(fixture("tools_list")["tools"][tool])
    session = FixtureSession(result)
    converted = convert_mcp_tool_to_langchain_tool(
        session, schema, server_name=DOCS_SERVER, handle_tool_errors=handle_tool_errors
    )
    return converted, session


def fake_settings(env: dict | None = None, *, runtime: dict | None = None):
    """Settings whose AgentTemplate binds the fake server (FAKE_BINDINGS).

    The config is the alpha14 ``ADKConfig``; ``runtime`` fills its runtime block
    (``control_plane_url`` selects the controller TaskStore). Without it, local mode.
    """
    from docs_checker.config import load_settings

    agent = {
        "http_tools": [
            {
                "params": {"url": f"http://{DOCS_SERVER}.kagent:3000/mcp"},
                "tools": list(FAKE_BINDINGS[DOCS_SERVER]),
            },
        ]
    }
    config = {"runtime": runtime or {}, "agent": agent}
    return load_settings({"KAGENT_CONFIG_JSON": json.dumps(config), **(env or {})})
