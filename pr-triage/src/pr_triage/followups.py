"""Follow-up-fix heuristic (spec §4). Keep behaviour identical to
skills/review-retro/skills/review-retro/scripts/followups.py."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .policy import component_of

WINDOW = timedelta(hours=72)
NOISE_BASENAMES = {"index.md", "README.md", "CLAUDE.md", "SPEC.md", "agent-docs-scope.txt"}


@dataclass
class MergedPR:
    number: int
    title: str
    merged_at: datetime
    paths: list[str]


def followup_components(paths: list[str]) -> set[str]:
    return {component_of(p) for p in paths
            if not p.startswith("docs/") and p.rsplit("/", 1)[-1] not in NOISE_BASENAMES}


def is_fix(title: str) -> bool:
    return title.lower().startswith(("fix", "revert"))


def find_followups(prs: list[MergedPR]) -> dict[int, list[int]]:
    """PR number -> numbers of later fix/revert PRs (<= 72 h) that share a component."""
    ordered = sorted(prs, key=lambda p: p.merged_at)
    comps = {p.number: followup_components(p.paths) for p in ordered}
    out: dict[int, list[int]] = {}
    for i, p in enumerate(ordered):
        hits = []
        for q in ordered[i + 1:]:
            if q.merged_at - p.merged_at > WINDOW:
                break
            if is_fix(q.title) and comps[p.number] & comps[q.number]:
                hits.append(q.number)
        out[p.number] = hits
    return out
