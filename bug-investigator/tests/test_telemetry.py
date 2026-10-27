"""telemetry.py: direct Loki/Prometheus queries with grafana.query's response shape."""

import io
import json
import math
import urllib.error
import urllib.parse

import pytest

from bug_investigator import grafana, telemetry
from bug_investigator import verify as V
from bug_investigator.grafana import count_results
from conftest import FakeGh
from test_verify import GH, by_id, findings

T0 = 1_761_555_600_000  # 2025-10-27T09:00:00Z in ms; any fixed instant works
NS = 1_000_000

LOKI_STREAMS = {"status": "success", "data": {"resultType": "streams", "result": [
    {"stream": {"namespace": "taskboard", "app": "taskboard"},
     "values": [[str((T0 + 2000) * NS), '{"msg":"permission_denied","rule":"P4"}'],
                [str((T0 + 1000) * NS), '{"msg":"permission_denied","rule":"P4"}']]},
    {"stream": {"namespace": "taskboard", "app": "taskboard-traffic"},
     "values": [[str((T0 + 1500) * NS), '{"msg":"request"}']]},
]}}
LOKI_EMPTY = {"status": "success", "data": {"resultType": "streams", "result": []}}
PROM_MATRIX = {"status": "success", "data": {"resultType": "matrix", "result": [
    {"metric": {"route": "/api/tasks"}, "values": [[T0 / 1000, "0"], [T0 / 1000 + 15, "0.5"], [T0 / 1000 + 30, "NaN"]]},
    {"metric": {"route": "/api/tasks/{id}"}, "values": [[T0 / 1000, "2"], [T0 / 1000 + 15, "+Inf"]]},
]}}
PROM_ZEROS = {"status": "success", "data": {"resultType": "matrix", "result": [
    {"metric": {}, "values": [[T0 / 1000, "0"], [T0 / 1000 + 15, "0"]]}]}}


class Resp:
    def __init__(self, body):
        self.body = body

    def read(self):
        return json.dumps(self.body).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class Opener:
    def __init__(self, body):
        self.body, self.calls = body, []

    def __call__(self, req, timeout):
        u = urllib.parse.urlsplit(req.full_url)
        self.calls.append((u.scheme + "://" + u.netloc + u.path, dict(urllib.parse.parse_qsl(u.query)), req.get_method()))
        return Resp(self.body)


def no_http(*a, **k):
    pytest.fail("no HTTP call expected")


# ---------------------------------------------------------------------------------- shape parity


def test_logql_frames_count_like_grafana():
    out = telemetry.query("logql", '{namespace="taskboard"} |= "permission_denied"', T0, T0 + 60_000,
                          opener=Opener(LOKI_STREAMS))
    frames = out["results"]["A"]["frames"]
    assert len(frames) == 1
    names = [f["name"] for f in frames[0]["schema"]["fields"]]
    assert names[:3] == ["labels", "Time", "Line"] and frames[0]["schema"]["meta"]["type"] == "log-lines"
    assert count_results(out) == 3
    assert frames[0]["data"]["values"][1] == [T0 + 2000, T0 + 1000, T0 + 1500]  # Time in ms, like Grafana
    assert count_results(telemetry.query("logql", '{namespace="taskboard"}', T0, T0 + 1, opener=Opener(LOKI_EMPTY))) == 0


def test_promql_frames_count_like_grafana():
    out = telemetry.query("promql", 'sum by (route) (rate(taskboard_http_requests_total[5m]))', T0, T0 + 60_000,
                          opener=Opener(PROM_MATRIX))
    frames = out["results"]["A"]["frames"]
    assert len(frames) == 2
    assert [f["type"] for f in frames[0]["schema"]["fields"]] == ["time", "number"]
    assert frames[0]["schema"]["fields"][1]["labels"] == {"route": "/api/tasks"}
    assert frames[0]["data"]["values"][0] == [T0, T0 + 15_000, T0 + 30_000]
    assert frames[0]["data"]["values"][1][2] is None  # NaN never counts
    assert count_results(out) == 3  # 0.5, 2, +Inf
    assert math.isinf(frames[1]["data"]["values"][1][1])
    assert count_results(telemetry.query("promql", "taskboard_tasks", T0, T0 + 1, opener=Opener(PROM_ZEROS))) == 0


def test_same_shape_as_grafana_query():
    """verify only reads results.A.frames[].schema.fields / data.values: the same keys Grafana returns."""
    out = telemetry.query("promql", "taskboard_tasks", T0, T0 + 1, opener=Opener(PROM_MATRIX))
    assert set(out) == {"results"} and set(out["results"]) == {"A"}
    for fr in out["results"]["A"]["frames"]:
        assert set(fr) == {"schema", "data"} and set(fr["data"]) == {"values"}
        assert len(fr["schema"]["fields"]) == len(fr["data"]["values"])
    json.dumps(telemetry.query("logql", '{namespace="taskboard"}', T0, T0 + 1, opener=Opener(LOKI_STREAMS)))


def test_requests(monkeypatch):
    monkeypatch.setenv("LOKI_URL", "http://loki.example:3100/")
    monkeypatch.setenv("PROMETHEUS_URL", "http://prom.example:9090")
    lo = Opener(LOKI_STREAMS)
    telemetry.query("logql", '{namespace="taskboard"}', T0, T0 + 3_600_000, opener=lo)
    url, params, method = lo.calls[0]
    assert url == "http://loki.example:3100/loki/api/v1/query_range" and method == "GET"
    assert params["query"] == '{namespace="taskboard"}'
    assert params["start"] == str(T0 * NS) and params["end"] == str((T0 + 3_600_000) * NS)
    assert params["limit"] == "100" and params["direction"] == "backward" and params["step"] == "15s"
    pr = Opener(PROM_MATRIX)
    telemetry.query("promql", "taskboard_tasks", T0, T0 + 86_400_000, opener=pr)
    url, params, _ = pr.calls[0]
    assert url == "http://prom.example:9090/api/v1/query_range"
    assert params["step"] == "87s"  # 24 h / 1000 points, rounded up
    assert float(params["start"]) == T0 / 1000


def test_default_urls(monkeypatch):
    monkeypatch.delenv("LOKI_URL", raising=False)
    monkeypatch.delenv("PROMETHEUS_URL", raising=False)
    assert telemetry.loki_url() == "http://loki.logging.svc.cluster.local:3100"
    assert telemetry.prometheus_url() == "http://prometheus.logging.svc.cluster.local:9090"


@pytest.mark.parametrize("kind,expr", [
    ("logql", '{namespace="kagent"}'), ("logql", '{app="taskboard"}'), ("promql", "up"),
    ("promql", 'sum(taskboard_tasks) / sum(kube_pod_info)'), ("traceql", "{}"),
])
def test_out_of_scope_never_reaches_http(kind, expr):
    with pytest.raises(telemetry.TelemetryError, match="out of scope") as e:
        telemetry.query(kind, expr, T0, T0 + 1, opener=no_http)
    assert isinstance(e.value, grafana.GrafanaError)  # verify's existing handler catches it


@pytest.mark.parametrize("fn,args", [
    (telemetry.loki_query_range, ('{namespace="kagent"}', T0, T0 + 1)),
    (telemetry.loki_query_instant, ('{namespace="kagent"}', T0)),
    (telemetry.loki_stats, ('{app="x"}', T0, T0 + 1)),
    (telemetry.loki_label_names, ('{namespace="kagent"}', T0, T0 + 1)),
    (telemetry.loki_label_names, ('{namespace="taskboard"} |= "x"', T0, T0 + 1)),
    (telemetry.loki_label_values, ("app", '{namespace=~".+"}', T0, T0 + 1)),
    (telemetry.prom_query_range, ("up", T0, T0 + 1)),
    (telemetry.prom_query_instant, ('kube_pod_info{namespace="kagent"}', T0)),
])
def test_every_helper_checks_scope(fn, args):
    with pytest.raises(telemetry.TelemetryError, match="out of scope"):
        fn(*args, opener=no_http)


def test_label_values_rejects_odd_label_names():
    with pytest.raises(telemetry.TelemetryError, match="not a label name"):
        telemetry.loki_label_values("../../labels", '{namespace="taskboard"}', T0, T0 + 1, opener=no_http)


@pytest.mark.parametrize("body,expect", [
    (b"parse error at line 1, col 5: syntax error", "HTTP 400 parse error at line 1, col 5: syntax error"),
    (b'{"status":"error","errorType":"bad_data","error":"invalid parameter"}', "HTTP 400 invalid parameter"),
    (b"", "HTTP 400"),
])
def test_http_error_detail(body, expect):
    def opener(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 400, "Bad Request", {}, io.BytesIO(body))

    with pytest.raises(telemetry.TelemetryError) as e:
        telemetry.query("logql", '{namespace="taskboard"}', T0, T0 + 1, opener=opener)
    assert str(e.value) == expect


def test_status_error_and_unreachable():
    with pytest.raises(telemetry.TelemetryError, match="boom"):
        telemetry.query("promql", "taskboard_tasks", T0, T0 + 1, opener=Opener({"status": "error", "error": "boom"}))

    def down(req, timeout):
        raise urllib.error.URLError("connection refused")

    with pytest.raises(telemetry.TelemetryError, match="connection refused"):
        telemetry.query("promql", "taskboard_tasks", T0, T0 + 1, opener=down)


# ---------------------------------------------------------------------------------- verify --telemetry direct


def direct_ctx(app_repo, deploy_repo):
    return V.Ctx(mode="full", repo="o/app", app_dir=app_repo["dir"], deploy_dir=deploy_repo["dir"], issue=7,
                 issue_created="2026-10-27T11:00:00Z", runner=FakeGh(GH), telemetry_mode="direct")


def test_verify_direct_needs_no_token_and_links_to_grafana(app_repo, deploy_repo, monkeypatch):
    calls = []

    def fake_query(kind, expr, s, e, namespace="taskboard", opener=None):
        calls.append((kind, expr))
        if kind == "logql" and "permission_denied" in expr:
            return telemetry.to_frames(LOKI_STREAMS["data"])
        return telemetry.to_frames(PROM_ZEROS["data"])

    monkeypatch.setattr(telemetry, "query", fake_query)
    ctx = direct_ctx(app_repo, deploy_repo)
    assert ctx.token == "" and ctx.grafana_url == "https://grafana.arigsela.com"
    out = V.verify(findings(app_repo), ctx)
    kept = by_id(out)
    assert kept["E6"]["verified"]["count"] == 3
    assert kept["E6"]["verified"]["link"].startswith("https://grafana.arigsela.com/explore?")
    assert "E8" in kept  # promql expect none: all zeros
    assert all("kagent" not in e for _, e in calls)


def test_verify_direct_failure_reason(app_repo, deploy_repo, monkeypatch):
    def failing(*a, **k):
        raise telemetry.TelemetryError("HTTP 503 Loki is restarting")

    monkeypatch.setattr(telemetry, "query", failing)
    out = V.verify(findings(app_repo), direct_ctx(app_repo, deploy_repo))
    dropped = {d["id"]: d["reason"] for d in out["verification"]["dropped"]}
    assert dropped["E6"] == "Loki/Prometheus query failed: HTTP 503 Loki is restarting"


def test_verify_grafana_mode_without_token_still_skips_telemetry(app_repo, deploy_repo):
    ctx = V.Ctx(mode="full", repo="o/app", app_dir=app_repo["dir"], deploy_dir=deploy_repo["dir"], issue=7,
                runner=FakeGh(GH), gquery=no_http)
    out = V.verify(findings(app_repo), ctx)
    dropped = {d["id"]: d["reason"] for d in out["verification"]["dropped"]}
    assert dropped["E6"] == "telemetry is not available in this run"


def test_verify_rejects_unknown_telemetry_mode(app_repo, deploy_repo):
    with pytest.raises(ValueError):
        V.Ctx(mode="full", repo="o/app", app_dir=app_repo["dir"], runner=FakeGh(GH), telemetry_mode="datadog")


def test_verify_cli_flag(tmp_path, app_repo, monkeypatch):
    seen = {}

    class Spy(V.Ctx):
        def __init__(self, **kw):
            seen.update(kw)
            super().__init__(**kw, runner=FakeGh(GH))

    monkeypatch.setattr(V, "Ctx", Spy)
    f = tmp_path / "f.json"
    f.write_text(json.dumps(findings(app_repo)))
    monkeypatch.setattr(telemetry, "query", lambda *a, **k: telemetry.to_frames(LOKI_EMPTY["data"]))
    rc = V.main(["--mode", "full", "--findings", str(f), "--repo", "o/app", "--issue", "7",
                 "--app-dir", app_repo["dir"], "--telemetry", "direct", "--out", str(tmp_path / "v.json")])
    assert rc == 0 and seen["telemetry_mode"] == "direct"
    assert json.loads((tmp_path / "v.json").read_text())["verification"]["total"] == 15
