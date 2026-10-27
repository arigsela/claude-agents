import io
import json
import os

import pytest

from bug_investigator import hook, scope
from bug_investigator.scope import check_bash, check_logql, check_path_tool, check_promql, check_tool_call

LOKI = "loki"
PROM = "PBFA97CFB590B2093"

# ------------------------------------------------------------------------------ LogQL

LOGQL_ALLOWED = [
    '{namespace="taskboard"}',
    '{namespace="taskboard"} | json | level="ERROR"',
    '{ namespace = "taskboard" , app="taskboard" }',
    'count_over_time({namespace="taskboard", app="taskboard"} |= "permission_denied" [10m])',
    'sum by (rule) (count_over_time({namespace="taskboard"} | json | msg="permission_denied" [5m]))',
    '{namespace="taskboard"} | json | line_format "{{.msg}} {{.user}}"',
    '{namespace="taskboard"} | line_format "{namespace=\\"kagent\\"}"',
    '{namespace="taskboard", app=~"taskboard.*"} |~ `no such column` | json | status >= 500',
    'sum(rate({namespace="taskboard"}[5m])) / sum(rate({namespace="taskboard", app="taskboard"}[5m]))',
    '{namespace=`taskboard`} != "healthz"',
    'quantile_over_time(0.99, {namespace="taskboard"} | json | unwrap duration_ms [5m]) by (route)',
    '{namespace="taskboard"} | json | label_format who=`{{.user}}` | drop stack',
    'sum(count_over_time({namespace="taskboard"} | json | level="ERROR" [1m])) or vector(0)',
    '{namespace="taskboard"} | json | user="ann" or role="viewer"',
    '{namespace="taskboard"} | logfmt --strict | duration > 1.5s',
]

LOGQL_REJECTED = [
    '{namespace="kagent"}',
    '{namespace=~"task.*"}',
    '{namespace=~"taskboard"}',
    '{namespace!="x"}',
    '{namespace!~"x"}',
    '{app="taskboard"}',
    '{}',
    'vector(1)',
    '',
    '   ',
    'sum(rate({namespace="taskboard"}[5m])) / sum(rate({namespace="other"}[5m]))',
    'sum(rate({namespace="taskboard"}[5m])) or sum(rate({app="x"}[5m]))',
    '{namespace="taskboard", namespace=~".+"}',
    '{namespace="taskboard", namespace="kagent"}',
    '{namespace="kagent"} | line_format "{namespace=\\"taskboard\\"}"',
    '{namespace="kagent"} |= "{namespace=\\"taskboard\\"}"',
    '{namespace="taskboard"} # comment\n or {namespace="kagent"}',
    "{namespace='taskboard'}",
    '{namespace="taskboard"} |= \'x {namespace="kagent"} y\'',
    '{namespace="task\\x62oard"}',
    '{namespace="taskboard"',
    '{namespace="taskboard"}}',
    '{namespace="taskboard" app="x"}',
    '{namespace}',
    '{"namespace"="taskboard"}',
    '{namespace="taskboard"} |= "unterminated',
    '{namespace="taskboard"} | json | line_format "ok"  ',
    "x" * 5000,
    None,
    42,
]


@pytest.mark.parametrize("q", LOGQL_ALLOWED)
def test_logql_allowed(q):
    assert check_logql(q) is None


@pytest.mark.parametrize("q", LOGQL_REJECTED)
def test_logql_rejected(q):
    assert check_logql(q) is not None


def test_logql_reason_names_the_selector():
    assert 'namespace="taskboard"' in check_logql('{app="taskboard"}')


# ------------------------------------------------------------------------------ PromQL

PROMQL_ALLOWED = [
    'sum by (rule) (rate(taskboard_permission_denied_total[5m]))',
    'rate(container_cpu_usage_seconds_total{namespace="taskboard"}[5m])',
    'taskboard_tasks',
    'taskboard_tasks{status="done"}',
    'sum(rate(taskboard_http_requests_total{status=~"5.."}[5m])) by (route)',
    'histogram_quantile(0.99, sum by (le, route) (rate(taskboard_http_request_duration_seconds_bucket[5m])))',
    'sum(rate(taskboard_http_requests_total{status=~"5.."}[5m])) / sum(rate(taskboard_http_requests_total[5m]))',
    'kube_pod_container_status_restarts_total{namespace="taskboard"} offset 1h',
    'increase(taskboard_tasks_archived_total[1h] offset -5m)',
    'max_over_time(taskboard_tasks{status="done"}[1h:5m])',
    'taskboard_build_info{commit!=""}',
    'count({__name__=~".+", namespace="taskboard"}) by (__name__)',
    'taskboard_tasks{status="done"} - taskboard_tasks{status="done"} offset 1d',
    'rate(taskboard_http_requests_total[5m]) > bool 0',
    'taskboard_tasks * on (pod) group_left (node) kube_pod_info{namespace="taskboard"}',
    'taskboard_tasks * on (pod) group_left kube_pod_info{namespace="taskboard"}',
    'sum without (instance) (taskboard_tasks)',
    'label_replace(taskboard_tasks, "x", "$1", "status", "(.*)")',
    'topk(5, taskboard_http_requests_total) and taskboard_http_requests_total > 1e3',
    'taskboard_tasks @ 1609746000',
    'taskboard_tasks @ end()',
    "taskboard_tasks{status='done'}",
    'sum(taskboard_tasks) or vector(0)',
    'taskboard_tasks > Inf',
]

PROMQL_REJECTED = [
    'up',
    'sum(rate(container_cpu_usage_seconds_total[5m]))',
    '{__name__=~".+"}',
    '{namespace="taskboard"} or {namespace="kagent"}',
    'rate(container_cpu_usage_seconds_total{namespace="kagent"}[5m])',
    'rate(container_cpu_usage_seconds_total{namespace=~"task.*"}[5m])',
    'rate(container_cpu_usage_seconds_total{namespace!="x"}[5m])',
    'taskboard_tasks{namespace="kagent"}',
    'taskboard_tasks{namespace=~".*"}',
    'sum(taskboard_tasks) / sum(kube_pod_info)',
    'taskboard_tasks * on (pod) group_left kube_pod_info',
    'absent(nonexistent_metric{job="x"})',
    '{job="x"}',
    'vector(1)',
    'time()',
    'info(taskboard_tasks, {k8s_cluster_name=~".+"})',
    'unknownfn(taskboard_tasks)',
    'sum by taskboard_tasks',
    'taskboard_tasks[5m] offset x',
    '{"some.metric", namespace="taskboard"}',
    'taskboard_tasks # comment\n or up',
    'taskboard_tasks + {namespace="taskboard"',
    'taskboard_tasks[5m',
    'rate(taskboard_tasks[foo])',
    'taskboard_tasks + rate',
    '',
    None,
]


@pytest.mark.parametrize("q", PROMQL_ALLOWED)
def test_promql_allowed(q):
    assert check_promql(q) is None


@pytest.mark.parametrize("q", PROMQL_REJECTED)
def test_promql_rejected(q):
    assert check_promql(q) is not None


def test_other_namespace_parameter():
    assert check_promql('up{namespace="kagent"}', namespace="kagent") is None
    assert check_promql('up{namespace="kagent"}') is not None


# ------------------------------------------------------------------------------ tool calls


def test_tool_calls_allowed():
    assert check_tool_call("mcp__grafana__query_loki_logs", {
        "datasourceUid": LOKI, "logql": '{namespace="taskboard"} | json',
        "startRfc3339": "2026-10-27T10:00:00Z", "endRfc3339": "2026-10-27T11:00:00Z", "limit": 50}) is None
    assert check_tool_call("mcp__grafana__query_loki_stats", {
        "datasourceUid": LOKI, "logql": '{namespace="taskboard"}'}) is None
    assert check_tool_call("mcp__grafana__query_prometheus", {
        "datasourceUid": PROM, "expr": "rate(taskboard_http_requests_total[5m])",
        "endTime": "now", "startTime": "now-1h", "stepSeconds": 60, "queryType": "range"}) is None
    assert check_tool_call("mcp__grafana__list_loki_label_values", {
        "datasourceUid": LOKI, "labelName": "app", "matcher": '{namespace="taskboard"}'}) is None
    assert check_tool_call("list_loki_label_names", {
        "datasourceUid": LOKI, "matcher": '{namespace="taskboard", app="taskboard"}'}) is None
    assert check_tool_call("mcp__grafana__query_prometheus", {
        "datasourceUid": PROM, "expr": "taskboard_tasks", "endTime": "now", "projectName": ""}) is None


@pytest.mark.parametrize("tool,inp", [
    ("mcp__grafana__query_loki_logs", {"datasourceUid": LOKI, "logql": '{namespace="kagent"}'}),
    ("mcp__grafana__query_loki_logs", {"datasourceUid": "other-loki", "logql": '{namespace="taskboard"}'}),
    ("mcp__grafana__query_loki_logs", {"datasourceUid": PROM, "logql": '{namespace="taskboard"}'}),
    ("mcp__grafana__query_loki_logs", {"logql": '{namespace="taskboard"}'}),
    ("mcp__grafana__query_loki_logs", {"datasourceUid": LOKI, "logql": '{namespace="taskboard"}', "orgId": 2}),
    ("mcp__grafana__query_prometheus", {"datasourceUid": LOKI, "expr": "taskboard_tasks", "endTime": "now"}),
    ("mcp__grafana__query_prometheus", {"datasourceUid": PROM, "expr": "up", "endTime": "now"}),
    ("mcp__grafana__query_prometheus", {"datasourceUid": PROM, "expr": "taskboard_tasks", "endTime": "now", "projectName": "p"}),
    ("mcp__grafana__list_loki_label_values", {"datasourceUid": LOKI, "labelName": "namespace"}),
    ("mcp__grafana__list_loki_label_values", {"datasourceUid": LOKI, "labelName": "namespace", "matcher": ""}),
    ("mcp__grafana__list_loki_label_values", {"datasourceUid": LOKI, "labelName": "app", "matcher": '{app="x"}'}),
    ("mcp__grafana__list_loki_label_names", {"datasourceUid": LOKI, "matcher": '{namespace="taskboard"} |= "x"'}),
    ("mcp__grafana__list_loki_label_names", {"datasourceUid": LOKI}),
    ("mcp__grafana__list_prometheus_metric_names", {"datasourceUid": PROM, "regex": ".*"}),
    ("mcp__grafana__list_prometheus_label_values", {"datasourceUid": PROM, "labelName": "namespace"}),
    ("mcp__grafana__search_tempo_traces", {"datasourceUid": "tempo", "query": "{}"}),
    ("mcp__grafana__query_loki_patterns", {"datasourceUid": LOKI, "logql": '{namespace="taskboard"}'}),
    ("mcp__grafana__list_datasources", {}),
    ("mcp__grafana__search_dashboards", {"query": ""}),
    ("mcp__grafana__grafana_api_request", {"path": "/api/ds/query"}),
    ("mcp__github__get_issue", {}),
    ("mcp__grafana__query_loki_logs", "not a dict"),
    (None, {}),
])
def test_tool_calls_rejected(tool, inp):
    assert check_tool_call(tool, inp) is not None


# ------------------------------------------------------------------------------ Bash


@pytest.fixture
def roots(tmp_path):
    app = tmp_path / "app"
    deploy = tmp_path / "deploy"
    app.mkdir()
    deploy.mkdir()
    return [str(app), str(deploy)]


@pytest.mark.parametrize("cmd", [
    "git log --oneline -20",
    "git log -p --since=2026-10-20 -- src/app.py",
    "git log --format='%H %an %s' main..HEAD",
    "git show abc1234",
    "git show HEAD~3:src/app.py",
    "git blame -L 40,60 src/app.py",
    "git diff abc123...def456 -- src",
    "gh pr view 12 --json title,body,reviews,comments",
    "gh pr list --state merged --limit 20",
    "gh pr diff 12",
    "gh issue view 3 --comments",
    "gh issue list --state closed --label bug",
    "gh pr list --json number,title --jq '.[] | {n: .number}'",
    "git log --oneline",
])
def test_bash_allowed(cmd, roots):
    assert check_bash(cmd, roots) is None


def test_bash_git_dash_c_deploy(roots):
    assert check_bash(f"git -C {roots[1]} log --oneline", roots) is None
    assert check_bash("git -C /etc log", roots) is not None


@pytest.mark.parametrize("cmd", [
    "cat /etc/passwd",
    "git log; cat /etc/passwd",
    "git log && env",
    "git log | head",
    "git log > /tmp/x",
    "git log $(cat x)",
    "git log `cat x`",
    'git log "$HOME"',
    "git log --output=/tmp/hook.py",
    "git log --outp=/tmp/hook.py",
    "git log --format=x --output /tmp/hook.py",
    "git show --output=x HEAD",
    "git diff --no-index a b",
    "git diff --no-ind a b",
    "git diff /home/runner/work/_temp/token /dev/null",
    "git diff ../secret x",
    "git diff a/../../secret x",
    "git diff ~/secret x",
    "git diff {/etc/passwd,x}",
    "git diff \\/etc/passwd x",
    "git blame --contents /home/runner/x src/app.py",
    "git blame --con /home/runner/x src/app.py",
    "git blame -S revs src/app.py",
    "git blame -Srevs src/app.py",
    "git blame --ignore-revs-file x src/app.py",
    "git log -p --ext-diff",
    "git -c core.pager=sh log",
    "git --git-dir=/x log",
    "git push",
    "git checkout main",
    "gh api repos/x/y",
    "gh search issues x",
    "gh issue comment 3 --body x",
    "gh issue edit 3 --add-label x",
    "gh pr view 3 --web",
    "gh pr merge 3",
    "git log\nenv",
    "git log 'unbalanced",
    "",
    None,
])
def test_bash_rejected(cmd, roots):
    assert check_bash(cmd, roots) is not None


def test_bash_rejected_in_n8n_mode(roots):
    assert check_bash("git log", roots, mode="n8n") is not None


# ------------------------------------------------------------------------------ paths


def test_path_tools(roots, tmp_path):
    app, deploy = roots
    (tmp_path / "app" / "src").mkdir()
    (tmp_path / "app" / "src" / "x.py").write_text("x")
    (tmp_path / "secret").write_text("glsa_abc")
    os.symlink(tmp_path / "secret", tmp_path / "app" / "link")
    assert check_path_tool("Read", {"file_path": f"{app}/src/x.py"}, roots) is None
    assert check_path_tool("Read", {"file_path": "src/x.py"}, roots) is None
    assert check_path_tool("Grep", {"pattern": "x", "path": deploy}, roots) is None
    assert check_path_tool("Grep", {"pattern": "x"}, roots) is None
    assert check_path_tool("Glob", {"pattern": "**/*.py"}, roots) is None
    assert check_path_tool("Read", {"file_path": str(tmp_path / "secret")}, roots) is not None
    assert check_path_tool("Read", {"file_path": f"{app}/link"}, roots) is not None
    assert check_path_tool("Read", {"file_path": f"{app}/../secret"}, roots) is not None
    assert check_path_tool("Read", {"file_path": "/home/runner/work/_actions/x/answer.md"}, roots) is not None
    assert check_path_tool("Grep", {"pattern": "x", "path": "/"}, roots) is not None
    assert check_path_tool("Glob", {"pattern": "/home/**"}, roots) is not None
    assert check_path_tool("Glob", {"pattern": "../**"}, roots) is not None
    assert check_path_tool("Glob", {"pattern": "*", "path": str(tmp_path)}, roots) is not None


# ------------------------------------------------------------------------------ hook


def run_hook(payload, mode="full", roots=("/nonexistent/app",)):
    args = ["--mode", mode]
    for r in roots:
        args += ["--root", r]
    stdin = io.StringIO(payload if isinstance(payload, str) else json.dumps(payload))
    return hook.main(args, stdin=stdin)


def test_hook_allows_scoped_query():
    assert run_hook({"tool_name": "mcp__grafana__query_loki_logs", "tool_input": {
        "datasourceUid": "loki", "logql": '{namespace="taskboard"} | json'}}) == 0


def test_hook_blocks_unscoped_query(capsys):
    assert run_hook({"tool_name": "mcp__grafana__query_prometheus", "tool_input": {
        "datasourceUid": PROM, "expr": "up", "endTime": "now"}}) == 2
    assert "namespace" in capsys.readouterr().err


def test_hook_blocks_other_tools_and_modes():
    assert run_hook({"tool_name": "mcp__grafana__search_tempo_traces", "tool_input": {}}) == 2
    assert run_hook({"tool_name": "mcp__grafana__query_loki_logs", "tool_input": {
        "datasourceUid": "loki", "logql": '{namespace="taskboard"}'}}, mode="n8n") == 2
    assert run_hook({"tool_name": "Bash", "tool_input": {"command": "git log"}}, mode="n8n") == 2
    assert run_hook({"tool_name": "Bash", "tool_input": {"command": "env"}}) == 2


def test_hook_fails_closed(capsys):
    assert run_hook("not json") == 2
    assert run_hook("[]") == 2
    assert "hook error" in capsys.readouterr().err


def test_hook_passes_unrelated_tools():
    assert run_hook({"tool_name": "StructuredOutput", "tool_input": {"summary": "x"}}) == 0


def test_hook_as_subprocess(tmp_path):
    """The exact command the settings file runs: python3 -I run.py hook ..."""
    import subprocess
    import sys

    run_py = os.path.join(os.path.dirname(__file__), "..", "run.py")
    bad = json.dumps({"tool_name": "mcp__grafana__query_prometheus", "tool_input": {
        "datasourceUid": PROM, "expr": 'sum(rate(container_cpu_usage_seconds_total[5m]))', "endTime": "now"}})
    good = json.dumps({"tool_name": "mcp__grafana__query_prometheus", "tool_input": {
        "datasourceUid": PROM, "expr": "taskboard_tasks", "endTime": "now"}})
    r = subprocess.run([sys.executable, "-I", run_py, "hook", "--root", str(tmp_path)], input=bad,
                       capture_output=True, text=True, cwd=tmp_path)
    assert r.returncode == 2 and "Blocked" in r.stderr
    r = subprocess.run([sys.executable, "-I", run_py, "hook", "--root", str(tmp_path)], input=good,
                       capture_output=True, text=True, cwd=tmp_path)
    assert r.returncode == 0, r.stderr


def test_scope_constants():
    assert scope.LOKI_UID == "loki" and scope.PROM_UID == PROM
