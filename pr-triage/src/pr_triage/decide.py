"""Combine rules, Jev and Claude into one triage decision. Spec §5.5."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .claude import ClaudeError
from .features import Features
from .jev import JevAnswers, JevError
from .policy import Policy, Thresholds
from .rules import RuleResult


@dataclass
class Decision:
    label: str        # "skip" | "skim" | "read"
    decided_by: str   # "rules" | "jev" | "claude" | "degraded"
    reasons: list[str] = field(default_factory=list)
    jev: JevAnswers | None = None
    degraded_reason: str | None = None


JevFn = Callable[[dict], JevAnswers]
ClaudeDecideFn = Callable[[dict, "dict | None"], "tuple[str, str]"]


def classify(jev: JevAnswers, t: Thresholds) -> tuple[str, list[str]]:
    """Pure threshold logic; calibrate.py replays it offline with other thresholds."""
    p = jev.probabilities
    flagged = [k for k, v in jev.flags.items() if v >= t.read_if_any_flag_gte]
    if p["read"] >= t.read_if_p_read_gte or flagged:
        return "read", [f"P(read)={p['read']:.2f}"] + [f"{k}={jev.flags[k]:.2f}" for k in flagged]
    if jev.confidence < t.escalate_if_confidence_lt:
        return "escalate", [f"Jev confidence {jev.confidence:.2f}"]
    if p["skip"] >= t.skip_if_p_skip_gte:
        return "skip", [f"P(skip)={p['skip']:.2f}"]
    return "skim", [f"P(skim)={p['skim']:.2f}, P(read)={p['read']:.2f}"]


def decide(features: Features, rules: RuleResult, policy: Policy,
           jev_fn: JevFn, claude_decide_fn: ClaudeDecideFn) -> Decision:
    if rules.decision:
        return Decision(rules.decision, "rules", rules.reasons)
    state = features.jev_state()
    try:
        jev = jev_fn(state)
    except JevError as err:
        return Decision("read", "degraded", ["rules undecided and Jev unavailable"], degraded_reason=str(err))
    label, reasons = classify(jev, policy.thresholds)
    decided_by = "jev"
    if label == "escalate":
        try:
            label, why = claude_decide_fn(state, jev.to_dict())
        except ClaudeError as err:
            return Decision("read", "degraded", reasons + ["Claude unavailable"], jev, str(err))
        decided_by = "claude"
        reasons = reasons + [f"Claude: {why}"]
    if label == "skip" and features.hot_components_touched:
        label = "skim"
        reasons.append("hot component: " + ", ".join(features.hot_components_touched))
    return Decision(label, decided_by, reasons, jev)
