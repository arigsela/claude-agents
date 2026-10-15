#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6", "pathspec>=0.12,<1"]
# ///
"""explainer: collect deterministic facts about a service (or a ticket's system) at one ref.

Usage: collect_system.py --service NAME [--service NAME]... [--repo owner/name] [--ref main]
                         [--doc FILE]... [--ticket KEY] [--all] --out DIR
--repo is required outside a checkout of the repo. --ref defaults to the repo's default branch.
The work is in facts_lib.collect_system(); this file parses arguments and writes facts.json.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from facts_lib import Trees, collect_system, repo_from_origin, sh


def default_branch(repo: str) -> str:
    try:
        return sh("gh", "api", f"repos/{repo}", "--jq", ".default_branch").strip() or "main"
    except RuntimeError:
        return "main"


def main() -> int:
    ap = argparse.ArgumentParser(description="Collect deterministic service or ticket facts for the explainer")
    ap.add_argument("--service", action="append", default=[], help="service name; repeat for several")
    ap.add_argument("--repo", help="owner/name (default: origin of the current checkout; required elsewhere)")
    ap.add_argument("--ref", help="branch, tag or sha to read (default: the repo's default branch)")
    ap.add_argument("--doc", action="append", default=[], help="a local text file (Confluence export, requirements); repeat")
    ap.add_argument("--ticket", help="IFS-123 or DX-123: read the ticket and infer the service from it")
    ap.add_argument("--all", action="store_true", help="accept more than 8 matched Applications")
    ap.add_argument("--out", required=True, help="work directory for facts.json")
    args = ap.parse_args()
    if not args.service and not args.ticket:
        sys.exit("collect: pass --service NAME and/or --ticket KEY")
    repo = args.repo or repo_from_origin()
    if not repo:
        sys.exit("collect: the current directory is not a GitHub checkout; pass --repo owner/name")
    ref = args.ref or default_branch(repo)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    trees = Trees.at(repo, ref)
    try:
        facts = collect_system(repo, trees, args.service, args.doc, args.ticket, args.all)
    finally:
        trees.close()
    (out / "facts.json").write_text(json.dumps(facts, indent=2))
    scopes = sorted({a["scope"] for a in facts["apps"] if a["scope"]})
    unrendered = [a["app"] for a in facts["apps"] if a["render"] != "rendered"]
    print(f"collect: {facts['mode']} mode at {ref} ({facts['query']['sha'][:7]}): "
          f"{len({a['app'] for a in facts['apps']})} apps in {scopes or ['one environment']}, "
          f"{len(facts['resources'])} resources, {len(facts['edges'])} edges, {len(facts['config'])} config rows, "
          f"{len(facts['terraform'])} terraform blocks, {len(facts['workflows'])} workflow entries, "
          f"{len(facts['docs'])} docs, ticket: {(facts['jira'] or {}).get('key') or 'none'}, "
          f"unrendered apps: {unrendered or 'none'}")
    print(f"collect: wrote {out / 'facts.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
