"""The model nodes: intake, extract, judge and fix.

Each node sends its frozen system prompt (``prompts``) and one user message in
which every piece of untrusted text (the request, doc lines, claim text, file
excerpts, a model's earlier reason) sits inside a data fence. Each asks for
structured output (``with_structured_output(Schema, method="json_schema",
include_raw=True)``) through ``llm.call_model``, which reserves the budget,
retries transient errors and accounts the call from ``raw``.

A parse failure is a result, never a retry. Each node's fallback:

- ``classify_intake``: ``"off_topic"``.
- ``extract_claims``: raises ``ExtractionFailed``. An empty list would read as
  "no claims" and the doc would pass as checked; the caller marks it incomplete.
- ``judge_claim``: ``unsupported`` at confidence 0.0, judged by that model.
- ``propose_fix``: ``""`` (no fix; the fix gate refuses an empty replacement).

API errors and ``BudgetExceeded`` propagate. Nothing a model writes is trusted:
claims are checked against the doc's own lines, paths go through
``parse_request``, verdicts are range-checked, and replacements pass
``prompts.validate_replacement``.

Tools: these nodes never run a tool loop. With ``tools_on_demand`` on no model
node carries a tool (intake's ``NODE_TOOLS`` resolve the ref in code, ruling U2);
off, every read tool is bound with ``models.no_tools_choice()``, so the model sees
but cannot call it.
"""

from __future__ import annotations

import hashlib
import json
import logging
from bisect import bisect_right
from contextvars import ContextVar
from typing import Any, Literal, Protocol

from anthropic import transform_schema
from langchain_core.messages import HumanMessage
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import BaseModel, ValidationError

from docs_checker import prompts
from docs_checker.config import Settings
from docs_checker.frontmatter import DocMeta
from docs_checker.ledger import CostLedger
from docs_checker.levers import Levers
from docs_checker.llm import DEFAULT_BUDGET, call_model
from docs_checker.models import ModelSet, no_tools_choice
from docs_checker.prompts import fence, fence_token
from docs_checker.request import RunRequest, parse_request
from docs_checker.state import Claim, ClaimKind, Decision, Verdict, Window
from docs_checker.tools import ToolBelt

logger = logging.getLogger("docs_checker.nodes")

# Lever 2 (typed handoffs) off: the doc branch sets a list here and every call made
# while it is set appends what the model was asked and what it answered, as text.
# None (the default) records nothing. The graph is the only writer.
TRANSCRIPT: ContextVar[list[str] | None] = ContextVar("docs_checker_transcript", default=None)


class NodeContext(Protocol):
    """What a model node needs from the run (Task 14's ``RunDeps`` satisfies it)."""

    models: ModelSet
    ledger: CostLedger
    levers: Levers
    settings: Settings
    belt: ToolBelt


class ExtractionFailed(Exception):
    """The extract model's answer could not be read; the doc was not checked."""


# --- what each model must answer -------------------------------------------------


class IntakeAnswer(BaseModel):
    intent: Literal["audit", "off_topic"]
    all_docs: bool
    paths: list[str]
    ref: str


class FoundClaim(BaseModel):
    line_start: int
    line_end: int
    text: str
    kind: ClaimKind
    keys: list[str]
    values: list[str]
    source_hint: str


class ExtractAnswer(BaseModel):
    claims: list[FoundClaim]


class JudgeAnswer(BaseModel):
    verdict: Verdict
    confidence: float
    reason: str
    window_index: int | None


class FixAnswer(BaseModel):
    replacement: str


# --- one structured call -----------------------------------------------------------


def _structured(model: Any, schema: type[BaseModel], tools: list[Any]) -> Any:
    """``model`` answering as ``schema``, carrying ``tools`` it cannot call.

    ``bind_tools`` returns a binding whose ``with_structured_output`` is the wrapped
    model's own, so calling it there would build from the bare model and drop the
    tools. ChatAnthropic's json_schema path only calls ``self.bind``, so it is called
    with the binding as ``self`` (pinned by the wire test in tests/test_nodes.py).
    """
    if tools:
        model = model.bind_tools(tools, tool_choice=no_tools_choice())
        inner = getattr(model, "bound", None)
        if inner is not None:
            return type(inner).with_structured_output(
                model, schema, method="json_schema", include_raw=True
            )
    return model.with_structured_output(schema, method="json_schema", include_raw=True)


def _overhead_chars(schema: type[BaseModel], tools: list[Any]) -> int:
    """What the request carries besides the messages: the output format and the tool
    schemas, measured as spaced JSON (and tools in the larger OpenAI shape), so the
    reservation stays an upper bound (ruling B1)."""
    chars = len(json.dumps(transform_schema(schema)))
    return chars + sum(len(json.dumps(convert_to_openai_tool(tool))) for tool in tools)


def _tools_for(ctx: NodeContext, node: str) -> list[Any]:
    """The schemas a node's model carries (lever 4). Intake's own tools are the code's
    ref resolution, not the model's, so with the lever on it carries none (U2)."""
    if node == "intake" and ctx.levers.tools_on_demand:
        return []
    return ctx.belt.schemas_for(node)


async def _ask(
    ctx: NodeContext, node: str, schema: type[BaseModel], system: str, user: str
) -> Any | None:
    """One structured call; the parsed answer, or None when it could not be read."""
    tools = _tools_for(ctx, node)
    messages = [
        prompts.system_message(system, cache=ctx.levers.cache_prefix, ttl=ctx.settings.cache_ttl),
        HumanMessage(user),
    ]
    result = await call_model(
        _structured(ctx.models.get(node), schema, tools),
        messages,
        node=node,
        model_name=ctx.models.name(node),
        ledger=ctx.ledger,
        budget=DEFAULT_BUDGET,
        max_tokens=ctx.settings.node_models[node].max_tokens,
        overhead_chars=_overhead_chars(schema, tools),
    )
    transcript = TRANSCRIPT.get()
    if transcript is not None:
        raw = result.get("raw") if isinstance(result, dict) else result
        transcript.append(f"[{node}] user:\n{user}\n\n[{node}] reply:\n{_text_of(raw)}")
    parsed = result.get("parsed") if isinstance(result, dict) else None
    if not isinstance(parsed, schema):
        error = result.get("parsing_error") if isinstance(result, dict) else None
        logger.warning("%s: the model's answer could not be read (%s)", node, type(error).__name__)
        return None
    return parsed


def _text_of(message: Any) -> str:
    """A reply's text: a string content as is, content blocks' text joined."""
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            str(block.get("text", "")) if isinstance(block, dict) else str(block)
            for block in content
        )
    return str(content)


def _cut(text: str, max_chars: int) -> str:
    """Each line at most ``max_chars`` characters (what a model is sent)."""
    return "\n".join(line[:max_chars] for line in text.split("\n"))


def _ws(text: str) -> str:
    return " ".join(text.split())


# --- intake ------------------------------------------------------------------------


async def classify_intake(text: str, ctx: NodeContext) -> RunRequest | Literal["off_topic"]:
    """A free-text request as a ``RunRequest``, or ``"off_topic"``.

    The model only reads the scope and the ref; they are checked as any request is
    (``parse_request``: in-scope, normalized paths and a valid ref), which raises
    ``ValueError``. Mode and memory never come from the model.
    """
    lines = _cut(text, ctx.settings.max_line_chars)
    # A request has no commit: its own digest makes the token (text cannot hold it).
    token = fence_token(
        hashlib.sha256(text.encode()).hexdigest(), "request", 1, len(text.split("\n"))
    )
    user = prompts.INTAKE_USER.format(request=fence(lines, token))
    answer = await _ask(ctx, "intake", IntakeAnswer, prompts.INTAKE, user)
    if answer is None or answer.intent == "off_topic":
        return "off_topic"
    data: dict[str, Any] = {"scope": "all" if answer.all_docs else answer.paths}
    if answer.ref:
        data["ref"] = answer.ref
    # With a scope in the data, parse_request returns a request or raises.
    return parse_request(None, data, max_paths=ctx.settings.max_docs) or "off_topic"


# --- extract -----------------------------------------------------------------------


def _span(
    text: str, doc_lines: list[str], start: int, end: int, first: int
) -> tuple[int, int] | None:
    """The lines of ``text``'s first occurrence in lines ``start..end`` (1-based,
    inclusive, at or after ``first``), whitespace-normalized; None when it is not there.

    One linear pass, however wide a range the model claims.
    """
    needle = _ws(text)
    if not needle or not first <= start <= end <= len(doc_lines):
        return None
    offsets: list[int] = []  # where each non-blank line starts in the joined text
    numbers: list[int] = []
    words: list[str] = []
    at = 0
    for number in range(start, end + 1):
        line = _ws(doc_lines[number - 1])
        if line:
            offsets.append(at)
            numbers.append(number)
            words.append(line)
            at += len(line) + 1
    found = " ".join(words).find(needle)
    if found < 0:
        return None
    last = found + len(needle) - 1
    return numbers[bisect_right(offsets, found) - 1], numbers[bisect_right(offsets, last) - 1]


def _grounded(found: FoundClaim) -> bool:
    """Every value occurs in the claim's text (case kept) and every key too (any case),
    whitespace-normalized. Values and keys pick the evidence windows and drive the
    code judge with no model in between, so they must come from the doc as well."""
    text = _ws(found.text)
    values = [_ws(value) for value in found.values]
    keys = [_ws(key).lower() for key in found.keys]
    return all(v and v in text for v in values) and all(k and k in text.lower() for k in keys)


async def extract_claims(
    doc_lines: list[str], meta: DocMeta, ctx: NodeContext, *, commit: str
) -> list[Claim]:
    """The doc's checkable claims, each found in its own lines, at most
    ``max_claims_per_doc`` (the first ones, in the model's order).

    ``doc_lines`` is the whole file (line 1 is the first front-matter fence); the
    body from ``meta.body_start`` is sent numbered, each line cut to
    ``max_line_chars``. A claim whose text is not in its lines (whitespace aside,
    case kept) is dropped, and so is one whose values or keys are not in its text;
    a claim that stays gets the lines of the text's first occurrence in its range.
    """
    first, last = meta.body_start, len(doc_lines)
    if first > last:
        return []
    width = ctx.settings.max_line_chars
    numbered = "\n".join(f"{n}: {doc_lines[n - 1][:width]}" for n in range(first, last + 1))
    sources = "\n".join([f"path: {meta.path}", *(f"source: {s.value}" for s in meta.sources)])
    user = prompts.EXTRACT_USER.format(
        sources=fence(_cut(sources, width), fence_token(commit, meta.path, 1, first - 1)),
        lines=fence(numbered, fence_token(commit, meta.path, first, last)),
    )
    answer = await _ask(ctx, "extract", ExtractAnswer, prompts.EXTRACT, user)
    if answer is None:
        raise ExtractionFailed(f"{meta.path}: the extract model's answer could not be read")

    claims: dict[str, Claim] = {}
    for found in answer.claims:
        if len(claims) >= ctx.settings.max_claims_per_doc:
            break
        span = _span(found.text, doc_lines, found.line_start, found.line_end, first)
        if span is None or not _grounded(found):
            continue
        try:
            claim = Claim(
                doc=meta.path,
                line_start=span[0],
                line_end=span[1],
                text=found.text,
                kind=found.kind,
                keys=found.keys,
                values=found.values,
                source_hint=found.source_hint,
            )
        except ValidationError:
            continue
        claims.setdefault(claim.id, claim)
    return list(claims.values())


# --- judge -------------------------------------------------------------------------


def _claim_block(claim: Claim, commit: str, **extra: Any) -> str:
    """The claim as fenced JSON. No doc path or line: a decision is identity-free."""
    data = {"text": claim.text, "kind": claim.kind, "keys": claim.keys, "values": claim.values}
    token = fence_token(commit, claim.doc, claim.line_start, claim.line_end)
    return fence(json.dumps({**data, **extra}, ensure_ascii=False), token)


def _window_block(window: Window, commit: str, width: int) -> str:
    text = f"source: {window.source} (lines {window.start}-{window.end})\n{window.text}"
    return fence(_cut(text, width), fence_token(commit, window.source, window.start, window.end))


async def _judge_once(
    node: str, claim: Claim, windows: list[Window], ctx: NodeContext, commit: str
) -> Decision:
    width = ctx.settings.max_line_chars
    user = prompts.JUDGE_USER.format(
        claim=_claim_block(claim, commit),
        windows="\n\n".join(
            prompts.JUDGE_WINDOW.format(index=i, block=_window_block(w, commit, width))
            for i, w in enumerate(windows)
        ),
    )
    answer = await _ask(ctx, node, JudgeAnswer, prompts.JUDGE, user)
    judged_by = ctx.models.name(node)
    index = answer.window_index if answer else None
    if (
        answer is None
        or not 0.0 <= answer.confidence <= 1.0
        or (index is not None and not 0 <= index < len(windows))
    ):
        return Decision(
            verdict="unsupported",
            confidence=0.0,
            reason="The model's answer could not be read.",
            window_index=None,
            judged_by=judged_by,
        )
    return Decision(
        verdict=answer.verdict,
        confidence=answer.confidence,
        reason=answer.reason[:300],
        window_index=index,
        judged_by=judged_by,
    )


async def judge_claim(
    claim: Claim, windows: list[Window], ctx: NodeContext, *, commit: str
) -> Decision:
    """Haiku first (``judge``); under 0.8 confidence, Sonnet (``judge_escalate``) decides.

    With ``right_size`` off every node is Sonnet already, so ``judge`` is the only
    call. One call per model, never a retry: an unreadable or impossible answer
    (confidence outside 0..1, a window that does not exist) is ``unsupported`` at
    0.0, which on Haiku sends the claim to Sonnet. Makes one or two model calls.
    """
    decision = await _judge_once("judge", claim, windows, ctx, commit)
    if ctx.levers.right_size and decision.confidence < prompts.ESCALATE_BELOW:
        return await _judge_once("judge_escalate", claim, windows, ctx, commit)
    return decision


# --- fix ---------------------------------------------------------------------------


async def propose_fix(
    claim: Claim,
    decision: Decision,
    window: Window,
    ctx: NodeContext,
    *,
    commit: str,
    doc_lines: list[str],
) -> str:
    """The claim's lines corrected from ``window``, validated; ``""`` when there is no
    fix (an unreadable or rejected answer, or the lines unchanged).

    The old text is ``doc_lines[line_start..line_end]`` (the whole file's lines),
    never model output. A line longer than ``max_line_chars`` gets no fix: the model
    would see only part of it.
    """
    old_lines = doc_lines[claim.line_start - 1 : claim.line_end]
    width = ctx.settings.max_line_chars
    if not old_lines or any(len(line) > width for line in old_lines):
        return ""
    old = "\n".join(old_lines)
    user = prompts.FIX_USER.format(
        old=fence(old, fence_token(commit, claim.doc, claim.line_start, claim.line_end)),
        claim=_claim_block(claim, commit, verdict=decision.verdict, reason=decision.reason),
        window=_window_block(window, commit, width),
    )
    answer = await _ask(ctx, "fix", FixAnswer, prompts.FIX, user)
    if answer is None:
        return ""
    replacement = prompts.validate_replacement(old, answer.replacement, window.text)
    return "" if replacement is None or replacement == old else replacement
