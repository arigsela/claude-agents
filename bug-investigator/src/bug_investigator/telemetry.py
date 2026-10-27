"""Telemetry adapter that talks to Loki and Prometheus directly, with no Grafana and no token.

The kagent version runs inside the cluster, where Loki and Prometheus answer anyone who can reach
them. So the scope check is the boundary here too: every function below runs it before any HTTP
call, whatever the caller already checked.

- `query()` has the same signature (after the URLs) and returns the same shape as `grafana.query`
  (Grafana's /api/ds/query data frames), so verify's `Ctx(gquery=...)` can swap it in and
  `grafana.count_results` counts it the same way.
- The other functions back the stdio MCP server (`mcp_server.py`): Loki query_range, index stats,
  label names and values; Prometheus instant and range queries.

Base URLs: env LOKI_URL and PROMETHEUS_URL, defaulting to the in-cluster services.
"""

from __future__ import annotations

import json
import math
import os
import re
import urllib.error
import urllib.parse
import urllib.request

from bug_investigator import grafana, scope

DEFAULT_LOKI_URL = "http://loki.logging.svc.cluster.local:3100"
DEFAULT_PROMETHEUS_URL = "http://prometheus.logging.svc.cluster.local:9090"
MAX_LINES = 100          # what grafana.query_body asks Grafana for (maxLines)
MAX_POINTS = 1000        # Grafana's maxDataPoints in grafana.query_body
MIN_STEP_S = 15          # Grafana's intervalMs in grafana.query_body
LABEL_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class TelemetryError(grafana.GrafanaError):
    """A failed or refused query. A GrafanaError subclass, so verify's handler catches it."""


def loki_url() -> str:
    return (os.environ.get("LOKI_URL") or DEFAULT_LOKI_URL).rstrip("/")


def prometheus_url() -> str:
    return (os.environ.get("PROMETHEUS_URL") or DEFAULT_PROMETHEUS_URL).rstrip("/")


# ---------------------------------------------------------------------------------- HTTP


def _get(url: str, params: dict, opener=None, timeout: int = 30):
    qs = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    req = urllib.request.Request(url + ("?" + qs if qs else ""), method="GET",
                                 headers={"Accept": "application/json", "User-Agent": "bug-investigator/1"})
    try:
        with (opener or urllib.request.urlopen)(req, timeout=timeout) as r:
            body = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise TelemetryError(f"HTTP {e.code} {_error_detail(e)}".strip()) from None
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as e:
        raise TelemetryError(str(e)) from None
    if isinstance(body, dict) and body.get("status") == "error":
        raise TelemetryError(str(body.get("error") or "query failed")[:300])
    return body


def _error_detail(e: urllib.error.HTTPError) -> str:
    """Loki answers errors in plain text, Prometheus in JSON ({"error": ...})."""
    try:
        raw = e.read().decode("utf-8", errors="replace")
    except OSError as err:
        return f"(error body unreadable: {err})"
    try:
        body = json.loads(raw)
    except ValueError:
        return raw.strip()[:200]
    if isinstance(body, dict) and (body.get("error") or body.get("message")):
        return str(body.get("error") or body.get("message"))[:200]
    return raw.strip()[:200]


def _data(body) -> dict:
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, dict) and not isinstance(data, list):
        raise TelemetryError("unexpected response: no data")
    return data


def _ns(ms: int) -> str:
    return str(int(ms) * 1_000_000)


def step_seconds(start_ms: int, end_ms: int) -> int:
    """Grafana's step for a range query: the interval, or range / maxDataPoints if larger."""
    return max(MIN_STEP_S, math.ceil(max(0, end_ms - start_ms) / 1000 / MAX_POINTS))


def _refuse(problem: str | None) -> None:
    if problem:
        raise TelemetryError(f"out of scope: {problem}")


# ---------------------------------------------------------------------------------- Loki


def loki_query_range(logql: str, start_ms: int, end_ms: int, *, limit: int = MAX_LINES,
                     direction: str = "backward", step_s: int | None = None,
                     namespace: str = scope.NAMESPACE, opener=None) -> dict:
    """Loki /query_range: {"resultType": "streams"|"matrix", "result": [...]}."""
    _refuse(scope.check_logql(logql, namespace))
    params = {"query": logql, "start": _ns(start_ms), "end": _ns(end_ms), "limit": int(limit),
              "direction": direction, "step": f"{step_s or step_seconds(start_ms, end_ms)}s"}
    return _data(_get(loki_url() + "/loki/api/v1/query_range", params, opener))


def loki_query_instant(logql: str, at_ms: int, *, limit: int = MAX_LINES, direction: str = "backward",
                       namespace: str = scope.NAMESPACE, opener=None) -> dict:
    """Loki /query (metric queries at one instant)."""
    _refuse(scope.check_logql(logql, namespace))
    params = {"query": logql, "time": _ns(at_ms), "limit": int(limit), "direction": direction}
    return _data(_get(loki_url() + "/loki/api/v1/query", params, opener))


def loki_stats(logql: str, start_ms: int, end_ms: int, *, namespace: str = scope.NAMESPACE, opener=None) -> dict:
    """Loki /index/stats: {"streams", "chunks", "entries", "bytes"} for a stream selector."""
    _refuse(scope.check_logql(logql, namespace))
    params = {"query": logql, "start": _ns(start_ms), "end": _ns(end_ms)}
    body = _get(loki_url() + "/loki/api/v1/index/stats", params, opener)
    if not isinstance(body, dict):
        raise TelemetryError("unexpected stats response")
    return body


def loki_label_names(matcher: str, start_ms: int, end_ms: int, *, namespace: str = scope.NAMESPACE,
                     opener=None) -> list:
    _refuse(scope.is_scoped_stream_selector(matcher, namespace))
    params = {"query": matcher, "start": _ns(start_ms), "end": _ns(end_ms)}
    return _data(_get(loki_url() + "/loki/api/v1/labels", params, opener)) or []


def loki_label_values(label: str, matcher: str, start_ms: int, end_ms: int, *,
                      namespace: str = scope.NAMESPACE, opener=None) -> list:
    _refuse(scope.is_scoped_stream_selector(matcher, namespace))
    if not isinstance(label, str) or not LABEL_RE.fullmatch(label):
        raise TelemetryError(f"labelName {label!r} is not a label name")
    params = {"query": matcher, "start": _ns(start_ms), "end": _ns(end_ms)}
    path = "/loki/api/v1/label/" + urllib.parse.quote(label, safe="") + "/values"
    return _data(_get(loki_url() + path, params, opener)) or []


# ---------------------------------------------------------------------------------- Prometheus


def prom_query_range(expr: str, start_ms: int, end_ms: int, *, step_s: int | None = None,
                     namespace: str = scope.NAMESPACE, opener=None) -> dict:
    """Prometheus /query_range: {"resultType": "matrix", "result": [...]}."""
    _refuse(scope.check_promql(expr, namespace))
    params = {"query": expr, "start": f"{start_ms / 1000:.3f}", "end": f"{end_ms / 1000:.3f}",
              "step": f"{step_s or step_seconds(start_ms, end_ms)}s"}
    return _data(_get(prometheus_url() + "/api/v1/query_range", params, opener))


def prom_query_instant(expr: str, at_ms: int, *, namespace: str = scope.NAMESPACE, opener=None) -> dict:
    _refuse(scope.check_promql(expr, namespace))
    params = {"query": expr, "time": f"{at_ms / 1000:.3f}"}
    return _data(_get(prometheus_url() + "/api/v1/query", params, opener))


# ---------------------------------------------------------------------------------- Grafana frames


def _num(v):
    """A Prometheus/Loki sample value ("1.5", "NaN", "+Inf") as a float; NaN becomes None."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def _series_frames(result: list, single: bool) -> list[dict]:
    frames = []
    for s in result or []:
        labels = s.get("metric") or {}
        points = [s["value"]] if single and "value" in s else (s.get("values") or [])
        times = [int(float(p[0]) * 1000) for p in points]
        vals = [_num(p[1]) for p in points]
        frames.append({"schema": {"fields": [{"name": "Time", "type": "time"},
                                             {"name": "Value", "type": "number", "labels": labels}]},
                       "data": {"values": [times, vals]}})
    return frames


def _stream_frame(result: list) -> dict:
    labels, times, lines, ts_ns = [], [], [], []
    for s in result or []:
        stream = s.get("stream") or {}
        for ts, line in s.get("values") or []:
            labels.append(stream)
            times.append(int(ts) // 1_000_000)
            lines.append(line)
            ts_ns.append(str(ts))
    return {"schema": {"meta": {"type": "log-lines"},
                       "fields": [{"name": "labels", "type": "other"}, {"name": "Time", "type": "time"},
                                  {"name": "Line", "type": "string"}, {"name": "tsNs", "type": "string"}]},
            "data": {"values": [labels, times, lines, ts_ns]}}


def to_frames(data: dict) -> dict:
    """Loki/Prometheus `data` as Grafana's /api/ds/query response for refId A."""
    rtype = data.get("resultType")
    result = data.get("result") or []
    if rtype == "streams":
        frames = [_stream_frame(result)] if result else []
    elif rtype in ("matrix", "vector"):
        frames = _series_frames(result, single=rtype == "vector")
    elif rtype == "scalar":
        frames = _series_frames([{"metric": {}, "value": result}], single=True) if result else []
    else:
        raise TelemetryError(f"unexpected resultType {rtype!r}")
    return {"results": {"A": {"status": 200, "frames": frames}}}


def query(kind: str, expr: str, start_ms: int, end_ms: int, namespace: str = scope.NAMESPACE,
          opener=None) -> dict:
    """Drop-in for `grafana.query` without the URL and token: same checks, same response shape."""
    bad = scope.check_query(kind, expr, namespace)
    if bad:
        raise TelemetryError(f"out of scope: {bad}")
    if kind == "logql":
        data = loki_query_range(expr, start_ms, end_ms, limit=MAX_LINES, namespace=namespace, opener=opener)
    else:
        data = prom_query_range(expr, start_ms, end_ms, namespace=namespace, opener=opener)
    return to_frames(data)
