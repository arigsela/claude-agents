#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///
"""review-retro: find Claude Code sessions that ran /code-review on the given PR numbers (spec §7.2)."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

PROJECTS = Path.home() / ".claude" / "projects"
CMD_RE = re.compile(r"<command-name>/(?:[\w-]+:)?code-review</command-name>")
ARGS_RE = re.compile(r"<command-args>(.*?)</command-args>", re.S)
NUM_RE = re.compile(r"(?<!--threshold )(?<![\d.])(\d{1,6})(?![\d.])")
GH_PR_RE = re.compile(r"gh pr (?:diff|view)\s+(\d+)")


def text_of(content) -> str:
    if isinstance(content, str):
        return content
    return "\n".join(b.get("text", "") for b in content or [] if isinstance(b, dict) and b.get("type") == "text")


def scan(path: Path, prs: set[int], repo_name: str | None) -> list[dict]:
    hits, seen, meta = [], set(), {"cwd": None, "started": None, "first_prompt": None}
    review_active = False
    with path.open(errors="replace") as fh:
        for lineno, line in enumerate(fh, start=1):
            if meta["first_prompt"] is not None and "code-review" not in line and "gh pr" not in line:
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
                if CMD_RE.search(text):
                    review_active = True
                    args = (ARGS_RE.search(text) or [None, ""])[1]
                    found += [(int(n), "command", args) for n in NUM_RE.findall(args)]
            elif rec.get("type") == "assistant":
                for b in msg.get("content") or []:
                    if not isinstance(b, dict) or b.get("type") != "tool_use":
                        continue
                    inp = b.get("input") or {}
                    if b.get("name") == "Skill" and str(inp.get("skill", "")).split(":")[-1] == "code-review":
                        review_active = True
                        args = str(inp.get("args", ""))
                        found += [(int(n), "skill", args) for n in NUM_RE.findall(args)]
                    elif review_active and b.get("name") == "Bash":
                        cmd = str(inp.get("command", ""))
                        found += [(int(n), "bash", cmd) for n in GH_PR_RE.findall(cmd)]
            for number, how, context in found:
                if number not in prs or number in seen:
                    continue
                cwd_ok = repo_name is None or (meta["cwd"] and Path(meta["cwd"]).name == repo_name)
                if not cwd_ok and repo_name not in context:
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
    repo_name = args.repo.split("/")[-1] if args.repo else None
    results = []
    for path in sorted(PROJECTS.glob("*/*.jsonl")):  # top level only; subagents live in subdirs
        results += scan(path, set(args.pr), repo_name)
    results.sort(key=lambda h: (h["pr"], h["started"] or ""))
    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
