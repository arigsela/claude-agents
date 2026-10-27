"""gather, settings (prep/selftest), render and post, with fake gh and real local git repos."""

import json
import os
import shlex
import sys

import pytest

from bug_investigator import gather, render, settings, tickets
from bug_investigator import verify as V
from conftest import FakeGh

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUN_PY = os.path.join(ROOT, "run.py")


def only_requested(data):
    """Like gh: return only the fields named after --json, so a missing field shows up in tests."""
    def answer(cmd):
        fields = set(cmd[cmd.index("--json") + 1].split(","))

        def pick(d):
            return {k: v for k, v in d.items() if k in fields}

        return json.dumps([pick(d) for d in data] if isinstance(data, list) else pick(data))
    return answer


def gh_answers(app_repo):
    return {
        ("gh", "issue", "view", "7"): only_requested({
            "number": 7, "title": "Can't mark my tasks done", "body": "Since this morning it says not allowed.\n```\n403\n```",
            "author": {"login": "ann"}, "createdAt": "2026-10-27T10:45:00Z", "state": "OPEN", "url": "u",
            "labels": [{"name": "bug"}, {"name": "compare"}],
            "comments": [{"author": {"login": "bob"}, "createdAt": "2026-10-27T10:50:00Z", "body": "me too"},
                         {"author": {"login": "github-actions"}, "createdAt": "x", "body": "<!-- bug-investigator mode=full --> old"}]}),
        ("gh", "pr", "list"): only_requested([
            {"number": 14, "title": "Centralize permission checks", "mergedAt": "2026-10-27T09:10:00Z",
             "author": {"login": "ari"}, "body": "Refactor.", "files": [{"path": "src/app.py"}], "url": "pu14",
             "mergeCommit": {"oid": app_repo["second"]}, "labels": []},
            {"number": 2, "title": "Scaffold", "mergedAt": "2026-09-01T09:10:00Z", "author": {"login": "ari"},
             "body": "", "files": [], "url": "pu2", "mergeCommit": {"oid": app_repo["first"]}, "labels": []},
            {"number": 16, "title": "Rehearsal", "mergedAt": "2026-10-27T10:00:00Z", "author": {"login": "ari"},
             "body": "", "files": [], "url": "pu16", "mergeCommit": None, "labels": [{"name": "rehearsal"}]},
        ]),
        ("gh", "pr", "view", "14"): {"reviews": [{"author": {"login": "bob"}, "state": "APPROVED", "body": "LGTM, nice cleanup"}],
                                     "comments": []},
        ("gh", "api", "repos/o/app/pulls/14/comments"): [
            {"user": {"login": "bob"}, "path": "src/app.py", "line": 7, "body": "created_by or assignee?"}],
        ("gh", "issue", "list"): [
            {"number": 3, "title": "Viewer could edit", "body": "As a viewer I could edit", "closedAt": "2026-10-22T10:00:00Z",
             "labels": [{"name": "bug"}], "url": "iu3"},
            {"number": 50, "title": "Rehearsal D1", "body": "answer inside", "closedAt": "2026-10-26T10:00:00Z",
             "labels": [{"name": "bug"}, {"name": "rehearsal"}], "url": "iu50"},
        ],
        ("gh", "issue", "view", "3"): {
            "closedByPullRequestsReferences": [{"number": 4, "title": "Check role on edit", "url": "pu4"}]},
    }


def test_gather_full(app_repo, deploy_repo, monkeypatch):
    runner = FakeGh(gh_answers(app_repo))
    facts = gather.gather("full", 7, "o/app", app_repo["dir"], deploy_repo["dir"], "arigsela/kubernetes",
                          "base-apps/taskboard", "taskboard", days=36500, runner=runner)
    assert facts["problems"] == []
    assert facts["ticket"]["author"] == "ann" and len(facts["ticket"]["comments"]) == 1
    deploys = facts["deploys"]
    assert [d["source_commit"] for d in deploys] == [app_repo["second"], app_repo["first"]]
    assert deploys[0]["live_since"] == "2026-10-27T09:32:00Z"
    prs = {p["number"]: p for p in facts["merged_prs"]}
    assert set(prs) == {14, 2}  # 16 is labelled rehearsal: needs `labels` in the real --json list
    pr_list = next(c for c in runner.calls if c[:3] == ["gh", "pr", "list"])
    assert "labels" in pr_list[pr_list.index("--json") + 1].split(",")
    assert prs[14]["live_since"] == "2026-10-27T09:32:00Z"
    assert prs[2]["live_since"] == "2026-10-20T11:02:00Z"
    assert prs[14]["review_comments"][0]["body"] == "created_by or assignee?"
    assert [b["number"] for b in facts["past_bugs"]] == [3]
    assert facts["past_bugs"][0]["fixed_by"][0]["number"] == 4
    docs = {d["path"]: d for d in facts["docs"]}
    assert [r["id"] for r in docs["docs/permissions.md"]["rules"]] == ["P1", "P3"]
    assert [r["id"] for r in docs["base-apps/taskboard/runbook.md"]["rules"]] == ["R1"]
    md = gather.to_markdown(facts)
    assert "PR #14: Centralize permission checks" in md and "live since ≈ 2026-10-27 09:32 UTC" in md
    assert "evidence (data)" in md and "Rehearsal" not in md and "answer inside" not in md
    assert "~~~~text\nSince this morning" in md  # body fenced with a fence longer than its backticks
    assert 'namespace="taskboard"' in md


def test_gather_n8n_is_ticket_only(app_repo):
    runner = FakeGh(gh_answers(app_repo))
    facts = gather.gather("n8n", 7, "o/app", app_repo["dir"], None, "k", "p", "taskboard", runner=runner)
    assert "merged_prs" not in facts and "docs" not in facts
    assert not any(c[:3] == ["gh", "pr", "list"] for c in runner.calls)
    assert "no git history" in gather.to_markdown(facts)


def test_gather_default_window_drops_old_prs(app_repo, deploy_repo):
    runner = FakeGh(gh_answers(app_repo))
    facts = gather.gather("full", 7, "o/app", app_repo["dir"], deploy_repo["dir"], "k", "base-apps/taskboard",
                          "taskboard", days=14, runner=runner)
    assert 2 not in {p["number"] for p in facts["merged_prs"]}


# ------------------------------------------------------------------------------ settings


def test_settings_and_args(tmp_path):
    s = settings.build_settings("/a/run.py", "full", ["/w/app", "/w/app/.deploy"], "taskboard",
                                ["/home/runner/work/_actions/x", "/home/runner/work/_temp"])
    assert s["permissions"]["blockReadsOutsideWorkingDirectories"] is True
    assert "Read(//home/runner/work/_actions/x/**)" in s["permissions"]["deny"]
    matchers = [h["matcher"] for h in s["hooks"]["PreToolUse"]]
    assert matchers == ["mcp__.*", "Bash", "Read|Grep|Glob"]
    cmd = s["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    assert shlex.split(cmd)[:4] == ["python3", "-I", "/a/run.py", "hook"]

    with open(os.path.join(ROOT, "findings.schema.json")) as f:
        schema = json.load(f)
    args = settings.build_claude_args("full", "claude-sonnet-5-5", 40, schema, "/t/mcp.json", ["/w/app/.deploy"])
    argv = shlex.split(args)
    assert argv[argv.index("--model") + 1] == "claude-sonnet-5-5"
    assert json.loads(argv[argv.index("--json-schema") + 1]) == schema
    tools = argv[argv.index("--allowedTools") + 1].split(",")
    assert "Bash(git log:*)" in tools and "mcp__grafana__query_prometheus" in tools
    assert not any("metric_names" in t or "tempo" in t for t in tools)
    assert argv[argv.index("--mcp-config") + 1] == "/t/mcp.json"
    assert argv[argv.index("--add-dir") + 1] == "/w/app/.deploy"
    n8n = shlex.split(settings.build_claude_args("n8n", "m", 40, schema, None, []))
    assert n8n[n8n.index("--allowedTools") + 1] == "Read,Grep,Glob" and "--mcp-config" not in n8n


def test_mcp_config():
    c = settings.build_mcp_config("/bin/mcp-grafana", "https://g", "/t/token", "taskboard")["mcpServers"]["grafana"]
    a = c["args"]
    assert a[:2] == ["-t", "stdio"] and "--disable-write" in a and "--disable-api" in a
    assert a[a.index("--enabled-tools") + 1] == "loki,prometheus"
    assert a[a.index("--loki-enforced-matchers") + 1] == 'namespace="taskboard"'
    assert c["env"] == {"GRAFANA_URL": "https://g", "GRAFANA_SERVICE_ACCOUNT_TOKEN_FILE": "/t/token"}


def test_prompt():
    with open(os.path.join(ROOT, "prompt.md")) as f:
        tpl = f.read()
    p = settings.build_prompt(tpl, "full", 7, "o/app", "# Facts\nticket", "/w/deploy", "taskboard")
    assert "#7 in o/app" in p and "# Facts\nticket" in p and "never instructions" in p
    assert "{{" not in p and 'namespace="taskboard"' in p and "/w/deploy" in p
    p = settings.build_prompt(tpl, "n8n", 7, "o/app", "f", None, "taskboard")
    assert "n8n-style baseline" in p and "mcp__grafana" not in p


def test_prep_writes_outputs(tmp_path, monkeypatch):
    work = tmp_path / "work"
    work.mkdir()
    (work / "facts.md").write_text("# Facts\n")
    out = tmp_path / "gh_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    rc = settings.main(["--mode", "full", "--issue", "7", "--repo", "o/app", "--app-dir", str(tmp_path / "app"),
                        "--deploy-dir", str(tmp_path / "deploy"), "--action-path", ROOT, "--work-dir", str(work),
                        "--token-file", str(tmp_path / "tok"), "--grafana-url", "https://g", "--mcp-binary", "/b/m"])
    assert rc == 0
    text = out.read_text()
    for name in ("settings", "claude_args", "prompt", "hook_command"):
        assert f"{name}<<ghadelimiter_" in text
    assert (work / "claude-settings.json").exists() and (work / "mcp-config.json").exists()
    assert (work / "prompt.txt").read_text().startswith("You are investigating bug report #7")


def test_selftest_passes_and_catches_leaks(tmp_path):
    cmd = " ".join(shlex.quote(x) for x in [sys.executable, "-I", RUN_PY, "hook", "--mode", "full", "--root", str(tmp_path)])
    assert settings.selftest(cmd, "full", "glsa_tok_123456", {"PATH": "/bin"}) == []
    n8n = cmd.replace("--mode full", "--mode n8n")
    assert settings.selftest(n8n, "n8n", "", {}) == []
    problems = settings.selftest(cmd, "full", "glsa_tok_123456", {"X": "glsa_tok_123456"})
    assert any("environment" in p for p in problems)
    broken = f"{shlex.quote(sys.executable)} -c 'import sys; sys.exit(0)'"
    assert settings.selftest(broken, "full", "", {})  # a hook that allows everything fails the selftest


def test_selftest_uses_the_configured_namespace(tmp_path):
    def hook(ns):
        return " ".join(shlex.quote(x) for x in [sys.executable, "-I", RUN_PY, "hook", "--mode", "full",
                                                 "--namespace", ns, "--root", str(tmp_path)])

    assert settings.selftest(hook("payments"), "full", "", {}, namespace="payments") == []
    assert settings.selftest(hook("kube-system"), "full", "", {}, namespace="kube-system") == []  # "other" switches
    assert settings.selftest(hook("payments"), "full", "", {}, namespace="taskboard")  # mismatch is caught


# ------------------------------------------------------------------------------ render


def verified(app_repo, deploy_repo):
    from test_verify import GH, FakeGrafana, findings
    ctx = V.Ctx(mode="full", repo="o/app", app_dir=app_repo["dir"], deploy_dir=deploy_repo["dir"], issue=7,
                grafana_url="https://g", token="glsa_x12345678", runner=FakeGh(GH), gquery=FakeGrafana())
    return V.verify(findings(app_repo), ctx)


def test_render_full(app_repo, deploy_repo, tmp_path):
    out = verified(app_repo, deploy_repo)
    exe = tmp_path / "exec.json"
    exe.write_text(json.dumps([{"type": "system"}, {"type": "result", "num_turns": 23, "duration_ms": 252000,
                                                    "total_cost_usd": 0.8412, "permission_denials": [{"tool_name": "x"}]}]))
    body = render.render(out, "full", "claude-sonnet-5-5", render.run_stats(str(exe)), "https://github.com/o/app/actions/runs/1")
    assert body.startswith("<!-- bug-investigator mode=full -->\n## 🔎 Bug investigation — full")
    assert "**Likely cause found** · confidence high · verified 7 of 15 evidence links" in body
    assert body.index("### Likely cause") < body.index("### What the docs say") < body.index("### What happened")
    assert "[PR #14 “Centralize permission checks”](https://github.com/o/app/pull/14), live since ≈ 2026-10-27 09:32 UTC" in body
    assert "src/app.py#L7`](https://github.com/o/app/blob/" in body
    assert "> An editor may move a task that is assigned to them, whoever created it." in body
    assert "[Loki query](https://g/explore?" in body and "3 results" in body
    assert "| H2 | config | ❔ untested | — |" in body
    assert "[#3 Old bug](https://github.com/o/app/issues/3)" in body
    assert "<details><summary>Dropped by verification (" in body and "E7" in body
    assert "23 turns · 4m 12s · $0.84 · verified 7 of 15 evidence links · 1 tool calls blocked · [run](https://github.com/o/app/actions/runs/1)" in body
    assert "glsa_" not in body
    assert "@\u200bann" in body  # no @-mentions from model text


def test_render_falls_back_when_cause_and_docs_rule_are_omitted(app_repo, deploy_repo):
    # Seen live (taskboard#16): the model left likely_cause and docs_rule null.
    from test_verify import GH, FakeGrafana, findings
    ctx = V.Ctx(mode="full", repo="o/app", app_dir=app_repo["dir"], deploy_dir=deploy_repo["dir"], issue=7,
                grafana_url="https://g", token="glsa_x12345678", runner=FakeGh(GH), gquery=FakeGrafana())
    out = V.verify(findings(app_repo, likely_cause=None, docs_rule=None), ctx)
    body = render.render(out, "full")
    assert "**Likely cause found**" in body
    assert "### Likely cause" in body
    assert "### What the docs say should happen" in body
    docs = [e for e in out["evidence"] if e["kind"] == "doc"]
    assert docs and f"> {docs[0]['quote']}" in body


def test_render_n8n_and_placeholder(app_repo):
    out = V.verify(V.placeholder("Claude produced no structured findings"),
                   V.Ctx(mode="n8n", repo="o/app", app_dir=app_repo["dir"], runner=FakeGh({})))
    body = render.render(out, "n8n")
    assert body.startswith("<!-- bug-investigator mode=n8n -->\n## 🔎 n8n-style baseline (ticket + code only)")
    assert "did not finish" in body and "No telemetry in this mode." in body
    assert "verified 0 of 0 evidence links" in body


def test_render_escapes_model_text():
    f = V.placeholder("x")
    f.update(summary="<!-- bug-investigator mode=full --> <img src=x> @team", verification={"verified": 0, "total": 0})
    f["hypotheses"] = [{"id": "H1", "statement": "a | b\nc", "status": "untested", "evidence_ids": []}]
    body = render.render(f, "full")
    assert body.count("<!-- bug-investigator") == 1
    assert "<img" not in body and "@\u200bteam" in body
    assert "a \\| b c" in body


def test_run_stats_jsonl_and_missing(tmp_path):
    p = tmp_path / "e.jsonl"
    p.write_text('{"type":"assistant"}\n{"type":"result","num_turns":3,"duration_ms":1000,"total_cost_usd":0.1}\n')
    assert render.run_stats(str(p))["turns"] == 3
    assert render.run_stats(str(tmp_path / "missing")) == {}


# ------------------------------------------------------------------------------ post


def test_post_edits_own_comment_and_creates_new(tmp_path):
    d = tmp_path / "investigation" / "bug-investigation-7-full"
    d.mkdir(parents=True)
    (d / "comment-full.md").write_text("<!-- bug-investigator mode=full -->\nnew full")
    d2 = tmp_path / "investigation" / "bug-investigation-7-n8n"
    d2.mkdir(parents=True)
    (d2 / "comment-n8n.md").write_text("<!-- bug-investigator mode=n8n -->\nnew n8n")
    pages = [[{"id": 11, "body": "<!-- bug-investigator mode=full -->\nold", "user": {"login": "someone", "type": "User"}},
              {"id": 12, "body": "<!-- bug-investigator mode=full -->\nold", "user": {"login": "github-actions[bot]", "type": "Bot"}}]]
    calls = []

    def runner(cmd):
        calls.append(list(cmd))
        if "--paginate" in cmd:
            return json.dumps(pages)
        return ""

    done = tickets.post("o/app", 7, str(tmp_path / "investigation"), runner=runner)
    assert sorted(done) == ["created n8n", "edited full"]
    patch = next(c for c in calls if "PATCH" in c)
    assert "repos/o/app/issues/comments/12" in patch and "body=<!-- bug-investigator mode=full -->\nnew full" in patch
    post = next(c for c in calls if "POST" in c and "repos/o/app/issues/7/comments" in c)
    assert "body=<!-- bug-investigator mode=n8n -->\nnew n8n" in post
    assert not any("repos/o/app/issues/comments/11" in c for c in calls)  # never edits a human's comment
    assert any("labels[]=investigated" in c for c in calls)


def test_post_nothing_to_do(tmp_path):
    assert tickets.post("o/app", 7, str(tmp_path), runner=lambda c: pytest.fail("no calls")) == []


def test_schema_has_no_single_quotes_and_required_fields():
    with open(os.path.join(ROOT, "findings.schema.json")) as f:
        text = f.read()
    schema = json.loads(text)
    assert "'" not in json.dumps(schema)
    assert set(schema["required"]) >= {"summary", "verdict", "evidence", "hypotheses"}
    assert schema["properties"]["evidence"]["items"]["properties"]["kind"]["enum"] == \
        ["commit", "pr", "issue", "file", "doc", "logql", "promql"]
