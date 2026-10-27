"""Claude Code PreToolUse hook: reject any tool call that leaves Taskboard or the checkouts.

Reads the hook JSON ({"tool_name", "tool_input", ...}) on stdin. Exit 0 allows the call;
exit 2 blocks it and Claude sees the reason from stderr. Any error blocks (fail closed).
"""

from __future__ import annotations

import argparse
import json
import shlex
import sys

from bug_investigator import scope


WRITE_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")


def decide(payload: dict, mode: str, roots: list[str], namespace: str,
           allow_commands: list[str] | tuple[str, ...] = ()) -> str | None:
    """None allows the call. Modes: full and n8n (investigate, read-only), fix (edit the app checkout)."""
    tool = payload.get("tool_name") or ""
    tool_input = payload.get("tool_input") or {}
    if tool.startswith("mcp__"):
        if mode != "full":
            return f"telemetry tools are not available in {mode} mode"
        return scope.check_tool_call(tool, tool_input, namespace)
    if tool == "Bash":
        extra = tuple(tuple(shlex.split(c)) for c in allow_commands if c.strip())
        return scope.check_bash(tool_input.get("command") if isinstance(tool_input, dict) else None, roots, mode,
                                extra)
    if tool in ("Read", "Grep", "Glob"):
        return scope.check_path_tool(tool, tool_input, roots)
    if tool in WRITE_TOOLS:
        if mode != "fix":
            return f"file edits are not available in {mode} mode"
        return scope.check_write_path(tool, tool_input, roots[0] if roots else "")
    return None


def main(argv: list[str] | None = None, stdin=None) -> int:
    p = argparse.ArgumentParser(prog="hook")
    p.add_argument("--mode", default="full")
    p.add_argument("--root", action="append", default=[], help="checkout dir; the first is the working dir")
    p.add_argument("--namespace", default=scope.NAMESPACE)
    p.add_argument("--allow-command", action="append", default=[],
                   help="fix mode: an extra allowed command prefix (the configured test command)")
    args = p.parse_args(argv)
    try:
        payload = json.load(stdin or sys.stdin)
        if not isinstance(payload, dict):
            raise ValueError("hook input is not an object")
        reason = decide(payload, args.mode, args.root, args.namespace, args.allow_command)
    except Exception as e:  # fail closed
        reason = f"hook error: {e}"
    if reason:
        print(f"Blocked by bug-investigator scope: {reason}", file=sys.stderr)
        return 2
    return 0
