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

# The read-only guarantee, made structural: only these MCP tool names are
# ever handed to the ReAct loop, regardless of what the remote MCP servers
# advertise. If a server is reconfigured (or a future version) starts
# exposing a write tool (e.g. `create_or_update_file`), it gets silently
# dropped here instead of becoming callable — the guarantee doesn't depend
# on trusting the server, only on this allowlist.
READ_ONLY_TOOLS = frozenset({"get_file_contents", "search_code", "get-catalog-entity"})


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
    get-catalog-entity) from the in-cluster MCP servers as LangChain tools.

    Filtered through READ_ONLY_TOOLS: whatever the MCP servers advertise,
    only the allowlisted read-only tools are bound into the ReAct loop.
    """
    client = MultiServerMCPClient(_mcp_server_config())
    tools_list = await client.get_tools()
    return [t for t in tools_list if t.name in READ_ONLY_TOOLS]


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


# --- doc retrieval: a prebuilt ReAct agent INSIDE one node -------------------


def _build_doc_agent(model, doc_tools, system_prompt: str):
    """Build the tool-calling loop for retrieval.

    LangGraph concept — create_react_agent vs a hand-built graph:
    `create_react_agent` compiles the standard agent loop for you — a model
    node with tools bound, a ToolNode that executes whichever tool the model
    called, and a `tools_condition` edge looping until the model stops
    calling tools. We hand-build the OUTER graph (auditable routing is the
    point of this migration) but use the prebuilt loop INSIDE retrieve,
    where "call read tools until you've gathered enough" is exactly the
    generic ReAct shape and hand-rolling it would add nothing.
    """
    try:
        from langgraph.prebuilt import create_react_agent
    except ImportError:
        # Newer stacks moved the prebuilt into langchain
        from langchain.agents import create_agent

        return create_agent(model, tools=doc_tools, system_prompt=system_prompt)
    return create_react_agent(model, doc_tools, prompt=system_prompt)


async def run_doc_retrieval(question: str, route: str) -> tuple[str, list[str]]:
    """Run the atlas→index→app traversal; return (findings, checked)."""
    from homelab_agent.model import get_model
    from homelab_agent.prompts import RETRIEVE_PROMPT

    doc_tools = await get_doc_tools()
    agent = _build_doc_agent(get_model(), doc_tools, RETRIEVE_PROMPT)
    result = await agent.ainvoke({"messages": [("user", f"Route: {route}\nQuestion: {question}")]})
    findings = result["messages"][-1].content

    checked = ["agent-docs MCP (get_file_contents / search_code)"]
    if route == "ownership":
        checked.append("backstage-catalog MCP (get-catalog-entity)")
    return findings, checked
