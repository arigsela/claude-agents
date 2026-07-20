"""Tools layer: MCP server config from env, and the A2A JSON-RPC client."""

import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from homelab_agent import tools


# --- MCP server config ------------------------------------------------------

def test_mcp_config_has_agent_docs_and_backstage(monkeypatch):
    monkeypatch.setenv("BACKSTAGE_MCP_TOKEN", "tok123")
    monkeypatch.setenv("AGENT_DOCS_MCP_AUTH_HEADER", "")
    # settings is module-level; rebuild from patched env for the test
    from homelab_agent.config import Settings
    with patch.object(tools, "settings", Settings.from_env()):
        cfg = tools._mcp_server_config()
    assert cfg["agent_docs"]["transport"] == "streamable_http"
    assert cfg["agent_docs"]["url"].endswith("/mcp")
    assert "headers" not in cfg["agent_docs"]  # no auth header configured
    assert cfg["backstage_catalog"]["headers"]["Authorization"] == "Bearer tok123"


def test_mcp_config_agent_docs_auth_header(monkeypatch):
    monkeypatch.setenv("AGENT_DOCS_MCP_AUTH_HEADER", "Basic abc=")
    from homelab_agent.config import Settings
    with patch.object(tools, "settings", Settings.from_env()):
        cfg = tools._mcp_server_config()
    assert cfg["agent_docs"]["headers"]["Authorization"] == "Basic abc="


# --- A2A text extraction ----------------------------------------------------

def test_extract_text_from_task_artifacts():
    result = {
        "artifacts": [
            {"parts": [{"kind": "text", "text": "vault is healthy"}]},
        ],
        "status": {"state": "completed"},
    }
    assert tools._extract_a2a_text(result) == "vault is healthy"


def test_extract_text_falls_back_to_status_message():
    result = {
        "artifacts": [],
        "status": {
            "state": "completed",
            "message": {"parts": [{"kind": "text", "text": "from status"}]},
        },
    }
    assert tools._extract_a2a_text(result) == "from status"


def test_extract_text_from_direct_message_result():
    result = {"kind": "message", "parts": [{"kind": "text", "text": "hi"}]}
    assert tools._extract_a2a_text(result) == "hi"


# --- a2a_send ---------------------------------------------------------------

async def test_a2a_send_posts_jsonrpc_and_returns_text():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": captured["body"]["id"],
                "result": {
                    "artifacts": [{"parts": [{"kind": "text", "text": "3 pods Running"}]}],
                    "status": {"state": "completed"},
                },
            },
        )

    transport = httpx.MockTransport(handler)
    with patch.object(tools, "_transport", transport):
        reply = await tools.a2a_send("http://fake-agent:8080", "pods in vault ns?")

    assert reply == "3 pods Running"
    body = captured["body"]
    assert body["method"] == "message/send"
    assert body["params"]["message"]["role"] == "user"
    assert body["params"]["message"]["parts"][0]["text"] == "pods in vault ns?"


async def test_a2a_send_raises_on_jsonrpc_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": "1",
                  "error": {"code": -32600, "message": "bad request"}},
        )

    with patch.object(tools, "_transport", httpx.MockTransport(handler)):
        with pytest.raises(RuntimeError, match="bad request"):
            await tools.a2a_send("http://fake-agent:8080", "q")


async def test_ask_k8s_reader_targets_configured_url():
    with patch.object(tools, "a2a_send", new=AsyncMock(return_value="ok")) as mock_send:
        out = await tools.ask_k8s_reader("is vault healthy?")
    assert out == "ok"
    mock_send.assert_awaited_once_with(
        tools.settings.k8s_reader_a2a_url, "is vault healthy?"
    )


# --- get_doc_tools read-only allowlist ---------------------------------------

class _FakeTool:
    def __init__(self, name: str):
        self.name = name


async def test_get_doc_tools_filters_to_read_only_allowlist():
    """Structural enforcement of the read-only guarantee: even if the MCP
    server advertises a write tool (server-side reconfiguration, a new
    server version, ...), get_doc_tools must never hand it to the ReAct
    loop. Filtering client-side means the guarantee doesn't depend on the
    remote server behaving."""
    fake_tools = [
        _FakeTool("get_file_contents"),
        _FakeTool("search_code"),
        _FakeTool("get-catalog-entity"),
        _FakeTool("create_or_update_file"),  # write tool: must be dropped
        _FakeTool("delete_file"),  # write tool: must be dropped
    ]
    with patch.object(
        tools.MultiServerMCPClient, "get_tools", AsyncMock(return_value=fake_tools)
    ):
        result = await tools.get_doc_tools()

    names = {t.name for t in result}
    assert names == {"get_file_contents", "search_code", "get-catalog-entity"}


# --- run_doc_retrieval -------------------------------------------------------

async def test_run_doc_retrieval_invokes_react_agent_and_reports_checked():
    class FakeAgent:
        def __init__(self):
            self.received_payload = None

        async def ainvoke(self, payload):
            self.received_payload = payload

            class Msg:
                content = "found: base-apps/cert-manager/docs.md"
            return {"messages": [Msg()]}

    agent = FakeAgent()
    with patch.object(tools, "get_doc_tools", new=AsyncMock(return_value=[])), \
         patch.object(tools, "_build_doc_agent", return_value=agent):
        findings, checked = await tools.run_doc_retrieval("what is cert-manager?", "docs")

    assert "cert-manager" in findings
    assert checked == ["agent-docs MCP (get_file_contents / search_code)"]

    user_message = agent.received_payload["messages"][0][1]
    assert user_message == "Route: docs\nQuestion: what is cert-manager?"


async def test_run_doc_retrieval_ownership_route_reports_backstage():
    class FakeAgent:
        def __init__(self):
            self.received_payload = None

        async def ainvoke(self, payload):
            self.received_payload = payload

            class Msg:
                content = "owner: platform-engineering"
            return {"messages": [Msg()]}

    agent = FakeAgent()
    with patch.object(tools, "get_doc_tools", new=AsyncMock(return_value=[])), \
         patch.object(tools, "_build_doc_agent", return_value=agent):
        findings, checked = await tools.run_doc_retrieval("who owns vault?", "ownership")

    assert checked == [
        "agent-docs MCP (get_file_contents / search_code)",
        "backstage-catalog MCP (get-catalog-entity)",
    ]

    user_message = agent.received_payload["messages"][0][1]
    assert user_message == "Route: ownership\nQuestion: who owns vault?"
