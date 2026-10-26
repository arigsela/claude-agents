"""backstage: catalog, CVE and scorecard client, fed by an injected fetch."""
from __future__ import annotations

import json
import os
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills/readiness/scripts"))

import backstage as b  # noqa: E402

DATA = Path(__file__).parent / "data"
BASE = "https://bs.example"


def load(name: str) -> bytes:
    return (DATA / name).read_bytes()


class Rec:
    def __init__(self, status=200, body=b"{}", exc=None):
        self.status, self.body, self.exc, self.calls = status, body, exc, []

    def __call__(self, method, url, body, headers, timeout):
        self.calls.append((method, url, body, dict(headers), timeout))
        if self.exc:
            raise self.exc
        return self.status, self.body


class RefTest(unittest.TestCase):
    def test_full(self):
        self.assertEqual(b.parse_ref("Component:hk-demo/hk-demo"), ("component", "hk-demo", "hk-demo"))

    def test_default_namespace(self):
        self.assertEqual(b.parse_ref("component:svc"), ("component", "default", "svc"))


class ClientTest(unittest.TestCase):
    def client(self, rec, token=None):
        return b.Backstage(BASE + "/", token, fetch=rec)

    def test_entities_by_slug(self):
        rec = Rec(body=json.dumps({"items": [{"kind": "Component"}]}).encode())
        self.assertEqual(self.client(rec).entities_by_slug("arigsela/hk-demo"), [{"kind": "Component"}])
        m, url, body, headers, timeout = rec.calls[0]
        self.assertEqual(m, "GET")
        self.assertEqual(url, BASE + "/api/catalog/entities/by-query?filter="
                         "metadata.annotations.github.com%2Fproject-slug%3Darigsela%2Fhk-demo")
        self.assertEqual(timeout, 15.0)

    def test_token(self):
        rec = Rec()
        self.client(rec).entity("component:a/b")
        self.assertNotIn("Authorization", rec.calls[0][3])
        rec = Rec()
        self.client(rec, "t0k").entity("component:a/b")
        self.assertEqual(rec.calls[0][3]["Authorization"], "Bearer t0k")

    def test_token_not_in_errors(self):
        for rec in (Rec(500), Rec(exc=TimeoutError("t0k")), Rec(exc=OSError("t0k")), Rec(body=b"<html>t0k")):
            with self.assertRaises(b.BackstageError) as cm:
                self.client(rec, "t0k").entity("component:a/b")
            self.assertNotIn("t0k", str(cm.exception))
            self.assertNotIn("t0k", repr(cm.exception))
            self.assertNotIn("t0k", cm.exception.reason)

    def test_entity(self):
        rec = Rec(body=load("entity.json"))
        e = self.client(rec).entity("component:hk-demo/hk-demo")
        self.assertEqual(rec.calls[0][1], BASE + "/api/catalog/entities/by-name/component/hk-demo/hk-demo")
        self.assertEqual(e["metadata"]["name"], "hk-demo")

    def test_entity_404(self):
        self.assertIsNone(self.client(Rec(404)).entity("component:hk-demo/hk-demo"))

    def test_cve_report(self):
        rec = Rec(body=load("cve.json"))
        r = self.client(rec).cve_report(["img@sha256:aa"])
        m, url, body, headers, _ = rec.calls[0]
        self.assertEqual((m, url), ("POST", BASE + "/api/cve/report"))
        self.assertEqual(json.loads(body), {"images": ["img@sha256:aa"]})
        self.assertEqual(headers["Content-Type"], "application/json")
        self.assertEqual(r["totals"]["actionable"], 2)

    def test_scorecard(self):
        rec = Rec(body=load("scorecard.json"))
        r = self.client(rec).scorecard("component:hk-demo/hk-demo")
        self.assertEqual(rec.calls[0][1], BASE + "/api/scorecard/metrics/catalog/component/hk-demo/hk-demo")
        self.assertEqual([x["id"] for x in r], ["github.openPRs", "filecheck.runbook",
                                                "filecheck.docs", "dependabot.alertsHigh"])
        self.assertEqual(r[3]["status"], "error")

    def test_scorecard_404(self):
        self.assertIsNone(self.client(Rec(404)).scorecard("component:hk-demo/hk-demo"))

    def test_errors(self):
        for rec, reason in ((Rec(500), "HTTP 500"), (Rec(exc=TimeoutError()), "timeout"),
                            (Rec(exc=OSError("down")), "unreachable"),
                            (Rec(body=b"<html>"), "invalid JSON")):
            with self.assertRaises(b.BackstageError) as cm:
                self.client(rec).entities_by_slug("a/b")
            self.assertEqual(cm.exception.reason, reason)


class _Recorder(BaseHTTPRequestHandler):
    """Records each request's headers; `location` set means answer 302 to it, else 200 with a JSON body."""

    seen: list = []
    location: str | None = None

    def do_GET(self):
        self.seen.append(dict(self.headers))
        if self.location:
            self.send_response(302)
            self.send_header("Location", self.location)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        body = b'{"kind": "Component"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class RedirectTest(unittest.TestCase):
    """The real urllib fetch against two local servers: the token never follows a redirect (final review I4)."""

    def serve(self, **attrs) -> str:
        handler = type("Handler", (_Recorder,), {"seen": [], **attrs})
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.handlers.append(handler)
        return f"http://127.0.0.1:{server.server_port}"

    def setUp(self):
        self.handlers = []
        env = mock.patch.dict(os.environ, {"no_proxy": "127.0.0.1", "NO_PROXY": "127.0.0.1"})
        env.start()
        self.addCleanup(env.stop)

    def test_authorization_not_sent_to_the_redirect_target(self):
        other = self.serve()
        first = self.serve(location=other + "/elsewhere")
        doc = b.Backstage(first, "t0k").entity("component:a/b")
        self.assertEqual(doc, {"kind": "Component"})
        sent, landed = self.handlers[1].seen, self.handlers[0].seen
        self.assertEqual(sent[0].get("Authorization"), "Bearer t0k")
        self.assertEqual(len(landed), 1)
        self.assertNotIn("authorization", {k.lower() for k in landed[0]})
        self.assertNotIn("t0k", json.dumps(landed))

    def test_no_redirect_keeps_the_header(self):
        status, raw = b.urllib_fetch("GET", self.serve() + "/x", None, {"Authorization": "Bearer t0k"}, 5)
        self.assertEqual((status, json.loads(raw)), (200, {"kind": "Component"}))
        self.assertEqual(self.handlers[0].seen[0].get("Authorization"), "Bearer t0k")


if __name__ == "__main__":
    unittest.main()
