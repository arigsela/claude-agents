"""Record and replay model responses, so a re-run whose prompts did not change is free.

``ReplayTransport`` sits under the Anthropic client as its httpx2 transport. Each
request has a key, ``sha256(method | url | canonical body)``: the url is the
request's path and query (the host is where it went, not what it asked, so a
cassette replays whatever ``ANTHROPIC_BASE_URL`` says), and the canonical body is
the JSON body with sorted keys and no spaces. A cassette, ``<key>.json`` in the
cassette directory, is the ordered list of attempts made for that key: status,
``request-id``, ``retry-after``, ``content-type`` and the JSON body (C#29).

- Within one transport (one run) the Nth request with a key gets the key's Nth
  attempt, so a recorded 529 and the 200 of its retry replay in that order.
- ``replay`` mode: a request past its recorded attempts raises ``CassetteMiss``
  (and is listed in ``misses``); the inner transport is never called.
- ``record-missing`` mode: such a request goes to the inner transport, and its
  response is appended to the cassette, with two exceptions. A cassette whose last
  attempt is not a 2xx (retries that ran out) is discarded at its first use in the
  run and recorded afresh, so a failure is never replayed for good; and a
  non-retryable 4xx (400, 401, 403: a bad request, a wrong key, no credit) is passed
  on but never stored. A 529 whose retry succeeded stays, in order.
- A replayed response carries ``x-docs-checker-replayed: 1``; ``llm.request_id_hook``
  copies it into the ledger, which then prices the call as workload, not cash.
- A cassette never holds the request (no prompt), the API key or any other header,
  and the body passes ``redact`` before it is written. The recording run gets the
  stored (redacted) response too, so it sees exactly what a replay will.
- ``overloaded=N`` answers the first N requests of every key with a synthetic 529
  before its cassette attempts (marked replayed, never recorded): the retry lever's
  row at no cost (C#43).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Literal

import httpx2

from docs_checker.llm import REPLAYED_HEADER, RETRYABLE_STATUS
from docs_checker.redact import redact, redact_obj

Mode = Literal["replay", "record-missing"]
MODES: tuple[Mode, ...] = ("replay", "record-missing")
CASSETTE_VERSION = 1
OVERLOADED_BODY = {"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}}


class CassetteMiss(Exception):
    """Replay mode met a request it has no recorded attempt for."""

    def __init__(self, key: str, attempt: int):
        self.key = key
        self.attempt = attempt
        super().__init__(
            f"no recorded attempt {attempt + 1} for request {key[:16]}; "
            "record it with --mode record-missing"
        )


def canonical_body(content: bytes) -> str:
    """The body as sorted, compact JSON; a body that is not JSON as its text."""
    try:
        data = json.loads(content)
    except ValueError:
        return content.decode("utf-8", "replace")
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def request_key(method: str, url: httpx2.URL, content: bytes) -> str:
    target = url.raw_path.decode("ascii", "replace")  # path and query
    blob = f"{method.upper()}|{target}|{canonical_body(content)}"
    return hashlib.sha256(blob.encode()).hexdigest()


def _attempt(response: httpx2.Response) -> dict[str, Any]:
    """What a cassette keeps of a response, redacted."""
    try:
        body: Any = redact_obj(json.loads(response.content))
        text = None
    except ValueError:
        body, text = None, redact(response.content.decode("utf-8", "replace"))
    attempt = {
        "status": response.status_code,
        "request_id": response.headers.get("request-id"),
        "retry_after": response.headers.get("retry-after"),
        "content_type": response.headers.get("content-type"),
        "body": body,
    }
    if text is not None:
        attempt["text"] = text
    return attempt


def _succeeded(attempt: dict[str, Any]) -> bool:
    status = attempt.get("status")
    return isinstance(status, int) and 200 <= status < 300


def _kept(status: int) -> bool:
    """A response worth recording: not a 4xx that a retry would get again."""
    return not (400 <= status < 500) or status in RETRYABLE_STATUS


def _response(attempt: dict[str, Any], request: httpx2.Request, *, replayed: bool):
    headers = {
        name: attempt[field]
        for name, field in (
            ("request-id", "request_id"),
            ("retry-after", "retry_after"),
            ("content-type", "content_type"),
        )
        if attempt.get(field)
    }
    if replayed:
        headers[REPLAYED_HEADER] = "1"
    if attempt.get("body") is not None:
        content = json.dumps(attempt["body"], ensure_ascii=False).encode()
    else:
        content = (attempt.get("text") or "").encode()
    return httpx2.Response(attempt["status"], headers=headers, content=content, request=request)


class ReplayTransport(httpx2.AsyncBaseTransport):
    """Serves recorded attempts in order per key; see the module docstring."""

    def __init__(
        self,
        inner: httpx2.AsyncBaseTransport,
        cassette_dir: Path | str,
        mode: Mode,
        *,
        overloaded: int = 0,
    ):
        if mode not in MODES:
            raise ValueError(f"mode must be one of {', '.join(MODES)}: {mode!r}")
        self.inner = inner
        self.cassette_dir = Path(cassette_dir)
        self.mode = mode
        self.overloaded = overloaded
        self.misses: list[CassetteMiss] = []
        self.missed = asyncio.Event()  # set on the first miss, so a run can stop early
        self.sent = 0  # requests handed to the inner transport (sent, maybe billed)
        self.live = 0  # responses that came from the inner transport
        self._seen: dict[str, int] = {}
        self._checked: set[str] = set()  # keys whose cassette this run has looked at
        self._locks: dict[str, asyncio.Lock] = {}

    def _path(self, key: str) -> Path:
        return self.cassette_dir / f"{key}.json"

    def _load(self, key: str) -> list[dict[str, Any]]:
        path = self._path(key)
        if not path.exists():
            return []
        data = json.loads(path.read_text())
        if data.get("version") != CASSETTE_VERSION:
            raise ValueError(f"{path}: unsupported cassette version {data.get('version')!r}")
        return list(data["attempts"])

    def _save(self, key: str, attempts: list[dict[str, Any]]) -> None:
        self.cassette_dir.mkdir(parents=True, exist_ok=True)
        text = json.dumps(
            {"version": CASSETTE_VERSION, "attempts": attempts},
            indent=1,
            sort_keys=True,
            ensure_ascii=False,
        )
        fd, tmp = tempfile.mkstemp(dir=self.cassette_dir, suffix=".tmp")
        with os.fdopen(fd, "w") as out:
            out.write(text + "\n")
        os.replace(tmp, self._path(key))

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        key = request_key(request.method, request.url, await request.aread())
        # One request per key at a time, so attempts are taken and stored in order.
        async with self._locks.setdefault(key, asyncio.Lock()):
            seen = self._seen.get(key, 0)
            if seen < self.overloaded:
                self._seen[key] = seen + 1
                attempt = {"status": 529, "content_type": "application/json"}
                return _response({**attempt, "body": OVERLOADED_BODY}, request, replayed=True)
            index = seen - self.overloaded
            attempts = self._load(key)
            if self.mode == "record-missing" and key not in self._checked:
                self._checked.add(key)
                if attempts and not _succeeded(attempts[-1]):
                    self._path(key).unlink()  # a failure is recorded afresh, not replayed
                    attempts = []
            if index < len(attempts):
                self._seen[key] = seen + 1
                return _response(attempts[index], request, replayed=True)
            if self.mode == "replay":
                miss = CassetteMiss(key, index)
                self.misses.append(miss)
                self.missed.set()
                raise miss
            self.sent += 1
            live = await self.inner.handle_async_request(request)
            try:
                await live.aread()
            finally:
                await live.aclose()
            self.live += 1
            attempt = _attempt(live)
            if not _kept(live.status_code):  # passed on, never stored; the cursor stays
                return _response(attempt, request, replayed=False)
            self._save(key, [*attempts, attempt])
            self._seen[key] = seen + 1
            return _response(attempt, request, replayed=False)

    async def aclose(self) -> None:
        await self.inner.aclose()


class Offline(httpx2.AsyncBaseTransport):
    """The inner transport of a replay-only run: nothing may leave."""

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        raise RuntimeError("a replay-only run tried to reach the API")


def replay_only(cassette_dir: Path | str) -> ReplayTransport:
    """``replay`` mode over ``Offline``: every response comes from ``cassette_dir``,
    nothing is recorded, and a request with no recording raises ``CassetteMiss``.

    The production seam (``DOCS_CHECKER_REPLAY_DIR``) uses one for the server's
    lifetime, so each recorded attempt is served once per process, in order."""
    return ReplayTransport(Offline(), cassette_dir, "replay")
