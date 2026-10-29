"""gather, settings (prep/selftest), render and post, with fake gh and real local git repos."""

import json
import os
import shlex
import sys

import pytest

from bug_investigator import gather, render, settings, tickets
from bug_investigator import steps as stepfmt
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



def test_render_keeps_lt_inside_code_spans():
    """GitHub shows code spans literally: `due_at < ?` must not read `due_at &lt; ?`."""
    f = V.placeholder("x")
    f.update(summary='Change it to `clauses.append("due_at < ?")`; <b>x</b> `<!-- bug-investigator mode=full -->`',
             verification={"verified": 0, "total": 0})
    body = render.render(f, "full")
    assert '`clauses.append("due_at < ?")`' in body
    assert "&lt;b>x&lt;/b>" in body and "<b>" not in body
    assert body.count("<!-- bug-investigator") == 1


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
        ["commit", "pr", "issue", "file", "doc", "logql", "promql", "ui"]


def conforms(value, schema, path="$") -> list[str]:
    """A minimal draft-07 check for the keywords findings.schema.json uses (no jsonschema dependency)."""
    types = schema.get("type")
    types = [types] if isinstance(types, str) else types or []
    kinds = {"object": dict, "array": list, "string": str, "null": type(None), "boolean": bool}
    ok = any((t == "integer" and isinstance(value, int) and not isinstance(value, bool))
             or (t in kinds and isinstance(value, kinds[t])) for t in types) if types else True
    if not ok:
        return [f"{path}: not {'/'.join(types)}"]
    probs = []
    if "enum" in schema and value not in schema["enum"]:
        probs.append(f"{path}: {value!r} not in enum")
    if isinstance(value, int) and "minimum" in schema and value < schema["minimum"]:
        probs.append(f"{path}: below minimum")
    if isinstance(value, str) and "maxLength" in schema and len(value) > schema["maxLength"]:
        probs.append(f"{path}: too long")
    if isinstance(value, dict):
        props = schema.get("properties", {})
        probs += [f"{path}: missing {k}" for k in schema.get("required", []) if k not in value]
        if schema.get("additionalProperties") is False:
            probs += [f"{path}: unknown {k}" for k in value if k not in props]
        for k, v in value.items():
            if k in props:
                probs += conforms(v, props[k], f"{path}.{k}")
    if isinstance(value, list):
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            probs.append(f"{path}: too many items")
        for i, v in enumerate(value):
            probs += conforms(v, schema.get("items", {}), f"{path}[{i}]")
    return probs


def test_schema_accepts_ui_item():
    from test_verify import ui_item
    with open(os.path.join(ROOT, "findings.schema.json")) as f:
        evidence = json.load(f)["properties"]["evidence"]["items"]
    props = evidence["properties"]
    assert props["fails_at"]["type"] == ["integer", "null"] and props["fails_at"]["minimum"] == 1
    step = props["steps"]["items"]
    assert props["steps"]["type"] == "array" and step["additionalProperties"] is False
    assert set(step["properties"]) == {"do", "target", "value", "note"}
    assert step["properties"]["do"]["enum"] == list(stepfmt.ACTIONS + stepfmt.CHECKS)
    target = step["properties"]["target"]
    assert target["additionalProperties"] is False
    assert set(target["properties"]) == {"role", "name", "label", "placeholder", "text", "within"}
    within = target["properties"]["within"]
    assert within["additionalProperties"] is False and set(within["properties"]) == {"css", "text"}
    assert "ui:" in props["ref"]["description"] and "ui" in props["detail"]["description"]

    for fails_at in (3, None):
        item = ui_item(fails_at=fails_at)
        assert conforms(item, evidence) == [] and stepfmt.validate(item["steps"], fails_at) == []
    bad = ui_item(fails_at=0, steps=[{"do": "hover", "target": {"role": "button", "xpath": "//b"}, "wait": 1}])
    assert sorted(conforms(bad, evidence)) == ["$.fails_at: below minimum", "$.steps[0].do: 'hover' not in enum",
                                               "$.steps[0].target: unknown xpath", "$.steps[0]: unknown wait"]


def test_prompt_says_there_is_no_browser():
    with open(os.path.join(ROOT, "prompt.md")) as f:
        assert "There is no browser in this run: never cite `ui` evidence." in f.read()


def test_browser_requirements_are_pinned():
    with open(os.path.join(ROOT, "browser-requirements.txt")) as f:
        lines = [x.strip() for x in f if x.strip() and not x.lstrip().startswith("#")]
    assert lines == [
        "playwright==1.64.0 --hash=sha256:5a59af1b230b234008524a5d42b613b233d4256f73bc1dd25bf3f11db0c81b75",
        "greenlet==3.5.6 --hash=sha256:975736b002ed080d124cf81a79cb7e05cb26d6b3f5c7a7b651c0fcce70353aa1",
        "pyee==14.0.0 --hash=sha256:3ac2d3229a9677f7de2c33d7f52fe25b638a46b19c413fea2edc8c6d0a644e4d",
        "typing-extensions==4.16.0 --hash=sha256:481caa481374e813c1b176ada14e97f1f67a4539ce9cfeb3f350d78d6370c2e8",
    ]


# ------------------------------------------------------------------------------ render: ui evidence

SHOT_SHA = "c" * 40


def with_ui(app_repo, deploy_repo, item, result):
    """The full findings plus one ui item (E16), verified the way the trigger does it."""
    from test_verify import GH, FakeGrafana, findings
    ctx = V.Ctx(mode="full", repo="o/app", app_dir=app_repo["dir"], deploy_dir=deploy_repo["dir"], issue=7,
                grafana_url="https://g", token="glsa_x12345678", runner=FakeGh(GH), gquery=FakeGrafana(),
                ui_replay=lambda steps, fails_at: result(steps))
    f = findings(app_repo)
    f["evidence"].append({**item, "id": "E16"})
    out = V.verify(f, ctx)
    assert "E16" in ctx.ui_shots
    return out, next(e for e in out["evidence"] if e["id"] == "E16")


def shot_urls(ns):
    base = f"https://github.com/o/app/blob/{SHOT_SHA}/issue-7/1"
    return [{"n": n, "url": f"{base}/E16-step-{n}.png?raw=true"} for n in ns]


def test_render_reproduced_section_with_and_without_urls(app_repo, deploy_repo):
    from test_verify import MISMATCH, ui_item, replay
    out, e = with_ui(app_repo, deploy_repo, ui_item(fails_at=3), lambda s: replay(s, failed_at=3))
    body = render.render(out, "full")
    assert body.index("### Likely cause") < body.index("### Reproduced in the browser") \
        < body.index("### What the docs say") < body.index("### What happened")
    assert "### Checked in the browser" not in body
    assert "**E16** Start leaves the task open — on a copy of what's live (commit `0123456`)" in body
    assert "1. ✓ open /\n" in body
    assert '2. ✓ click button "Start" in .card "Write copy for the pricing page"\n' in body
    assert f'3. ✗ expect status to contain "moved to in progress" — {MISMATCH}\n' in body
    assert "![step" not in body and "All steps" not in body  # no URLs: the steps only
    # Listed once more among the evidence, like the telemetry items, in a readable form.
    assert "- **E16** browser replay: dana starts her own open task — Start leaves the task open" in body
    assert "verified 8 of 16 evidence links" in body

    e["verified"]["screenshots"] = shot_urls([1, 2, 3])  # set by the trigger after the upload
    body = render.render(out, "full")
    failing = f"![step 3](https://github.com/o/app/blob/{SHOT_SHA}/issue-7/1/E16-step-3.png?raw=true)"
    assert failing in body and body.count("![step") == 3
    folded = body.index("<details><summary>All steps</summary>")
    assert body.index('3. ✗ expect status') < body.index(failing) < folded \
        < body.index("![step 1](") < body.index("![step 2](") < body.index("### What the docs say")


def test_render_checked_section_for_null_fails_at(app_repo, deploy_repo):
    from test_verify import ui_item, replay
    out, e = with_ui(app_repo, deploy_repo, ui_item(fails_at=None), lambda s: replay(s))
    e["verified"]["screenshots"] = shot_urls([1, 2, 3])
    body = render.render(out, "full")
    assert "### Checked in the browser" in body and "### Reproduced in the browser" not in body
    section = body[body.index("### Checked in the browser"):body.index("### What the docs say")]
    assert "✗" not in section and section.count("✓") == 3
    last = f"![step 3](https://github.com/o/app/blob/{SHOT_SHA}/issue-7/1/E16-step-3.png?raw=true)"
    assert section.index(last) < section.index("<details><summary>All steps</summary>") < section.index("![step 1](")


def test_render_ui_escapes_hostile_text(app_repo, deploy_repo):
    from test_verify import ui_item, replay
    steps = [{"do": "click", "target": {"role": "button", "name": "<img src=x onerror=alert(1)> @dana"}},
             {"do": "expect_visible", "target": {"text": "`<!-- bug-investigator mode=full -->`"}}]
    item = ui_item(fails_at=2, steps=steps, ref="<script>x</script> @ref",
                   detail="<!-- bug-investigator mode=full --> <b>bold</b> @team")
    out, e = with_ui(app_repo, deploy_repo, item, lambda s: replay(s, failed_at=2, failure="missing",
                                                                   error="<i>nothing</i> for @ann"))
    e["verified"]["screenshots"] = [{"n": 2, "url": "https://x.example/a.png) ![evil](https://evil.example/p.png"},
                                    {"n": 1, "url": "javascript:alert(1)"}]
    body = render.render(out, "full")
    assert body.count("<!-- bug-investigator") == 1
    for raw in ("<img", "<script", "<b>", "<i>", "evil", "javascript:", "![step"):
        assert raw not in body
    for who in ("dana", "team", "ann", "ref"):
        assert f"@​{who}" in body
