"""The StateGraph: nodes + edges.

LangGraph concept — a NODE is a plain function `state -> partial update`.
This module grows across tasks following the learning arc:
  Task 3: orient (this file's first node) wired orient → END
  Task 5: retrieve
  Task 6: delegate_k8s, drift_check, synthesize + conditional routing
"""

import logging

from langgraph.graph import END, StateGraph

from homelab_agent import tools
from homelab_agent.model import get_model, get_router_model
from homelab_agent.prompts import DRIFT_PROMPT, ROUTER_PROMPT, SYNTHESIZE_PROMPT
from homelab_agent.state import AgentState, Route

logger = logging.getLogger(__name__)

# Deterministic first pass, à la oncall-crewai's router: cheap, predictable,
# and it keeps the LLM out of the loop for the common phrasings.
_OWNERSHIP_KEYWORDS = (
    "who owns",
    "owner",
    "depends on",
    "dependency",
    "dependencies",
    "what system",
    "part of",
)
_LIVE_KEYWORDS = (
    "crashloop",
    "crashing",
    "pending",
    "stuck",
    "failing",
    "down",
    "healthy",
    "health",
    "status",
    "logs",
    "events",
    "restart",
    "running",
    "sync",
)
_DOCS_KEYWORDS = (
    "what is",
    "how does",
    "how do",
    "how is",
    "where does",
    "where is",
    "explain",
    "pattern",
    "onboard",
    "deploy a new",
)


def _keyword_route(question: str) -> Route | None:
    q = question.lower()
    if any(k in q for k in _OWNERSHIP_KEYWORDS):
        return "ownership"
    if any(k in q for k in _LIVE_KEYWORDS):
        return "live"
    if any(k in q for k in _DOCS_KEYWORDS):
        return "docs"
    return None  # ambiguous → LLM fallback


def orient(state: AgentState) -> dict:
    """Node 1: classify the question. Writes `route` (+ a one-line `plan`)."""
    question = state["question"]
    route = _keyword_route(question)
    if route is not None:
        return {"route": route, "plan": f"keyword-routed to '{route}'"}

    # Ambiguity: ask the cheap router model for a single-word verdict.
    try:
        reply = get_router_model().invoke(ROUTER_PROMPT.format(question=question))
        candidate = reply.content.strip().lower()
    except Exception as exc:  # LLM down ≠ agent down: degrade to docs-only
        logger.warning("router model failed (%s); defaulting to docs", exc)
        candidate = ""
    route = candidate if candidate in ("docs", "live", "ownership") else "docs"
    return {"route": route, "plan": f"llm-routed to '{route}'"}


async def retrieve(state: AgentState) -> dict:
    """Node 2: always runs. Doc retrieval via the ReAct sub-agent.

    Thin by design: the node owns the STATE contract (which fields it
    writes); tools.py owns the HOW. That keeps nodes trivially testable —
    tests patch tools.run_doc_retrieval and never touch MCP or the model.
    """
    findings, checked = await tools.run_doc_retrieval(state["question"], state["route"])
    return {"doc_findings": findings, "checked": checked}


async def delegate_k8s(state: AgentState) -> dict:
    """Node 3 (conditional): live-state lookup via the k8s-reader delegate."""
    reply = await tools.ask_k8s_reader(state["question"])
    return {"live_findings": reply, "checked": ["k8s-reader (A2A delegate)"]}


async def drift_check(state: AgentState) -> dict:
    """Node 4: docs vs live diff. Only reachable on the live path, so both
    inputs always exist when this runs (see routing below)."""
    reply = await get_model().ainvoke(
        DRIFT_PROMPT.format(
            docs=state.get("doc_findings", ""),
            live=state.get("live_findings", ""),
        )
    )
    text = reply.content.strip()
    if text.upper().startswith("NONE"):
        return {"drift": []}
    drift = [
        line.lstrip("- ").strip() for line in text.splitlines() if line.strip().startswith("-")
    ]
    return {"drift": drift}


async def synthesize(state: AgentState) -> dict:
    """Node 5: compose the final answer in the required response format."""
    reply = await get_model().ainvoke(
        SYNTHESIZE_PROMPT.format(
            question=state.get("question", ""),
            doc_findings=state.get("doc_findings", ""),
            live_findings=state.get("live_findings", ""),
            drift="\n".join(state.get("drift", [])) or "(none)",
            checked="\n".join(f"- {c}" for c in state.get("checked", [])),
        )
    )
    return {"answer": reply.content}


def needs_live(state: AgentState) -> str:
    """Conditional edge after retrieve.

    LangGraph concept — a conditional edge is a FUNCTION of state returning
    a label; add_conditional_edges maps labels to destination nodes. This is
    the deterministic branch point: only `route == "live"` visits the
    delegate; ownership/docs go straight to synthesize. Because branching is
    a routing DECISION (one path taken), not a fan-out (both paths taken),
    there is no join to stall and every node runs at most once — the
    correctness property the design doc calls out.
    """
    return "live" if state.get("route") == "live" else "docs"


def build_graph(checkpointer=None):
    """Assemble and compile the StateGraph.

    LangGraph concept — you declare nodes and edges on a StateGraph builder,
    then compile() it into a runnable. `set_entry_point` marks where START
    routes to; END is a sentinel, not a node you define.
    """
    g = StateGraph(AgentState)
    g.add_node("orient", orient)
    g.add_node("retrieve", retrieve)
    g.add_node("delegate_k8s", delegate_k8s)
    g.add_node("drift_check", drift_check)
    g.add_node("synthesize", synthesize)

    g.set_entry_point("orient")
    g.add_edge("orient", "retrieve")
    g.add_conditional_edges("retrieve", needs_live, {"live": "delegate_k8s", "docs": "synthesize"})
    g.add_edge("delegate_k8s", "drift_check")
    g.add_edge("drift_check", "synthesize")
    g.add_edge("synthesize", END)
    return g.compile(checkpointer=checkpointer)
