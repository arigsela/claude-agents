"""The StateGraph: nodes + edges.

LangGraph concept — a NODE is a plain function `state -> partial update`.
This module grows across tasks following the learning arc:
  Task 3: orient (this file's first node) wired orient → END
  Task 5: retrieve
  Task 6: delegate_k8s, drift_check, synthesize + conditional routing
"""

import logging

from langgraph.graph import END, StateGraph

from homelab_agent.model import get_router_model
from homelab_agent.prompts import ROUTER_PROMPT
from homelab_agent.state import AgentState, Route

logger = logging.getLogger(__name__)

# Deterministic first pass, à la oncall-crewai's router: cheap, predictable,
# and it keeps the LLM out of the loop for the common phrasings.
_OWNERSHIP_KEYWORDS = (
    "who owns", "owner", "depends on", "dependency", "dependencies",
    "what system", "part of",
)
_LIVE_KEYWORDS = (
    "crashloop", "crashing", "pending", "stuck", "failing", "down",
    "healthy", "health", "status", "logs", "events", "restart",
    "running", "sync",
)
_DOCS_KEYWORDS = (
    "what is", "how does", "how do", "how is", "where does", "where is",
    "explain", "pattern", "onboard", "deploy a new",
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


def build_graph(checkpointer=None):
    """Assemble and compile the StateGraph.

    LangGraph concept — you declare nodes and edges on a StateGraph builder,
    then compile() it into a runnable. `set_entry_point` marks where START
    routes to; END is a sentinel, not a node you define.
    """
    g = StateGraph(AgentState)
    g.add_node("orient", orient)
    g.set_entry_point("orient")
    g.add_edge("orient", END)  # extended in later tasks
    return g.compile(checkpointer=checkpointer)
