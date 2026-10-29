"""A small Streamable HTTP MCP client (standard library only) for the verifier.

`McpClient` opens one session (initialize, notifications/initialized, then calls, DELETE on close).
`replay_via_mcp` calls the `replay_ui_steps` tool of the taskboard-browser server and returns its
JSON plus the decoded screenshots. Request bodies are never logged or put in errors.
"""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request

PROTOCOL_VERSION = "2025-06-18"


class McpError(RuntimeError):
    """A failed MCP request: HTTP, network, protocol or JSON-RPC error."""


def _result(msg: dict, method: str) -> dict:
    if "error" in msg:
        err = msg["error"] or {}
        raise McpError(f"MCP {method}: error {err.get('code')} {err.get('message')}")
    return msg.get("result") or {}


def _parse_sse(text: str, rid: int | None, method: str) -> dict:
    """The JSON-RPC message with id `rid` from a text/event-stream body; other events are ignored."""
    for block in text.replace("\r\n", "\n").split("\n\n"):
        data = "\n".join(line[5:].lstrip(" ") for line in block.split("\n") if line.startswith("data:"))
        if not data:
            continue
        try:
            msg = json.loads(data)
        except ValueError:
            continue
        if isinstance(msg, dict) and msg.get("id") == rid and ("result" in msg or "error" in msg):
            return msg
    raise McpError(f"MCP {method}: no response event in stream")


class McpClient:
    def __init__(self, url: str, *, timeout: float = 120.0, opener=None):
        self.url = url
        self.timeout = timeout
        self._open = opener or urllib.request.urlopen
        self._session: str | None = None
        self._ready = False
        self._id = 0

    def __enter__(self) -> "McpClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if self._session:
            h["Mcp-Session-Id"] = self._session
        return h

    def _post(self, method: str, params: dict | None, notify: bool = False) -> dict | None:
        msg: dict = {"jsonrpc": "2.0", "method": method}
        rid = None
        if not notify:
            self._id += 1
            rid = self._id
            msg["id"] = rid
        if params is not None:
            msg["params"] = params
        req = urllib.request.Request(self.url, data=json.dumps(msg).encode(), headers=self._headers(), method="POST")
        try:
            with self._open(req, timeout=self.timeout) as r:
                sid = r.headers.get("Mcp-Session-Id")
                if sid and not self._session:
                    self._session = sid
                ctype = (r.headers.get("Content-Type") or "").lower()
                raw = r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            try:
                body = e.read().decode("utf-8", "replace")
            except Exception:  # noqa: BLE001
                body = ""
            raise McpError(f"MCP {method}: HTTP {e.code} {body[:300]}") from None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
            raise McpError(f"MCP {method}: {type(e).__name__} {e}"[:400]) from None
        if notify:
            return None
        if "text/event-stream" in ctype:
            return _parse_sse(raw, rid, method)
        try:
            out = json.loads(raw)
        except ValueError:
            raise McpError(f"MCP {method}: response is not JSON") from None
        if not isinstance(out, dict):
            raise McpError(f"MCP {method}: unexpected response")
        return out

    def _ensure(self) -> None:
        if self._ready:
            return
        _result(self._post("initialize", {"protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                                          "clientInfo": {"name": "bug-investigator", "version": "1"}}) or {},
                "initialize")
        self._post("notifications/initialized", None, notify=True)
        self._ready = True

    def call(self, name: str, args: dict) -> dict:
        self._ensure()
        msg = self._post("tools/call", {"name": name, "arguments": args})
        return _result(msg or {}, "tools/call")

    def close(self) -> None:
        if not self._session:
            return
        req = urllib.request.Request(self.url, headers={"Mcp-Session-Id": self._session}, method="DELETE")
        self._session = None
        self._ready = False
        try:
            with self._open(req, timeout=min(self.timeout, 10.0)) as r:
                r.read()
        except Exception:  # noqa: BLE001 - best effort
            pass


def replay_via_mcp(url: str, steps: list, fails_at: int | None, *, screenshots: str = "all",
                   timeout: float = 120.0, opener=None) -> dict:
    args: dict = {"steps": steps, "screenshots": screenshots}
    if fails_at is not None:
        args["fails_at"] = fails_at
    with McpClient(url, timeout=timeout, opener=opener) as c:
        res = c.call("replay_ui_steps", args)
    content = res.get("content") or []
    texts = [i for i in content if isinstance(i, dict) and i.get("type") == "text"]
    if res.get("isError"):
        text = texts[0].get("text", "") if texts else "tool error"
        return {"ok": False, "failed_at": None, "matches_claim": None, "commit": None, "steps": [],
                "snapshot": None, "app_log": None, "console": [], "screenshots": [], "error": text}
    if not content or content[0].get("type") != "text":
        raise McpError("MCP tools/call: first content item is not text")
    try:
        out = json.loads(content[0].get("text", ""))
    except ValueError:
        raise McpError("MCP tools/call: result text is not JSON") from None
    if not isinstance(out, dict):
        raise McpError("MCP tools/call: result JSON is not an object")
    shots: list = []
    pending: int | None = None
    for item in content[1:]:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "text":
            t = str(item.get("text", "")).strip()
            pending = int(t[5:]) if t.startswith("step ") and t[5:].isdigit() else None
        elif item.get("type") == "image" and pending is not None:
            try:
                shots.append((pending, base64.b64decode(item.get("data", ""))))
            except ValueError:
                pass
            pending = None
    out.setdefault("matches_claim", None)
    out["screenshots"] = shots
    out["error"] = None
    return out
