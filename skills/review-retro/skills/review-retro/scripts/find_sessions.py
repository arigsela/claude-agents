#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///
"""review-retro: find Claude Code sessions that ran /code-review on the given PR numbers (spec §7.2)."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

PROJECTS = Path.home() / ".claude" / "projects"
CMD_RE = re.compile(r"<command-name>/(?:code-review|code-review:code-review)</command-name>")
SKILL_NAMES = {"code-review", "code-review:code-review"}
ARGS_RE = re.compile(r"<command-args>(.*?)</command-args>", re.S)
NUM_RE = re.compile(r"(?<!--threshold )(?<![\d.])(\d{1,6})(?![\d.])")
GH_PR_RE = re.compile(r"gh pr (?:diff|view)\s+(\d+)")


_ORIGIN_CACHE: dict[str, str | None] = {}
_REMOTE_RE = re.compile(r"(?:github\.com[:/])([^/\s]+)/([^/\s]+?)(?:\.git)?/?$")


def origin_repo(cwd: str | None) -> str | None:
    """owner/name of the cwd's origin remote (https or ssh), or None if it cannot be resolved."""
    if not cwd:
        return None
    if cwd not in _ORIGIN_CACHE:
        repo = None
        try:
            url = subprocess.run(["git", "-C", cwd, "remote", "get-url", "origin"],
                                 capture_output=True, text=True, check=True, timeout=10).stdout.strip()
            m = _REMOTE_RE.search(url)
            repo = f"{m.group(1)}/{m.group(2)}" if m else None
        except (subprocess.SubprocessError, OSError):
            pass
        _ORIGIN_CACHE[cwd] = repo
    return _ORIGIN_CACHE[cwd]


def repo_matches(repo: str | None, cwd: str | None, context: str) -> bool:
    if repo is None:
        return True
    resolved = origin_repo(cwd)
    if resolved:
        return resolved.lower() == repo.lower()
    if repo in context:
        return True
    return bool(cwd) and not Path(cwd).exists() and Path(cwd).name == repo.split("/")[-1]


def is_human_prompt(rec: dict) -> bool:
    """A real human turn: user record, not a tool_result, not isMeta, not a task-notification."""
    if rec.get("type") != "user" or rec.get("isMeta"):
        return False
    if (rec.get("origin") or {}).get("kind") == "task-notification":
        return False
    content = (rec.get("message") or {}).get("content")
    return not (isinstance(content, list)
                and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content))


def text_of(content) -> str:
    if isinstance(content, str):
        return content
    return "\n".join(b.get("text", "") for b in content or [] if isinstance(b, dict) and b.get("type") == "text")


def scan(path: Path, prs: set[int], repo: str | None) -> list[dict]:
    hits, seen, meta = [], set(), {"cwd": None, "started": None, "first_prompt": None}
    armed = False  # gh fallback: only after a code-review invocation that named no PR number
    with path.open(errors="replace") as fh:
        for lineno, line in enumerate(fh, start=1):
            if (meta["first_prompt"] is not None and "code-review" not in line and "gh pr" not in line
                    and '"type":"user"' not in line and '"type": "user"' not in line):
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            meta["started"] = meta["started"] or rec.get("timestamp")
            meta["cwd"] = meta["cwd"] or rec.get("cwd")
            msg = rec.get("message") or {}
            found: list[tuple[int, str, str]] = []
            if rec.get("type") == "user":
                text = text_of(msg.get("content"))
                if meta["first_prompt"] is None and text.strip() and "tool_result" not in line:
                    meta["first_prompt"] = text.strip()[:200]
                if not CMD_RE.search(text) and is_human_prompt(rec):
                    armed = False  # the next human prompt disarms the gh fallback
                if CMD_RE.search(text):
                    args = (ARGS_RE.search(text) or [None, ""])[1]
                    nums = NUM_RE.findall(args)
                    armed = not nums
                    found += [(int(n), "command", args) for n in nums]
            elif rec.get("type") == "assistant":
                for b in msg.get("content") or []:
                    if not isinstance(b, dict) or b.get("type") != "tool_use":
                        continue
                    inp = b.get("input") or {}
                    if b.get("name") == "Skill" and str(inp.get("skill", "")) in SKILL_NAMES:
                        args = str(inp.get("args", ""))
                        nums = NUM_RE.findall(args)
                        armed = not nums
                        found += [(int(n), "skill", args) for n in nums]
                    elif armed and b.get("name") == "Bash":
                        cmd = str(inp.get("command", ""))
                        m = GH_PR_RE.search(cmd)
                        if m:
                            armed = False  # first gh pr diff|view consumes the fallback
                            found.append((int(m.group(1)), "bash", cmd))
            for number, how, context in found:
                if number not in prs or number in seen:
                    continue
                if not repo_matches(repo, meta["cwd"], context):
                    continue
                seen.add(number)
                hits.append({"pr": number, "session_id": path.stem, "path": str(path), "line": lineno,
                             "match": how, **meta})
    return hits


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", help="owner/name; sessions must run in a checkout of it or name it")
    ap.add_argument("--pr", type=int, action="append", required=True)
    args = ap.parse_args()
    results = []
    for path in sorted(PROJECTS.glob("*/*.jsonl")):  # top level only; subagents live in subdirs
        try:
            results += scan(path, set(args.pr), args.repo)
        except (OSError, UnicodeError) as e:
            print(f"find_sessions: skipped {path}: {e}", file=sys.stderr)
    results.sort(key=lambda h: (h["pr"], h["started"] or ""))
    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
