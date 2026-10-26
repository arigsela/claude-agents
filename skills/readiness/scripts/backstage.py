"""backstage: read the catalog, CVE report and scorecard over REST. Fails soft via BackstageError."""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable

Fetch = Callable[[str, str, "bytes | None", "dict[str, str]", float], "tuple[int, bytes]"]


def urllib_fetch(method: str, url: str, body: bytes | None, headers: dict[str, str],
                 timeout: float) -> tuple[int, bytes]:
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


class BackstageError(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def parse_ref(ref: str) -> tuple[str, str, str]:
    kind, _, rest = ref.partition(":")
    ns, sep, name = rest.partition("/")
    if not sep:
        ns, name = "default", rest
    return kind.lower(), ns, name


class Backstage:
    def __init__(self, base_url: str, token: str | None, fetch: Fetch = urllib_fetch,
                 timeout: float = 15.0):
        self._base = base_url.rstrip("/")
        self._token = token
        self._fetch = fetch
        self._timeout = timeout

    def __repr__(self) -> str:
        return f"Backstage({self._base!r})"

    def url(self, path: str) -> str:
        return self._base + path

    def _call(self, method: str, path: str, payload: dict | None = None, soft404: bool = False):
        headers = {"Accept": "application/json"}
        body = None
        if payload is not None:
            body = json.dumps(payload).encode()
            headers["Content-Type"] = "application/json"
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        try:
            status, raw = self._fetch(method, self.url(path), body, headers, self._timeout)
        except TimeoutError:
            raise BackstageError("timeout") from None
        except OSError:
            raise BackstageError("unreachable") from None
        if status == 404 and soft404:
            return None
        if not 200 <= status < 300:
            raise BackstageError(f"HTTP {status}")
        try:
            return json.loads(raw)
        except ValueError:
            raise BackstageError("invalid JSON") from None

    def entities_by_slug(self, slug: str) -> list[dict]:
        q = urllib.parse.urlencode({"filter": f"metadata.annotations.github.com/project-slug={slug}"})
        data = self._call("GET", f"/api/catalog/entities/by-query?{q}")
        items = data.get("items") if isinstance(data, dict) else None
        return items if isinstance(items, list) else []

    def _entity_path(self, ref: str) -> str:
        kind, ns, name = (urllib.parse.quote(p, safe="") for p in parse_ref(ref))
        return f"{kind}/{ns}/{name}"

    def entity(self, ref: str) -> dict | None:
        return self._call("GET", f"/api/catalog/entities/by-name/{self._entity_path(ref)}", soft404=True)

    def cve_report(self, images: list[str]) -> dict:
        return self._call("POST", "/api/cve/report", {"images": images})

    def scorecard(self, ref: str) -> list[dict] | None:
        return self._call("GET", f"/api/scorecard/metrics/catalog/{self._entity_path(ref)}", soft404=True)
