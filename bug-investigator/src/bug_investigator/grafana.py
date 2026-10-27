"""Telemetry adapter for verify and render: Grafana's /api/ds/query and Explore links.

The agent queries through the mcp-grafana server; verify re-runs each query here.
Every query passes scope.check_query first (the caller does it; query() does it again).
"""

from __future__ import annotations

import json
import math
import urllib.error
import urllib.parse
import urllib.request

from bug_investigator import scope

DATASOURCES = {
    "logql": {"uid": scope.LOKI_UID, "type": "loki"},
    "promql": {"uid": scope.PROM_UID, "type": "prometheus"},
}


class GrafanaError(RuntimeError):
    pass


def query_body(kind: str, expr: str, start_ms: int, end_ms: int) -> dict:
    ds = DATASOURCES[kind]
    q = {"refId": "A", "datasource": dict(ds), "expr": expr}
    if kind == "logql":
        q.update({"queryType": "range", "maxLines": 100})
    else:
        q.update({"range": True, "instant": False, "intervalMs": 15000, "maxDataPoints": 1000})
    return {"from": str(start_ms), "to": str(end_ms), "queries": [q]}


def query(base_url: str, token: str, kind: str, expr: str, start_ms: int, end_ms: int,
          namespace: str = scope.NAMESPACE, opener=None, timeout: int = 30) -> dict:
    bad = scope.check_query(kind, expr, namespace)
    if bad:
        raise GrafanaError(f"out of scope: {bad}")
    body = json.dumps(query_body(kind, expr, start_ms, end_ms)).encode()
    req = urllib.request.Request(
        base_url.rstrip("/") + "/api/ds/query", data=body, method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json", "Accept": "application/json"})
    try:
        with (opener or urllib.request.urlopen)(req, timeout=timeout) as r:
            data = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise GrafanaError(f"HTTP {e.code} {_error_detail(e)}".strip()) from None
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        raise GrafanaError(str(e)) from None
    res = (data.get("results") or {}).get("A") or {}
    if res.get("error"):
        raise GrafanaError(str(res["error"])[:300])
    return data


def _error_detail(e: urllib.error.HTTPError) -> str:
    """Grafana's error message from the response body, or why it could not be read."""
    try:
        raw = e.read().decode("utf-8", errors="replace")
    except OSError as err:
        return f"(error body unreadable: {err})"
    try:
        body = json.loads(raw)
    except ValueError:
        return raw.strip()[:200]
    if isinstance(body, dict) and body.get("message"):
        return str(body["message"])[:200]
    return raw.strip()[:200]


def count_results(resp: dict) -> int:
    """Log lines for log frames; non-zero samples for numeric frames.

    A metric query that returns only zeros (no denials, no errors) does not count as "found".
    """
    frames = ((resp.get("results") or {}).get("A") or {}).get("frames") or []
    total = 0
    for fr in frames:
        fields = (fr.get("schema") or {}).get("fields") or []
        values = (fr.get("data") or {}).get("values") or []
        if not values:
            continue
        names = [str(f.get("name", "")).lower() for f in fields]
        types = [f.get("type") for f in fields]
        is_logs = "line" in names or ((fr.get("schema") or {}).get("meta") or {}).get("type") == "log-lines"
        if is_logs:
            total += len(values[0])
            continue
        for idx, t in enumerate(types):
            if t == "number" and idx < len(values):
                for v in values[idx]:
                    if isinstance(v, (int, float)) and not (isinstance(v, float) and math.isnan(v)) and v != 0:
                        total += 1
    return total


def explore_link(base_url: str, kind: str, expr: str, start_ms: int, end_ms: int) -> str:
    ds = DATASOURCES[kind]
    q = {"refId": "A", "datasource": {"type": ds["type"], "uid": ds["uid"]}, "expr": expr}
    if kind == "logql":
        q["queryType"] = "range"
    else:
        q["range"] = True
    panes = {"a": {"datasource": ds["uid"], "queries": [q], "range": {"from": str(start_ms), "to": str(end_ms)}}}
    return (base_url.rstrip("/") + "/explore?schemaVersion=1&orgId=1&panes="
            + urllib.parse.quote(json.dumps(panes, separators=(",", ":")), safe=""))
