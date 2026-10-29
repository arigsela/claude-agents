"""A small app for the replay engine's tests, started the way Taskboard is: `python3 server.py`.

Env: PORT; DB_PATH (created, otherwise unused); TASKBOARD_COMMIT (logged); FIXTURE_BROKEN=1 drops
the second card's Done button; FIXTURE_DELAY_MS delays the cards' data, so the board renders late;
FIXTURE_ACT_DELAY_MS delays a button's answer; FIXTURE_CHILD=1 starts a sleeping child process,
FIXTURE_CHILD=ignore-term one that ignores SIGTERM (it logs `child-ready` once it does).
Serves /healthz. Logs one JSON line per request on stdout, after a start line naming its env keys.
"""

import json
import os
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CARDS = ["Write copy for the pricing page", "Update the cookie banner copy"]
BROKEN = os.environ.get("FIXTURE_BROKEN") == "1"
DELAY_S = int(os.environ.get("FIXTURE_DELAY_MS") or 0) / 1000
ACT_DELAY_S = int(os.environ.get("FIXTURE_ACT_DELAY_MS") or 0) / 1000

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Fixture board</title></head>
<body>
<h1>Fixture board</h1>
<label>User <select id="user"><option value="sam">sam (viewer)</option><option value="dana">dana (editor)</option></select></label>
<a href="http://other.invalid/">Elsewhere</a>
<button type="button" disabled>Archive all</button>
<form id="new"><input name="title" placeholder="New task"></form>
<p id="message" role="status"></p>
<div id="board"></div>
<script src="/app.js"></script>
</body></html>
"""

APP_JS = """
const say = (text) => { document.getElementById('message').textContent = text; };
const post = async (path, body) => (await fetch(path, {method: 'POST', body: JSON.stringify(body)})).json();
function card(c) {
  const el = document.createElement('div');
  el.className = 'card';
  const title = document.createElement('span');
  title.textContent = c.title;
  el.append(title);
  for (const name of c.buttons) {
    const b = document.createElement('button');
    b.textContent = name;
    b.onclick = async () => say((await post('/api/act', {id: c.id, button: name, user: document.getElementById('user').value})).message);
    el.append(b);
  }
  return el;
}
document.getElementById('new').onsubmit = async (e) => {
  e.preventDefault();
  say((await post('/api/add', {title: e.target.title.value})).message);
};
fetch('/api/cards').then((r) => r.json()).then((cards) => document.getElementById('board').replaceChildren(...cards.map(card)));
"""


def cards():
    out = []
    for i, title in enumerate(CARDS):
        buttons = ["Start", "Done"] if not (BROKEN and i == 1) else ["Start"]
        out.append({"id": i, "title": title, "buttons": buttons})
    return out


class Handler(BaseHTTPRequestHandler):
    def _send(self, status, body, ctype="application/json"):
        data = body.encode() if isinstance(body, str) else json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
        print(json.dumps({"method": self.command, "path": self.path, "status": status}), flush=True)

    def do_GET(self):
        if self.path == "/":
            self._send(200, PAGE, "text/html; charset=utf-8")
        elif self.path == "/app.js":
            self._send(200, APP_JS, "text/javascript")
        elif self.path == "/healthz":
            self._send(200, {"ok": True})
        elif self.path == "/api/cards":
            time.sleep(DELAY_S)
            self._send(200, cards())
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        if self.path == "/api/act":
            time.sleep(ACT_DELAY_S)
            moved = {"Start": "in progress", "Done": "done"}[body["button"]]
            self._send(200, {"message": f'{CARDS[body["id"]]} moved to {moved} by {body["user"]}'})
        elif self.path == "/api/add":
            self._send(200, {"message": f'added {body["title"]}'})
        else:
            self._send(404, {"error": "not found"})

    def log_message(self, format, *args):
        pass


if __name__ == "__main__":
    open(os.environ["DB_PATH"], "a").close()
    print(json.dumps({"event": "start", "commit": os.environ.get("TASKBOARD_COMMIT"), "env": sorted(os.environ)}),
          flush=True)
    if os.environ.get("FIXTURE_CHILD") in ("1", "ignore-term"):
        code = "import time; time.sleep(120)"
        if os.environ["FIXTURE_CHILD"] == "ignore-term":
            code = ("import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                    "print('{\"event\": \"child-ready\"}', flush=True); time.sleep(120)")
        child = subprocess.Popen([sys.executable, "-c", code])
        print(json.dumps({"event": "child", "pid": child.pid}), flush=True)
    ThreadingHTTPServer(("127.0.0.1", int(os.environ["PORT"])), Handler).serve_forever()
