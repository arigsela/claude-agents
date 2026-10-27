"""Ticket adapter (GitHub Issues through `gh`): read the ticket, past bugs, PRs; post the update.

Monday mapping (README): items and updates over GraphQL; post with create_update.
`main` is the `post` command, the only code that writes.
"""

from __future__ import annotations

import argparse
import glob
import os
import re
import sys

from bug_investigator.util import CommandError, Runner, run, run_json

MARKER = "<!-- bug-investigator mode={mode} -->"
MARKER_RE = re.compile(r"<!-- bug-investigator mode=([a-z0-9]+) -->")


class Gh:
    def __init__(self, repo: str, runner: Runner = run):
        self.repo = repo
        self.run = runner

    def json(self, *args: str):
        return run_json(self.run, ["gh", *args])

    def issue(self, number: int) -> dict:
        return self.json("issue", "view", str(number), "--repo", self.repo, "--json",
                         "number,title,body,author,createdAt,comments,labels,state,url")

    def merged_prs(self, limit: int = 50) -> list[dict]:
        return self.json("pr", "list", "--repo", self.repo, "--state", "merged", "--limit", str(limit), "--json",
                         "number,title,mergedAt,author,body,files,url,mergeCommit,labels") or []

    def pr_discussion(self, number: int) -> dict:
        d = self.json("pr", "view", str(number), "--repo", self.repo, "--json", "reviews,comments") or {}
        try:
            inline = self.json("api", f"repos/{self.repo}/pulls/{number}/comments", "--paginate") or []
        except (CommandError, ValueError):
            inline = []
        d["review_comments"] = inline
        return d

    def closed_bugs(self, limit: int = 50) -> list[dict]:
        return self.json("issue", "list", "--repo", self.repo, "--state", "closed", "--label", "bug",
                         "--limit", str(limit), "--json", "number,title,body,closedAt,labels,url") or []

    def closing_prs(self, number: int) -> list[dict]:
        try:
            d = self.json("issue", "view", str(number), "--repo", self.repo, "--json", "closedByPullRequestsReferences")
        except (CommandError, ValueError):
            return []
        return (d or {}).get("closedByPullRequestsReferences") or []

    def pr_state(self, number: int) -> dict | None:
        try:
            return self.json("pr", "view", str(number), "--repo", self.repo, "--json", "number,state,mergedAt,title,url")
        except (CommandError, ValueError):
            return None

    def issue_state(self, number: int) -> dict | None:
        try:
            return self.json("issue", "view", str(number), "--repo", self.repo, "--json", "number,state,title,url,labels")
        except (CommandError, ValueError):
            return None


def label_names(item: dict) -> set[str]:
    return {(lb.get("name") if isinstance(lb, dict) else str(lb)) for lb in item.get("labels") or []}


# ---------------------------------------------------------------------------------- post


def find_own_comment(comments: list[dict], mode: str) -> dict | None:
    marker = MARKER.format(mode=mode)
    for c in comments:
        user = c.get("user") or {}
        if marker in (c.get("body") or "") and (user.get("type") == "Bot" or user.get("login", "").endswith("[bot]")):
            return c
    return None


def post(repo: str, issue: int, comment_dir: str, runner: Runner = run, label: str = "investigated") -> list[str]:
    files = sorted(glob.glob(os.path.join(comment_dir, "**", "comment-*.md"), recursive=True))
    if not files:
        print("no comment files to post", file=sys.stderr)
        return []
    pages = run_json(runner, ["gh", "api", "--paginate", "--slurp", f"repos/{repo}/issues/{issue}/comments?per_page=100"]) or []
    comments = [c for page in pages for c in (page if isinstance(page, list) else [page])]
    done = []
    for path in files:
        with open(path) as f:
            body = f.read()
        m = MARKER_RE.search(body)
        if not m:
            print(f"{path}: no marker, skipped", file=sys.stderr)
            continue
        mode = m.group(1)
        existing = find_own_comment(comments, mode)
        if existing:
            runner(["gh", "api", "-X", "PATCH", f"repos/{repo}/issues/comments/{existing['id']}",
                    "-f", f"body={body}", "--silent"])
            done.append(f"edited {mode}")
        else:
            runner(["gh", "api", "-X", "POST", f"repos/{repo}/issues/{issue}/comments", "-f", f"body={body}", "--silent"])
            done.append(f"created {mode}")
    if done and label:
        try:
            runner(["gh", "api", "-X", "POST", f"repos/{repo}/issues/{issue}/labels", "-f", f"labels[]={label}", "--silent"])
        except CommandError as e:
            print(f"could not add label {label}: {e}", file=sys.stderr)
    return done


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="post")
    p.add_argument("--repo", required=True)
    p.add_argument("--issue", type=int, required=True)
    p.add_argument("--dir", required=True, help="directory holding comment-<mode>.md files")
    p.add_argument("--label", default="investigated")
    a = p.parse_args(argv)
    for line in post(a.repo, a.issue, a.dir, label=a.label):
        print(line)
    return 0
