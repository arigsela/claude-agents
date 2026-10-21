"""Thin wrappers over the gh CLI (auth via GH_TOKEN or `gh auth login`)."""
from __future__ import annotations

import json
import subprocess


class GhError(RuntimeError):
    pass


def _run(args: list[str], stdin: str | None = None) -> str:
    proc = subprocess.run(["gh", *args], input=stdin, capture_output=True, text=True)
    if proc.returncode != 0:
        raise GhError(f"gh {' '.join(args)} failed: {proc.stderr.strip()} {proc.stdout.strip()}")
    return proc.stdout


def api(path: str, *, method: str = "GET", body: dict | None = None, paginate: bool = False):
    args = ["api", "-X", method, path]
    if paginate:
        args += ["--paginate", "--slurp"]
    stdin = None
    if body is not None:
        args += ["--input", "-"]
        stdin = json.dumps(body)
    out = _run(args, stdin)
    if not out.strip():
        return None
    data = json.loads(out)
    if paginate:  # --slurp wraps each page in an outer list
        return [item for page in data for item in page]
    return data


def get_pr(repo: str, number: int) -> dict:
    return api(f"repos/{repo}/pulls/{number}")


def get_pr_files(repo: str, number: int) -> list[dict]:
    return api(f"repos/{repo}/pulls/{number}/files?per_page=100", paginate=True)


def get_file(repo: str, path: str, ref: str) -> str | None:
    try:
        return _run(["api", "-H", "Accept: application/vnd.github.raw",
                     f"repos/{repo}/contents/{path}?ref={ref}"])
    except GhError as err:
        if "404" in str(err) or "Not Found" in str(err):
            return None
        raise


def list_issue_comments(repo: str, number: int) -> list[dict]:
    return api(f"repos/{repo}/issues/{number}/comments?per_page=100", paginate=True)


def create_comment(repo: str, number: int, body: str) -> None:
    api(f"repos/{repo}/issues/{number}/comments", method="POST", body={"body": body})


def update_comment(repo: str, comment_id: int, body: str) -> None:
    api(f"repos/{repo}/issues/comments/{comment_id}", method="PATCH", body={"body": body})


def ensure_label(repo: str, name: str, color: str) -> None:
    try:
        api(f"repos/{repo}/labels", method="POST", body={"name": name, "color": color})
    except GhError as err:
        if "already_exists" not in str(err):
            raise


def labels_on(repo: str, number: int) -> list[str]:
    return [label["name"] for label in api(f"repos/{repo}/issues/{number}/labels")]


def add_label(repo: str, number: int, name: str) -> None:
    api(f"repos/{repo}/issues/{number}/labels", method="POST", body={"labels": [name]})


def remove_label(repo: str, number: int, name: str) -> None:
    api(f"repos/{repo}/issues/{number}/labels/{name}", method="DELETE")


def list_merged_prs(repo: str, limit: int) -> list[dict]:
    out = _run(["pr", "list", "-R", repo, "--state", "merged", "--limit", str(limit),
                "--json", "number,title,mergedAt,additions,deletions"])
    return json.loads(out)
