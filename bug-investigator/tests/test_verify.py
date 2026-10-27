import json
from pathlib import Path

import pytest

from bug_investigator import verify as V
from bug_investigator.grafana import count_results, explore_link, query_body
from bug_investigator.util import CommandError, scrub_text
from conftest import FakeGh

LOG_FRAME = {"schema": {"fields": [{"name": "labels", "type": "other"}, {"name": "Time", "type": "time"},
                                   {"name": "Line", "type": "string"}]},
             "data": {"values": [[{}, {}, {}], [1, 2, 3], ["a", "b", "c"]]}}
ZERO_SERIES = {"schema": {"fields": [{"name": "Time", "type": "time"}, {"name": "Value", "type": "number"}]},
               "data": {"values": [[1, 2, 3], [0, 0, 0]]}}
SERIES = {"schema": {"fields": [{"name": "Time", "type": "time"}, {"name": "Value", "type": "number"}]},
          "data": {"values": [[1, 2, 3], [0, 0.5, 2]]}}


def resp(*frames):
    return {"results": {"A": {"frames": list(frames)}}}


class FakeGrafana:
    def __init__(self):
        self.calls = []

    def __call__(self, kind, expr, start, end):
        self.calls.append((kind, expr, start, end))
        if "permission_denied" in expr and kind == "logql":
            return resp(LOG_FRAME)
        if "permission_denied" in expr:
            return resp(SERIES)
        if "zero" in expr:
            return resp(ZERO_SERIES)
        return resp()


GH = {
    ("gh", "pr", "view", "14"): {"number": 14, "state": "MERGED", "mergedAt": "2026-10-27T09:10:00Z",
                                 "title": "Centralize permission checks", "url": "https://github.com/o/app/pull/14"},
    ("gh", "pr", "view", "15"): {"number": 15, "state": "OPEN", "mergedAt": None, "title": "WIP", "url": "u"},
    ("gh", "pr", "view"): CommandError("not found"),
    ("gh", "issue", "view", "3"): {"number": 3, "state": "CLOSED", "title": "Old bug", "url": "https://github.com/o/app/issues/3", "labels": []},
    ("gh", "issue", "view", "7"): {"number": 7, "state": "OPEN", "title": "This bug", "url": "u7", "labels": []},
    ("gh", "issue", "view", "50"): {"number": 50, "state": "CLOSED", "title": "Rehearsal", "url": "u50",
                                    "labels": [{"name": "rehearsal"}]},
    ("gh", "issue", "view"): CommandError("not found"),
}


@pytest.fixture
def ctx(app_repo, deploy_repo):
    g = FakeGrafana()
    c = V.Ctx(mode="full", repo="o/app", app_dir=app_repo["dir"], deploy_dir=deploy_repo["dir"], issue=7,
              issue_created="2026-10-27T11:00:00Z", grafana_url="https://grafana.example", token="glsa_SECRETtoken123456",
              runner=FakeGh(GH), gquery=g)
    c.fake_grafana = g
    return c


def findings(app_repo, **over):
    Path(app_repo["dir"]).parent.joinpath("outside.txt").write_text("secret\n")
    f = {
        "summary": "Editors get 403 since PR #14 went live. Token glsa_SECRETtoken123456 and glsa_otherAAAAAAAAAA.",
        "verdict": "likely_cause", "confidence": "high",
        "report": {"who": "@ann", "what": "cannot complete", "when_start": "2026-10-27T09:00:00Z",
                   "when_end": "2026-10-27T11:00:00Z", "where": "PATCH /api/tasks/{id}", "expected": "200", "actual": "403"},
        "docs_rule": {"path": "docs/permissions.md", "rule_id": "P3",
                      "quote": "An editor may move a task that is assigned to them, whoever created it."},
        "likely_cause": {"change_ref": "#14", "live_since": "2026-10-27T09:32:00Z", "code_ref": "src/app.py:7",
                         "explanation": "checks created_by instead of assignee"},
        "hypotheses": [
            {"id": "H1", "statement": "PR 14 checks created_by", "test": "t", "status": "supported", "evidence_ids": ["E1", "E3", "E6"]},
            {"id": "H2", "statement": "config", "test": "t", "status": "supported", "evidence_ids": ["E7"]},
            {"id": "H3", "statement": "db", "test": "t", "status": "ruled_out", "evidence_ids": ["E2"]},
        ],
        "evidence": [
            {"id": "E1", "kind": "commit", "ref": app_repo["second"][:10], "detail": "the change"},
            {"id": "E2", "kind": "commit", "ref": "deadbeefdeadbeef", "detail": "made up"},
            {"id": "E3", "kind": "file", "ref": "src/app.py", "line": 7, "quote": "return user.name == task.created_by", "detail": "the check"},
            {"id": "E4", "kind": "file", "ref": "src/app.py", "line": 99, "quote": "x", "detail": "bad line"},
            {"id": "E5", "kind": "doc", "ref": "docs/permissions.md", "quote": "**P3** An editor may move a task", "detail": "rule"},
            {"id": "E6", "kind": "logql", "ref": '{namespace="taskboard"} |= "permission_denied"', "detail": "403s",
             "start": "2026-10-27T09:00:00Z", "end": "2026-10-27T11:00:00Z", "expect": "found"},
            {"id": "E7", "kind": "logql", "ref": '{namespace="kagent"}', "detail": "out of scope"},
            {"id": "E8", "kind": "promql", "ref": 'sum(rate(taskboard_permission_denied_total[5m]))', "detail": "x", "expect": "none"},
            {"id": "E9", "kind": "pr", "ref": "#14", "detail": "merged the refactor"},
            {"id": "E10", "kind": "pr", "ref": "#99", "detail": "nope"},
            {"id": "E11", "kind": "promql", "ref": 'sum(rate(taskboard_zero_total[5m]))', "detail": "zeros", "expect": "found"},
            {"id": "E12", "kind": "pr", "ref": "#15", "detail": "merged yesterday"},
            {"id": "E13", "kind": "file", "ref": "base-apps/taskboard/code-configmap.yaml", "repo": "deploy",
             "line": 6, "quote": "taskboard.arigsela.com/source-commit", "detail": "deploy annotation"},
            {"id": "E14", "kind": "file", "ref": "src/app.py:4", "quote": "def can_move(user, task):", "detail": "path:line form"},
            {"id": "E15", "kind": "file", "ref": "../outside.txt", "detail": "escape attempt"},
        ],
        "similar_past_bugs": [{"issue": "#3", "why": "same area"}, {"issue": "#7", "why": "itself"},
                              {"issue": "#50", "why": "rehearsal"}, {"issue": "#404", "why": "missing"}],
        "next_step": "fix it", "could_not_check": ["traces"],
    }
    f.update(over)
    return f


def by_id(out):
    return {e["id"]: e for e in out["evidence"]}


def test_verify_keeps_good_and_drops_bad(ctx, app_repo):
    out = V.verify(findings(app_repo), ctx)
    kept = by_id(out)
    assert set(kept) == {"E1", "E3", "E5", "E6", "E9", "E13", "E14"}
    dropped = {d["id"]: d["reason"] for d in out["verification"]["dropped"]}
    assert "not found" in dropped["E2"]
    assert "outside" in dropped["E4"]
    assert "out of scope" in dropped["E7"]
    assert "expected none" in dropped["E8"]
    assert "not found" in dropped["E10"]
    assert "returned nothing" in dropped["E11"]
    assert "not merged" in dropped["E12"]
    assert "not found" in dropped["E15"]
    assert out["verification"]["verified"] == 7 and out["verification"]["total"] == 15


def test_verify_links(ctx, app_repo):
    out = V.verify(findings(app_repo), ctx)
    kept = by_id(out)
    head = ctx.heads["app"]
    assert kept["E1"]["verified"]["link"] == f"https://github.com/o/app/commit/{app_repo['second']}"
    assert kept["E3"]["verified"]["link"] == f"https://github.com/o/app/blob/{head}/src/app.py#L7"
    assert kept["E5"]["verified"]["line"] == 4
    assert kept["E13"]["verified"]["link"].startswith(f"https://github.com/arigsela/kubernetes/blob/{ctx.heads['deploy']}/")
    assert kept["E14"]["verified"]["line"] == 4
    assert kept["E6"]["verified"]["count"] == 3
    assert kept["E6"]["verified"]["link"].startswith("https://grafana.example/explore?")


def test_verify_never_sends_out_of_scope_queries(ctx, app_repo):
    V.verify(findings(app_repo), ctx)
    exprs = [c[1] for c in ctx.fake_grafana.calls]
    assert '{namespace="kagent"}' not in exprs
    assert all("taskboard" in e for e in exprs)


def test_hypotheses_and_verdict(ctx, app_repo):
    out = V.verify(findings(app_repo), ctx)
    h = {x["id"]: x for x in out["hypotheses"]}
    assert h["H1"]["status"] == "supported" and h["H1"]["evidence_ids"] == ["E1", "E3", "E6"]
    assert h["H2"]["status"] == "untested" and h["H2"]["evidence_ids"] == []
    assert h["H3"]["status"] == "untested"
    assert out["verdict"] == "likely_cause"
    assert out["likely_cause"]["change_verified"]["number"] == 14
    assert out["likely_cause"]["code_verified"]["line"] == 7
    assert out["docs_rule"]["verified"]["line"] == 4


def test_likely_cause_without_support_becomes_unclear(ctx, app_repo):
    f = findings(app_repo)
    f["hypotheses"] = [{"id": "H1", "statement": "s", "test": "t", "status": "supported", "evidence_ids": ["E2"]}]
    out = V.verify(f, ctx)
    assert out["verdict"] == "unclear"
    assert out["likely_cause"]["unconfirmed"] is True


def test_bad_docs_rule_and_cause_dropped(ctx, app_repo):
    f = findings(app_repo, docs_rule={"path": "docs/permissions.md", "rule_id": "P3", "quote": "Editors may do anything"},
                 likely_cause={"change_ref": "#99", "live_since": "", "code_ref": "src/nope.py:1", "explanation": "x"})
    out = V.verify(f, ctx)
    assert out["docs_rule"] is None
    assert out["likely_cause"] is None
    assert out["verdict"] == "unclear"


def test_not_a_bug_needs_a_verified_docs_rule(ctx, app_repo):
    bad = findings(app_repo, verdict="not_a_bug", likely_cause=None,
                   docs_rule={"path": "docs/permissions.md", "rule_id": "P9", "quote": "Editors may never complete tasks"})
    out = V.verify(bad, ctx)
    assert out["docs_rule"] is None and out["verdict"] == "unclear"
    assert any(d["id"] == "verdict" and "docs_rule" in d["reason"] for d in out["verification"]["dropped"])
    good = findings(app_repo, verdict="not_a_bug", likely_cause=None)
    out = V.verify(good, ctx)
    assert out["verdict"] == "not_a_bug" and out["docs_rule"]["verified"]["line"] == 4
    missing = findings(app_repo, verdict="not_a_bug", likely_cause=None, docs_rule=None)
    assert V.verify(missing, ctx)["verdict"] == "unclear"


def test_past_bugs(ctx, app_repo):
    out = V.verify(findings(app_repo), ctx)
    assert [b["verified"]["number"] for b in out["similar_past_bugs"]] == [3]


def test_scrub(ctx, app_repo):
    out = V.verify(findings(app_repo), ctx)
    text = json.dumps(out)
    assert "glsa_" not in text and "SECRETtoken" not in text


def test_n8n_mode_has_no_telemetry(app_repo):
    c = V.Ctx(mode="n8n", repo="o/app", app_dir=app_repo["dir"], issue=7, runner=FakeGh(GH),
              gquery=lambda *a: pytest.fail("no Grafana in n8n mode"))
    f = findings(app_repo)
    out = V.verify(f, c)
    dropped = {d["id"]: d["reason"] for d in out["verification"]["dropped"]}
    assert "not available" in dropped["E6"]
    assert "E13" in dropped  # no deploy checkout in n8n mode


def test_placeholder_when_no_findings(ctx):
    f, problem = V.load_findings(None, "")
    assert f is None and "no structured findings" in problem
    out = V.verify(V.placeholder(problem), ctx)
    assert out["verdict"] == "unclear" and out["verification"]["total"] == 0
    assert V.load_findings(None, "not json")[0] is None
    assert V.load_findings(None, "[]")[0] is None


def test_default_window_is_report_window_padded(ctx, app_repo):
    f = findings(app_repo, evidence=[{"id": "E1", "kind": "logql", "ref": '{namespace="taskboard"} |= "permission_denied"', "detail": "x"}],
                 hypotheses=[])
    out = V.verify(f, ctx)
    v = out["evidence"][0]["verified"]
    assert v["start"] == "2026-10-27T07:00:00Z" and v["end"] == "2026-10-27T13:00:00Z"


def test_window_capped_at_24h(ctx, app_repo):
    f = findings(app_repo, evidence=[{"id": "E1", "kind": "logql", "ref": '{namespace="taskboard"} |= "permission_denied"',
                                      "detail": "x", "start": "2026-10-01T00:00:00Z", "end": "2026-10-27T00:00:00Z"}],
                 hypotheses=[])
    out = V.verify(f, ctx)
    v = out["evidence"][0]["verified"]
    assert v["start"] == "2026-10-26T00:00:00Z"


# ------------------------------------------------------------------------------ grafana helpers


def test_count_results():
    assert count_results(resp(LOG_FRAME)) == 3
    assert count_results(resp(ZERO_SERIES)) == 0
    assert count_results(resp(SERIES)) == 2
    assert count_results(resp()) == 0
    assert count_results({}) == 0


def test_query_body_and_link():
    b = query_body("logql", '{namespace="taskboard"}', 1000, 2000)
    assert b["from"] == "1000" and b["queries"][0]["datasource"] == {"uid": "loki", "type": "loki"}
    assert b["queries"][0]["queryType"] == "range"
    p = query_body("promql", "taskboard_tasks", 1000, 2000)["queries"][0]
    assert p["datasource"]["uid"] == "PBFA97CFB590B2093" and p["range"] is True
    link = explore_link("https://g", "promql", "taskboard_tasks", 1000, 2000)
    assert link.startswith("https://g/explore?schemaVersion=1&orgId=1&panes=%7B%22a%22")
    assert "(" not in link and ")" not in link


def test_grafana_query_rejects_out_of_scope():
    from bug_investigator import grafana
    with pytest.raises(grafana.GrafanaError, match="out of scope"):
        grafana.query("https://g", "t", "promql", "up", 0, 1, opener=lambda *a, **k: pytest.fail("no HTTP"))


def test_grafana_query_http(monkeypatch):
    from bug_investigator import grafana
    seen = {}

    class R:
        def __init__(self, body):
            self.body = body

        def read(self):
            return json.dumps(self.body).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def opener(req, timeout):
        seen["url"] = req.full_url
        seen["auth"] = req.headers["Authorization"]
        seen["body"] = json.loads(req.data)
        return R(resp(LOG_FRAME))

    out = grafana.query("https://g/", "tok", "logql", '{namespace="taskboard"}', 1, 2, opener=opener)
    assert count_results(out) == 3
    assert seen["url"] == "https://g/api/ds/query" and seen["auth"] == "Bearer tok"
    assert seen["body"]["queries"][0]["expr"] == '{namespace="taskboard"}'


@pytest.mark.parametrize("body,expect", [
    (b'{"message": "bad query: parse error"}', "HTTP 400 bad query: parse error"),
    (b"<html>gateway</html>", "HTTP 400 <html>gateway</html>"),
    (b"", "HTTP 400"),
])
def test_grafana_http_error_detail(body, expect):
    import io
    import urllib.error

    from bug_investigator import grafana

    def opener(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 400, "Bad Request", {}, io.BytesIO(body))

    with pytest.raises(grafana.GrafanaError) as e:
        grafana.query("https://g", "t", "logql", '{namespace="taskboard"}', 1, 2, opener=opener)
    assert str(e.value) == expect


def test_grafana_error_drops_item_with_reason(ctx, app_repo):
    from bug_investigator import grafana

    def failing(*a):
        raise grafana.GrafanaError("HTTP 502 upstream")

    ctx.gquery = failing
    out = V.verify(findings(app_repo), ctx)
    dropped = {d["id"]: d["reason"] for d in out["verification"]["dropped"]}
    assert dropped["E6"] == "Grafana query failed: HTTP 502 upstream"


def test_scrub_text_keeps_shas_and_metric_names():
    sha = "a" * 40
    s = f"commit {sha} metric taskboard_http_request_duration_seconds_bucket_long_name_here ok"
    assert scrub_text(s) == s
    assert "[redacted]" in scrub_text("Authorization: Bearer abcdefghijklmnop")
    assert "[redacted]" in scrub_text("key sk-ant-api03-abcdefghijkl")
    assert "[redacted]" in scrub_text("ghs_abcdefghijklmnopqrstuv")
    assert "[redacted]" in scrub_text("blob QWxhZGRpbjpvcGVuIHNlc2FtZQ1234567890abcdefghijklmnopq")
