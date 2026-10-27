"""Taskboard telemetry as a stdio MCP server: Loki and Prometheus, scoped to one namespace.

The kagent version of the bug investigator has no PreToolUse hook, so the scope check moves into
the tool server. The tools have mcp-grafana 2.1.1's names and argument names (the ones scope.py's
GRAFANA_TOOLS already checks and the capability taxonomy already classifies `read`), so the
prompt, the hook's rules and verify carry over unchanged. Every call runs
`scope.check_tool_call` exactly as the hook does, and telemetry.py checks the query again before
any HTTP request. There is no Grafana and no token: Loki and Prometheus are queried directly.

Transport: newline-delimited JSON-RPC 2.0 on stdin/stdout (agentgateway serves it as Streamable
HTTP). Only protocol messages go to stdout; logs go to stderr. A refused or failed call is a tool
result with isError: true, never a crash.

    python3 -I /core/src/bug_investigator/mcp_server.py      # env LOKI_URL, PROMETHEUS_URL, NAMESPACE
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

if __package__ in (None, ""):  # run as a script (python3 -I .../mcp_server.py): -I drops PYTHONPATH
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bug_investigator import scope, telemetry  # noqa: E402
from bug_investigator.util import iso, parse_time, scrub  # noqa: E402

SERVER_NAME = "taskboard-telemetry"
SERVER_VERSION = "0.1.0"
PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
MAX_OUTPUT_CHARS = 60_000
DEFAULT_WINDOW = timedelta(hours=1)
MAX_WINDOW = {"loki": timedelta(hours=24), "prometheus": timedelta(days=7)}
DEFAULT_LOG_LIMIT = 10
REL_RE = re.compile(r"^now(?:\s*-\s*(\d+)\s*([smhdw]))?$")
UNITS = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days", "w": "weeks"}


class ToolError(Exception):
    """Bad input or a refused/failed query: becomes a result with isError: true."""


def _log(msg: str) -> None:
    print(f"{SERVER_NAME}: {msg}", file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------------- tool schemas

_TIME = {"type": "string", "description": "RFC 3339 time (2026-10-27T15:00:00Z), or now / now-30m / now-2h."}


def _tools(namespace: str) -> list[dict]:
    loki = {"type": "string", "description": f"Must be {scope.LOKI_UID!r}.", "enum": [scope.LOKI_UID]}
    prom = {"type": "string", "description": f"Must be {scope.PROM_UID!r}.", "enum": [scope.PROM_UID]}
    sel = f'{{namespace="{namespace}"}}'
    scoped = (f'Every stream selector must contain namespace="{namespace}" exactly; anything else is '
              "refused. Put a |= \"...\" line filter before any regex, and keep the window short.")
    ro = {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}

    def tool(name, description, props, required):
        allowed = scope.GRAFANA_TOOLS[name][3]
        assert set(props) <= allowed, (name, set(props) - allowed)  # the hook's rules are the contract
        return {"name": name, "description": description, "annotations": ro,
                "inputSchema": {"type": "object", "properties": props, "required": required,
                                "additionalProperties": False}}

    return [
        tool("query_loki_logs",
             "Run a LogQL query against Loki and return log lines (or samples for a metric query). " + scoped
             + f" Default window: the last hour; at most {MAX_WINDOW['loki'].days * 24} h.",
             {"datasourceUid": loki,
              "logql": {"type": "string", "description": f"LogQL, e.g. {sel} |= \"permission_denied\" | json"},
              "startRfc3339": _TIME, "endRfc3339": _TIME,
              "limit": {"type": "integer", "minimum": 1, "maximum": telemetry.MAX_LINES,
                        "description": f"Lines to return (default {DEFAULT_LOG_LIMIT}, at most {telemetry.MAX_LINES})."},
              "direction": {"type": "string", "enum": ["backward", "forward"],
                            "description": "backward = newest first (default)."},
              "queryType": {"type": "string", "enum": ["range", "instant"],
                            "description": "range (default) or instant (metric queries only, at endRfc3339)."},
              "stepSeconds": {"type": "integer", "minimum": 1, "description": "Step for metric queries."},
              "format": {"type": "string", "description": "Ignored; results are always JSON."}},
             ["datasourceUid", "logql"]),
        tool("query_loki_stats",
             "Loki index statistics (streams, chunks, entries, bytes) for a stream selector. " + scoped,
             {"datasourceUid": loki, "logql": {"type": "string", "description": f"A stream selector, e.g. {sel}"},
              "startRfc3339": _TIME, "endRfc3339": _TIME},
             ["datasourceUid", "logql"]),
        tool("query_prometheus",
             "Run a PromQL query against Prometheus. Every selector needs namespace=\"" + namespace
             + f"\" or a {namespace}_* metric name; anything else is refused. Default: a range query over "
             f"the last hour; at most {MAX_WINDOW['prometheus'].days} days.",
             {"datasourceUid": prom,
              "expr": {"type": "string", "description": f"PromQL, e.g. sum by (route) (rate({namespace}_http_requests_total[5m]))"},
              "startTime": _TIME, "endTime": _TIME,
              "stepSeconds": {"type": "integer", "minimum": 1, "description": "Step for a range query."},
              "queryType": {"type": "string", "enum": ["range", "instant"],
                            "description": "range (default) or instant (at endTime)."}},
             ["datasourceUid", "expr"]),
        tool("list_loki_label_names",
             f"Label names on the streams that match a selector (it must be {sel} or narrower).",
             {"datasourceUid": loki, "matcher": {"type": "string", "description": f"A stream selector, e.g. {sel}"},
              "startRfc3339": _TIME, "endRfc3339": _TIME},
             ["datasourceUid", "matcher"]),
        tool("list_loki_label_values",
             f"Values of one label on the streams that match a selector (it must be {sel} or narrower).",
             {"datasourceUid": loki, "labelName": {"type": "string", "description": "e.g. app, level, pod"},
              "matcher": {"type": "string", "description": f"A stream selector, e.g. {sel}"},
              "startRfc3339": _TIME, "endRfc3339": _TIME},
             ["datasourceUid", "labelName", "matcher"]),
    ]


# ---------------------------------------------------------------------------------- argument parsing


def _time(value, field: str, now: datetime) -> datetime | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ToolError(f"{field} must be a string")
    m = REL_RE.match(value.strip())
    if m:
        if not m.group(1):
            return now
        return now - timedelta(**{UNITS[m.group(2)]: int(m.group(1))})
    dt = parse_time(value)
    if dt is None:
        raise ToolError(f"{field} {value!r} is not an RFC 3339 time or now-<n><s|m|h|d|w>")
    return dt


def _window(args: dict, start_key: str, end_key: str, backend: str) -> tuple[int, int]:
    now = datetime.now(timezone.utc)
    start, end = _time(args.get(start_key), start_key, now), _time(args.get(end_key), end_key, now)
    end = end or (start + DEFAULT_WINDOW if start else now)
    start = start or end - DEFAULT_WINDOW
    if start >= end:
        raise ToolError(f"{start_key} must be before {end_key}")
    if end - start > MAX_WINDOW[backend]:
        raise ToolError(f"the window {iso(start)}..{iso(end)} is longer than {MAX_WINDOW[backend]}; narrow it")
    return telemetry_ms(start), telemetry_ms(end)


def telemetry_ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def _int(args: dict, key: str, default: int | None, lo: int, hi: int | None = None) -> int | None:
    v = args.get(key)
    if v is None:
        return default
    if isinstance(v, bool) or not isinstance(v, (int, float)) or int(v) != v:
        raise ToolError(f"{key} must be an integer")
    v = int(v)
    if v < lo or (hi is not None and v > hi):
        raise ToolError(f"{key} must be between {lo} and {hi}" if hi else f"{key} must be at least {lo}")
    return v


def _choice(args: dict, key: str, options: tuple[str, ...]) -> str:
    v = args.get(key) or options[0]
    if v not in options:
        raise ToolError(f"{key} must be one of {', '.join(options)}")
    return v


# ---------------------------------------------------------------------------------- results


def _ts(ns) -> str:
    n = int(ns)
    return datetime.fromtimestamp(n // 1_000_000_000, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") + f".{n % 1_000_000_000:09d}Z"


def _sec(t) -> str:
    return datetime.fromtimestamp(float(t), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _series(data: dict) -> list[dict]:
    rtype, result = data.get("resultType"), data.get("result") or []
    if rtype == "scalar":
        return [{"labels": {}, "values": [{"time": _sec(result[0]), "value": result[1]}]}] if result else []
    out = []
    for s in result:
        points = [s["value"]] if rtype == "vector" else (s.get("values") or [])
        out.append({"labels": s.get("metric") or {},
                    "values": [{"time": _sec(p[0]), "value": p[1]} for p in points]})
    return out


def _logs(data: dict, direction: str, limit: int) -> list[dict]:
    if data.get("resultType") != "streams":
        return _series(data)
    entries = []
    for s in data.get("result") or []:
        labels = s.get("stream") or {}
        for ts, line in s.get("values") or []:
            entries.append((int(ts), labels, line))
    entries.sort(key=lambda e: e[0], reverse=direction == "backward")
    return [{"timestamp": _ts(ts), "labels": labels, "line": line} for ts, labels, line in entries[:limit]]


def _render(value) -> str:
    """JSON text, secrets scrubbed, cut to MAX_OUTPUT_CHARS (whole items when it is a list)."""
    value = scrub(value)
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    if isinstance(value, list):
        kept = list(value)
        while kept and len(json.dumps(kept, ensure_ascii=False, separators=(",", ":"))) > MAX_OUTPUT_CHARS - 200:
            kept = kept[: max(1, len(kept) * 3 // 4)] if len(kept) > 1 else []
        return json.dumps({"truncated": True, "returned": len(kept), "total": len(value), "items": kept},
                          ensure_ascii=False, separators=(",", ":"))
    return text[:MAX_OUTPUT_CHARS] + " ...[truncated]"


# ---------------------------------------------------------------------------------- tools


def call_tool(name: str, args, namespace: str = scope.NAMESPACE, opener=None) -> str:
    """Run one tool; raises ToolError for anything refused, malformed or failed."""
    if name not in scope.GRAFANA_TOOLS:
        raise ToolError(f"unknown tool {name!r}; available: {', '.join(sorted(scope.GRAFANA_TOOLS))}")
    if args is None:
        args = {}
    problem = scope.check_tool_call(name, args, namespace)
    if problem:
        raise ToolError(f"refused: {problem}")
    try:
        if name == "query_loki_logs":
            start, end = _window(args, "startRfc3339", "endRfc3339", "loki")
            limit = _int(args, "limit", DEFAULT_LOG_LIMIT, 1, telemetry.MAX_LINES)
            direction = _choice(args, "direction", ("backward", "forward"))
            qtype = _choice(args, "queryType", ("range", "instant"))
            step = _int(args, "stepSeconds", None, 1)
            if qtype == "instant":
                data = telemetry.loki_query_instant(args["logql"], end, limit=limit, direction=direction,
                                                    namespace=namespace, opener=opener)
            else:
                data = telemetry.loki_query_range(args["logql"], start, end, limit=limit, direction=direction,
                                                  step_s=step, namespace=namespace, opener=opener)
            return _render(_logs(data, direction, limit))
        if name == "query_loki_stats":
            start, end = _window(args, "startRfc3339", "endRfc3339", "loki")
            return _render(telemetry.loki_stats(args["logql"], start, end, namespace=namespace, opener=opener))
        if name == "query_prometheus":
            start, end = _window(args, "startTime", "endTime", "prometheus")
            qtype = _choice(args, "queryType", ("range", "instant"))
            step = _int(args, "stepSeconds", None, 1)
            if qtype == "instant":
                data = telemetry.prom_query_instant(args["expr"], end, namespace=namespace, opener=opener)
            else:
                data = telemetry.prom_query_range(args["expr"], start, end, step_s=step, namespace=namespace,
                                                  opener=opener)
            return _render({"resultType": data.get("resultType"), "series": _series(data)})
        if name == "list_loki_label_names":
            start, end = _window(args, "startRfc3339", "endRfc3339", "loki")
            return _render(telemetry.loki_label_names(args["matcher"], start, end, namespace=namespace, opener=opener))
        start, end = _window(args, "startRfc3339", "endRfc3339", "loki")
        label = args.get("labelName")
        return _render(telemetry.loki_label_values(label, args["matcher"], start, end, namespace=namespace,
                                                   opener=opener))
    except telemetry.TelemetryError as e:
        raise ToolError(f"query failed: {e}") from None


# ---------------------------------------------------------------------------------- JSON-RPC


class Server:
    def __init__(self, out=None, namespace: str | None = None, opener=None, workers: int = 4):
        self.out = out or sys.stdout
        self.namespace = namespace or os.environ.get("NAMESPACE") or scope.NAMESPACE
        self.opener = opener
        self.lock = threading.Lock()
        self.pool = ThreadPoolExecutor(max_workers=workers)
        self.tools = _tools(self.namespace)

    def send(self, msg: dict | list) -> None:
        line = json.dumps(msg, ensure_ascii=True, separators=(",", ":"))
        with self.lock:
            self.out.write(line + "\n")
            self.out.flush()

    @staticmethod
    def result(mid, result: dict) -> dict:
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    @staticmethod
    def error(mid, code: int, message: str) -> dict:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}

    def tool_result(self, mid, params) -> dict:
        name = params.get("name")
        try:
            text = call_tool(name, params.get("arguments"), self.namespace, self.opener)
            return self.result(mid, {"content": [{"type": "text", "text": text}], "isError": False})
        except ToolError as e:
            _log(f"{name}: {e}")
            return self.result(mid, {"content": [{"type": "text", "text": str(e)}], "isError": True})
        except Exception as e:  # never let a bug kill the server
            _log(f"{name}: internal error: {e!r}")
            return self.result(mid, {"content": [{"type": "text", "text": f"internal error: {type(e).__name__}"}],
                                     "isError": True})

    def handle(self, msg) -> dict | None:
        """One message -> its response (None for notifications and responses)."""
        if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
            return self.error(msg.get("id") if isinstance(msg, dict) else None, -32600, "invalid request")
        method, mid = msg.get("method"), msg.get("id")
        is_note = "id" not in msg
        if method is None:
            return None  # a response to something we never sent
        if not isinstance(method, str):
            return None if is_note else self.error(mid, -32600, "invalid request")
        params = msg.get("params") if isinstance(msg.get("params"), dict) else {}
        if is_note:
            return None  # notifications/initialized, notifications/cancelled, ...
        if method == "initialize":
            asked = params.get("protocolVersion")
            version = asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
            return self.result(mid, {
                "protocolVersion": version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                "instructions": (f"Loki and Prometheus for namespace {self.namespace!r} only. Loki datasourceUid "
                                 f"{scope.LOKI_UID!r}, Prometheus datasourceUid {scope.PROM_UID!r}. Every query "
                                 f"must select namespace=\"{self.namespace}\"; anything else is refused.")})
        if method == "ping":
            return self.result(mid, {})
        if method == "tools/list":
            return self.result(mid, {"tools": self.tools})
        if method == "tools/call":
            if not isinstance(params.get("name"), str):
                return self.error(mid, -32602, "tools/call needs params.name")
            return self.tool_result(mid, params)
        return self.error(mid, -32601, f"method not found: {method}")

    def dispatch(self, msg) -> None:
        """Answer one parsed message; a tools/call runs on the pool so a slow query blocks nothing."""
        if isinstance(msg, list):  # a JSON-RPC batch (2025-03-26): answer it as one array
            if not msg:
                self.send(self.error(None, -32600, "empty batch"))
                return
            replies = [r for r in (self.handle(m) for m in msg) if r is not None]
            if replies:
                self.send(replies)
            return
        if isinstance(msg, dict) and msg.get("method") == "tools/call" and "id" in msg:
            self.pool.submit(lambda: self.send(self.handle(msg)))
            return
        reply = self.handle(msg)
        if reply is not None:
            self.send(reply)

    def serve(self, inp=None) -> None:
        inp = inp or sys.stdin
        _log(f"ready (namespace {self.namespace}, loki {telemetry.loki_url()}, prometheus {telemetry.prometheus_url()})")
        while True:
            line = inp.readline()
            if not line:
                break
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except ValueError:
                self.send(self.error(None, -32700, "parse error"))
                continue
            self.dispatch(msg)
        self.pool.shutdown(wait=True)


def main(argv: list[str] | None = None) -> int:
    Server().serve()
    return 0


if __name__ == "__main__":
    sys.exit(main())
