"""Deterministic always_read / always_skip rules. Spec §5.3."""
from __future__ import annotations

from dataclasses import dataclass, field

from .features import Features
from .policy import Policy


@dataclass
class RuleResult:
    decision: str | None  # "read" | "skip" | None (undecided -> Jev)
    reasons: list[str] = field(default_factory=list)


def apply_rules(features: Features, files: list[dict], policy: Policy) -> RuleResult:
    reasons: list[str] = []
    for f in files:
        for path in filter(None, (f["filename"], f.get("previous_filename"))):
            if policy.always_read_paths.match_file(path):
                reasons.append(f"always_read.paths ({path})")
    reasons += [f"always_read.kinds {k}" for k in features.kinds_changed if k in policy.always_read_kinds]
    reasons += [f"always_read.signals {s}" for s in features.signals if s in policy.always_read_signals]
    if reasons:
        return RuleResult("read", reasons)

    def skippable(f: dict) -> bool:
        # Both the new and the pre-rename path must qualify (a rename out of a code dir is not docs-only).
        paths = [p for p in (f["filename"], f.get("previous_filename")) if p]
        return all(policy.always_skip_paths.match_file(p)
                   or (policy.image_tag_bump_only and p == f["filename"] and p in features.image_bump_files)
                   for p in paths)

    if files and all(skippable(f) for f in files):
        kinds = []
        if any(policy.always_skip_paths.match_file(f["filename"]) for f in files):
            kinds.append("docs/markdown")
        if features.image_bump_files:
            kinds.append("image tag bump")
        return RuleResult("skip", [f"always_skip ({' + '.join(kinds)} only)"])
    return RuleResult(None)
