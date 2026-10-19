"""The per-doc subgraph: load -> extract -> locate -> judge -> fix -> gate -> finish.

One branch per doc, reached by ``Send`` from the parent graph (``graph.py``), which
hands it ``meta``, ``commit``, ``mode`` and ``search`` and takes back one
``DocOutcome``. Nothing a model writes crosses a node boundary as text: claims,
evidence windows, decisions and findings are the typed models of ``state.py``.

Costs are bounded per doc. Every model call counts against ``calls_used``, capped
at ``max_calls_per_doc`` while ``retry_limits`` is on (ruling U3: a judgement is
reserved as two calls before it is made). Claims left unjudged at the cap are
``unsupported`` and the doc is ``incomplete``. ``BudgetExceeded`` (raised by the
ledger before any call) ends the doc's model work: its status is ``skipped-budget``
and the findings it already has go on to the gate.

What makes a doc ``incomplete`` (Review Focus 1): a source read that is
``transient``, ``denied`` or ``error``, the call cap, or an extraction that could
not be read. Only a read the server confirms ``absent`` is a ``missing`` finding,
on the source's own front-matter line. A claim with no evidence after the
fallbacks (ruling S3) is ``unsupported`` and the doc stays complete.

Repeated work is never paid twice: extractions, fixes and decisions are kept in
the task's replay memo (``RunDeps.replay``) and decisions also in the single-flight
``DecisionMemo`` and, in scheduled mode, the memory store (ruling J4/R5).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import interrupt

from docs_checker.evidence import (
    decide_in_code,
    insufficient,
    is_evidence_source,
    whole_files,
    windows_for,
)
from docs_checker.frontmatter import DocMeta
from docs_checker.gate import FixAction, render_fix, render_intent
from docs_checker.ledger import BudgetExceeded
from docs_checker.memory import fingerprint
from docs_checker.nodes import (
    TRANSCRIPT,
    ExtractionFailed,
    extract_claims,
    judge_claim,
    propose_fix,
)
from docs_checker.prompts import AGENT_DESCRIPTION, CHECKER_VERSION
from docs_checker.repo import ReadResult, RepoReader
from docs_checker.scope import expand_sources
from docs_checker.state import (
    Claim,
    Decision,
    DocOutcome,
    Evidence,
    Finding,
    Window,
    evidence_hash,
)
from docs_checker.tools import ToolEvent, _approved

if TYPE_CHECKING:
    from docs_checker.graph import RunDeps

logger = logging.getLogger(__name__)

Mode = Literal["scheduled", "interactive"]

# Findings under this confidence go to "needs a look" (global constraints).
NEEDS_LOOK_BELOW = 0.7
# A search's hits read as evidence, at most (ruling S3).
MAX_SEARCH_HITS = 2
MAX_WINDOWS = 5
WINDOW_RADIUS = 3

_NO_FIX_MISSING = "the thing the line names no longer exists at this commit: repoint or remove it"
_NO_FIX_BUDGET = "no fix was proposed: the run budget was exhausted"
_NO_FIX_CAP = "no fix was proposed: the per-doc call cap was reached"
_NO_FIX_PROPOSED = "the fixer proposed no fix that passes the replacement rule"
_NO_FIX_REJECTED = "a human rejected the fix"


class DocState(TypedDict, total=False):
    """The child state. ``meta``, ``commit``, ``mode`` and ``search`` arrive with the
    ``Send``; the rest is built step by step; ``outcome`` is what the parent takes."""

    meta: DocMeta
    commit: str
    mode: Mode
    search: bool
    doc_text: str
    sources: dict[str, ReadResult]
    skipped_sources: list[str]
    claims: list[Claim]
    evidence: dict[str, Evidence]
    decisions: dict[str, Decision]
    findings: list[Finding]
    refused: int
    calls_used: int
    incomplete: bool
    reasons: list[str]
    budget_exceeded: bool
    tool_events: list[ToolEvent]
    transcript: list[str]
    outcome: DocOutcome


# --- shared helpers --------------------------------------------------------------------


def reader_for(deps: RunDeps, commit: str, search: bool = False) -> RepoReader:
    """The run's reader at ``commit``, built once per deps (and again after a restart,
    when the deps are new); every read goes through the task's replay memo."""
    reader = deps.reader
    if reader is None or reader.commit != commit or reader.search_allowed != search:
        reader = RepoReader(deps.belt, commit, search_allowed=search, memo=deps.replay)
        deps.reader = reader
    return reader


def _lines(state: DocState) -> list[str]:
    return (state.get("doc_text") or "").split("\n")


def _events(state: DocState, new: list[ToolEvent]) -> list[ToolEvent]:
    return [*(state.get("tool_events") or []), *new]


def _can_call(deps: RunDeps, used: int, calls: int) -> bool:
    return not deps.levers.retry_limits or used + calls <= deps.settings.max_calls_per_doc


def _judge_calls(deps: RunDeps) -> int:
    """What one judgement counts for (ruling U3): Haiku and maybe Sonnet with
    ``right_size`` on, one Sonnet call with it off."""
    return 2 if deps.levers.right_size else 1


def _memo_get(deps: RunDeps, key: str) -> Any | None:
    return deps.replay.get(key) if deps.replay is not None else None


def _memo_put(deps: RunDeps, key: str, value: Any) -> None:
    if deps.replay is not None:
        deps.replay[key] = value


@contextmanager
def _transcribing(deps: RunDeps, state: DocState):
    """With ``typed_handoffs`` off, every model call of the node is recorded into the
    doc's transcript (the synthetic anti-pattern row, C#40)."""
    log = list(state.get("transcript") or [])
    if deps.levers.typed_handoffs:
        yield log
        return
    token = TRANSCRIPT.set(log)
    try:
        yield log
    finally:
        TRANSCRIPT.reset(token)


def _unsupported(reason: str, judged_by: str) -> Decision:
    return Decision(
        verdict="unsupported", confidence=0.0, reason=reason, window_index=None, judged_by=judged_by
    )


# --- load ------------------------------------------------------------------------------


def _missing_source(meta: DocMeta, path: str, line: int, doc_lines: list[str], deps, commit):
    """A ``missing`` finding on the front-matter line that names an absent source."""
    text = doc_lines[line - 1] if 1 <= line <= len(doc_lines) else f"- {path}"
    claim = Claim(
        doc=meta.path,
        line_start=line,
        line_end=line,
        text=(text.strip() or path)[:400],
        kind="path",
        keys=[],
        values=[path],
        source_hint=path,
    )
    return Finding(
        id=claim.id,
        instance=deps.ledger.run_id,
        commit=commit,
        doc=meta.path,
        line_start=line,
        line_end=line,
        claim=claim,
        verdict="missing",
        evidence=None,
        evidence_hash=evidence_hash([]),
        confidence=0.95,
        old_text=text,
        replacement="",
        fix_withheld=_NO_FIX_MISSING,
    )


async def load(state: DocState, runtime: Runtime[RunDeps]) -> dict:
    """The doc and its sources at the run's commit. A doc that will not read is
    ``failed``; an absent source is a ``missing`` finding; any other failed source
    read makes the doc ``incomplete`` (Review Focus 1)."""
    deps = runtime.context
    meta, commit = state["meta"], state["commit"]
    reader = reader_for(deps, commit, state.get("search", False))
    events: list[ToolEvent] = []
    doc = await reader.read(meta.path, node="load", events=events)
    if not doc.found:
        outcome = DocOutcome(
            doc=meta.path,
            commit=commit,
            status="failed",
            reason=f"the doc could not be read ({doc.status})",
            tool_events=events,
        )
        return {"outcome": outcome, "tool_events": events}
    settings = deps.settings
    sources, skipped = await expand_sources(
        reader,
        meta,
        max_dir_files=settings.max_dir_files,
        max_file_bytes=settings.max_file_bytes,
        events=events,
    )
    doc_lines = (doc.text or "").split("\n")
    findings: list[Finding] = []
    reasons: list[str] = []
    for source in meta.sources:
        if source.kind == "url":
            continue
        result = sources.get(source.value.rstrip("/"))
        if result is None or result.found:
            continue
        if result.status == "absent":
            findings.append(
                _missing_source(meta, source.value, source.line, doc_lines, deps, commit)
            )
        else:
            reasons.append(f"{result.path}: {result.status}")
    return {
        "doc_text": doc.text or "",
        "sources": sources,
        "skipped_sources": skipped,
        "findings": findings,
        "incomplete": bool(reasons),
        "reasons": reasons,
        "tool_events": events,
        "calls_used": 0,
        "refused": 0,
    }


# --- extract ---------------------------------------------------------------------------


async def extract(state: DocState, runtime: Runtime[RunDeps]) -> dict:
    """The doc's claims (one model call), replayed from the task's memo on a re-run."""
    deps = runtime.context
    meta, commit = state["meta"], state["commit"]
    used = state.get("calls_used", 0)
    reasons = list(state.get("reasons") or [])
    incomplete = state.get("incomplete", False)
    budget_exceeded = state.get("budget_exceeded", False)
    memo_key = f"extract:{commit}:{meta.path}"
    cached = _memo_get(deps, memo_key)
    claims: list[Claim] = []
    with _transcribing(deps, state) as transcript:
        if cached is not None:
            claims = [Claim.model_validate(c) for c in cached]
        elif not _can_call(deps, used, 1):
            incomplete = True
            reasons.append("the per-doc call cap left the doc unextracted")
        else:
            try:
                claims = await extract_claims(_lines(state), meta, deps, commit=commit)
                used += 1
                _memo_put(deps, memo_key, [c.model_dump() for c in claims])
            except ExtractionFailed as error:
                used += 1
                incomplete = True
                reasons.append(f"claims could not be extracted: {error}")
            except BudgetExceeded:
                budget_exceeded = True
    return {
        "claims": claims,
        "calls_used": used,
        "incomplete": incomplete,
        "reasons": reasons,
        "budget_exceeded": budget_exceeded,
        "transcript": transcript,
    }


# --- locate ----------------------------------------------------------------------------


def _texts(sources: dict[str, ReadResult]) -> dict[str, str]:
    return {p: r.text for p, r in sources.items() if r.found and r.text is not None}


def _windows(claim: Claim, texts: dict[str, str], deps: RunDeps) -> list[Window]:
    if deps.levers.shrink_results:
        return windows_for(claim, texts, radius=WINDOW_RADIUS, max_windows=MAX_WINDOWS)
    return whole_files(texts)[:MAX_WINDOWS]  # Evidence holds at most 5 windows


def _app_of(meta: DocMeta) -> str | None:
    parts = meta.path.split("/")
    return parts[1] if len(parts) >= 3 and parts[0] == "base-apps" else None


async def _read_evidence(
    reader: RepoReader, paths: list[str], known: dict[str, ReadResult], deps, events
) -> dict[str, ReadResult]:
    """Read ``paths`` (non-doc files only, bounded) that are not known yet."""
    extra: dict[str, ReadResult] = {}
    for path in paths:
        if path in known or path in extra or not is_evidence_source(path):
            continue
        result = await reader.read(path, node="load", events=events)
        if result.found and len((result.text or "").encode()) > deps.settings.max_file_bytes:
            continue
        extra[path] = result
    return extra


async def _widen_to_app(
    reader: RepoReader, meta: DocMeta, known: dict[str, ReadResult], deps, events
) -> dict[str, ReadResult]:
    """Ruling S3: the doc's app directory (non-doc files) and the app's Argo
    Application manifest, when the doc is under base-apps/<app>/."""
    app = _app_of(meta)
    if app is None:
        return {}
    listing = await reader.list_dir(f"base-apps/{app}", node="load", events=events)
    files = [e for e in (listing.text or "").split("\n") if e and not e.endswith("/")]
    paths = files[: deps.settings.max_dir_files] + [f"base-apps/{app}.yaml"]
    extra = await _read_evidence(reader, paths, known, deps, events)
    # An absent app manifest is not a finding: nothing claimed it exists.
    return {p: r for p, r in extra.items() if r.found or p != f"base-apps/{app}.yaml"}


async def locate(state: DocState, runtime: Runtime[RunDeps]) -> dict:
    """Evidence windows per claim from the sources; when none holds a claim value,
    widen to the app directory, then (search enabled, at HEAD) one search whose
    first two non-doc hits are read and windowed."""
    deps = runtime.context
    meta = state["meta"]
    reader = reader_for(deps, state["commit"], state.get("search", False))
    sources = dict(state.get("sources") or {})
    texts = _texts(sources)
    events: list[ToolEvent] = []
    evidence: dict[str, Evidence] = {}
    widened = False
    for claim in state.get("claims") or []:
        windows = _windows(claim, texts, deps)
        searched = False
        if insufficient(windows, claim) and not widened:
            widened = True
            extra = await _widen_to_app(reader, meta, sources, deps, events)
            sources.update(extra)
            texts = _texts(sources)
            windows = _windows(claim, texts, deps)
        if insufficient(windows, claim) and state.get("search"):
            hits = await reader.search(claim.values[0], node="locate", events=events)
            searched = hits is not None
            if hits:
                wanted = [h for h in hits if is_evidence_source(h) and h not in sources]
                extra = await _read_evidence(
                    reader, wanted[:MAX_SEARCH_HITS], sources, deps, events
                )
                sources.update(extra)
                texts = _texts(sources)
                windows = _windows(claim, texts, deps)
        evidence[claim.id] = Evidence(claim_id=claim.id, windows=windows, searched=searched)
    return {"evidence": evidence, "sources": sources, "tool_events": _events(state, events)}


# --- judge -----------------------------------------------------------------------------


def _known_decision(deps: RunDeps, key: str, mode: Mode) -> Decision | None:
    """A decision already made: this task's memo, the run's single-flight memo, or
    (scheduled mode, ``short_circuit`` on) the memory store."""
    cached = _memo_get(deps, f"decision:{key}")
    if cached is not None:
        return Decision.model_validate(cached)
    if not deps.levers.short_circuit:
        return None
    decision = deps.decisions.peek(key)
    if decision is None and mode == "scheduled" and deps.store is not None:
        decision = deps.store.get_decision(key)
    return decision


def _remember(deps: RunDeps, key: str, decision: Decision, mode: Mode) -> None:
    _memo_put(deps, f"decision:{key}", decision.model_dump())
    if deps.levers.short_circuit and mode == "scheduled" and deps.store is not None:
        deps.store.put_decision(key, decision)


async def _judged(
    deps: RunDeps, key: str, factory: Callable[[], Awaitable[Decision]]
) -> tuple[Decision, bool]:
    """The decision for ``key`` and whether this doc paid for it (another doc may have
    computed it meanwhile: single-flight, C#8)."""
    ran = False

    async def counted() -> Decision:
        nonlocal ran
        ran = True
        return await factory()

    if deps.levers.short_circuit:
        decision = await deps.decisions.get_or_compute(key, counted)
    else:
        decision = await counted()
    return decision, ran


async def judge(state: DocState, runtime: Runtime[RunDeps]) -> dict:
    """Code first (``right_size`` on), then a known decision, else a model judgement
    reserved as two calls; at the cap a claim is ``unsupported`` and the doc
    ``incomplete``; past the budget the doc is ``skipped-budget``."""
    deps = runtime.context
    commit, mode = state["commit"], state["mode"]
    sources = state.get("sources") or {}
    evidence = state.get("evidence") or {}
    absent = {p for p, r in sources.items() if r.status == "absent"}
    used = state.get("calls_used", 0)
    budget_exceeded = state.get("budget_exceeded", False)
    reasons = list(state.get("reasons") or [])
    decisions: dict[str, Decision] = {}
    unjudged = 0
    with _transcribing(deps, state) as transcript:
        for claim in state.get("claims") or []:
            windows = evidence[claim.id].windows if claim.id in evidence else []
            decision = decide_in_code(claim, windows, absent) if deps.levers.right_size else None
            if decision is None and not windows:
                decision = _unsupported("No evidence was found in the doc's sources.", "code")
            if decision is None:
                key = claim.semantic_key(CHECKER_VERSION, evidence_hash(windows))
                decision = _known_decision(deps, key, mode)
            if decision is None:
                if budget_exceeded:
                    decision = _unsupported("Not judged: the run budget was exhausted.", "budget")
                elif not _can_call(deps, used, _judge_calls(deps)):
                    unjudged += 1
                    decision = _unsupported("Not judged: the per-doc call cap was reached.", "cap")
                else:

                    async def factory(claim=claim, windows=windows) -> Decision:
                        return await judge_claim(claim, windows, deps, commit=commit)

                    try:
                        decision, paid = await _judged(deps, key, factory)
                    except BudgetExceeded:
                        budget_exceeded = True
                        decision = _unsupported(
                            "Not judged: the run budget was exhausted.", "budget"
                        )
                    else:
                        if paid:
                            used += _judge_calls(deps)
                        _remember(deps, key, decision, mode)
            decisions[claim.id] = decision
    if unjudged:
        cap = deps.settings.max_calls_per_doc
        reasons.append(f"the per-doc call cap ({cap}) left {unjudged} claims unjudged")
    return {
        "decisions": decisions,
        "calls_used": used,
        "incomplete": state.get("incomplete", False) or unjudged > 0,
        "reasons": reasons,
        "budget_exceeded": budget_exceeded,
        "transcript": transcript,
    }


# --- fix -------------------------------------------------------------------------------


def _window_of(decision: Decision, windows: list[Window]) -> Window | None:
    index = decision.window_index
    if index is not None and 0 <= index < len(windows):
        return windows[index]
    return windows[0] if windows else None


async def fix(state: DocState, runtime: Runtime[RunDeps]) -> dict:
    """A finding per stale or missing claim; the fix (one model call, replayed from
    the memo on a re-run) only for stale ones with an evidence window."""
    deps = runtime.context
    commit = state["commit"]
    doc_lines = _lines(state)
    evidence = state.get("evidence") or {}
    decisions = state.get("decisions") or {}
    findings = list(state.get("findings") or [])
    used = state.get("calls_used", 0)
    budget_exceeded = state.get("budget_exceeded", False)
    incomplete = state.get("incomplete", False)
    reasons = list(state.get("reasons") or [])
    with _transcribing(deps, state) as transcript:
        for claim in state.get("claims") or []:
            decision = decisions.get(claim.id)
            if decision is None or decision.verdict not in ("stale", "missing"):
                continue
            windows = evidence[claim.id].windows if claim.id in evidence else []
            window = _window_of(decision, windows)
            ev_hash = evidence_hash(windows)
            replacement, withheld = "", None
            if decision.verdict == "missing":
                withheld = _NO_FIX_MISSING
            elif window is None:
                withheld = _NO_FIX_PROPOSED
            else:
                memo_key = f"fix:{commit}:{claim.doc}:{claim.id}:{ev_hash}"
                cached = _memo_get(deps, memo_key)
                if cached is not None:
                    replacement = cached
                elif budget_exceeded:
                    withheld = _NO_FIX_BUDGET
                elif not _can_call(deps, used, 1):
                    withheld = _NO_FIX_CAP
                    incomplete = True
                    reasons.append(f"the per-doc call cap left line {claim.line_start} unfixed")
                else:
                    try:
                        replacement = await propose_fix(
                            claim, decision, window, deps, commit=commit, doc_lines=doc_lines
                        )
                    except BudgetExceeded:
                        budget_exceeded = True
                        withheld = _NO_FIX_BUDGET
                    else:
                        used += 1
                        _memo_put(deps, memo_key, replacement)
                if not replacement and withheld is None:
                    withheld = _NO_FIX_PROPOSED
            findings.append(
                Finding(
                    id=claim.id,
                    instance=deps.ledger.run_id,
                    commit=commit,
                    doc=claim.doc,
                    line_start=claim.line_start,
                    line_end=claim.line_end,
                    claim=claim,
                    verdict=decision.verdict,
                    evidence=window,
                    evidence_hash=ev_hash,
                    confidence=decision.confidence,
                    old_text="\n".join(doc_lines[claim.line_start - 1 : claim.line_end]),
                    replacement=replacement,
                    fix_withheld=withheld,
                    needs_look=decision.confidence < NEEDS_LOOK_BELOW,
                )
            )
    return {
        "findings": findings,
        "calls_used": used,
        "budget_exceeded": budget_exceeded,
        "incomplete": incomplete,
        "reasons": reasons,
        "transcript": transcript,
    }


# --- gate ------------------------------------------------------------------------------


def _intent(finding: Finding) -> str:
    where = f"{finding.doc} lines {finding.line_start}-{finding.line_end}"
    evidence = (
        f"{finding.evidence.source}:{finding.evidence.start}-{finding.evidence.end}"
        if finding.evidence
        else "none"
    )
    return render_intent(
        AGENT_DESCRIPTION,
        f"Correct the {finding.verdict} claim {finding.claim.text!r} on {where}; evidence: {evidence}.",
    )


def _withheld(finding: Finding, reason: str) -> Finding:
    return finding.model_copy(update={"replacement": "", "fix_withheld": reason})


async def gate(state: DocState, runtime: Runtime[RunDeps]) -> dict:
    """``FixGate.check`` on every proposed fix: allow keeps it; ask pauses the run in
    interactive mode (resumed by a strict approval bound to the fix's digest, C#24)
    and marks ``needs_look`` in scheduled mode; refuse withholds the fix (containment)
    or drops the finding (wrong target), counted either way (ruling F1)."""
    deps = runtime.context
    mode = state["mode"]
    doc_lines = _lines(state)
    refused = state.get("refused", 0)
    kept: list[Finding] = []
    for finding in state.get("findings") or []:
        if not finding.replacement:
            kept.append(finding)
            continue
        action = FixAction(finding=finding, claim=finding.claim, doc_lines=doc_lines)
        result = await deps.fix_gate.check(_intent(finding), action)
        if result.decision == "allow":
            kept.append(finding)
        elif result.decision == "ask":
            if mode != "interactive":
                kept.append(finding.model_copy(update={"needs_look": True}))
                continue
            digest = finding.action_digest
            reply = interrupt(
                {
                    "action_requests": [
                        {
                            "name": "propose_fix",
                            "id": digest,
                            "call_id": digest,
                            "args": {
                                "doc": finding.doc,
                                "line_start": finding.line_start,
                                "line_end": finding.line_end,
                                "claim": finding.claim.text,
                                "old_text": finding.old_text,
                                "replacement": finding.replacement,
                                "evidence": (
                                    f"{finding.evidence.source}:{finding.evidence.start}"
                                    f"-{finding.evidence.end}"
                                    if finding.evidence
                                    else ""
                                ),
                            },
                        }
                    ],
                    "hint": f"{render_fix(action)} ({result.reason})",
                }
            )
            if _approved(reply, digest):
                kept.append(finding)
            else:
                refused += 1
                kept.append(_withheld(finding, _NO_FIX_REJECTED))
        else:
            refused += 1
            if result.kind == "target":
                logger.warning("fix dropped for %s: %s", finding.doc, result.reason)
            else:
                kept.append(_withheld(finding, result.reason))
    return {"findings": kept, "refused": refused}


# --- finish ----------------------------------------------------------------------------


async def finish(state: DocState, runtime: Runtime[RunDeps]) -> dict:
    """The doc's outcome: status, counts, the fingerprint memory needs (scheduled mode)
    and the first 50 tool events."""
    deps = runtime.context
    meta, commit = state["meta"], state["commit"]
    decisions = state.get("decisions") or {}
    claims = state.get("claims") or []
    counts: dict[str, int] = {"claims": len(claims)}
    for decision in decisions.values():
        counts[decision.verdict] = counts.get(decision.verdict, 0) + 1
    evidence_paths = sorted(
        {w.source for e in (state.get("evidence") or {}).values() for w in e.windows}
    )
    events: list[ToolEvent] = []
    fp: dict[str, str] = {}
    if state["mode"] == "scheduled" and deps.levers.short_circuit:
        reader = reader_for(deps, commit, state.get("search", False))
        fp = await fingerprint(meta, reader, evidence_paths, CHECKER_VERSION)
    if state.get("budget_exceeded"):
        status = "skipped-budget"
        judged = sum(1 for d in decisions.values() if d.judged_by != "budget")
        reason = f"the run budget was exhausted after {judged} of {len(claims)} claims"
    elif state.get("incomplete"):
        status, reason = "incomplete", "; ".join(state.get("reasons") or [])
    else:
        status, reason = "checked", ""
    findings = sorted(state.get("findings") or [], key=lambda f: (f.line_start, f.line_end))
    outcome = DocOutcome(
        doc=meta.path,
        commit=commit,
        status=status,
        reason=reason,
        findings=findings,
        counts=counts,
        fingerprint=fp,
        evidence_paths=evidence_paths,
        refused=state.get("refused", 0),
        tool_events=_events(state, events),
        transcript=state.get("transcript") or [],
    )
    return {"outcome": outcome}


def _after_load(state: DocState) -> str:
    return END if state.get("outcome") is not None else "extract"


def build_doc_graph():
    """The compiled per-doc subgraph; it takes the parent's checkpointer through the
    config it is invoked with."""
    from docs_checker.graph import RunDeps

    graph = StateGraph(DocState, context_schema=RunDeps)
    for name, node in (
        ("load", load),
        ("extract", extract),
        ("locate", locate),
        ("judge", judge),
        ("fix", fix),
        ("gate", gate),
        ("finish", finish),
    ):
        graph.add_node(name, node)
    graph.add_edge(START, "load")
    graph.add_conditional_edges("load", _after_load, ["extract", END])
    graph.add_edge("extract", "locate")
    graph.add_edge("locate", "judge")
    graph.add_edge("judge", "fix")
    graph.add_edge("fix", "gate")
    graph.add_edge("gate", "finish")
    graph.add_edge("finish", END)
    return graph.compile()
