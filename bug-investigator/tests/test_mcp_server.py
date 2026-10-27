"""mcp_server.py: the stdio MCP server, over a real subprocess against a fake Loki/Prometheus."""

import io
import json
import os
import queue
import subprocess
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from bug_investigator import mcp_server, scope
from test_scope import LOGQL_REJECTED, PROMQL_REJECTED

SRC = Path(__file__).resolve().parents[1] / "src"
SERVER = SRC / "bug_investigator" / "mcp_server.py"
LOKI, PROM = scope.LOKI_UID, scope.PROM_UID
NOW_NS = int(time.time()) * 1_000_000_000

ANSWERS = {
    "/loki/api/v1/query_range": {"status": "success", "data": {"resultType": "streams", "result": [
        {"stream": {"namespace": "taskboard", "app": "taskboard"},
         "values": [[str(NOW_NS - 2_000_000_000), '{"msg":"permission_denied","rule":"P4","user":"ann"}'],
                    [str(NOW_NS - 1_000_000_000), '{"msg":"auth","token":"glsa_SECRETtoken123456"}']]}]}},
    "/loki/api/v1/index/stats": {"streams": 2, "chunks": 4, "entries": 120, "bytes": 9000},
    "/loki/api/v1/labels": {"status": "success", "data": ["app", "namespace", "pod"]},
    "/loki/api/v1/label/app/values": {"status": "success", "data": ["taskboard", "taskboard-traffic"]},
    "/api/v1/query_range": {"status": "success", "data": {"resultType": "matrix", "result": [
        {"metric": {"route": "/api/tasks"}, "values": [[time.time() - 60, "0.5"], [time.time(), "1"]]}]}},
    "/api/v1/query": {"status": "success", "data": {"resultType": "vector", "result": [
        {"metric": {"route": "/api/tasks"}, "value": [time.time(), "3"]}]}},
}


@pytest.fixture(scope="module")
def backend():
    seen = []

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            u = urllib.parse.urlsplit(self.path)
            seen.append((u.path, dict(urllib.parse.parse_qsl(u.query))))
            body = ANSWERS.get(u.path)
            self.send_response(200 if body else 404)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(body or {"status": "error", "error": "no such path"}).encode())

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", seen
    srv.shutdown()


class Proc:
    """The server as kagent's agentgateway runs it: python3 -I <path>, nothing on PYTHONPATH."""

    def __init__(self, url, tmp_path):
        env = {"PATH": os.environ.get("PATH", ""), "LOKI_URL": url, "PROMETHEUS_URL": url}
        self.p = subprocess.Popen([sys.executable, "-I", str(SERVER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True, env=env, cwd=tmp_path)
        self.q = queue.Queue()
        self.raw = []
        threading.Thread(target=self._read, daemon=True).start()
        self.next_id = 0

    def _read(self):
        for line in self.p.stdout:
            self.raw.append(line)
            self.q.put(json.loads(line))

    def send(self, msg):
        self.p.stdin.write(json.dumps(msg) + "\n")
        self.p.stdin.flush()

    def request(self, method, params=None):
        self.next_id += 1
        self.send({"jsonrpc": "2.0", "id": self.next_id, "method": method, **({"params": params} if params is not None else {})})
        return self.next_id

    def responses(self, ids, timeout=30):
        want, got = set(ids), {}
        deadline = time.time() + timeout
        while want - set(got):
            msg = self.q.get(timeout=max(0.1, deadline - time.time()))
            got[msg.get("id")] = msg
        return got

    def call(self, method, params=None):
        return self.responses([self.request(method, params)])[self.next_id]

    def close(self):
        if self.p.returncode is None:
            self.p.stdin.close()
            self.p.wait(timeout=10)
            self.stderr = self.p.stderr.read()
        return self.stderr


@pytest.fixture
def proc(backend, tmp_path):
    p = Proc(backend[0], tmp_path)
    init = p.call("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                 "clientInfo": {"name": "test", "version": "0"}})
    assert init["result"]["protocolVersion"] == "2025-06-18"
    p.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
    yield p
    p.close()


def tool(p, name, args):
    r = p.call("tools/call", {"name": name, "arguments": args})
    res = r["result"]
    return res["isError"], res["content"][0]["text"]


# ---------------------------------------------------------------------------------- round trip


def test_round_trip(proc, backend):
    assert proc.call("ping") == {"jsonrpc": "2.0", "id": proc.next_id, "result": {}}
    tools = proc.call("tools/list")["result"]["tools"]
    assert [t["name"] for t in tools] == ["query_loki_logs", "query_loki_stats", "query_prometheus",
                                          "list_loki_label_names", "list_loki_label_values"]
    for t in tools:
        assert set(t["inputSchema"]["properties"]) <= scope.GRAFANA_TOOLS[t["name"]][3]
        assert t["inputSchema"]["additionalProperties"] is False and t["annotations"]["readOnlyHint"] is True

    err, text = tool(proc, "query_loki_logs", {"datasourceUid": LOKI, "logql": '{namespace="taskboard"} |= "permission"',
                                                "startRfc3339": "now-1h", "endRfc3339": "now", "limit": 5})
    assert not err
    lines = json.loads(text)
    assert [json.loads(x["line"])["msg"] for x in lines] == ["auth", "permission_denied"]  # newest first
    assert lines[0]["labels"]["namespace"] == "taskboard" and lines[0]["timestamp"].endswith("Z")
    assert "glsa_SECRET" not in text  # tool output is scrubbed
    path, params = backend[1][-1]
    assert path == "/loki/api/v1/query_range" and params["limit"] == "5" and params["direction"] == "backward"

    err, text = tool(proc, "query_prometheus", {"datasourceUid": PROM, "expr": "sum by (route) (rate(taskboard_http_requests_total[5m]))",
                                                 "startTime": "now-30m", "endTime": "now", "stepSeconds": 60})
    assert not err and json.loads(text)["series"][0]["values"][1]["value"] == "1"
    assert backend[1][-1][1]["step"] == "60s"
    err, text = tool(proc, "query_prometheus", {"datasourceUid": PROM, "expr": "taskboard_tasks", "queryType": "instant"})
    assert not err and json.loads(text)["resultType"] == "vector"
    err, text = tool(proc, "query_loki_stats", {"datasourceUid": LOKI, "logql": '{namespace="taskboard"}'})
    assert not err and json.loads(text)["entries"] == 120
    err, text = tool(proc, "list_loki_label_names", {"datasourceUid": LOKI, "matcher": '{namespace="taskboard"}'})
    assert not err and "namespace" in json.loads(text)
    err, text = tool(proc, "list_loki_label_values", {"datasourceUid": LOKI, "labelName": "app",
                                                      "matcher": '{namespace="taskboard"}'})
    assert not err and json.loads(text) == ["taskboard", "taskboard-traffic"]


def test_protocol_errors(proc):
    assert proc.call("resources/list")["error"]["code"] == -32601
    assert proc.call("tools/call", {"arguments": {}})["error"]["code"] == -32602
    proc.send({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 1}})  # no reply
    proc.p.stdin.write("{not json\n")
    proc.p.stdin.flush()
    msg = proc.q.get(timeout=10)
    assert msg["error"]["code"] == -32700 and msg["id"] is None
    assert proc.call("ping")["result"] == {}  # still alive


def test_unknown_protocol_version_gets_ours(backend, tmp_path):
    p = Proc(backend[0], tmp_path)
    try:
        assert p.call("initialize", {"protocolVersion": "1999-01-01"})["result"]["protocolVersion"] == "2025-06-18"
        assert p.call("initialize", {"protocolVersion": "2024-11-05"})["result"]["protocolVersion"] == "2024-11-05"
    finally:
        p.close()


def test_stdout_is_protocol_only(proc):
    proc.call("tools/list")
    tool(proc, "query_loki_logs", {"datasourceUid": LOKI, "logql": '{namespace="kagent"}'})
    stderr = proc.close()
    for line in proc.raw:
        assert json.loads(line)["jsonrpc"] == "2.0"
    assert "ready" in stderr and "refused" in stderr


# ---------------------------------------------------------------------------------- scope through the server


def _rejected_calls():
    for q in LOGQL_REJECTED:
        yield "query_loki_logs", {"datasourceUid": LOKI, "logql": q}
        yield "query_loki_stats", {"datasourceUid": LOKI, "logql": q}
        yield "list_loki_label_values", {"datasourceUid": LOKI, "labelName": "app", "matcher": q}
    for q in PROMQL_REJECTED:
        yield "query_prometheus", {"datasourceUid": PROM, "expr": q}
    ok_logql, ok_prom = '{namespace="taskboard"}', "taskboard_tasks"
    yield "query_loki_logs", {"datasourceUid": PROM, "logql": ok_logql}           # wrong datasource
    yield "query_prometheus", {"datasourceUid": "other", "expr": ok_prom}
    yield "query_prometheus", {"datasourceUid": PROM, "expr": ok_prom, "projectName": "x"}
    yield "query_loki_logs", {"datasourceUid": LOKI, "logql": ok_logql, "url": "http://evil"}  # extra parameter
    yield "list_loki_label_names", {"datasourceUid": LOKI}                         # no matcher
    yield "list_loki_label_names", {"datasourceUid": LOKI, "matcher": ok_logql + ' |= "x"'}
    yield "list_prometheus_metric_names", {"datasourceUid": PROM}                  # not served here
    yield "query_tempo", {"datasourceUid": "tempo", "query": "{}"}
    yield "query_loki_logs", None
    yield "query_loki_logs", ["not", "an", "object"]
    yield "query_loki_logs", {"datasourceUid": LOKI, "logql": ok_logql, "limit": 101}
    yield "query_loki_logs", {"datasourceUid": LOKI, "logql": ok_logql, "startRfc3339": "yesterday"}
    yield "query_loki_logs", {"datasourceUid": LOKI, "logql": ok_logql, "startRfc3339": "now-3d", "endRfc3339": "now"}  # window too long
    yield "list_loki_label_values", {"datasourceUid": LOKI, "labelName": "../x", "matcher": ok_logql}
    yield "query_loki_logs", {"datasourceUid": LOKI, "logql": ok_logql, "startRfc3339": "now", "endRfc3339": "now-1h"}
    yield "query_prometheus", {"datasourceUid": PROM, "expr": ok_prom, "queryType": "both"}


def test_every_rejected_query_is_an_error_and_never_reaches_loki_or_prometheus(proc, backend):
    seen = backend[1]
    before = len(seen)
    calls = list(_rejected_calls())
    ids = {}
    for name, args in calls:
        ids[proc.request("tools/call", {"name": name, "arguments": args})] = (name, args)
    got = proc.responses(ids)
    for mid, (name, args) in ids.items():
        res = got[mid].get("result")
        assert res is not None, (name, args, got[mid])
        assert res["isError"] is True, (name, args, res)
        assert res["content"][0]["text"], (name, args)
    assert len(seen) == before, seen[before:]
    assert len(calls) > 100


def test_backend_failure_is_a_tool_error(tmp_path):
    p = Proc("http://127.0.0.1:9", tmp_path)  # nothing listens on port 9
    try:
        p.call("initialize", {"protocolVersion": "2025-06-18"})
        err, text = tool(p, "query_prometheus", {"datasourceUid": PROM, "expr": "taskboard_tasks"})
        assert err and text.startswith("query failed:")
        assert p.call("ping")["result"] == {}
    finally:
        p.close()


# ---------------------------------------------------------------------------------- in process


def test_batch_and_invalid_messages():
    out = io.StringIO()
    s = mcp_server.Server(out=out)
    s.dispatch([{"jsonrpc": "2.0", "id": 1, "method": "ping"}, {"jsonrpc": "2.0", "method": "notifications/initialized"}])
    s.dispatch([])
    s.dispatch({"id": 2, "method": "ping"})        # no jsonrpc
    s.dispatch("hello")
    s.dispatch({"jsonrpc": "2.0", "id": 3, "result": {}})  # a response: ignored
    s.pool.shutdown(wait=True)
    replies = [json.loads(x) for x in out.getvalue().splitlines()]
    assert replies[0] == [{"jsonrpc": "2.0", "id": 1, "result": {}}]
    assert replies[1]["error"]["code"] == -32600
    assert replies[2] == {"jsonrpc": "2.0", "id": 2, "error": {"code": -32600, "message": "invalid request"}}
    assert replies[3]["error"]["code"] == -32600 and replies[3]["id"] is None
    assert len(replies) == 4


def test_internal_error_is_contained(monkeypatch):
    def boom(*a, **k):
        raise KeyError("bug")

    monkeypatch.setattr(mcp_server, "call_tool", boom)
    s = mcp_server.Server(out=io.StringIO())
    r = s.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "query_loki_logs", "arguments": {}}})
    assert r["result"]["isError"] is True and "internal error" in r["result"]["content"][0]["text"]


def test_namespace_from_env(monkeypatch):
    monkeypatch.setenv("NAMESPACE", "other")
    s = mcp_server.Server(out=io.StringIO())
    assert s.namespace == "other"
    r = s.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                  "params": {"name": "query_loki_logs", "arguments": {"datasourceUid": LOKI, "logql": '{namespace="taskboard"}'}}})
    assert r["result"]["isError"] is True


def test_output_is_capped(monkeypatch):
    big = [{"line": "x" * 1000, "i": i} for i in range(200)]
    text = mcp_server._render(big)
    assert len(text) <= mcp_server.MAX_OUTPUT_CHARS
    body = json.loads(text)
    assert body["truncated"] is True and body["total"] == 200 and 0 < body["returned"] < 200
