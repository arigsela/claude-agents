"""Test doubles: scripted chat models with usage metadata, fake MCP tools.

No network, no API key. The scripted model mimics what ChatAnthropic returns:
an ``AIMessage`` whose ``usage_metadata`` follows langchain-anthropic's
convention (``input_tokens`` is the whole prompt, cache tokens included).
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.tools import StructuredTool


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
    """Serves each branch from its own script (keyed by its specialist), so parallel
    Sends are deterministic."""

    def __init__(self, scripts: dict[str, list]):
        super().__init__([])
        self.scripts = {k: list(v) for k, v in scripts.items()}

    async def ainvoke(self, messages, *_, **__):
        self.calls.append(list(messages))
        task = json.loads(messages[1].content)
        return self.scripts[task["specialist"]].pop(0)


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

    async def get_file_contents(owner: str, repo: str, path: str) -> str:
        calls.append(("get_file_contents", path))
        return f"# {path}\nchart: vault\nversion: 0.30.1\n" + "x" * 10_000

    async def search_code(query: str) -> str:
        calls.append(("search_code", query))
        return "base-apps/vault/values.yaml"

    async def get_catalog_entity(kind: str, namespace: str, name: str) -> str:
        calls.append(("get-catalog-entity", name))
        return json.dumps(
            {
                "kind": "Component",
                "metadata": {"name": name, "namespace": namespace, "annotations": {"a": "b" * 500}},
                "spec": {"owner": "group:default/platform", "lifecycle": "production"},
                "relations": [{"type": "ownedBy"}] * 50,
            }
        )

    async def delete_file(path: str) -> str:  # a write tool a server might also expose
        calls.append(("delete_file", path))
        return "deleted"

    return [
        StructuredTool.from_function(
            coroutine=get_file_contents, name="get_file_contents", description="Read a file"
        ),
        StructuredTool.from_function(
            coroutine=search_code, name="search_code", description="Search code"
        ),
        StructuredTool.from_function(
            coroutine=get_catalog_entity, name="get-catalog-entity", description="Get entity"
        ),
        StructuredTool.from_function(
            coroutine=delete_file, name="delete_file", description="Delete a file"
        ),
    ]


DOCS_SERVER = "agent-docs-mcp"
CATALOG_SERVER = "backstage-catalog-mcp"

# What the AgentTemplate binds, per server. delete_file is bound on purpose: the
# code allowlist must refuse it even when a binding wrongly lists it.
FAKE_BINDINGS: dict[str, tuple[str, ...]] = {
    DOCS_SERVER: ("delete_file", "get_file_contents", "search_code"),
    CATALOG_SERVER: ("get-catalog-entity",),
}


def fake_tools_by_server(calls: list | None = None) -> dict[str, list[StructuredTool]]:
    """The fake tools grouped by the server that advertises them."""
    tools = {t.name: t for t in fake_tools(calls)}
    return {
        DOCS_SERVER: [tools["get_file_contents"], tools["search_code"], tools["delete_file"]],
        CATALOG_SERVER: [tools["get-catalog-entity"]],
    }


def fake_settings(env: dict | None = None):
    """Settings whose AgentTemplate binds the two fake servers (FAKE_BINDINGS)."""
    from docs_checker.config import load_settings

    config = {
        "http_tools": [
            {
                "params": {"url": f"http://{DOCS_SERVER}.kagent:3000/mcp"},
                "tools": list(FAKE_BINDINGS[DOCS_SERVER]),
            },
            {
                "params": {"url": f"http://{CATALOG_SERVER}.kagent:8080/mcp"},
                "tools": list(FAKE_BINDINGS[CATALOG_SERVER]),
            },
        ]
    }
    return load_settings({"KAGENT_CONFIG_JSON": json.dumps(config), **(env or {})})
