#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///
"""pr-explainer: read (--get-url) or upsert the sticky explainer comment on a PR."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys

MARKER_RE = re.compile(r"^<!-- pr-explainer url=(\S+) sha=(\S+) -->")


URL_PREFIX = "https://claude.ai/"


def gh(*args: str, stdin: str | None = None) -> str:
    proc = subprocess.run(["gh", *args], input=stdin, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.exit(f"post_comment: gh {' '.join(args[:3])} failed: {proc.stderr.strip()}")
    return proc.stdout


def comments(repo: str, pr: int) -> list[dict]:
    pages = json.loads(gh("api", "--paginate", "--slurp", f"repos/{repo}/issues/{pr}/comments?per_page=100"))
    return [c for page in pages for c in page]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--pr", type=int, required=True)
    ap.add_argument("--get-url", action="store_true")
    ap.add_argument("--url")
    ap.add_argument("--sha")
    args = ap.parse_args()
    if not args.get_url:
        if not (args.url and args.sha):
            sys.exit("post_comment: --url and --sha are required to post")
        if not args.url.startswith(URL_PREFIX):
            sys.exit(f"post_comment: refusing --url that does not start with {URL_PREFIX}")
    login = gh("api", "user", "--jq", ".login").strip()
    existing = next((c for c in comments(args.repo, args.pr)
                     if (c.get("user") or {}).get("login") == login
                     and MARKER_RE.match(c.get("body") or "")), None)
    if args.get_url:
        if existing:
            url = MARKER_RE.match(existing["body"]).group(1)
            if url.startswith(URL_PREFIX):
                print(url)
        return 0
    body = (f"<!-- pr-explainer url={args.url} sha={args.sha} -->\n"
            f"📖 Explainer for `{args.sha[:7]}`: {args.url} (private link)")
    payload = json.dumps({"body": body})
    if existing:
        gh("api", "-X", "PATCH", f"repos/{args.repo}/issues/comments/{existing['id']}", "--input", "-", stdin=payload)
    else:
        gh("api", "-X", "POST", f"repos/{args.repo}/issues/{args.pr}/comments", "--input", "-", stdin=payload)
    print("post_comment: done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
