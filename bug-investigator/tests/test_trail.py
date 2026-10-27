"""The reasoning trail: extraction from a real (sanitized) execution log, edge cases, and rendering."""

import json
import os
import urllib.parse

from bug_investigator import render, trail
from bug_investigator import verify as V

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE = os.path.join(HERE, "fixtures", "claude-execution-full.json")
SHA = "eb97a0bd6f49ebe233ed5694b82e49d6564454ae"
APP = "/home/runner/work/taskboard/taskboard"


def real_trail():
    return trail.build(trail.load_messages(FIXTURE), repo="arigsela/taskboard", sha=SHA,
                       grafana_url="https://g", namespace="taskboard")


def test_real_log_steps():
    t = real_trail()
    steps = t["steps"]
    assert t["tool_calls"] == 7 and t["blocked"] == 0
    assert [s["tool"] for s in steps] == ["Read", "Read", "Loki", "Bash", "Grep", "Bash", "Loki"]  # no ToolSearch/StructuredOutput
    assert [s["n"] for s in steps] == list(range(1, 8))
    read = steps[0]
    assert read["input"] == "taskboard/permissions.py" and read["result"] == "74 lines"
    assert read["link"] == f"https://github.com/arigsela/taskboard/blob/{SHA}/taskboard/permissions.py"
    loki = steps[2]
    assert loki["input"] == '{namespace="taskboard"} | json | msg="permission_denied" | rule="P4"'
    assert loki["window"] == "2026-10-27 15:30–16:30 UTC" and loki["result"] == "5 log lines"
    assert loki["link"].startswith("https://g/explore?")
    assert steps[3]["input"] == "git show eb97a0b^2 -- taskboard/app.py"
    assert steps[4]["input"] == "change_status in taskboard" and steps[4]["result"] == "2 lines"
    assert steps[5]["narration"] == "Cause confirmed. A quick check of the old code and the pre-deploy baseline."
    assert steps[6]["result"] == "2 log lines"
    # Counts only: nothing from file bodies or log lines.
    blob = json.dumps(t)
    assert "(line)" not in blob and "(log line)" not in blob and APP not in blob


def tool_use(i, name, inp):
    return {"type": "tool_use", "id": f"t{i}", "name": name, "input": inp}


def tool_result(i, content, is_error=None):
    return {"type": "tool_result", "tool_use_id": f"t{i}", "content": content, "is_error": is_error}


def run_of(*pairs, denials=()):
    msgs = [{"type": "system", "subtype": "init", "cwd": APP}]
    for blocks, results in pairs:
        msgs.append({"type": "assistant", "message": {"content": blocks}})
        if results:
            msgs.append({"type": "user", "message": {"content": results}})
    msgs.append({"type": "result", "num_turns": 3, "permission_denials": list(denials)})
    return msgs


def test_blocked_errors_paths_and_scrubbing():
    msgs = run_of(
        ([{"type": "text", "text": "Checking the deploy timeline. Token glsa_abcdefghijklmnop leaked?"},
          tool_use(1, "Bash", {"command": f"git -C {APP}/.bug-investigator-deploy log -- base-apps/taskboard"})],
         [tool_result(1, "abc one\ndef two\n")]),
        ([tool_use(2, "Bash", {"command": "env"})],
         [tool_result(2, "PreToolUse:Bash hook error: Blocked by bug-investigator scope: only these commands are "
                         "allowed: git log", True)]),
        ([tool_use(3, "mcp__grafana__query_prometheus",
                   {"datasourceUid": "PBFA97CFB590B2093", "expr": "sum(rate(container_cpu_usage_seconds_total[5m]))",
                    "startTime": "2026-10-27T15:00:00Z", "endTime": "2026-10-27T16:00:00Z"})],
         [tool_result(3, [{"type": "text", "text": "[]"}])]),
        ([tool_use(4, "Read", {"file_path": f"{APP}/.bug-investigator-deploy/base-apps/taskboard/runbook.md"})],
         [tool_result(4, "1\tx\n2\ty\n")]),
        ([tool_use(5, "Grep", {"pattern": "assignee", "path": f"{APP}/taskboard"})],
         [tool_result(5, "No matches found")]),
        ([tool_use(6, "Read", {"file_path": "/etc/passwd"})], []),
        ([tool_use(7, "Glob", {"pattern": "**/*.py"})], [tool_result(7, "boom: something failed", True)]),
        ([{"type": "text", "text": "Done; reporting."}], []),
        denials=[{"tool_name": "Read", "tool_use_id": "t6", "tool_input": {}}],
    )
    t = trail.build(msgs, repo="o/app", sha="a" * 40, deploy_repo="o/deploy", deploy_sha="b" * 40,
                    grafana_url="https://g", namespace="taskboard")
    s = {x["n"]: x for x in t["steps"]}
    assert s[1]["input"] == "git -C <deploy> log -- base-apps/taskboard" and s[1]["result"] == "2 lines of output"
    assert "glsa_" not in s[1]["narration"] and "[redacted]" in s[1]["narration"]
    assert s[2]["status"] == "blocked" and s[2]["result"] == "blocked: only these commands are allowed: git log"
    assert s[3]["tool"] == "Prometheus" and s[3]["result"] == "no results" and s[3]["link"] is None  # unscoped: no link
    assert s[4]["input"] == "deploy:base-apps/taskboard/runbook.md"
    assert s[4]["link"] == f"https://github.com/o/deploy/blob/{'b' * 40}/base-apps/taskboard/runbook.md"
    assert s[5]["input"] == "assignee in taskboard" and s[5]["result"] == "no results"
    assert s[6]["status"] == "blocked" and s[6]["result"].startswith("blocked:") and s[6]["link"] is None
    assert s[7]["status"] == "error" and s[7]["result"] == "error: boom: something failed"
    assert s[8]["tool"] is None and s[8]["narration"] == "Done; reporting."
    assert t["blocked"] == 2 and t["tool_calls"] == 7


def test_trail_main_survives_a_missing_log(tmp_path):
    out = tmp_path / "trail.json"
    assert trail.main(["--execution-file", str(tmp_path / "missing.json"), "--out", str(out)]) == 0
    assert json.loads(out.read_text())["steps"] == []


def test_trail_main_reads_heads_from_findings(tmp_path):
    f = tmp_path / "findings.json"
    f.write_text(json.dumps({"verification": {"heads": {"app": SHA}}}))
    out = tmp_path / "trail.json"
    trail.main(["--execution-file", FIXTURE, "--findings", str(f), "--repo", "arigsela/taskboard", "--out", str(out)])
    steps = json.loads(out.read_text())["steps"]
    assert steps[0]["link"].endswith(f"/blob/{SHA}/taskboard/permissions.py")


# ------------------------------------------------------------------------------ render


def base_findings():
    f = V.placeholder("x")
    f.update(summary="s", verdict="unclear", verification={"verified": 0, "total": 0},
             could_not_check=["Tempo traces"], next_step="Look at line 56.",
             evidence=[{"id": "E1", "kind": "file", "ref": "a.py", "detail": "d",
                        "verified": {"path": "a.py", "line": 1, "link": "https://x"}}])
    return f


def test_render_trail_section():
    body = render.render(base_findings(), "full", trail=real_trail())
    assert "<details><summary>How the agent worked (7 steps)</summary>" in body
    assert body.index("### Couldn't check") < body.index("How the agent worked") < body.index("<summary>Evidence")
    assert (f"1. Read: [`taskboard/permissions.py`](https://github.com/arigsela/taskboard/blob/{SHA}/"
            "taskboard/permissions.py) → 74 lines") in body
    assert ('3. Loki: [`{namespace="taskboard"} | json | msg="permission_denied" | rule="P4"`](https://g/explore?'
            in body)
    assert "2026-10-27 15:30–16:30 UTC → 5 log lines" in body
    assert ("6. Cause confirmed. A quick check of the old code and the pre-deploy baseline. — Bash: "
            "`git show eb97a0b^1:taskboard/permissions.py` → 52 lines of output") in body


def test_render_trail_cap_escaping_and_blocked():
    steps = [{"n": i, "narration": None, "tool": "Bash", "input": f"git log -{i}", "result": "1 line of output",
              "status": "ok", "link": None, "window": None} for i in range(1, 46)]
    steps[0].update(narration="<img src=x> ping @team", input="a `b` c", status="blocked", result="blocked: nope")
    body = render.render(base_findings(), "full", trail={"steps": steps})
    assert "How the agent worked (45 steps)" in body
    assert "40. Bash: `git log -40`" in body and "41. Bash" not in body and "… 5 more steps" in body
    assert "<img" not in body and "@​team" in body
    assert "⛔ Bash: `a 'b' c` → blocked: nope" in body


def test_render_without_trail_has_no_section():
    assert "How the agent worked" not in render.render(base_findings(), "full")
    assert "How the agent worked" not in render.render(base_findings(), "full", trail={"steps": []})


def test_render_fix_lines():
    proposed = {"status": "proposed", "summary": "Check the assignee for P4.",
                "tests": {"command": "python3 -m unittest discover -s tests", "passed": True,
                          "summary": "Ran 42 tests: OK"}}
    body = render.render(base_findings(), "full", fix=proposed)
    assert "### Proposed fix" in body and "🛠 Check the assignee for P4. Tests: Ran 42 tests: OK." in body
    assert body.index("### Suggested next step") < body.index("### Proposed fix") < body.index("### Couldn't check")
    body = render.render(base_findings(), "full", fix={"status": "rejected", "reason": "the tests fail"})
    assert "No fix proposed: the tests fail" in body and "### Proposed fix" not in body
    assert "No fix proposed" not in render.render(base_findings(), "full")


def test_render_main_reads_trail_and_fix(tmp_path):
    (tmp_path / "f.json").write_text(json.dumps(base_findings()))
    (tmp_path / "trail.json").write_text(json.dumps(real_trail()))
    (tmp_path / "fix.json").write_text(json.dumps({"status": "skipped", "reason": "the verdict is unclear"}))
    out = tmp_path / "c.md"
    render.main(["--mode", "full", "--findings", str(tmp_path / "f.json"), "--trail", str(tmp_path / "trail.json"),
                 "--fix", str(tmp_path / "fix.json"), "--out", str(out)])
    body = out.read_text()
    assert "How the agent worked (7 steps)" in body and "No fix proposed: the verdict is unclear" in body
    render.main(["--mode", "full", "--findings", str(tmp_path / "f.json"), "--trail", str(tmp_path / "nope.json"),
                 "--fix", str(tmp_path / "nope.json"), "--out", str(out)])
    assert "How the agent worked" not in out.read_text()


def test_load_messages_json_jsonl_and_bad(tmp_path):
    msgs = trail.load_messages(FIXTURE)
    assert msgs[0]["type"] == "system" and msgs[-1]["type"] == "result"
    jl = tmp_path / "e.jsonl"
    jl.write_text("\n".join(json.dumps(m) for m in msgs) + "\nnot json\n")
    assert trail.load_messages(str(jl)) == msgs  # the bad line is skipped
    assert trail.build(trail.load_messages(str(jl)))["tool_calls"] == 7
    one = tmp_path / "one.json"
    one.write_text(json.dumps({"type": "result", "num_turns": 1}))
    assert trail.load_messages(str(one)) == [{"type": "result", "num_turns": 1}]
    scalar = tmp_path / "s.json"
    scalar.write_text("42")
    assert trail.load_messages(str(scalar)) == []
    assert trail.load_messages(None) == [] and trail.load_messages(str(tmp_path / "missing")) == []


def test_secret_in_query_or_path_never_reaches_summary_or_link():
    token = "glsa_" + "AbC123xyz" * 4
    msgs = run_of(
        ([tool_use(1, "mcp__grafana__query_loki_logs",
                   {"datasourceUid": "loki", "logql": f'{{namespace="taskboard"}} |= "{token}"',
                    "startRfc3339": "2026-10-27T15:00:00Z", "endRfc3339": "2026-10-27T16:00:00Z"})],
         [tool_result(1, [{"type": "text", "text": '{"data": []}'}])]),
        ([tool_use(2, "Read", {"file_path": f"{APP}/{token}.py"})], [tool_result(2, "1\tx\n")]),
    )
    t = trail.build(msgs, repo="o/app", sha="a" * 40, grafana_url="https://g", namespace="taskboard")
    assert all(s["link"] is None for s in t["steps"])
    assert "[redacted]" in t["steps"][0]["input"] and t["steps"][0]["result"] == "no log lines"
    body = render.render(base_findings(), "full", trail=t)
    forms = {token, "AbC123xyz", urllib.parse.quote(token), urllib.parse.quote(token, safe=""),
             urllib.parse.quote(json.dumps(token)), urllib.parse.quote_plus(token)}
    for text in (json.dumps(t), json.dumps(t, ensure_ascii=False), body, urllib.parse.unquote(body)):
        for form in forms:
            assert form not in text


def test_render_ignores_wrongly_shaped_trail_and_fix(tmp_path):
    f = base_findings()
    for bad in (None, [], [1, 2], "x", 3, {"steps": "x"}, {"steps": [1, "a", None]}, {"nope": 1},
                {"status": "weird"}, {"status": ["proposed"]}):
        body = render.render(f, "full", trail=bad, fix=bad)
        assert "How the agent worked" not in body and "No fix proposed" not in body and "Proposed fix" not in body
    body = render.render(f, "full", fix={"status": "proposed", "summary": "s", "tests": "not a dict"})
    assert "Tests: passed." in body
    body = render.render(f, "full", trail={"steps": [{"n": "x", "tool": "Bash", "input": "git log",
                                                       "link": "javascript:alert(1)", "result": "r"}]})
    assert "(1 steps)" in body and "?. Bash: `git log` → r" in body and "javascript:" not in body
    (tmp_path / "f.json").write_text(json.dumps(f))
    for name, content in (("arr.json", "[1, 2]"), ("scalar.json", "7"), ("broken.json", "{")):
        (tmp_path / name).write_text(content)
        out = tmp_path / "c.md"
        assert render.main(["--mode", "full", "--findings", str(tmp_path / "f.json"), "--trail", str(tmp_path / name),
                            "--fix", str(tmp_path / name), "--out", str(out)]) == 0
        text = out.read_text()
        assert "How the agent worked" not in text and "fix proposed" not in text.lower()
