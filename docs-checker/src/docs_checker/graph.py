"""The audit graph: one run of docs-checker, from the request to the report.

    START -> intake -> scope -> dispatch --Send("doc") x N--> doc -> dispatch
                 |        |        |                                   |
               (refused   (failed  +-----------------> collect -> report -> END
                or failed) scope)

- ``intake`` reads the request (``parse_request``; Haiku only for free text, and
  off-topic text is refused) and resolves its ref to the run's one commit (C#18).
- ``scope`` discovers or validates the docs (bounded), parses each one's front
  matter (a malformed one is ``failed``) and, in scheduled mode with
  ``short_circuit`` on, skips unchanged docs with their carried findings.
- ``dispatch`` fans out: with ``cache_prefix`` on the first doc goes alone, so
  the prompt cache is warm for the rest (C#41); after every round it sends what
  is still pending. In interactive mode, docs skipped for budget are offered once
  through ``interrupt``: an approval raises the limit by the same amount and
  re-sends only them, and nothing is judged twice (C#26).
- ``doc`` runs the per-doc subgraph (``graph_doc.py``) and adapts its output to
  ``{"outcomes": {doc: outcome}}``.
- ``collect`` drops dismissed findings, applies the confidence split and writes
  memory (checked docs, scheduled mode only).
- ``report`` renders the Markdown and the ``Report``; with ``typed_handoffs`` off
  one extra model call writes a report from the transcripts (C#40).

``RunDeps`` is the runtime context: never checkpointed, rebuilt per turn by the
executor. Everything a resume needs beyond the checkpoint is in the task's replay
memo (``replay``): tool results, extractions, fixes and decisions. The executor
keeps the memo and the ledger of a paused task (``paused.PausedTasks``), in the
checkpoint db in production, so a resume after a restart has them too.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any, TypedDict

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.utils.function_calling import convert_to_openai_tool
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import Send, interrupt

from docs_checker import prompts
from docs_checker.config import Settings, load_settings
from docs_checker.dismissals import Dismissal, is_dismissed, parse_dismissals
from docs_checker.frontmatter import DocMeta, FrontMatterError, SourceRef, parse_front_matter
from docs_checker.gate import FixGate
from docs_checker.graph_doc import NEEDS_LOOK_BELOW, DocState, build_doc_graph, reader_for
from docs_checker.ledger import BudgetExceeded, CostLedger, Outcome
from docs_checker.levers import Levers
from docs_checker.llm import call_model
from docs_checker.memory import CHECKER_KEY, SnapshotStore, fingerprint, skip_unchanged
from docs_checker.models import ModelSet, no_tools_choice
from docs_checker.nodes import classify_intake
from docs_checker.prompts import CHECKER_VERSION, fence, fence_token
from docs_checker.redact import redact
from docs_checker.repo import ReadResult, RefError, RepoReader, resolve_commit
from docs_checker.report import Report, render_report
from docs_checker.request import RunRequest, parse_request
from docs_checker.scope import DiscoveryError, discover
from docs_checker.state import (
    Claim,
    Decision,
    DocOutcome,
    Evidence,
    Finding,
    OutcomeMap,
    Window,
)
from docs_checker.tools import ToolBelt, _approved

logger = logging.getLogger(__name__)

DISMISSALS_PATH = "docs/docs-checker-dismissed.yaml"
REFUSAL = (
    "docs-checker only checks the documentation in arigsela/kubernetes against the "
    "manifests it describes (read-only). Ask it to check all docs or named doc files."
)

# Every type the checkpointer may meet in the state, for the serializer's allowlist.
STATE_TYPES: tuple[type, ...] = (
    Claim,
    Window,
    Evidence,
    Decision,
    Finding,
    DocOutcome,
    Report,
    RunRequest,
    DocMeta,
    SourceRef,
    ReadResult,
)


class DecisionMemo:
    """In-run reuse of judgements, single-flight (C#8): one ``asyncio.Future`` per
    key, so concurrent misses on the same key compute once and the others wait.
    Keyed by ``Claim.semantic_key(CHECKER_VERSION, evidence_hash)``; the caller
    attaches its own claim id afterwards.

    A failed computation is not kept, and it fails only the doc that ran it: a
    waiter whose owner raised treats the key as a miss and computes it itself
    (ruling L1), so one doc's provider error never decides another doc's claim. A
    cancellation is passed on as is."""

    def __init__(self) -> None:
        self._futures: dict[str, asyncio.Future[Decision]] = {}

    def peek(self, key: str) -> Decision | None:
        future = self._futures.get(key)
        if future is None or not future.done() or future.cancelled() or future.exception():
            return None
        return future.result()

    async def get_or_compute(
        self, key: str, factory: Callable[[], Awaitable[Decision]]
    ) -> Decision:
        while (future := self._futures.get(key)) is not None:
            try:
                # shield: a waiter cancelled must not cancel the shared future
                return await asyncio.shield(future)
            except asyncio.CancelledError:
                raise
            except Exception as error:  # noqa: BLE001 - the owner failed, its key is gone
                logger.info("shared judgement failed (%s); computing it here", type(error).__name__)
                continue
        future = asyncio.get_running_loop().create_future()
        self._futures[key] = future
        try:
            decision = await factory()
        except BaseException as error:
            self._futures.pop(key, None)
            if not future.done():
                future.set_exception(error)
                future.exception()  # retrieved: no "never retrieved" warning
            raise
        future.set_result(decision)
        return decision


@dataclass
class RunDeps:
    """Per-run dependencies, passed as LangGraph runtime context (never checkpointed).

    Satisfies ``nodes.NodeContext`` (models, ledger, levers, settings, belt). The
    reader, store and dismissals are built inside the graph from the run's commit
    and request, and cached here for the turn; a new turn rebuilds them.
    """

    models: ModelSet
    belt: ToolBelt
    ledger: CostLedger
    settings: Settings = field(default_factory=lambda: load_settings({}))
    levers: Levers | None = None
    # One A2A task's memo of completed model replies and tool results. LangGraph
    # re-runs an interrupted node from its start on resume; with the memo the
    # re-run replays that work instead of paying for it (or running a tool)
    # again. None turns it off (each re-run is fresh).
    replay: dict[str, Any] | None = None
    # The last check on every proposed fix (``FixGate.check``) before it reaches the
    # report or a person. The executor passes the one production builds
    # (``gate.build_fix_gate``); left out, it is still the rules gate, never none.
    fix_gate: FixGate = field(default_factory=FixGate)
    reader: RepoReader | None = None
    decisions: DecisionMemo = field(default_factory=DecisionMemo)
    store: SnapshotStore | None = None
    dismissals: tuple[list[Dismissal], list[str]] | None = None

    def __post_init__(self) -> None:
        if self.levers is None:
            self.levers = self.settings.levers


def budget_limit(request: RunRequest, settings: Settings) -> float:
    """The run budget a request gets (C#1): the whole-repo budget for ``all``, else one
    doc's budget for each doc it names."""
    if request.scope == "all":
        return settings.run_budget_all_usd
    return settings.run_budget_doc_usd * len(request.scope)


def run_config(task_id: str, settings: Settings, levers: Levers) -> dict:
    """One checkpointer thread per A2A task, not per conversation (a HITL resume
    continues the same task, so it finds its paused thread); the recursion limit
    (lever 5: LangGraph's 10007 default with ``retry_limits`` off) and the doc
    concurrency (C#7: a run setting, not a compile one)."""
    return {
        "configurable": {"thread_id": task_id},
        "recursion_limit": settings.recursion_limit if levers.retry_limits else 10007,
        "max_concurrency": settings.concurrency,
    }


def checkpoint_serde() -> JsonPlusSerializer:
    """The checkpoint serializer that admits exactly the state's own types."""
    return JsonPlusSerializer(allowed_msgpack_modules=STATE_TYPES)


@asynccontextmanager
async def open_checkpointer(path: str) -> AsyncIterator[Any]:
    """The production checkpointer: ``AsyncSqliteSaver`` at ``path`` (its parent
    directory created first, C#5), open for the server's lifetime."""
    import aiosqlite
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    Path(path).parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(path) as conn:
        yield AsyncSqliteSaver(conn, serde=checkpoint_serde())


def _merge_lists(
    old: dict[str, list[str]] | None, new: dict[str, list[str]]
) -> dict[str, list[str]]:
    return {**(old or {}), **new}


class RunState(TypedDict, total=False):
    text: str
    request: RunRequest
    commit: str
    search: bool
    docs: list[DocMeta]
    truncated: bool
    outcomes: OutcomeMap
    skipped_sources: Annotated[dict[str, list[str]], _merge_lists]
    round: int
    next_docs: list[str]
    continued: bool
    notes: list[str]
    report: str
    report_data: Report
    outcome: Outcome


# --- intake ----------------------------------------------------------------------------


def _refused(reason: str) -> dict:
    return {"outcome": "refused", "report": f"Request refused: {reason}\n\n{REFUSAL}\n"}


async def intake(state: RunState, runtime: Runtime[RunDeps]) -> dict:
    deps = runtime.context
    request = state.get("request")
    if request is None:
        text = state.get("text") or ""
        try:
            request = parse_request(text, None, max_paths=deps.settings.max_docs)
            if request is None:
                classified = await classify_intake(text, deps)
                if classified == "off_topic":
                    return _refused("the request is not a docs check")
                request = classified
                # The executor sized the budget for this intake call alone; the scope
                # is known now (C#1).
                deps.ledger.budget.limit_usd = budget_limit(request, deps.settings)
        except ValueError as error:
            return _refused(f"the request could not be read ({error})")
    try:
        commit = await resolve_commit(deps.belt, request.ref, memo=deps.replay)
    except RefError as error:
        return {
            "request": request,
            "outcome": "failed",
            "report": f"docs-checker failed: {error}\n",
        }
    return {"request": request, "commit": commit}


def _after_intake(state: RunState) -> str:
    return "scope" if state.get("commit") else END


# --- scope -----------------------------------------------------------------------------


async def _search_allowed(deps: RunDeps, request: RunRequest, commit: str) -> bool:
    """Searches run against the default branch only (C#17), so only a run at its
    head may use them, and only when the operator enabled search (ruling S1)."""
    if not deps.settings.search_enabled:
        return False
    if request.ref in ("main", "HEAD"):
        return True
    try:
        head = await resolve_commit(deps.belt, "main", node="scope", memo=deps.replay)
    except RefError:
        return False
    return head == commit


def _failed_doc(path: str, commit: str, reason: str) -> DocOutcome:
    return DocOutcome(doc=path, commit=commit, status="failed", reason=reason)


async def scope(state: RunState, runtime: Runtime[RunDeps]) -> dict:
    deps = runtime.context
    request, commit = state["request"], state["commit"]
    search = await _search_allowed(deps, request, commit)
    reader = reader_for(deps, commit, search)
    if deps.store is None:  # the executor loads the request's memory; tests may not
        deps.store = SnapshotStore.from_snapshot(request.memory, mode=request.mode)
    if request.scope == "all":
        try:
            paths, truncated = await discover(reader, max_docs=deps.settings.max_docs)
        except DiscoveryError as error:
            return {"outcome": "failed", "report": f"docs-checker failed: {error}\n"}
    else:
        paths, truncated = list(request.scope), False
    docs: list[DocMeta] = []
    outcomes: dict[str, DocOutcome] = {}
    remember = request.mode == "scheduled" and deps.levers.short_circuit
    for path in paths:
        result = await reader.read(path, node="scope")
        if not result.found:
            outcomes[path] = _failed_doc(
                path, commit, f"the doc could not be read ({result.status})"
            )
            continue
        try:
            meta = parse_front_matter(path, result.text or "")
        except FrontMatterError as error:
            outcomes[path] = _failed_doc(path, commit, f"front matter: {error.reason}")
            continue
        if not meta.sources:
            outcomes[path] = _failed_doc(path, commit, "the front matter lists no sources")
            continue
        stored = deps.store.get_doc(path) if remember else None
        if stored:
            known = [k for k in stored.get("fingerprint", {}) if k != CHECKER_KEY]
            current = await fingerprint(meta, reader, known, CHECKER_VERSION)
            if skip_unchanged(meta, stored, current):
                # Rebased onto this run's commit (C#18): the lines are still there,
                # at this commit, and the report names only this commit.
                carried = [
                    Finding.model_validate(f).model_copy(update={"carried": True, "commit": commit})
                    for f in stored.get("open_findings", [])
                ]
                outcomes[path] = DocOutcome(
                    doc=path,
                    commit=commit,
                    status="unchanged",
                    findings=carried,
                    fingerprint=current,
                )
                continue
        docs.append(meta)
    return {
        "docs": docs,
        "outcomes": outcomes,
        "truncated": truncated,
        "search": search,
        "round": 0,
        "continued": False,
    }


def _after_scope(state: RunState) -> str:
    return END if state.get("outcome") == "failed" else "dispatch"


# --- dispatch --------------------------------------------------------------------------


def _digest(*parts: object) -> str:
    blob = json.dumps(list(parts), ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:24]


async def dispatch(state: RunState, runtime: Runtime[RunDeps]) -> dict:
    """What to send next: the pending docs (the first one alone when warming the
    prompt cache), or, once, the docs skipped for budget after an approval."""
    deps = runtime.context
    outcomes = state.get("outcomes") or {}
    pending = [m.path for m in state.get("docs") or [] if m.path not in outcomes]
    rnd = state.get("round", 0)
    if pending:
        if rnd == 0 and deps.levers.cache_prefix and len(pending) > 1:
            return {"next_docs": pending[:1], "round": 1}
        return {"next_docs": pending, "round": rnd + 1}
    skipped = [p for p, o in outcomes.items() if o.status == "skipped-budget"]
    budget = deps.ledger.budget
    if (
        skipped
        and state["request"].mode == "interactive"
        and not state.get("continued")
        and budget.limit_usd is not None
    ):
        limit = budget.limit_usd
        digest = _digest(state["commit"], sorted(skipped), limit)
        spent = round(budget.spent_usd, 6)
        reply = interrupt(
            {
                "action_requests": [
                    {
                        "name": "raise_budget",
                        "id": digest,
                        "call_id": digest,
                        "args": {
                            "spent_usd": spent,
                            "limit_usd": limit,
                            "raise_by_usd": limit,
                            "docs": skipped,
                        },
                    }
                ],
                "hint": (
                    f"The run budget of ${limit:.2f} is spent (${spent:.4f}); "
                    f"{len(skipped)} docs were skipped. Approve to raise it by "
                    f"${limit:.2f} and check them."
                ),
            }
        )
        if _approved(reply, digest):
            budget.limit_usd = limit + limit
            return {"next_docs": skipped, "continued": True, "round": rnd + 1}
        return {"next_docs": [], "continued": True}
    return {"next_docs": []}


def _route(state: RunState) -> list[Send] | str:
    wanted = state.get("next_docs") or []
    if not wanted:
        return "collect"
    by_path = {m.path: m for m in state.get("docs") or []}
    sends = [
        Send(
            "doc",
            DocState(
                meta=by_path[path],
                commit=state["commit"],
                mode=state["request"].mode,
                search=state.get("search", False),
            ),
        )
        for path in wanted
        if path in by_path
    ]
    return sends or "collect"  # an empty list of Sends would end the run without a report


# --- doc (the subgraph, adapted) -------------------------------------------------------

DOC_GRAPH = build_doc_graph()


async def doc(state: DocState, runtime: Runtime[RunDeps], config: RunnableConfig) -> dict:
    """One doc's branch: the subgraph's outcome, keyed by doc for the reducer."""
    result = await DOC_GRAPH.ainvoke(state, config, context=runtime.context)
    outcome: DocOutcome = result["outcome"]
    return {
        "outcomes": {outcome.doc: outcome},
        "skipped_sources": {outcome.doc: list(result.get("skipped_sources") or [])},
    }


# --- collect ---------------------------------------------------------------------------


async def _dismissals(deps: RunDeps, reader: RepoReader) -> tuple[list[Dismissal], list[str]]:
    """Ari's dismissals from the repo at the run's commit; absent is none, a failed
    read is none plus a note."""
    if deps.dismissals is None:
        result = await reader.read(DISMISSALS_PATH, node="scope")
        if result.found:
            deps.dismissals = parse_dismissals(result.text)
        elif result.status == "absent":
            deps.dismissals = ([], [])
        else:
            deps.dismissals = ([], [f"{DISMISSALS_PATH} could not be read ({result.status})"])
    return deps.dismissals


async def collect(state: RunState, runtime: Runtime[RunDeps]) -> dict:
    deps = runtime.context
    request, commit = state["request"], state["commit"]
    reader = reader_for(deps, commit, state.get("search", False))
    if deps.store is None:  # a new turn after a pause: rebuilt from the request
        deps.store = SnapshotStore.from_snapshot(request.memory, mode=request.mode)
    dismissals, errors = await _dismissals(deps, reader)
    today = dt.date.today()
    outcomes: dict[str, DocOutcome] = {}
    for path, outcome in (state.get("outcomes") or {}).items():
        kept = [
            f.model_copy(update={"needs_look": f.needs_look or f.confidence < NEEDS_LOOK_BELOW})
            for f in outcome.findings
            if not is_dismissed(f, dismissals, today)
        ]
        updated = outcome.model_copy(update={"findings": kept})
        outcomes[path] = updated
        if request.mode == "scheduled" and updated.status == "checked":
            deps.store.put_doc(
                path,
                status="checked",
                fingerprint=updated.fingerprint,
                checker=CHECKER_VERSION,
                open_findings=[f.model_dump() for f in kept],
            )
    return {"outcomes": outcomes, "notes": list(errors)}


# --- report ----------------------------------------------------------------------------


async def _report_from_transcripts(deps: RunDeps, outcomes: dict[str, DocOutcome], commit) -> str:
    """Lever 2 off: one model call that writes a report from the branches' transcripts
    (the synthetic anti-pattern, C#40). Its text is appended to the typed report."""
    width = deps.settings.max_line_chars
    blocks = []
    for path, outcome in sorted(outcomes.items()):
        if outcome.transcript:
            text = "\n".join(line[:width] for line in "\n\n".join(outcome.transcript).split("\n"))
            blocks.append(f"Doc {path}:\n{fence(text, fence_token(commit, path, 0, 0))}")
    if not blocks:
        return ""
    model = deps.models.get("report")
    tools = [] if deps.levers.tools_on_demand else deps.belt.schemas_for("report")
    if tools:
        model = model.bind_tools(tools, tool_choice=no_tools_choice())
    messages = [
        prompts.system_message(
            prompts.REPORT, cache=deps.levers.cache_prefix, ttl=deps.settings.cache_ttl
        ),
        HumanMessage(prompts.REPORT_USER.format(transcripts="\n\n".join(blocks))),
    ]
    try:
        result = await call_model(
            model,
            messages,
            node="report",
            model_name=deps.models.name("report"),
            ledger=deps.ledger,
            max_tokens=deps.settings.node_models["report"].max_tokens,
            overhead_chars=sum(len(json.dumps(convert_to_openai_tool(t))) for t in tools),
        )
    except BudgetExceeded:
        return "(the model-written report was skipped: the run budget is spent)"
    except Exception as error:  # noqa: BLE001 - ruling L1: the typed report stands
        logger.warning("the model-written report failed: %s", type(error).__name__)
        return f"(the model-written report failed: {type(error).__name__})"
    content = getattr(result, "content", result)
    if isinstance(content, list):
        content = "\n".join(
            str(b.get("text", "")) if isinstance(b, dict) else str(b) for b in content
        )
    return str(content)


async def report(state: RunState, runtime: Runtime[RunDeps]) -> dict:
    deps = runtime.context
    outcomes = state.get("outcomes") or {}
    commit = state.get("commit") or ""
    complete = all(o.status in ("checked", "unchanged") for o in outcomes.values())
    outcome: Outcome = "verified" if complete and not state.get("truncated") else "unverified"
    extra = (
        "" if deps.levers.typed_handoffs else await _report_from_transcripts(deps, outcomes, commit)
    )
    summary = deps.ledger.summary(outcome)  # after the extra call, so it is in the spend
    skipped = [
        f"{path}: {item}"
        for path, items in sorted((state.get("skipped_sources") or {}).items())
        for item in items
    ]
    notes = {
        "truncated": bool(state.get("truncated")),
        "skipped_sources": skipped,
        "dismissal_errors": state.get("notes") or [],
        "lines": list(deps.ledger.lower_bound),  # e.g. "cost after restart is a lower bound"
    }
    markdown, data = render_report(
        outcomes.values(), run_id=deps.ledger.run_id, commit=commit, summary=summary, notes=notes
    )
    if extra:
        markdown += (
            "\n## Report written by the model from the transcripts (typed handoffs off)\n\n"
            f"{redact(extra)}\n"
        )
    return {"report": markdown, "report_data": data, "outcome": outcome}


# --- the graph -------------------------------------------------------------------------


def build_graph(*, checkpointer: Any):
    """The compiled parent graph on ``checkpointer`` (``open_checkpointer`` in
    production, an ``InMemorySaver`` in tests); the per-doc subgraph shares it."""
    graph = StateGraph(RunState, context_schema=RunDeps)
    graph.add_node("intake", intake)
    graph.add_node("scope", scope)
    graph.add_node("dispatch", dispatch)
    graph.add_node("doc", doc)
    graph.add_node("collect", collect)
    graph.add_node("report", report)
    graph.add_edge(START, "intake")
    graph.add_conditional_edges("intake", _after_intake, ["scope", END])
    graph.add_conditional_edges("scope", _after_scope, ["dispatch", END])
    graph.add_conditional_edges("dispatch", _route, ["doc", "collect"])
    graph.add_edge("doc", "dispatch")
    graph.add_edge("collect", "report")
    graph.add_edge("report", END)
    return graph.compile(checkpointer=checkpointer)
