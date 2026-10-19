"""Two gates: the drift seam before every tool call, and the fix gate before a fix
reaches a person. No LLM sits in either path.

Tool calls (``ToolGate``). Order at each call (``tools.ToolBelt.call``):
authorization first (the tool is on this agent's allowlist and bound in its
AgentTemplate), then this gate, then the tool. The gate compares the *intent* (the
agent card's description plus the original task, never the latest hop) with the
*action* (the tool call rendered as one sentence) as the angle between two
embeddings, and answers allow, ask or refuse by per-workflow thresholds. Until the
drift phase ships, production runs ``AllowGate`` (allows everything, keeps nothing);
``RecordingGate`` allows everything and keeps the rendered sentences, for calibration
runs that collect them. ``AngleGate`` is the real check; it needs an ``Embedder``
(see the design doc for the embedding-source decision).

Fixes (``FixGate``, spec section 7). A proposed fix is model output steered by doc
and manifest text that anyone who can edit the repository writes, so it is
untrusted, and this gate is the last check before it reaches the report or a
person. Two layers:

1. Rules, deterministic, always on (``FixGate`` without an embedder, which is what
   production runs: ``build_fix_gate``). The trusted fields, the claim's range and
   the doc's lines, come from the claim and the doc, never from the finding the
   model filled in. Then the replacement rule (``prompts.validate_replacement``),
   ruling G1 for names, and the render check (``render.structure_refusal``, ruling
   G5): the fixed doc must have the original's structure, token for token, with
   only plain text and code changed. Per-line rules cannot see block context
   outside the claim's lines (a fence, an HTML block or a comment above); the
   render check is the authority on markdown semantics. Any exception while the
   rules run is a refusal (fail closed).
2. Angle (offline only, plan R2): with an embedder, the angle between the intent
   and the rendered fix may add an ask or a refusal, never allow what the rules
   refused.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Protocol

from docs_checker.prompts import is_word, occurs_whole, replacement_tokens, validate_replacement
from docs_checker.render import structure_refusal

if TYPE_CHECKING:
    from docs_checker.config import Settings
    from docs_checker.state import Claim, Finding

logger = logging.getLogger(__name__)

Decision = Literal["allow", "ask", "refuse"]


@dataclass(frozen=True)
class ToolCallContext:
    intent: str
    action: str
    tool: str
    args: Mapping[str, object]
    workflow: str


RefusalKind = Literal["containment", "target"]


@dataclass(frozen=True)
class GateResult:
    decision: Decision
    angle_deg: float | None = None
    reason: str = ""
    # Fix refusals only (ruling F1): ``target`` means the fix is not for the claim's
    # own lines of its own doc (the finding is dropped); ``containment`` means the
    # fix itself is unsafe (the finding stays, its fix withheld). None otherwise.
    kind: RefusalKind | None = None


class ToolGate(Protocol):
    async def check(self, call: ToolCallContext) -> GateResult: ...


class Embedder(Protocol):
    async def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


def render_intent(card_description: str, question: str) -> str:
    return f"{card_description.strip()} Task: {question.strip()}"


_ACTION_TEMPLATES = {
    "get_file_contents": "Read the file {path} from the {owner}/{repo} repository.",
    "search_code": "Search code for '{query}'.",
    "get-catalog-entity": "Look up the catalog entity {kind}:{namespace}/{name}.",
}


def render_action(tool: str, args: Mapping[str, object]) -> str:
    """The tool call as one deterministic sentence (sorted, no free text added)."""
    template = _ACTION_TEMPLATES.get(tool)
    if template:
        try:
            return template.format(**{k: v for k, v in args.items()})
        except (KeyError, IndexError):
            pass
    rendered = ", ".join(f"{k}={args[k]!r}" for k in sorted(args))
    return f"Call the tool {tool} with {rendered}." if rendered else f"Call the tool {tool}."


def angle_degrees(a: Sequence[float], b: Sequence[float]) -> float:
    """cos theta = (A.I) / (|A| |I|), returned as degrees in [0, 180]."""
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    if norm == 0:
        return 180.0
    return math.degrees(math.acos(max(-1.0, min(1.0, dot / norm))))


@dataclass(frozen=True)
class Thresholds:
    """Angles in degrees: below ``ask_at`` allow, from ``refuse_at`` refuse, between ask."""

    ask_at: float
    refuse_at: float

    def __post_init__(self) -> None:
        _check_order(self)

    def decide(self, angle: float) -> Decision:
        if angle >= self.refuse_at:
            return "refuse"
        if angle >= self.ask_at:
            return "ask"
        return "allow"


def _check_order(thresholds: Any) -> None:
    """``ask_at`` strictly below ``refuse_at`` (C#49); NaN fails too."""
    if not thresholds.ask_at < thresholds.refuse_at:
        raise ValueError(
            f"thresholds need ask_at < refuse_at, got ask_at={thresholds.ask_at!r}, "
            f"refuse_at={thresholds.refuse_at!r}"
        )


class AllowGate:
    """Allow everything and keep nothing: production's tool gate until the drift check
    ships (a gate that recorded every call would grow for the life of the process)."""

    async def check(self, call: ToolCallContext) -> GateResult:
        return GateResult(decision="allow", reason="drift check not enabled")


@dataclass
class RecordingGate:
    """Allow everything; keep (workflow, intent, action) for threshold calibration."""

    seen: list[ToolCallContext] = field(default_factory=list)

    async def check(self, call: ToolCallContext) -> GateResult:
        self.seen.append(call)
        return GateResult(decision="allow", reason="drift check not enabled")


class AngleGate:
    def __init__(
        self,
        embedder: Embedder,
        thresholds: Mapping[str, Thresholds],
        default: Thresholds,
    ):
        self._embedder = embedder
        self._thresholds = dict(thresholds)
        self._default = default

    async def check(self, call: ToolCallContext) -> GateResult:
        intent_vec, action_vec = await self._embedder.embed([call.intent, call.action])
        angle = angle_degrees(intent_vec, action_vec)
        thresholds = self._thresholds.get(call.workflow, self._default)
        decision = thresholds.decide(angle)
        return GateResult(
            decision=decision,
            angle_deg=round(angle, 2),
            reason=f"{angle:.1f} deg vs ask {thresholds.ask_at} / refuse {thresholds.refuse_at}",
        )


# --- the fix gate --------------------------------------------------------------------


@dataclass(frozen=True)
class FixAction:
    """A proposed fix and what it is checked against (C#9).

    ``claim`` and ``doc_lines`` (the whole doc at the run's commit, line 1 first) are
    trusted: the gate takes the range and the old lines from them, never from the
    finding the model filled in.
    """

    finding: Finding
    claim: Claim
    doc_lines: list[str]


def render_fix(action: FixAction) -> str:
    """The fix as one deterministic sentence (the action the angle layer embeds)."""
    finding = action.finding
    return (
        f"In {finding.doc}, replace lines {finding.line_start}-{finding.line_end} "
        f"{json.dumps(finding.old_text)} with {json.dumps(finding.replacement)}."
    )


def apply_fix(
    doc_lines: Sequence[str], line_start: int, line_end: int, replacement: str
) -> list[str]:
    """The doc's lines with ``line_start..line_end`` (1-based, inclusive) replaced by
    the replacement's lines."""
    return [*doc_lines[: line_start - 1], *replacement.split("\n"), *doc_lines[line_end:]]


# Kinds whose words are names: a plain word may change only to one the evidence has.
NAMED_KINDS = frozenset({"image", "host", "namespace", "name"})


def _ungrounded_word(old: str, new: str, evidence: str) -> bool:
    """Ruling G1: ``new`` has a plain word that is neither in ``old`` nor, whole, in
    the evidence's code (``redis`` -> ``evilredis``)."""
    return any(
        is_word(token) and not occurs_whole(token, old) and not occurs_whole(token, evidence)
        for token in replacement_tokens(new)
    )


def _refusal(action: FixAction) -> tuple[RefusalKind, str] | None:
    """Why the rules refuse ``action`` (its kind and reason), or None when it passes
    every one."""
    # Not at module level: evidence -> state -> tools -> gate would make a cycle.
    from docs_checker.evidence import code_only

    finding, claim, lines = action.finding, action.claim, action.doc_lines
    if finding.doc != claim.doc:
        return "target", "the fix is for another doc than its claim"
    if finding.claim != claim:
        return "target", "the fix carries another claim"
    if (finding.line_start, finding.line_end) != (claim.line_start, claim.line_end):
        return "target", "the fix changes other lines than its claim's"
    if not 1 <= claim.line_start <= claim.line_end <= len(lines):
        return "target", "the claim's lines are not in the doc"
    old = "\n".join(lines[claim.line_start - 1 : claim.line_end])
    if finding.old_text != old:
        return "target", "the fix's old text is not the doc's lines"
    # Comments are never evidence (validate_replacement strips them too).
    evidence = code_only(finding.evidence.text) if finding.evidence else ""
    if validate_replacement(old, finding.replacement, evidence) != finding.replacement:
        return "containment", "the replacement fails the replacement rule"
    if finding.verdict == "stale" and finding.replacement == old:
        return "containment", "the fix of a stale claim changes nothing"
    if claim.kind in NAMED_KINDS and _ungrounded_word(old, finding.replacement, evidence):
        return "containment", f"a new word in a {claim.kind} claim is not in the evidence"
    patched = apply_fix(lines, claim.line_start, claim.line_end, finding.replacement)
    reason = structure_refusal(lines, patched)
    return ("containment", reason) if reason is not None else None


class FixGate:
    """The rules layer, then the angle layer when an embedder is set (see the module
    docstring). The angle may only add an ask or a refusal."""

    def __init__(self, *, embedder: Embedder | None = None, thresholds: Thresholds | None = None):
        if thresholds is not None:
            _check_order(thresholds)
        elif embedder is not None:
            raise ValueError("an embedder needs thresholds")
        self._embedder = embedder
        self._thresholds = thresholds

    async def check(self, intent: str, action: FixAction) -> GateResult:
        try:
            # The render check parses the doc four times: keep it off the event loop.
            refusal = await asyncio.to_thread(_refusal, action)
        except Exception as error:  # noqa: BLE001 - fail closed on anything the rules raise
            logger.warning("fix gate rules failed: %s", type(error).__name__)
            return GateResult(
                decision="refuse",
                reason=f"the rules could not run ({type(error).__name__})",
                kind="containment",
            )
        if refusal is not None:
            return GateResult(decision="refuse", reason=refusal[1], kind=refusal[0])
        if self._embedder is None or self._thresholds is None:
            return GateResult(decision="allow", reason="the fix passes every rule")
        intent_vec, action_vec = await self._embedder.embed([intent, render_fix(action)])
        angle = angle_degrees(intent_vec, action_vec)
        thresholds = self._thresholds
        decision = thresholds.decide(angle)
        return GateResult(
            decision=decision,
            angle_deg=round(angle, 2),
            reason=(
                f"the fix passes every rule; {angle:.1f} deg vs ask {thresholds.ask_at} "
                f"/ refuse {thresholds.refuse_at}"
            ),
            kind="containment" if decision == "refuse" else None,
        )


def build_fix_gate(settings: Settings) -> FixGate:
    """The fix gate production runs: the rules alone. The angle layer is an offline
    demonstration (plan R2), so no embedder is configured; ``settings`` is where one
    would come from."""
    return FixGate()
