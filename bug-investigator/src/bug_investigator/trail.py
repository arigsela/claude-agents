"""The reasoning trail: what the agent said and did, step by step, from the Claude execution log.

Each step is the agent's narration (its text before a tool call), the tool, a compact input summary
(a repo-relative path, a pattern, a command, a query and its window) and a compact result summary
(a count, "no results", "error: …" or "blocked: …"). Never file contents or log lines: counts only.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import urllib.parse

from bug_investigator import grafana, scope
from bug_investigator.util import ms, parse_time, read_json, scrub_text, write_json

SKIP = {"ToolSearch", "StructuredOutput"}
DEPLOY_DIRNAME = ".bug-investigator-deploy"
RUNNER_CHECKOUT = re.compile(r"/home/runner/work/[^/\s]+/[^/\s]+")
BLOCKED_RE = re.compile(r"(?i)blocked by bug-investigator|pretooluse|hook|permission|not allowed|denied|"
                        r"haven't granted")
NARRATION_MAX = 280
INPUT_MAX = 300
ERROR_MAX = 120
TOOL_LABELS = {
    "mcp__grafana__query_loki_logs": "Loki", "mcp__grafana__query_loki_stats": "Loki stats",
    "mcp__grafana__query_prometheus": "Prometheus", "mcp__grafana__list_loki_label_names": "Loki labels",
    "mcp__grafana__list_loki_label_values": "Loki label values",
}


def load_messages(path: str | None) -> list[dict]:
    """The SDK messages from an execution file (a JSON array, one object, or JSON lines)."""
    if not path or not os.path.isfile(path):
        return []
    with open(path) as f:
        text = f.read()
    try:
        msgs = json.loads(text)
    except ValueError:
        msgs = []
        for line in text.splitlines():
            try:
                msgs.append(json.loads(line))
            except ValueError:
                continue
    if isinstance(msgs, dict):
        msgs = [msgs]
    return [m for m in msgs if isinstance(m, dict)] if isinstance(msgs, list) else []


def one_line(s, limit: int) -> str:
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    return s if len(s) <= limit else s[: limit - 1].rstrip() + "…"


def result_text(content) -> str:
    """The text of a tool_result's content (a string or a list of blocks)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(b.get("text") or "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return ""


class Paths:
    """Turns runner paths into repo-relative ones: app files as `path`, deploy files as `deploy:path`."""

    def __init__(self, app_dir: str | None, deploy_dir: str | None):
        self.app = (app_dir or "").rstrip("/")
        self.deploy = (deploy_dir or (self.app + "/" + DEPLOY_DIRNAME if self.app else "")).rstrip("/")

    def rel(self, p) -> tuple[str | None, str]:
        """(where, path): where is "app", "deploy" or None (outside both)."""
        p = str(p or "")
        for where, root in (("deploy", self.deploy), ("app", self.app)):
            if root and (p == root or p.startswith(root + "/")):
                return where, p[len(root):].lstrip("/") or "."
        m = RUNNER_CHECKOUT.match(p)
        if m:
            rest = p[m.end():].lstrip("/")
            if rest == DEPLOY_DIRNAME or rest.startswith(DEPLOY_DIRNAME + "/"):
                return "deploy", rest[len(DEPLOY_DIRNAME):].lstrip("/") or "."
            return "app", rest or "."
        if p and not p.startswith(("/", "~")) and ".." not in p.split("/"):
            return "app", p
        return None, p

    def show(self, p) -> str:
        where, rel = self.rel(p)
        return f"deploy:{rel}" if where == "deploy" else rel

    def shorten(self, text: str) -> str:
        """Paths inside a command: the deploy checkout becomes <deploy>, the app checkout is dropped."""
        text = str(text or "")
        if self.deploy:
            text = text.replace(self.deploy, "<deploy>")
        if self.app:
            text = text.replace(self.app + "/", "").replace(self.app, ".")
        text = RUNNER_CHECKOUT.sub(".", text).replace("./" + DEPLOY_DIRNAME, "<deploy>")
        return text


def _window(start, end) -> tuple[str, int | None, int | None]:
    s, e = parse_time(start), parse_time(end)
    if s and e:
        same_day = s.date() == e.date()
        label = f"{s:%Y-%m-%d %H:%M}–{e:%H:%M} UTC" if same_day else f"{s:%Y-%m-%d %H:%M}–{e:%Y-%m-%d %H:%M} UTC"
        return label, ms(s), ms(e)
    if start or end:
        return f"{start or '?'} – {end or '?'}", None, None
    return "", None, None


def summarize_input(name: str, inp: dict, paths: Paths, ctx: dict) -> dict:
    """{"input": summary, "kind": query kind or None, "link": link or None, "window": label or None}."""
    inp = inp if isinstance(inp, dict) else {}
    if name in ("Read", "Edit", "Write", "MultiEdit", "NotebookEdit"):
        p = inp.get("file_path") or inp.get("notebook_path")
        where, rel = paths.rel(p)
        shown = f"deploy:{rel}" if where == "deploy" else rel
        if name == "Read" and inp.get("offset"):
            lo = int(inp.get("offset") or 1)
            shown += f" (from line {lo})"
        link = None
        repo, sha = (ctx.get("repo"), ctx.get("sha")) if where == "app" else (ctx.get("deploy_repo"), ctx.get("deploy_sha"))
        if where and repo and sha and rel != "." and name == "Read" and scrub_text(rel) == rel:
            link = f"https://github.com/{repo}/blob/{sha}/{urllib.parse.quote(rel)}"
        return {"input": one_line(shown, INPUT_MAX), "link": link}
    if name == "Grep":
        s = f"{inp.get('pattern', '')}"
        if inp.get("path"):
            s += f" in {paths.show(inp['path'])}"
        if inp.get("glob"):
            s += f" ({inp['glob']})"
        return {"input": one_line(s, INPUT_MAX)}
    if name == "Glob":
        s = str(inp.get("pattern", ""))
        if inp.get("path"):
            s += f" in {paths.show(inp['path'])}"
        return {"input": one_line(s, INPUT_MAX)}
    if name == "Bash":
        return {"input": one_line(paths.shorten(inp.get("command", "")), INPUT_MAX)}
    if name in ("mcp__grafana__query_loki_logs", "mcp__grafana__query_loki_stats", "mcp__grafana__query_prometheus"):
        kind = "promql" if name.endswith("prometheus") else "logql"
        expr = str(inp.get("expr" if kind == "promql" else "logql") or "")
        start, end = (inp.get("startTime"), inp.get("endTime")) if kind == "promql" else \
            (inp.get("startRfc3339"), inp.get("endRfc3339"))
        label, s_ms, e_ms = _window(start, end)
        link = None
        gurl = ctx.get("grafana_url")
        # Link only in-scope queries with nothing secret-looking: the link URL-encodes the query, so the
        # scrubber could not catch a token inside it later.
        if gurl and s_ms is not None and e_ms is not None and expr and scrub_text(expr) == expr and \
                scope.check_query(kind, expr, ctx.get("namespace") or scope.NAMESPACE) is None:
            link = grafana.explore_link(gurl, kind, expr, s_ms, e_ms)
        return {"input": one_line(expr, INPUT_MAX), "kind": kind, "link": link, "window": label or None}
    if name.startswith("mcp__grafana__list_loki_label"):
        s = str(inp.get("matcher") or "")
        if inp.get("labelName"):
            s = f"{inp['labelName']} in {s}" if s else str(inp["labelName"])
        return {"input": one_line(s, INPUT_MAX)}
    return {"input": one_line(", ".join(sorted(inp)[:6]), INPUT_MAX)}


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def _json_payload(text: str):
    try:
        return json.loads(text)
    except ValueError:
        return None


def summarize_result(name: str, text: str) -> tuple[str, str]:
    """(summary, status) for a successful tool call; status is ok or empty. Counts only."""
    body = text.split("<system-reminder>", 1)[0]
    stripped = body.strip()
    if name == "Read":
        lines = [ln for ln in body.splitlines() if re.match(r"^\s*\d+\t", ln)]
        n = len(lines) or len([ln for ln in body.splitlines() if ln.strip()])
        return (_plural(n, "line"), "ok") if n else ("empty file", "empty")
    if name in ("Grep", "Glob"):
        if not stripped or stripped.startswith(("No files found", "No matches found")):
            return "no results", "empty"
        m = re.match(r"Found (\d+) files?", stripped)
        if m:
            return _plural(int(m.group(1)), "file"), "ok"
        n = len([ln for ln in stripped.splitlines() if ln.strip() and not ln.startswith("(Results are truncated")])
        return _plural(n, "file" if name == "Glob" else "line"), "ok"
    if name == "Bash":
        n = len([ln for ln in stripped.splitlines() if ln.strip()])
        return (_plural(n, "line") + " of output", "ok") if n else ("no output", "empty")
    if name.startswith("mcp__grafana__"):
        data = _json_payload(stripped)
        if name == "mcp__grafana__query_loki_logs":
            n = _count_loki(data) if data is not None else None
            if n is None:
                return ("no results", "empty") if not stripped or stripped in ("[]", "null") else ("result received", "ok")
            return (_plural(n, "log line"), "ok") if n else ("no log lines", "empty")
        if name == "mcp__grafana__query_loki_stats" and isinstance(data, dict):
            n = data.get("entries")
            if isinstance(n, int):
                return (_plural(n, "entry").replace("entrys", "entries"), "ok") if n else ("no entries", "empty")
        if name == "mcp__grafana__query_prometheus":
            n = _count_series(data)
            if n is not None:
                return (_plural(n, "series").replace("seriess", "series"), "ok") if n else ("no results", "empty")
        if isinstance(data, list):
            return (_plural(len(data), "value"), "ok") if data else ("no results", "empty")
        return ("result received", "ok") if stripped else ("no results", "empty")
    return ("done", "ok") if stripped else ("no output", "empty")


def _count_loki(data) -> int | None:
    if isinstance(data, list):
        return len(data)
    if not isinstance(data, dict):
        return None
    n = 0
    seen = False
    if isinstance(data.get("data"), list):
        n += len(data["data"])
        seen = True
    for s in data.get("streams") or []:
        if isinstance(s, dict):
            n += len(s.get("lines") or s.get("values") or s.get("entries") or [])
            seen = True
    return n if seen or "streams" in data or "data" in data else None


def _count_series(data) -> int | None:
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict):
        for k in ("data", "result", "matrix", "vector"):
            v = data.get(k)
            if isinstance(v, list):
                return len(v)
            if isinstance(v, dict) and isinstance(v.get("result"), list):
                return len(v["result"])
    return None


def blocked_reason(text: str) -> str:
    m = re.search(r"Blocked by bug-investigator scope:\s*(.*)", text)
    reason = m.group(1) if m else text
    return one_line(reason, ERROR_MAX)


def build(messages: list[dict], app_dir: str | None = None, deploy_dir: str | None = None, **ctx) -> dict:
    """The ordered steps of one run, scrubbed."""
    if not app_dir:
        init = next((m for m in messages if m.get("type") == "system" and m.get("cwd")), None)
        app_dir = init.get("cwd") if init else None
    paths = Paths(app_dir, deploy_dir)
    result_msg = next((m for m in reversed(messages) if m.get("type") == "result"), {}) or {}
    denied = {d.get("tool_use_id") for d in result_msg.get("permission_denials") or [] if isinstance(d, dict)}

    results: dict[str, dict] = {}
    for m in messages:
        if m.get("type") != "user":
            continue
        content = (m.get("message") or {}).get("content")
        for b in content if isinstance(content, list) else []:
            if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("tool_use_id"):
                results[b["tool_use_id"]] = b

    steps: list[dict] = []
    pending: list[str] = []
    for m in messages:
        if m.get("type") != "assistant":
            continue
        for b in (m.get("message") or {}).get("content") or []:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "text" and str(b.get("text") or "").strip():
                pending.append(str(b["text"]))
                continue
            if b.get("type") != "tool_use":
                continue
            name = str(b.get("name") or "")
            if name in SKIP:
                continue
            si = summarize_input(name, b.get("input") or {}, paths, ctx)
            link = si.get("link")
            res = results.get(b.get("id"))
            text = result_text((res or {}).get("content"))
            if b.get("id") in denied:
                summary, status = "blocked: " + (blocked_reason(text) if text else "permission denied"), "blocked"
            elif res is None:
                summary, status = "no result (the run ended)", "error"
            elif res.get("is_error"):
                if BLOCKED_RE.search(text):
                    summary, status = "blocked: " + blocked_reason(text), "blocked"
                else:
                    summary, status = "error: " + one_line(text, ERROR_MAX), "error"
            else:
                summary, status = summarize_result(name, text)
            if status == "blocked":
                link = None
            steps.append({"narration": one_line(" ".join(pending), NARRATION_MAX) or None,
                          "tool": TOOL_LABELS.get(name, name.replace("mcp__grafana__", "Grafana ")),
                          "tool_name": name, "input": si.get("input"), "kind": si.get("kind"),
                          "window": si.get("window"), "link": link,
                          "result": summary, "status": status})
            pending = []
    if pending:
        steps.append({"narration": one_line(" ".join(pending), NARRATION_MAX), "tool": None, "tool_name": None,
                      "input": None, "kind": None, "window": None, "link": None, "result": None,
                      "status": "note"})
    for i, s in enumerate(steps, 1):
        s["n"] = i
        for k in ("narration", "input", "result", "window"):
            if s.get(k):
                s[k] = scrub_text(s[k])
        if s.get("link") and scrub_text(urllib.parse.unquote(s["link"])) != urllib.parse.unquote(s["link"]):
            s["link"] = None  # belt and braces: no link that decodes to anything secret-looking
    tools = [s for s in steps if s["tool"]]
    return {"version": 1, "steps": steps, "tool_calls": len(tools),
            "blocked": sum(1 for s in tools if s["status"] == "blocked")}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="trail")
    p.add_argument("--execution-file", required=True)
    p.add_argument("--findings", help="verified findings, for the investigated SHAs")
    p.add_argument("--repo", default="")
    p.add_argument("--deploy-repo", default="")
    p.add_argument("--app-dir")
    p.add_argument("--deploy-dir")
    p.add_argument("--grafana-url", default="")
    p.add_argument("--namespace", default=scope.NAMESPACE)
    p.add_argument("--out", required=True)
    a = p.parse_args(argv)
    heads = {}
    if a.findings and os.path.isfile(a.findings):
        try:
            heads = (read_json(a.findings).get("verification") or {}).get("heads") or {}
        except (ValueError, OSError, AttributeError):
            heads = {}
    try:
        trail = build(load_messages(a.execution_file), a.app_dir, a.deploy_dir, repo=a.repo,
                      sha=heads.get("app"), deploy_repo=a.deploy_repo, deploy_sha=heads.get("deploy"),
                      grafana_url=a.grafana_url, namespace=a.namespace)
    except Exception as e:  # the trail is a nice-to-have; never fail the run over it
        trail = {"version": 1, "steps": [], "tool_calls": 0, "blocked": 0, "error": str(e)[:200]}
    write_json(a.out, trail)
    print(f"trail: {len(trail['steps'])} steps, {trail['tool_calls']} tool calls, {trail['blocked']} blocked -> {a.out}")
    return 0
