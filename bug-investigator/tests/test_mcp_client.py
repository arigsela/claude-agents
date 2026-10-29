"""mcp_client against a threaded fake Streamable HTTP MCP server."""
import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from bug_investigator import mcp_client
from bug_investigator.mcp_client import McpClient, McpError, replay_via_mcp

PNG = b"\x89PNG\r\n\x1a\nfake"


class Fake:
    def __init__(self, sse=False, tool_result=None, fail_status=None):
        self.sse = sse
        self.tool_result = tool_result or {"content": [{"type": "text", "text": "hi"}], "isError": False}
        self.fail_status = fail_status
        self.log = []  # (method, path, headers dict, parsed body)
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _rec(self):
                n = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(n) if n else b""
                body = json.loads(raw) if raw else None
                fake.log.append((self.command, self.path, {k.lower(): v for k, v in self.headers.items()}, body))
                return body

            def do_DELETE(self):
                self._rec()
                self.send_response(200)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def do_POST(self):
                body = self._rec()
                if fake.fail_status and body.get("method") == "tools/call":
                    data = b"boom " * 200
                    self.send_response(fake.fail_status)
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
                if "id" not in body:
                    self.send_response(202)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                m = body["method"]
                if m == "initialize":
                    res = {"protocolVersion": "2025-06-18", "capabilities": {}, "serverInfo": {"name": "x", "version": "1"}}
                else:
                    res = fake.tool_result
                msg = {"jsonrpc": "2.0", "id": body["id"], "result": res}
                if fake.sse:
                    other = {"jsonrpc": "2.0", "method": "notifications/message", "params": {}}
                    out = ("event: message\ndata: %s\n\nevent: message\ndata: %s\n\n"
                           % (json.dumps(other), json.dumps(msg))).encode()
                    ct = "text/event-stream"
                else:
                    out, ct = json.dumps(msg).encode(), "application/json"
                self.send_response(200)
                self.send_header("Content-Type", ct)
                if m == "initialize":
                    self.send_header("Mcp-Session-Id", "sess-1")
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = "http://127.0.0.1:%d/mcp" % self.srv.server_port
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


@pytest.fixture
def fake():
    made = []

    def make(**kw):
        f = Fake(**kw)
        made.append(f)
        return f

    yield make
    for f in made:
        f.close()


def test_session_lifecycle(fake):
    f = fake()
    with McpClient(f.url, timeout=5) as c:
        res = c.call("echo", {"a": 1})
        assert res["content"][0]["text"] == "hi"
        c.call("echo", {})
    methods = [(m, b and b.get("method")) for m, _, _, b in f.log]
    assert methods == [("POST", "initialize"), ("POST", "notifications/initialized"),
                       ("POST", "tools/call"), ("POST", "tools/call"), ("DELETE", None)]
    init = f.log[0]
    assert init[3]["params"]["protocolVersion"] == "2025-06-18"
    assert init[3]["params"]["clientInfo"]["name"] == "bug-investigator"
    assert init[3]["params"]["capabilities"] == {}
    assert init[2]["accept"] == "application/json, text/event-stream"
    assert "mcp-session-id" not in init[2]
    for _, _, h, _ in f.log[1:]:
        assert h["mcp-session-id"] == "sess-1"
    assert f.log[2][3]["params"] == {"name": "echo", "arguments": {"a": 1}}


def test_sse_response_parsed(fake):
    f = fake(sse=True)
    with McpClient(f.url, timeout=5) as c:
        assert c.call("echo", {})["content"][0]["text"] == "hi"


def test_is_error_surfaces(fake):
    f = fake(tool_result={"content": [{"type": "text", "text": "browser unavailable: no cpu"}], "isError": True})
    with McpClient(f.url, timeout=5) as c:
        res = c.call("replay_ui_steps", {})
    assert res["isError"] is True
    out = replay_via_mcp(f.url, [{"do": "goto", "value": "/"}], None, timeout=5)
    assert out["ok"] is False and out["failed_at"] is None
    assert out["error"] == "browser unavailable: no cpu"
    assert out["steps"] == [] and out["screenshots"] == []
    assert out["matches_claim"] is None and out["commit"] is None


def test_replay_via_mcp_pairs_images_with_steps(fake):
    body = {"ok": False, "failed_at": 2, "matches_claim": True, "commit": "abc",
            "steps": [{"n": 1, "ok": True}, {"n": 2, "ok": False}], "snapshot": "s", "app_log": "l", "console": []}
    img = {"type": "image", "data": base64.b64encode(PNG).decode(), "mimeType": "image/png"}
    f = fake(tool_result={"content": [
        {"type": "text", "text": json.dumps(body)},
        {"type": "text", "text": "step 1"}, img,
        {"type": "text", "text": "step 2"}, img], "isError": False})
    out = replay_via_mcp(f.url, [{"do": "goto", "value": "/"}], 2, timeout=5)
    assert out["failed_at"] == 2 and out["matches_claim"] is True and out["error"] is None
    assert out["screenshots"] == [(1, PNG), (2, PNG)]
    call = [b for _, _, _, b in f.log if b and b.get("method") == "tools/call"][0]
    args = call["params"]["arguments"]
    assert args["fails_at"] == 2 and args["screenshots"] == "all"
    assert f.log[-1][0] == "DELETE"
    replay_via_mcp(f.url, [], None, timeout=5, screenshots="none")
    call = [b for _, _, _, b in f.log if b and b.get("method") == "tools/call"][-1]
    assert "fails_at" not in call["params"]["arguments"]


def test_http_error_raises_with_status(fake):
    f = fake(fail_status=500)
    with pytest.raises(McpError) as e:
        with McpClient(f.url, timeout=5) as c:
            c.call("echo", {})
    msg = str(e.value)
    assert msg.startswith("MCP tools/call: HTTP 500 boom")
    assert len(msg) < 400


def test_jsonrpc_error_raises():
    with pytest.raises(McpError, match="-32602"):
        mcp_client._result({"jsonrpc": "2.0", "id": 1, "error": {"code": -32602, "message": "bad"}}, "tools/call")
