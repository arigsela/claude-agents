"""The StateGraph: nodes + edges.

LangGraph concept — a NODE is a plain function `state -> partial update`.
This module grows across tasks following the learning arc:
  Task 3: orient (this file's first node) wired orient → END
  Task 5: retrieve
  Task 6: delegate_k8s, drift_check, synthesize + conditional routing
"""

import logging
import re
import uuid

from langgraph.graph import END, StateGraph

from homelab_agent import tools
from homelab_agent.config import settings
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


def _compile_phrase_patterns(phrases: tuple[str, ...]) -> list[re.Pattern]:
    """Word-boundary-anchored patterns for a keyword tuple.

    Anchored on the LEFT (`\\b` before the phrase) only, case-insensitively.
    That's enough to stop a phrase matching mid-word inside an unrelated
    word — e.g. LIVE's "down" no longer fires on "markdown" (no boundary
    between "mark" and "down"), and OWNERSHIP's "part of" no longer fires
    inside "counterpart of" — while still allowing a phrase to match as the
    PREFIX of a longer word, e.g. LIVE's "crashloop" still fires on
    "CrashLooping"/"CrashLoopBackOff". A trailing `\\b` would break that
    legitimate case, so it's intentionally left off.
    """
    return [re.compile(r"\b" + re.escape(phrase), re.IGNORECASE) for phrase in phrases]


_OWNERSHIP_PATTERNS = _compile_phrase_patterns(_OWNERSHIP_KEYWORDS)
_LIVE_PATTERNS = _compile_phrase_patterns(_LIVE_KEYWORDS)
_DOCS_PATTERNS = _compile_phrase_patterns(_DOCS_KEYWORDS)


def _keyword_route(question: str) -> Route | None:
    if any(p.search(question) for p in _OWNERSHIP_PATTERNS):
        return "ownership"
    if any(p.search(question) for p in _LIVE_PATTERNS):
        return "live"
    if any(p.search(question) for p in _DOCS_PATTERNS):
        return "docs"
    return None  # ambiguous → LLM fallback


def orient(state: AgentState) -> dict:
    """Node 1: classify the question. Writes `route` (+ a one-line `plan`).

    orient is always the first node of a turn, so it also resets per-turn
    state: `checked`/`drift`: None is the accumulate() reset sentinel (see
    state.py) that wipes entries a *previous* turn left behind; `live_findings`:
    "" resets the plain scalar the same way — it's written only by
    delegate_k8s (the live path), so without this it would survive
    untouched on a persisted checkpointer thread and leak a stale live
    answer into a later docs-route turn's synthesize prompt. Safe because
    last-writer-wins: delegate_k8s overwrites it again on live turns.
    """
    question = state["question"]
    reset = {"checked": None, "drift": None, "live_findings": "", "memory_findings": ""}
    route = _keyword_route(question)
    if route is not None:
        return {"route": route, "plan": f"keyword-routed to '{route}'", **reset}

    # Ambiguity: ask the cheap router model for a single-word verdict.
    try:
        reply = get_router_model().invoke(ROUTER_PROMPT.format(question=question))
        candidate = reply.content.strip().lower()
    except Exception as exc:  # LLM down ≠ agent down: degrade to docs-only
        logger.warning("router model failed (%s); defaulting to docs", exc)
        candidate = ""
    route = candidate if candidate in ("docs", "live", "ownership") else "docs"
    return {"route": route, "plan": f"llm-routed to '{route}'", **reset}


async def recall(state: AgentState, *, store=None) -> dict:
    """Node: semantic recall of similar past exchanges (no-op without a store).

    LangGraph injects `store` (the one passed to build_graph/compile) by
    parameter name; it is None when memory is unconfigured, so this node
    degrades to a no-op exactly like the store factory does.
    """
    if store is None:
        return {}
    namespace = (settings.memory_namespace, "memories")
    hits = store.search(namespace, query=state["question"], limit=settings.memory_top_k)
    kept = [h for h in hits if (h.score or 0.0) >= settings.memory_similarity_floor]
    if not kept:
        return {}
    findings = "\n".join(
        f"- Q: {h.value.get('question', '')}\n  A: {h.value.get('answer', '')}" for h in kept
    )
    label = f"memory ({len(kept)} prior exchange{'s' if len(kept) != 1 else ''})"
    return {"memory_findings": findings, "checked": [label]}


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
    # re.sub, not str.lstrip("- "): lstrip strips a CHARACTER SET, so it
    # would eat the leading "-" off a legitimate negative number too (e.g.
    # "- -1 replica..." -> "1 replica..." instead of "-1 replica...").
    # The regex only strips the bullet marker itself: one leading "-" plus
    # its following whitespace.
    drift = [
        re.sub(r"^-\s*", "", line.strip())
        for line in text.splitlines()
        if line.strip().startswith("-")
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
            memory_findings=state.get("memory_findings", "") or "(none)",
        )
    )
    return {"answer": reply.content}


async def remember(state: AgentState, *, store=None) -> dict:
    """Node: persist this turn's (question, answer) exchange (no-op without a store)."""
    if store is None:
        return {}
    namespace = (settings.memory_namespace, "memories")
    store.put(
        namespace,
        str(uuid.uuid4()),
        {"question": state.get("question", ""), "answer": state.get("answer", "")},
    )
    return {}


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


def build_graph(checkpointer=None, store=None):
    """Assemble and compile the StateGraph.

    LangGraph concept — you declare nodes and edges on a StateGraph builder,
    then compile() it into a runnable. `set_entry_point` marks where START
    routes to; END is a sentinel, not a node you define.
    """
    g = StateGraph(AgentState)
    g.add_node("orient", orient)
    g.add_node("recall", recall)
    g.add_node("retrieve", retrieve)
    g.add_node("delegate_k8s", delegate_k8s)
    g.add_node("drift_check", drift_check)
    g.add_node("synthesize", synthesize)
    g.add_node("remember", remember)

    g.set_entry_point("orient")
    g.add_edge("orient", "recall")
    g.add_edge("recall", "retrieve")
    g.add_conditional_edges("retrieve", needs_live, {"live": "delegate_k8s", "docs": "synthesize"})
    g.add_edge("delegate_k8s", "drift_check")
    g.add_edge("drift_check", "synthesize")
    g.add_edge("synthesize", "remember")
    g.add_edge("remember", END)
    return g.compile(checkpointer=checkpointer, store=store)
