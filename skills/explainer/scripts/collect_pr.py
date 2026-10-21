#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6", "pathspec>=0.12,<1"]
# ///
"""explainer: collect deterministic facts about a PR into <out>/facts.json and <out>/diff.patch.

Usage: collect_pr.py --pr N [--repo owner/name] --out DIR   (--repo is required outside a checkout of the repo)
The work is in facts_lib.collect(); this file only parses arguments, fetches the PR with gh and writes the files.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from facts_lib import Trees, collect, gh_pages, repo_from_origin, sh, trusted_comments


def main() -> int:
    ap = argparse.ArgumentParser(description="Collect deterministic PR facts for the explainer")
    ap.add_argument("--pr", type=int, required=True)
    ap.add_argument("--repo", help="owner/name (default: origin of the current checkout; required elsewhere)")
    ap.add_argument("--out", required=True, help="work directory for facts.json and diff.patch")
    args = ap.parse_args()
    repo = args.repo or repo_from_origin()
    if not repo:
        sys.exit("collect: the current directory is not a GitHub checkout; pass --repo owner/name")
    pr = json.loads(sh("gh", "api", f"repos/{repo}/pulls/{args.pr}"))
    files = gh_pages(f"repos/{repo}/pulls/{args.pr}/files?per_page=100")
    comments = gh_pages(f"repos/{repo}/issues/{args.pr}/comments?per_page=100")
    comments = trusted_comments(comments, sh("gh", "api", "user", "--jq", ".login").strip())
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "diff.patch").write_text(sh("gh", "pr", "diff", str(args.pr), "-R", repo))
    trees = Trees(repo, args.pr, pr["base"]["sha"], pr["head"]["sha"])
    try:
        facts = collect(repo, pr, files, comments, trees)
    finally:
        trees.close()
    (out / "facts.json").write_text(json.dumps(facts, indent=2))
    changed = sum(r["action"] not in ("context", "generated") for r in facts["resources"])
    unrendered = [a["app"] for a in facts["apps"] if a["render"] != "rendered"]
    wf_changed = sum(w["action"] != "context" for w in facts["workflows"])
    print(f"collect: {changed} changed resources, {len(facts['terraform'])} terraform resources, "
          f"{wf_changed} workflow entries, {len(facts['edges'])} edges, "
          f"{len(facts['non_manifest_changes'])} non-manifest files, {len(facts['policy_hits'])} policy hits, "
          f"unrendered apps: {unrendered or 'none'}")
    print(f"collect: plans: {[p['environment'] or p['source'] for p in facts['terraform_plans']] or 'none'}, "
          f"ticket: {(facts['jira'] or {}).get('key') or 'none'}")
    print(f"collect: wrote {out / 'facts.json'} and {out / 'diff.patch'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
