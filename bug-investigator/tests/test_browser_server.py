"""browser_server.py: the taskboard-browser stdio MCP server, with a fake replay (no browser).

The tests marked `browser` run the real engine through the server; they skip without Playwright and
run in the Playwright image (see tests/test_browser.py).
"""

import base64
import io
import json
import os
import queue
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from bug_investigator import browser, browser_server, mcp_server, scope, steps as stepfmt
from test_browser import AS_DANA, HAVE_PLAYWRIGHT, PNG, START, STARTED, make_app

SRC = Path(__file__).resolve().parents[1] / "src"
SERVER = SRC / "bug_investigator" / "browser_server.py"
TOOL = "replay_ui_steps"
STEPS = [AS_DANA, START, STARTED]
SHOT1, SHOT3 = PNG + b"one", PNG + b"three"

needs_chromium = pytest.mark.skipif(not HAVE_PLAYWRIGHT, reason="needs Playwright and Chromium (the Playwright image)")


class FakeReplay:
    """Stands in for browser.replay: records each call, returns `result` or raises it."""

    def __init__(self, result=None):
        self.result = result
        self.calls = []

    def __call__(self, app_dir, steps, *, commit=None, shots="all"):
        self.calls.append({"app_dir": app_dir, "steps": steps, "commit": commit, "shots": shots})
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


def replay_result(failed_at=None, failure="missing", shots=(1, 3), app_log=30) -> browser.Replay:
    steps = []
    for n in range(1, 4):
        if failed_at is not None and n > failed_at:
            break
        bad = n == failed_at
        png = {1: SHOT1, 3: SHOT3}.get(n) if n in shots else None
        steps.append(browser.StepResult(n, stepfmt.describe(STEPS[n - 1]), not bad, "it broke" if bad else None, png,
                                        failure if bad else None))
    return browser.Replay(ok=failed_at is None, failed_at=failed_at, steps=steps, snapshot="- heading \"Taskboard\"",
                          app_log=[f"line {i}" for i in range(app_log)], console=["replay: a note"], commit="abc123",
                          seconds=2.5)


@pytest.fixture
def app_dir(tmp_path):
    d = tmp_path / "taskboard"
    d.mkdir()
    (d / ".source-commit").write_text("abc123")  # as the ConfigMap key: no trailing newline
    return d


def server(app_dir, fake):
    return browser_server.BrowserServer(app_dir=str(app_dir), replay=fake, out=io.StringIO())


def call(srv, args, name=TOOL):
    r = srv.handle({"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": name, "arguments": args}})
    return r["result"]


def body(result) -> dict:
    assert result["isError"] is False, result
    return json.loads(result["content"][0]["text"])


# ---------------------------------------------------------------------------------- the server as a process


class Proc:
    """A server subprocess: send JSON-RPC lines, collect the replies."""

    def __init__(self, argv, env, cwd):
        self.p = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  text=True, env=env, cwd=cwd)
        self.q = queue.Queue()
        self.raw = []
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()
        self.next_id = 0

    def _read(self):
        for line in self.p.stdout:
            self.raw.append(line)
            self.q.put(json.loads(line))

    def request(self, method, params=None):
        self.next_id += 1
        msg = {"jsonrpc": "2.0", "id": self.next_id, "method": method, **({"params": params} if params else {})}
        self.p.stdin.write(json.dumps(msg) + "\n")
        self.p.stdin.flush()
        return self.next_id

    def reply(self, mid, timeout=30):
        deadline = time.time() + timeout
        while True:
            msg = self.q.get(timeout=max(0.1, deadline - time.time()))
            if msg.get("id") == mid:
                return msg

    def call(self, method, params=None, timeout=30):
        return self.reply(self.request(method, params), timeout)

    def wait(self, timeout=30) -> int:
        """Wait for the exit and for every stdout line to reach `raw`."""
        code = self.p.wait(timeout=timeout)
        self.reader.join(timeout)
        return code

    def finish(self, timeout=30):
        """Close stdin, wait for the exit; returns (exit code, stderr)."""
        self.p.stdin.close()
        return self.wait(timeout), self.p.stderr.read()


def env_for(tmp_path, app_dir, **extra):
    deps = tmp_path / "deps"
    deps.mkdir(exist_ok=True)
    return {"PATH": os.environ.get("PATH", ""), "APP_DIR": str(app_dir), "DEPS_DIR": str(deps),
            "TMPDIR": str(tmp_path), **extra}


INIT = {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "0"}}


def test_initialize_and_list_without_playwright(tmp_path, app_dir):
    """Playwright cannot be imported at all: initialize and tools/list still answer, and a call is a tool
    error. (A server down at initialize fails every agent bound to it.)"""
    blocked = (f"import runpy, sys; sys.modules['playwright'] = None; "
               f"runpy.run_path({str(SERVER)!r}, run_name='__main__')")
    p = Proc([sys.executable, "-I", "-c", blocked], env_for(tmp_path, app_dir), tmp_path)
    init = p.call("initialize", INIT)["result"]
    assert init["serverInfo"] == {"name": "taskboard-browser", "version": browser_server.SERVER_VERSION}
    assert init["protocolVersion"] == "2025-06-18" and init["capabilities"] == {"tools": {"listChanged": False}}
    tools = p.call("tools/list")["result"]["tools"]
    assert [t["name"] for t in tools] == [TOOL]
    t = tools[0]
    assert t["annotations"] == {"readOnlyHint": True, "openWorldHint": False}
    schema = t["inputSchema"]
    assert set(schema["properties"]) == {"steps", "fails_at", "screenshots"} and schema["required"] == ["steps"]
    assert schema["properties"]["steps"]["type"] == "array" and schema["properties"]["steps"]["items"] == {"type": "object"}
    assert schema["properties"]["fails_at"]["type"] == "integer" and "fails_at" not in schema["required"]
    assert schema["properties"]["screenshots"]["enum"] == ["none", "failure", "all"]
    assert schema["properties"]["screenshots"]["default"] == "failure"
    assert schema["additionalProperties"] is False
    d = t["description"]
    for words in ("live", "fresh database", "demo data", "persists", "fails_at", "within", "expect_absent",
                  "omit `fails_at` when you expect every step to pass, and read `ok`"):
        assert words in d, words
    res = p.call("tools/call", {"name": TOOL, "arguments": {"steps": STEPS}})["result"]
    assert res["isError"] is True
    assert res["content"][0]["text"].startswith("browser unavailable: Playwright is not installed"), res
    assert p.call("ping")["result"] == {}
    code, stderr = p.finish()
    assert code == 0, stderr
    assert "ready" in stderr and "abc123" in stderr
    for line in p.raw:
        assert json.loads(line)["jsonrpc"] == "2.0"  # stdout carries the protocol only


def test_runs_as_agentgateway_runs_it(tmp_path, app_dir):
    """python3 -I <path>, nothing on PYTHONPATH; everything piped at once, then EOF: every request answered."""
    p = Proc([sys.executable, "-I", str(SERVER)], env_for(tmp_path, app_dir), tmp_path)
    ids = [p.request("initialize", INIT), p.request("tools/list"),
           p.request("tools/call", {"name": TOOL, "arguments": {"steps": []}}), p.request("ping")]
    code, stderr = p.finish()
    assert code == 0, stderr
    got = {m["id"]: m for m in (json.loads(x) for x in p.raw)}
    assert set(got) == set(ids)
    assert got[ids[2]]["result"]["isError"] is True and got[ids[3]]["result"] == {}


# ---------------------------------------------------------------------------------- tool errors


def test_invalid_steps_is_error(app_dir):
    fake = FakeReplay(replay_result())
    srv = server(app_dir, fake)
    for bad in ([], [{"do": "goto", "value": "//evil.example"}], [START] * 16, "click Start", None,
                [{"do": "click", "target": {"role": "button", "name": "Start"}, "value": "x"}]):
        res = call(srv, {"steps": bad})
        assert res["isError"] is True, bad
        assert res["content"][0]["text"] == "; ".join(stepfmt.validate(bad)), bad
    for args, says in (({"steps": STEPS, "fails_at": 4}, "fails_at must be null or a step number from 1 to 3"),
                       ({"steps": STEPS, "fails_at": 0}, "fails_at"),
                       ({"steps": STEPS, "fails_at": "2"}, "fails_at"),
                       ({"steps": STEPS, "fails_at": True}, "fails_at"),
                       ({"steps": STEPS, "screenshots": "some"}, "screenshots must be one of none, failure, all"),
                       ({"steps": STEPS, "url": "http://evil.example"}, "unknown arguments: url"),
                       (["not", "an", "object"], "arguments must be an object"),
                       (None, "steps must be a non-empty list")):
        res = call(srv, args)
        assert res["isError"] is True and says in res["content"][0]["text"], (args, res)
    res = call(srv, {"steps": STEPS}, name="query_loki_logs")
    assert res["isError"] is True and "unknown tool" in res["content"][0]["text"]
    assert fake.calls == []  # nothing invalid ever reaches the browser


def test_launch_failure_is_tool_error(app_dir):
    fake = FakeReplay(browser.BrowserError("Chromium did not launch: libnss3.so: cannot open shared object file"))
    srv = server(app_dir, fake)
    res = call(srv, {"steps": STEPS, "fails_at": None})
    assert res == {"isError": True, "content": [{"type": "text", "text":
                   "browser unavailable: Chromium did not launch: libnss3.so: cannot open shared object file"}]}
    assert srv.handle({"jsonrpc": "2.0", "id": 8, "method": "ping"})["result"] == {}  # still serving


def test_a_failing_step_is_a_result_not_an_error(app_dir):
    res = call(server(app_dir, FakeReplay(replay_result(failed_at=2))), {"steps": STEPS})
    doc = body(res)
    assert doc["ok"] is False and doc["failed_at"] == 2
    assert doc["steps"][-1] == {"n": 2, "text": stepfmt.describe(START), "ok": False, "error": "it broke",
                                "failure": "missing"}


# ---------------------------------------------------------------------------------- results


def test_result_shape_and_images(app_dir):
    fake = FakeReplay(replay_result())
    res = call(server(app_dir, fake), {"steps": STEPS, "screenshots": "all"})
    assert fake.calls == [{"app_dir": str(app_dir), "steps": STEPS, "commit": "abc123", "shots": "all"}]
    doc = body(res)
    assert list(doc) == ["ok", "failed_at", "commit", "steps", "snapshot", "app_log", "console"]  # no claim, no key
    assert doc["ok"] is True and doc["failed_at"] is None and doc["commit"] == "abc123"
    assert doc["steps"] == [{"n": n, "text": stepfmt.describe(s), "ok": True, "error": None, "failure": None}
                            for n, s in enumerate(STEPS, 1)]
    assert doc["snapshot"] == "- heading \"Taskboard\"" and doc["console"] == ["replay: a note"]
    assert doc["app_log"] == [f"line {i}" for i in range(10, 30)]  # the last 20
    assert res["content"][1:] == [
        {"type": "text", "text": "step 1"},
        {"type": "image", "data": base64.b64encode(SHOT1).decode(), "mimeType": "image/png"},
        {"type": "text", "text": "step 3"},
        {"type": "image", "data": base64.b64encode(SHOT3).decode(), "mimeType": "image/png"},
    ]


def test_screenshots_default_to_failure_and_pass_through(app_dir):
    fake = FakeReplay(replay_result(shots=()))
    srv = server(app_dir, fake)
    res = call(srv, {"steps": STEPS})
    assert len(res["content"]) == 1  # no screenshot taken, no image items
    call(srv, {"steps": STEPS, "screenshots": None})
    call(srv, {"steps": STEPS, "screenshots": "none"})
    assert [c["shots"] for c in fake.calls] == ["failure", "failure", "none"]


def test_commit_from_app_dir(tmp_path, app_dir):
    (app_dir / ".source-commit").write_text("d7b37f21c045fc252f4033ef10501cbd582141f8\n")
    fake = FakeReplay(replay_result())
    call(server(app_dir, fake), {"steps": STEPS})
    assert fake.calls[-1]["commit"] == "d7b37f21c045fc252f4033ef10501cbd582141f8"
    bare = tmp_path / "bare"
    bare.mkdir()
    call(server(bare, fake), {"steps": STEPS})
    assert fake.calls[-1]["commit"] is None and fake.calls[-1]["app_dir"] == str(bare)


def test_app_dir_from_env(monkeypatch, app_dir):
    monkeypatch.setenv("APP_DIR", str(app_dir))
    assert browser_server.BrowserServer(out=io.StringIO()).app_dir == str(app_dir)
    monkeypatch.delenv("APP_DIR")
    assert browser_server.BrowserServer(out=io.StringIO()).app_dir == "/taskboard"


def _types(schema, path="inputSchema"):
    """Every (path, type) in a JSON Schema, and any anyOf/oneOf/allOf found on the way."""
    if isinstance(schema, dict):
        for key in ("anyOf", "oneOf", "allOf"):
            if key in schema:
                yield f"{path}.{key}", key
        if "type" in schema:
            yield path, schema["type"]
        for key, sub in schema.items():
            if key in ("properties", "items", "anyOf", "oneOf", "allOf"):
                yield from _types(sub, f"{path}.{key}")
            elif path.endswith(".properties"):
                yield from _types(sub, f"{path}.{key}")
    elif isinstance(schema, list):
        for i, sub in enumerate(schema):
            yield from _types(sub, f"{path}[{i}]")


def test_input_schema_has_one_type_per_property():
    """A schema kagent's Go ADK cannot load fails the whole agent: one plain JSON type per property, no
    type arrays, no anyOf/oneOf/allOf. (The telemetry tools are held to the same rule.)"""
    for tool in [browser_server.TOOL, *mcp_server._tools("taskboard")]:
        found = list(_types(tool["inputSchema"]))
        assert ("inputSchema.properties.steps", "array") in found or tool is not browser_server.TOOL
        for path, t in found:
            assert isinstance(t, str), (tool["name"], path, t)
    props = browser_server.TOOL["inputSchema"]["properties"]
    assert {name: p["type"] for name, p in props.items()} == {"steps": "array", "fails_at": "integer",
                                                             "screenshots": "string"}


def test_description_names_the_failure_kinds_and_the_rules():
    d = browser_server.DESCRIPTION
    for kind in browser.FAILURES:
        assert f"`{kind}`" in d, kind
    assert browser.FAILURES == ("ambiguous", "missing", "mismatch", "invalid", "timeout", "error")
    for words in ("never matches a claim", "only a `missing`, `mismatch` or `error` failure matches", "an ARIA role",
                  f"longer than {browser.REPLAY_S} s",
                  # match semantics (Minor 3 of the Phase A review)
                  "`name`, `label` and `placeholder` match the whole text exactly",
                  "`text` and `within.text` match a case-insensitive substring",
                  "a case-sensitive substring"):
        assert words in d, words


def test_null_fails_at_is_no_claim(app_dir):
    """null is accepted and means the same as an absent fails_at: no matches_claim; the caller reads ok."""
    for failed_at in (None, 2):
        srv = server(app_dir, FakeReplay(replay_result(failed_at)))
        with_null, absent = body(call(srv, {"steps": STEPS, "fails_at": None})), body(call(srv, {"steps": STEPS}))
        assert with_null == absent and "matches_claim" not in with_null
        assert with_null["ok"] is (failed_at is None)


@pytest.mark.parametrize("fails_at, failed_at, failure, expected", [
    (2, 2, "missing", True),           # the claimed step failed
    (2, 2, "mismatch", True),
    (2, 2, "error", True),
    (2, 2, "ambiguous", False),        # a badly written step is never evidence
    (2, 2, "invalid", False),          # nor one that cannot run on any page (ruling R13)
    (2, 2, "timeout", False),          # nor a replay that ran out of time there (ruling R14b)
    (2, 2, None, False),               # an allowlist (ruling R16): no kind, or one it does not know, never counts
    (2, 2, "flaky", False),
    (2, 3, "missing", False),          # another step failed
    (3, 2, "missing", False),
    (2, None, None, False),            # nothing failed
])
def test_matches_claim(app_dir, fails_at, failed_at, failure, expected):
    doc = body(call(server(app_dir, FakeReplay(replay_result(failed_at, failure))),
                    {"steps": STEPS, "fails_at": fails_at}))
    assert list(doc)[:3] == ["ok", "failed_at", "matches_claim"]
    assert doc["matches_claim"] is expected


def test_evidence_failures_are_an_allowlist():
    # One list, importable without Playwright, shared by the server and verify.
    assert stepfmt.EVIDENCE_FAILURES == ("missing", "mismatch", "error")
    assert set(stepfmt.EVIDENCE_FAILURES) < set(browser.FAILURES)
    assert not hasattr(browser_server, "NOT_EVIDENCE")


# ---------------------------------------------------------------------------------- SIGTERM

SLOW = """\
import os, sys, time
from bug_investigator import browser_server

def mark(name):
    open(os.path.join({marks!r}, name), "w").close()

def slow(app_dir, steps, *, commit=None, shots="all"):
    mark("started")
    try:
        time.sleep(60)
    finally:  # what browser.replay's finally does: close Chromium, stop the app's process group
        mark("cleaning")
        time.sleep(1)
        mark("cleaned")

sys.exit(browser_server.main(replay=slow))
"""


def _wait_for(path: Path, timeout=10):
    deadline = time.time() + timeout
    while not path.exists():
        assert time.time() < deadline, f"{path.name} never appeared"
        time.sleep(0.05)


def test_sigterm_tears_down_a_running_call(tmp_path, app_dir):
    """agentgateway stops the stdio child with SIGTERM: a running replay unwinds through its finally
    blocks (they tear down the app and Chromium), a second SIGTERM does not cut that short, and the
    process exits without waiting for the call to end."""
    marks = tmp_path / "marks"
    marks.mkdir()
    code = SLOW.format(marks=str(marks))
    p = Proc([sys.executable, "-I", "-c", f"import sys; sys.path.insert(0, {str(SRC)!r})\n" + code],
             env_for(tmp_path, app_dir), tmp_path)
    p.call("initialize", INIT)
    call_id = p.request("tools/call", {"name": TOOL, "arguments": {"steps": STEPS}})
    _wait_for(marks / "started")
    assert p.call("ping", timeout=5)["result"] == {}  # stdin is still read while a call runs
    t0 = time.time()
    p.p.send_signal(signal.SIGTERM)
    _wait_for(marks / "cleaning")
    p.p.send_signal(signal.SIGTERM)  # ignored: the teardown finishes
    rc = p.wait(timeout=10)
    assert (marks / "cleaned").exists()
    assert rc == 128 + signal.SIGTERM, p.p.stderr.read()
    assert time.time() - t0 < 10  # not the 60 s the call would have taken
    assert all(json.loads(x).get("id") != call_id for x in p.raw)  # the call was cut short, never answered


# ---------------------------------------------------------------------------------- the shared JSON-RPC loop


def test_telemetry_server_unchanged(monkeypatch):
    """The telemetry server runs on the shared loop and answers exactly as before (tests/test_mcp_server.py
    covers the rest, unchanged)."""
    monkeypatch.delenv("NAMESPACE", raising=False)
    s = mcp_server.Server(out=io.StringIO())
    assert isinstance(s, mcp_server.StdioServer)
    init = s.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}})
    assert init["result"] == {
        "protocolVersion": "2025-06-18", "capabilities": {"tools": {"listChanged": False}},
        "serverInfo": {"name": "taskboard-telemetry", "version": "0.1.0"},
        "instructions": ("Loki and Prometheus for namespace 'taskboard' only. Loki datasourceUid 'loki', Prometheus "
                         f"datasourceUid {scope.PROM_UID!r}. Every query must select namespace=\"taskboard\"; "
                         "anything else is refused.")}
    assert s.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"] == {"tools": mcp_server._tools("taskboard")}
    r = s.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "nope", "arguments": {}}})
    assert r == {"jsonrpc": "2.0", "id": 3, "result": {"isError": True, "content": [{"type": "text", "text": (
        "unknown tool 'nope'; available: list_loki_label_names, list_loki_label_values, query_loki_logs, "
        "query_loki_stats, query_prometheus")}]}}
    s.pool.shutdown(wait=True)


def test_shared_loop_accepts_content_lists_and_text():
    out = io.StringIO()
    items = [{"type": "text", "text": "a"}, {"type": "image", "data": "eA==", "mimeType": "image/png"}]

    def call_tool(name, args):
        if name == "boom":
            raise mcp_server.ToolError("no")
        return items if name == "list" else "plain"

    s = mcp_server.StdioServer("x", "1.0", [{"name": "list"}, {"name": "text"}], call_tool, out=out)
    assert "instructions" not in s.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize"})["result"]

    def res(name):
        return s.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": name}})["result"]

    assert res("list") == {"content": items, "isError": False}
    assert res("text") == {"content": [{"type": "text", "text": "plain"}], "isError": False}
    assert res("boom") == {"content": [{"type": "text", "text": "no"}], "isError": True}
    s.dispatch([{"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "text"}}])  # a batch with a call
    s.pool.shutdown(wait=True)
    assert json.loads(out.getvalue()) == [{"jsonrpc": "2.0", "id": 3, "result": {
        "content": [{"type": "text", "text": "plain"}], "isError": False}}]


# ---------------------------------------------------------------------------------- the real engine


@needs_chromium
@pytest.mark.browser
def test_replays_through_the_server(tmp_path):
    app = Path(make_app(tmp_path))
    (app / ".source-commit").write_text("abc123")
    p = Proc([sys.executable, "-I", str(SERVER)], {**os.environ, "APP_DIR": str(app)}, tmp_path)
    p.call("initialize", INIT)
    res = p.call("tools/call", {"name": TOOL, "arguments": {"steps": STEPS, "screenshots": "all"}},
                 timeout=120)["result"]
    doc = body(res)
    assert doc["ok"] is True and "matches_claim" not in doc and doc["commit"] == "abc123", doc
    assert [c.get("text") for c in res["content"][1::2]] == ["step 1", "step 2", "step 3"]
    for img in res["content"][2::2]:
        assert img["type"] == "image" and img["mimeType"] == "image/png"
        assert base64.b64decode(img["data"]).startswith(PNG)
    broken = [AS_DANA, START, {"do": "expect_visible", "target": {"role": "button", "name": "Nope"}}]
    res = p.call("tools/call", {"name": TOOL, "arguments": {"steps": broken, "fails_at": 3}}, timeout=120)["result"]
    doc = body(res)
    assert doc["failed_at"] == 3 and doc["matches_claim"] is True and doc["steps"][-1]["failure"] == "missing"
    assert [c.get("text") for c in res["content"][1::2]] == ["step 3"]  # screenshots: failure by default
    code, stderr = p.finish()
    assert code == 0, stderr


@needs_chromium
@pytest.mark.browser
def test_chromium_launch_failure_through_the_server(tmp_path):
    app = Path(make_app(tmp_path))
    env = {**os.environ, "APP_DIR": str(app), "PLAYWRIGHT_BROWSERS_PATH": str(tmp_path / "no-browsers")}
    p = Proc([sys.executable, "-I", str(SERVER)], env, tmp_path)
    assert p.call("initialize", INIT)["result"]["serverInfo"]["name"] == "taskboard-browser"
    assert [t["name"] for t in p.call("tools/list")["result"]["tools"]] == [TOOL]
    res = p.call("tools/call", {"name": TOOL, "arguments": {"steps": STEPS}}, timeout=120)["result"]
    assert res["isError"] is True
    assert res["content"][0]["text"].startswith("browser unavailable: Chromium did not launch"), res
    code, stderr = p.finish()
    assert code == 0, stderr
