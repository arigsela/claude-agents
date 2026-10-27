"""Build what claude-code-action gets: settings (permissions + hooks), MCP config, prompt, claude_args.

`prep` writes them and sets step outputs. `selftest` proves the hook blocks before Claude starts,
and that the Grafana token is in no environment variable (claude-code-action passes the whole
environment to Claude).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import uuid

from bug_investigator import scope
from bug_investigator.util import read_secret, write_json

FULL_TOOLS = [
    "Read", "Grep", "Glob",
    "Bash(git log:*)", "Bash(git show:*)", "Bash(git blame:*)", "Bash(git diff:*)",
    "Bash(gh pr view:*)", "Bash(gh pr list:*)", "Bash(gh pr diff:*)",
    "Bash(gh issue view:*)", "Bash(gh issue list:*)",
] + [f"mcp__grafana__{t}" for t in scope.GRAFANA_TOOLS]
N8N_TOOLS = ["Read", "Grep", "Glob"]
DISALLOWED = ["WebFetch", "WebSearch", "Write", "Edit", "MultiEdit", "NotebookEdit", "Task"]
# The fix agent: read, edit the app checkout, look at its diff, and run the tests only through the
# exact run-tests.sh command (a sandbox container). No MCP, no web, no gh, no other commands.
FIX_TOOLS = ["Read", "Grep", "Glob", "Edit", "Write", "Bash(git diff:*)", "Bash(git status:*)"]
FIX_DISALLOWED = ["WebFetch", "WebSearch", "MultiEdit", "NotebookEdit", "Task"]
SAFE_COMMAND = re.compile(r"^[A-Za-z0-9_./=:+-]+( [A-Za-z0-9_./=:+-]+)*$")

FULL_NOTES = """## Tools in this run

- Read, Grep, Glob over the Taskboard checkout (your working directory){deploy_note}.
- Bash, one command at a time, no pipes or redirects: `git log`, `git show`, `git blame`,
  `git diff` (use `git -C {deploy_dir} log ...` for the deploy repo), `gh pr view|list|diff`,
  `gh issue view|list`.
- Grafana: `mcp__grafana__query_loki_logs`, `query_loki_stats`, `list_loki_label_names`,
  `list_loki_label_values` (datasourceUid `{loki}`) and `mcp__grafana__query_prometheus`
  (datasourceUid `{prom}`). Every Loki stream selector must include `namespace="{ns}"`; every
  Prometheus selector must include `namespace="{ns}"` or use a `{ns}_*` metric. Other queries are
  blocked. Pass explicit RFC 3339 start and end times.
"""

N8N_NOTES = """## Tools in this run (n8n-style baseline)

This run sees what a simple ticket-to-LLM flow sees: the ticket and the code at HEAD. You have
Read, Grep and Glob over the checkout and nothing else: no git history, no pull requests, no
product docs, no deploy timeline, no past bugs, no telemetry. Do your best with the code; evidence
can only be `file` items. Put everything you would have needed into `could_not_check`.
"""


def hook_command(run_py: str, mode: str, roots: list[str], namespace: str, allow_commands: tuple = ()) -> str:
    parts = ["python3", "-I", run_py, "hook", "--mode", mode, "--namespace", namespace]
    for r in roots:
        parts += ["--root", r]
    for c in allow_commands:
        parts += ["--allow-command", c]
    return " ".join(shlex.quote(p) for p in parts)


def check_test_command(cmd: str) -> str | None:
    """The test command goes into --allowedTools and the hook: plain words only."""
    if not isinstance(cmd, str) or not SAFE_COMMAND.match(cmd.strip()):
        return f"test-command {cmd!r} must be plain words (letters, digits, _ . / = : + -), no shell syntax"
    return None


RUN_TESTS = "run-tests"


def run_tests_command(action_path: str, app_dir: str, test_command: str) -> str:
    """The one test command the fix agent may run: `run-tests`, a wrapper on PATH (run_tests_wrapper).

    It names no path on purpose: Claude Code refuses Bash commands that mention a path outside the
    working directory (or under a denied Read rule), and the action dir is both, so a command like
    `bash <action>/run-tests.sh …` is always denied (seen on taskboard#26)."""
    for part in (os.path.join(action_path, "run-tests.sh"), app_dir, test_command):
        problem = check_test_command(part)
        if problem:
            raise ValueError(problem)
    return RUN_TESTS


def run_tests_wrapper(action_path: str, app_dir: str, test_command: str) -> str:
    """The script installed as `run-tests` on PATH: the sandbox script with fixed arguments, no others."""
    run_tests_command(action_path, app_dir, test_command)  # same checks
    argv = [os.path.join(action_path, "run-tests.sh"), app_dir] + test_command.split()
    return ("#!/usr/bin/env bash\n"
            "# The fix agent's only way to run tests: the sandbox container (run-tests.sh), fixed arguments.\n"
            "set -euo pipefail\n"
            'if [ "$#" -ne 0 ]; then echo "run-tests takes no arguments" >&2; exit 2; fi\n'
            f"exec bash {' '.join(shlex.quote(x) for x in argv)}\n")


def build_settings(run_py: str, mode: str, roots: list[str], namespace: str, deny_dirs: list[str],
                   run_command: str | None = None) -> dict:
    allow = (run_command,) if mode == "fix" and run_command else ()
    cmd = hook_command(run_py, mode, roots, namespace, allow)
    entry = {"type": "command", "command": cmd, "timeout": 10}
    # Read rules also cover Grep and Glob. A leading // means an absolute path.
    deny = [f"Read(/{d.rstrip('/')}/**)" for d in deny_dirs if d]
    hooks = [
        {"matcher": "mcp__.*", "hooks": [entry]},
        {"matcher": "Bash", "hooks": [entry]},
        {"matcher": "Read|Grep|Glob", "hooks": [entry]},
    ]
    if mode == "fix":
        app = roots[0].rstrip("/")
        for tool in ("Edit", "Write"):
            deny += [f"{tool}(/{d.rstrip('/')}/**)" for d in deny_dirs if d]
            # The hook checks every protected path; these rules are a second layer for the main ones.
            deny += [f"{tool}(/{app}/{p}/**)" for p in scope.PROTECTED_DIRS + (".git",)]
            deny += [f"{tool}(/{app}/{p})" for p in sorted(scope.PROTECTED_NAMES)]
        hooks.append({"matcher": "Edit|Write|MultiEdit|NotebookEdit", "hooks": [entry]})
    return {"permissions": {"blockReadsOutsideWorkingDirectories": True, "deny": deny},
            "hooks": {"PreToolUse": hooks}}


def build_mcp_config(binary: str, grafana_url: str, token_file: str, namespace: str) -> dict:
    return {"mcpServers": {"grafana": {
        "command": binary,
        "args": ["-t", "stdio", "--disable-write", "--disable-api", "--disable-rendering",
                 "--enabled-tools", "loki,prometheus", "--max-loki-log-limit", "100",
                 "--loki-enforced-matchers", f'namespace="{namespace}"', "--usage-stats=disabled"],
        "env": {"GRAFANA_URL": grafana_url, "GRAFANA_SERVICE_ACCOUNT_TOKEN_FILE": token_file},
    }}}


def build_claude_args(mode: str, model: str, max_turns: int, schema: dict, mcp_config: str | None,
                      add_dirs: list[str], run_command: str | None = None) -> str:
    schema_json = json.dumps(schema, separators=(",", ":"))
    if "'" in schema_json:
        raise ValueError("findings schema must not contain single quotes (claude_args quoting)")
    if mode == "fix":
        tools, disallowed = list(FIX_TOOLS), FIX_DISALLOWED
        if run_command:
            if check_test_command(run_command):
                raise ValueError(check_test_command(run_command))
            tools.append(f"Bash({run_command})")  # exact: no other arguments
        mcp_config, add_dirs = None, []  # the fix agent gets no MCP servers and no other directories
    else:
        tools, disallowed = (FULL_TOOLS if mode == "full" else N8N_TOOLS), DISALLOWED
    args = [f"--model {shlex.quote(model)}", f"--max-turns {int(max_turns)}",
            f'--allowedTools "{",".join(tools)}"', f'--disallowedTools "{",".join(disallowed)}"',
            f"--json-schema '{schema_json}'"]
    if mcp_config:
        args.append(f"--mcp-config {shlex.quote(mcp_config)}")
    for d in add_dirs:
        args.append(f"--add-dir {shlex.quote(d)}")
    return "\n".join(args)


def build_prompt(template: str, mode: str, issue: int, repo: str, facts_md: str, deploy_dir: str | None,
                 namespace: str) -> str:
    if mode == "full":
        notes = FULL_NOTES.format(
            deploy_note=f", and the deploy repo checkout at `{deploy_dir}` (Read/Grep it by absolute path)"
            if deploy_dir else "",
            deploy_dir=deploy_dir or "<deploy dir>", loki=scope.LOKI_UID, prom=scope.PROM_UID, ns=namespace)
    else:
        notes = N8N_NOTES
    return (template.replace("{{ISSUE}}", str(issue)).replace("{{REPO}}", repo)
            .replace("{{MODE_NOTES}}", notes.strip()).replace("{{FACTS}}", facts_md.strip()))


def set_output(path: str | None, name: str, value: str) -> None:
    if not path:
        print(f"{name}={value}")
        return
    delim = f"ghadelimiter_{uuid.uuid4().hex}"
    with open(path, "a") as f:
        f.write(f"{name}<<{delim}\n{value}\n{delim}\n")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="prep")
    p.add_argument("--mode", choices=("full", "n8n"), required=True)
    p.add_argument("--issue", type=int, required=True)
    p.add_argument("--repo", required=True)
    p.add_argument("--app-dir", required=True)
    p.add_argument("--deploy-dir")
    p.add_argument("--action-path", required=True)
    p.add_argument("--work-dir", required=True, help="outside every working dir; holds settings, facts, outputs")
    p.add_argument("--deny-dir", action="append", default=[])
    p.add_argument("--token-file")
    p.add_argument("--grafana-url", default="")
    p.add_argument("--mcp-binary")
    p.add_argument("--model", default="claude-sonnet-5-5")
    p.add_argument("--max-turns", type=int, default=40)
    p.add_argument("--namespace", default=scope.NAMESPACE)
    a = p.parse_args(argv)

    run_py = os.path.join(a.action_path, "run.py")
    roots = [a.app_dir] + ([a.deploy_dir] if a.mode == "full" and a.deploy_dir else [])
    deny = [a.action_path, a.work_dir] + a.deny_dir
    settings_path = os.path.join(a.work_dir, "claude-settings.json")
    write_json(settings_path, build_settings(run_py, a.mode, roots, a.namespace, deny))

    mcp_path = None
    if a.mode == "full":
        if not (a.mcp_binary and a.token_file and a.grafana_url):
            print("full mode needs --mcp-binary, --token-file and --grafana-url", file=sys.stderr)
            return 2
        mcp_path = os.path.join(a.work_dir, "mcp-config.json")
        write_json(mcp_path, build_mcp_config(a.mcp_binary, a.grafana_url, a.token_file, a.namespace))

    with open(os.path.join(a.action_path, "findings.schema.json")) as f:
        schema = json.load(f)
    claude_args = build_claude_args(a.mode, a.model, a.max_turns, schema, mcp_path, roots[1:])
    with open(os.path.join(a.action_path, "prompt.md")) as f:
        template = f.read()
    with open(os.path.join(a.work_dir, "facts.md")) as f:
        facts_md = f.read()
    prompt = build_prompt(template, a.mode, a.issue, a.repo, facts_md, roots[1] if len(roots) > 1 else None, a.namespace)
    with open(os.path.join(a.work_dir, "prompt.txt"), "w") as f:
        f.write(prompt)

    out = os.environ.get("GITHUB_OUTPUT")
    set_output(out, "settings", settings_path)
    set_output(out, "claude_args", claude_args)
    set_output(out, "prompt", prompt)
    set_output(out, "hook_command", hook_command(run_py, a.mode, roots, a.namespace))
    print(f"prep: mode={a.mode} roots={roots} prompt={len(prompt)} chars")
    return 0


# ---------------------------------------------------------------------------------- selftest

PROM = scope.PROM_UID


def selftest(hook_cmd: str, mode: str, token: str, env: dict, namespace: str = scope.NAMESPACE) -> list[str]:
    other = "kube-system" if namespace != "kube-system" else "default"
    scoped = {"tool_name": "mcp__grafana__query_loki_logs", "tool_input": {
        "datasourceUid": scope.LOKI_UID, "logql": f'{{namespace="{namespace}"}} | json'}}
    cases = [
        ({"tool_name": "mcp__grafana__query_prometheus", "tool_input": {
            "datasourceUid": PROM, "expr": "sum(rate(container_cpu_usage_seconds_total[5m]))", "endTime": "now"}}, 2),
        ({"tool_name": "mcp__grafana__query_loki_logs", "tool_input": {
            "datasourceUid": scope.LOKI_UID, "logql": f'{{namespace="{other}"}}'}}, 2),
        ({"tool_name": "Bash", "tool_input": {"command": "env"}}, 2),
        ({"tool_name": "Read", "tool_input": {"file_path": "/etc/passwd"}}, 2),
        # Full mode must allow a scoped query; n8n mode must block every telemetry call.
        (scoped, 0 if mode == "full" else 2),
    ]
    problems = []
    for payload, want in cases:
        r = subprocess.run(["bash", "-c", hook_cmd], input=json.dumps(payload), capture_output=True, text=True, timeout=30)
        if r.returncode != want:
            problems.append(f"hook returned {r.returncode}, want {want}, for {payload['tool_name']}: {r.stderr.strip()}")
    if token:
        leaked = sorted(k for k, v in env.items() if token in v)
        if leaked:
            problems.append(f"the Grafana token is in environment variables: {', '.join(leaked)}")
    return problems


def selftest_main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="selftest")
    p.add_argument("--hook-command", required=True)
    p.add_argument("--mode", required=True)
    p.add_argument("--token-file")
    p.add_argument("--namespace", default=scope.NAMESPACE)
    a = p.parse_args(argv)
    problems = selftest(a.hook_command, a.mode, read_secret(a.token_file), dict(os.environ), a.namespace)
    for x in problems:
        print(f"selftest: {x}", file=sys.stderr)
    if problems:
        return 1
    print("selftest: hook blocks out-of-scope calls; token not in the environment")
    return 0
