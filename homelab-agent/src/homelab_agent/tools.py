"""External capabilities: MCP doc tools and the k8s-reader A2A delegate.

LangGraph concept — MCP tools as LangGraph tools:
`langchain-mcp-adapters`' MultiServerMCPClient speaks the MCP protocol to
remote servers and converts each discovered MCP tool into a LangChain `BaseTool`.
Anything that accepts LangChain tools (bind_tools, ToolNode, prebuilt agents)
can then call them — the graph never knows MCP is underneath.

Note: kagent does NOT inject MCP tools into BYO containers (Phase 0 finding
#3) — this module is the replacement wiring, pointed at the same in-cluster
MCP servers the Declarative agent used.
"""

import logging
import uuid

import httpx
from langchain_mcp_adapters.client import MultiServerMCPClient

from homelab_agent.config import settings

logger = logging.getLogger(__name__)

# Test seam: tests inject an httpx.MockTransport here.
_transport: httpx.AsyncBaseTransport | None = None


def _mcp_server_config() -> dict:
    """Build MultiServerMCPClient config from env (see README env table)."""
    agent_docs: dict = {
        "transport": "streamable_http",
        "url": settings.agent_docs_mcp_url,
    }
    if settings.agent_docs_mcp_auth_header:
        agent_docs["headers"] = {"Authorization": settings.agent_docs_mcp_auth_header}

    backstage: dict = {
        "transport": "streamable_http",
        "url": settings.backstage_mcp_url,
    }
    if settings.backstage_mcp_token:
        backstage["headers"] = {"Authorization": f"Bearer {settings.backstage_mcp_token}"}

    return {"agent_docs": agent_docs, "backstage_catalog": backstage}


async def get_doc_tools() -> list:
    """Discover the doc tools (get_file_contents, search_code,
    get-catalog-entity) from the in-cluster MCP servers as LangChain tools."""
    client = MultiServerMCPClient(_mcp_server_config())
    return await client.get_tools()


# --- A2A client (delegation is an HTTP call, not a CRD tool) -----------------

def _extract_a2a_text(result: dict) -> str:
    """Pull the text out of an A2A `message/send` result.

    The result may be a Task (text lives in artifacts, or in the final
    status message) or a direct Message. Mirrors the tolerant extraction
    oncall-crewai uses on the server side.
    """
    texts: list[str] = []

    def _collect(parts) -> None:
        for part in parts or []:
            text = part.get("text")
            if text:
                texts.append(text)

    for artifact in result.get("artifacts") or []:
        _collect(artifact.get("parts"))
    if not texts:
        message = (result.get("status") or {}).get("message") or {}
        _collect(message.get("parts"))
    if not texts and result.get("kind") == "message":
        _collect(result.get("parts"))
    return "\n".join(texts)


async def a2a_send(url: str, text: str, timeout: float = 120.0) -> str:
    """Send one A2A JSON-RPC `message/send` and return the reply text."""
    payload = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": "message/send",
        "params": {
            "message": {
                "kind": "message",
                "role": "user",
                "messageId": str(uuid.uuid4()),
                "parts": [{"kind": "text", "text": text}],
            }
        },
    }
    async with httpx.AsyncClient(timeout=timeout, transport=_transport) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()
    if "error" in data:
        raise RuntimeError(f"A2A error from {url}: {data['error'].get('message')}")
    return _extract_a2a_text(data.get("result") or {})


async def ask_k8s_reader(question: str) -> str:
    """Delegate a live-state question to the read-only k8s-reader agent.

    This replaces the Declarative agent's `type: Agent` CRD tool: in a BYO
    container, delegation is an explicit A2A client call from a graph node.
    Capability-transitivity is preserved — k8s-reader binds only read tools.
    """
    return await a2a_send(settings.k8s_reader_a2a_url, question)
