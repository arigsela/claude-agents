"""The intent-vs-action drift seam: one deterministic check before every tool call.

Order at each call (``tools.ToolBelt.call``): authorization first (the tool is
on this agent's allowlist and bound in its AgentTemplate), then this gate, then
the tool. The gate compares the *intent* (the agent card's description plus the
original task, never the latest hop) with the *action* (the tool call rendered
as one sentence) as the angle between two embeddings, and answers allow, ask
or refuse by per-workflow thresholds. No LLM sits in this path.

Phases: until the drift phase ships, ``RecordingGate`` allows everything and
keeps the rendered sentences, which become the calibration set. ``AngleGate``
is the real check; it needs an ``Embedder`` (see the design doc for the
embedding-source decision).
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal, Protocol

Decision = Literal["allow", "ask", "refuse"]


@dataclass(frozen=True)
class ToolCallContext:
    intent: str
    action: str
    tool: str
    args: Mapping[str, object]
    workflow: str


@dataclass(frozen=True)
class GateResult:
    decision: Decision
    angle_deg: float | None = None
    reason: str = ""


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

    def decide(self, angle: float) -> Decision:
        if angle >= self.refuse_at:
            return "refuse"
        if angle >= self.ask_at:
            return "ask"
        return "allow"


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
