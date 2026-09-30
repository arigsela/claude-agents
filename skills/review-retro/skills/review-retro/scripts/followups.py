#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///
"""review-retro: follow-up-fix heuristic (spec §4). Must match pr-triage/src/pr_triage/followups.py.

  followups.py --repo R --pr N        -> {"pr": N, "merged_at": ..., "followups": [...]}
  followups.py --repo R --since 14d   -> [{"pr", "title", "merged_at", "followups": [...]}, ...]
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone

WINDOW = timedelta(hours=72)
MAX_SINCE_DAYS = 30
NOISE_BASENAMES = {"index.md", "README.md", "CLAUDE.md", "SPEC.md", "agent-docs-scope.txt"}


def component_of(path: str) -> str:
    parts = path.split("/")
    if parts[0] == "base-apps" and len(parts) >= 2:
        name = parts[1]
        if len(parts) == 2 and name.endswith((".yaml", ".yml")):
            name = name.rsplit(".", 1)[0]
        return f"base-apps/{name}"
    return "/".join(parts[:2])


def components(paths: list[str]) -> set[str]:
    return {component_of(p) for p in paths
            if not p.startswith("docs/") and p.rsplit("/", 1)[-1] not in NOISE_BASENAMES}


def is_fix(title: str) -> bool:
    return title.lower().startswith(("fix", "revert"))


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def merged_prs(repo: str, limit: int = 500) -> list[dict]:
    try:
        out = subprocess.run(["gh", "pr", "list", "-R", repo, "--state", "merged", "--limit", str(limit),
                              "--json", "number,title,mergedAt,files"],
                             capture_output=True, text=True, check=True).stdout
    except subprocess.CalledProcessError as e:
        sys.exit(f"followups: gh failed: {(e.stderr or '').strip() or e}")
    except FileNotFoundError as e:
        sys.exit(f"followups: gh failed: {e}")
    prs = json.loads(out)
    for p in prs:
        p["merged"] = parse_ts(p["mergedAt"])
        p["comps"] = components([f["path"] for f in p.get("files") or []])
    return sorted(prs, key=lambda p: p["merged"])


def followups_for(pr: dict, prs: list[dict]) -> list[dict]:
    return [q for q in prs
            if pr["merged"] < q["merged"] <= pr["merged"] + WINDOW
            and is_fix(q["title"]) and pr["comps"] & q["comps"]]


def brief(q: dict, pr: dict) -> dict:
    return {"number": q["number"], "title": q["title"], "merged_at": q["mergedAt"],
            "shared_components": sorted(pr["comps"] & q["comps"])}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--pr", type=int)
    group.add_argument("--since", help="window like 14d (max 30d: transcript retention)")
    args = ap.parse_args()
    if args.since is not None:
        m = re.fullmatch(r"(\d+)d", args.since)
        if not m or int(m.group(1)) < 1:
            ap.error(f"--since must be <positive int>d (e.g. 14d), got {args.since!r}")
        requested = int(m.group(1))
        if requested > MAX_SINCE_DAYS:
            print(f"followups: --since {requested}d capped to {MAX_SINCE_DAYS}d (transcript retention)", file=sys.stderr)
    prs = merged_prs(args.repo)
    if args.pr:
        me = next((p for p in prs if p["number"] == args.pr), None)
        if me is None:
            sys.exit(f"followups: #{args.pr} is not among the last 500 merged PRs of {args.repo}")
        print(json.dumps({"pr": me["number"], "merged_at": me["mergedAt"],
                          "followups": [brief(q, me) for q in followups_for(me, prs)]}, indent=2))
        return 0
    days = min(requested, MAX_SINCE_DAYS)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    print(json.dumps([{"pr": p["number"], "title": p["title"], "merged_at": p["mergedAt"],
                       "followups": [brief(q, p) for q in followups_for(p, prs)]}
                      for p in prs if p["merged"] >= cutoff], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
