"""Load .github/review-policy.yaml and answer path/component questions."""
from __future__ import annotations

from dataclasses import dataclass

import pathspec
import yaml


@dataclass(frozen=True)
class Thresholds:
    read_if_p_read_gte: float = 0.30
    read_if_any_flag_gte: float = 0.70
    skip_if_p_skip_gte: float = 0.90
    escalate_if_confidence_lt: float = 0.50


@dataclass(frozen=True)
class Policy:
    always_read_paths: pathspec.PathSpec
    always_read_kinds: frozenset[str]
    always_read_signals: frozenset[str]
    always_skip_paths: pathspec.PathSpec
    image_tag_bump_only: bool
    hot_components: dict[str, float]
    thresholds: Thresholds
    risk_callouts: dict[str, str]


def _spec(patterns: list[str] | None) -> pathspec.PathSpec:
    return pathspec.PathSpec.from_lines("gitwildmatch", patterns or [])


def load_policy(text: str) -> Policy:
    raw = yaml.safe_load(text) or {}
    if raw.get("version") != 1:
        raise ValueError(f"unsupported review-policy version: {raw.get('version')!r}")
    read = raw.get("always_read") or {}
    skip = raw.get("always_skip") or {}
    return Policy(
        always_read_paths=_spec(read.get("paths")),
        always_read_kinds=frozenset(read.get("kinds") or []),
        always_read_signals=frozenset(read.get("signals") or []),
        always_skip_paths=_spec(skip.get("paths")),
        image_tag_bump_only=bool(skip.get("image_tag_bump_only", False)),
        hot_components={str(k): float(v) for k, v in (raw.get("hot_components") or {}).items()},
        thresholds=Thresholds(**(raw.get("thresholds") or {})),
        risk_callouts={str(k): str(v) for k, v in (raw.get("risk_callouts") or {}).items()},
    )


def component_of(path: str) -> str:
    """base-apps/<app>/** and base-apps/<app>.yaml -> base-apps/<app>; else first two segments."""
    parts = path.split("/")
    if parts[0] == "base-apps" and len(parts) >= 2:
        name = parts[1]
        if len(parts) == 2 and name.endswith((".yaml", ".yml")):
            name = name.rsplit(".", 1)[0]
        return f"base-apps/{name}"
    return "/".join(parts[:2])
