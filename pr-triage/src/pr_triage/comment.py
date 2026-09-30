"""Sticky triage comment and review:* labels. Spec §5.6."""
from __future__ import annotations

from . import gh
from .decide import Decision
from .features import Features

MARKER = "<!-- pr-triage -->"
LABELS = {"skip": ("review:skip", "0e8a16"), "skim": ("review:skim", "fbca04"), "read": ("review:read", "d93f0b")}
EMOJI = {"skip": "🟢", "skim": "🟡", "read": "🔴"}


def _safe(text: str) -> str:
    return text.replace("@", "@​")  # model/PR text must not @-mention anyone


def render_comment(pr_number: int, features: Features, decision: Decision,
                   note: list[str], versions: dict[str, str]) -> str:
    lines = [MARKER, f"### {EMOJI[decision.label]} {LABELS[decision.label][0]}",
             f"**Why:** {_safe('; '.join(decision.reasons))}"]
    if decision.degraded_reason:
        lines.append(f"> triage degraded: {_safe(decision.degraded_reason)}")
    if note:
        lines += ["**What to look at:**", *[f"- {_safe(b)}" for b in note]]
    if decision.label in ("skim", "read"):
        lines.append(f"**Next:** `/pr-explainer {pr_number}` · `/code-review {pr_number}`")
    signals = [f"decided_by: {decision.decided_by}",
               f"size: {features.size_bucket} ({features.lines_changed} lines)",
               f"components: {', '.join(features.components) or '-'}"]
    if features.hot_components_touched:
        signals.append(f"hot components: {', '.join(features.hot_components_touched)}")
    if decision.jev:
        p = decision.jev.probabilities
        signals.append(f"Jev: P(skip)={p['skip']:.2f} P(skim)={p['skim']:.2f} "
                       f"P(read)={p['read']:.2f} confidence={decision.jev.confidence:.2f}")
        signals.append("flags: " + ", ".join(f"{k}={v:.2f}" for k, v in decision.jev.flags.items()))
    lines += ["<details><summary>Signals</summary>", "", *[f"- {s}" for s in signals], "", "</details>",
              f"<sub>pr-triage {versions['action']} · {versions['jev']} · {versions['claude']} · "
              f"policy @ {versions['policy']}</sub>"]
    return "\n".join(lines)


def upsert_comment(repo: str, pr_number: int, body: str) -> None:
    for c in gh.list_issue_comments(repo, pr_number):
        if MARKER in (c.get("body") or ""):
            gh.update_comment(repo, c["id"], body)
            return
    gh.create_comment(repo, pr_number, body)


def apply_label(repo: str, pr_number: int, label: str) -> None:
    name, color = LABELS[label]
    gh.ensure_label(repo, name, color)
    current = set(gh.labels_on(repo, pr_number))
    for other, _ in LABELS.values():
        if other != name and other in current:
            gh.remove_label(repo, pr_number, other)
    if name not in current:
        gh.add_label(repo, pr_number, name)
