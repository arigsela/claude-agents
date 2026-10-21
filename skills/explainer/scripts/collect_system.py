#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6", "pathspec>=0.12,<1"]
# ///
"""explainer: collect deterministic facts about a service, a ticket's system or a plan's repo at one ref.

Usage: collect_system.py --service NAME [--service NAME]... [--repo owner/name] [--ref main]
                         [--doc FILE]... [--ticket KEY] [--all] --out DIR
       collect_system.py --plan --doc ONE_PAGER [--term TERM]... [--repo owner/name] [--ref main] --out DIR
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
    ap.add_argument("--plan", action="store_true", help="the --doc files are a plan (a one-pager); no Application is required")
    ap.add_argument("--term", action="append", default=[], help="plan mode: a term to search for besides the plan's backticked identifiers; repeat")
    ap.add_argument("--out", required=True, help="work directory for facts.json")
    args = ap.parse_args()
    if args.plan and not args.doc:
        sys.exit("collect: --plan needs the plan as --doc FILE")
    if args.term and not args.plan:
        sys.exit("collect: --term only applies with --plan")
    if not args.service and not args.ticket and not args.plan:
        sys.exit("collect: pass --service NAME, --ticket KEY or --plan --doc FILE")
    repo = args.repo or repo_from_origin()
    if not repo:
        sys.exit("collect: the current directory is not a GitHub checkout; pass --repo owner/name")
    ref = args.ref or default_branch(repo)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    trees = Trees.at(repo, ref)
    try:
        facts = collect_system(repo, trees, args.service, args.doc, args.ticket, args.all, args.plan, args.term)
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
    if "term_hits" in facts["query"]:
        hits = facts["query"]["term_hits"]
        print(f"collect: {len(hits)} {facts['mode']} terms, {sum(1 for v in hits.values() if v)} found in the repo, "
              f"missing: {[t for t, v in hits.items() if not v] or 'none'}")
    links = (facts.get("jira") or {}).get("doc_links") or []
    read = {d.get("url") for d in facts["docs"]}
    if [u for u in links if u not in read]:
        print(f"collect: Confluence pages the ticket or its epic link to, not yet read: {[u for u in links if u not in read]}")
    print(f"collect: wrote {out / 'facts.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
