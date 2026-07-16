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
