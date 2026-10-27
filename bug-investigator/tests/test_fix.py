"""Automatic fix proposals: protected paths, the fix hook and settings, the sandbox script, the patch
filter, test-integrity rules, fix-prep/fix-check end to end (stub sandbox), propose (real git, fake gh)."""

import hashlib
import json
import os
import shlex
import stat
import subprocess
import sys

import pytest

from bug_investigator import fix, hook, scope, settings
from conftest import FakeGh, commit, git

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUN_PY = os.path.join(ROOT, "run.py")
SCRIPT = os.path.join(ROOT, "run-tests.sh")
TEST_CMD = "python3 -m unittest discover -s tests"

PERM_PY = 'def can_move(user, task):\n    return user == task["created_by"]\n'
PERM_FIXED = 'def can_move(user, task):\n    return user in (task["created_by"], task.get("assignee"))\n'
TEST_PY = '''import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
import perm  # noqa: E402


class PermTest(unittest.TestCase):
    def test_creator_moves(self):
        self.assertTrue(perm.can_move("ann", {"created_by": "ann", "assignee": "bob"}))
'''
NEW_TEST = '''
    def test_issue_42_assignee_moves(self):
        self.assertTrue(perm.can_move("bob", {"created_by": "ann", "assignee": "bob"}))
'''


@pytest.fixture(autouse=True)
def hermetic_git(monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")


@pytest.fixture
def repo(tmp_path):
    d = tmp_path / "app"
    d.mkdir()
    git(d, "init", "-q", "-b", "main")
    sha = commit(d, {"app/perm.py": PERM_PY, "tests/test_perm.py": TEST_PY, "docs/rules.md": "# P4 assignee\n"},
                 "base", date="2026-10-27T09:00:00Z")
    return {"dir": str(d), "sha": sha}


def write(d, rel, text, mode="w"):
    p = os.path.join(d, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, mode) as f:
        f.write(text)


def patch_of(d, changes: dict, tmp_path) -> str:
    """The patch fix-check would make for these working-tree changes (then the tree is reset)."""
    base = fix.snapshot(d, str(tmp_path / "base.index"))
    for rel, text in changes.items():
        if text is None:
            os.remove(os.path.join(d, rel))
        elif isinstance(text, tuple):
            write(d, rel, text[0], "a")
        else:
            write(d, rel, text)
    after = fix.snapshot(d, str(tmp_path / "after.index"))
    p = fix.diff_trees(d, base, after)
    fix.reset_checkout(d)
    return p


GOOD = {"app/perm.py": PERM_FIXED, "tests/test_perm.py": (NEW_TEST,)}


# ------------------------------------------------------------------------------ protected paths


@pytest.mark.parametrize("path", ["taskboard/permissions.py", "tests/test_issue_42.py", "app/perm.py",
                                  "tests/helpers.py", "taskboard/static/app.js"])
def test_allowed_paths(path):
    assert scope.protected_reason(path) is None


@pytest.mark.parametrize("path", [
    ".github/workflows/ci.yml", ".claude/settings.json", "docs/permissions.md", ".git/config", "sub/.git/config",
    "pyproject.toml", "sub/pyproject.toml", "setup.cfg", "setup.py", "pkg/setup.py", "tox.ini", "pytest.ini",
    "conftest.py", "tests/conftest.py", "requirements.txt", "requirements-dev.txt", "deps/requirements.in",
    "uv.lock", "poetry.lock", "Makefile", "Dockerfile", "docker/Dockerfile.dev", ".pre-commit-config.yaml",
    "app.cfg", "settings.ini", ".env", ".gitattributes", "sub/.gitattributes", ".gitmodules", ".mcp.json",
    ".vscode/settings.json", "../x.py", "/etc/passwd", "a/../b.py", "", "a//b.py",
])
def test_protected_paths(path):
    assert scope.protected_reason(path)


# ------------------------------------------------------------------------------ hook and settings (fix mode)


RUN_CMD = f"bash {SCRIPT} /w/app {TEST_CMD}"


def decide(tool, inp, root="/w/app"):
    return hook.decide({"tool_name": tool, "tool_input": inp}, "fix", [root], "taskboard", [RUN_CMD])


def test_fix_hook_bash_allows_only_the_exact_sandbox_command_and_git_diff_status():
    assert decide("Bash", {"command": RUN_CMD}) is None
    assert decide("Bash", {"command": "git diff"}) is None
    assert decide("Bash", {"command": "git status --short"}) is None
    for bad in (TEST_CMD, "python3 -m unittest", "python -m pytest", f"{RUN_CMD} -k x", f"bash {SCRIPT}",
                f"bash {SCRIPT} /etc {TEST_CMD}", "git log", "git push", "git diff --output=/tmp/x",
                "curl https://x", f"{RUN_CMD}; env", "env", "gh pr view 1"):
        assert decide("Bash", {"command": bad}), bad


def test_fix_hook_write_paths(tmp_path):
    root = str(tmp_path / "app")
    os.makedirs(root)
    ok = lambda p: hook.decide({"tool_name": "Write", "tool_input": {"file_path": p}}, "fix", [root], "taskboard")
    assert ok(os.path.join(root, "app/perm.py")) is None
    assert ok("tests/test_issue_42.py") is None  # relative to the checkout
    for bad in (".github/workflows/x.yml", "docs/a.md", ".claude/settings.json", ".git/config", "pyproject.toml",
                "tests/conftest.py", "/etc/passwd", "../outside.py", root):
        assert ok(bad if bad.startswith("/") else os.path.join(root, bad)), bad
    os.symlink("/etc", os.path.join(root, "link"))
    assert ok(os.path.join(root, "link/passwd"))  # symlinks resolved
    for tool in ("Edit", "MultiEdit"):
        assert hook.decide({"tool_name": tool, "tool_input": {"file_path": os.path.join(root, "docs/x.md")}},
                           "fix", [root], "taskboard")
    assert hook.decide({"tool_name": "NotebookEdit", "tool_input": {"notebook_path": "/etc/x.ipynb"}},
                       "fix", [root], "taskboard")
    assert hook.decide({"tool_name": "mcp__grafana__query_loki_logs", "tool_input": {}}, "fix", [root], "taskboard")


def test_write_tools_are_blocked_outside_fix_mode(tmp_path):
    for mode in ("full", "n8n"):
        assert "not available" in hook.decide({"tool_name": "Write", "tool_input": {"file_path": str(tmp_path / "a")}},
                                              mode, [str(tmp_path)], "taskboard")


def test_fix_hook_as_subprocess(tmp_path):
    root = str(tmp_path)
    cmd = settings.hook_command(RUN_PY, "fix", [root], "taskboard", (f"bash {SCRIPT} {root} {TEST_CMD}",))
    assert fix.selftest_fix_hook(cmd.replace("python3", shlex.quote(sys.executable), 1), root,
                                 f"bash {SCRIPT} {root} {TEST_CMD}", TEST_CMD) == []
    loose = settings.hook_command(RUN_PY, "full", [root], "taskboard")
    assert fix.selftest_fix_hook(loose.replace("python3", shlex.quote(sys.executable), 1), root,
                                 f"bash {SCRIPT} {root} {TEST_CMD}", TEST_CMD)  # a full-mode hook fails it


def test_fix_settings_and_args():
    run_cmd = settings.run_tests_command("/a", "/w/app", TEST_CMD)
    assert run_cmd == f"bash /a/run-tests.sh /w/app {TEST_CMD}"
    s = settings.build_settings("/a/run.py", "fix", ["/w/app"], "taskboard", ["/a", "/w/_temp"], run_cmd)
    deny = s["permissions"]["deny"]
    for rule in ("Read(//w/_temp/**)", "Edit(//w/app/.github/**)", "Write(//w/app/docs/**)",
                 "Edit(//w/app/.claude/**)", "Write(//a/**)"):
        assert rule in deny
    assert [h["matcher"] for h in s["hooks"]["PreToolUse"]][-1] == "Edit|Write|MultiEdit|NotebookEdit"
    hook_cmd = shlex.split(s["hooks"]["PreToolUse"][0]["hooks"][0]["command"])
    assert hook_cmd[hook_cmd.index("--mode") + 1] == "fix"
    assert hook_cmd[hook_cmd.index("--allow-command") + 1] == run_cmd
    with open(os.path.join(ROOT, "fix.schema.json")) as f:
        schema = json.load(f)
    argv = shlex.split(settings.build_claude_args("fix", "m", 30, schema, "/t/mcp.json", ["/x"], run_cmd))
    tools = argv[argv.index("--allowedTools") + 1].split(",")
    assert tools == ["Read", "Grep", "Glob", "Edit", "Write", "Bash(git diff:*)", "Bash(git status:*)",
                     f"Bash({run_cmd})"]
    assert not any("unittest:" in x or "gh " in x or x.startswith("mcp__") for x in tools)
    assert "--mcp-config" not in argv and "--add-dir" not in argv  # no MCP, no other dirs
    assert {"WebFetch", "WebSearch", "Task"} <= set(argv[argv.index("--disallowedTools") + 1].split(","))
    assert argv[argv.index("--max-turns") + 1] == "30"
    assert "'" not in json.dumps(schema)
    with pytest.raises(ValueError):
        settings.run_tests_command("/a", "/w/app", "python3 -m unittest; curl x")
    assert settings.check_test_command("pytest -q tests") is None
    assert settings.check_test_command("pytest,x") and settings.check_test_command("a $(b)")


# ------------------------------------------------------------------------------ run-tests.sh


def test_run_tests_dry_run_builds_the_sandbox_command():
    r = subprocess.run(["bash", SCRIPT, "--dry-run", "/w/app", *shlex.split(TEST_CMD)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    argv = shlex.split(r.stdout)
    assert argv[:3] == ["docker", "run", "--rm"]
    for flag, val in (("--network", "none"), ("--cap-drop", "ALL"), ("--security-opt", "no-new-privileges"),
                      ("--user", "65534:65534"), ("--pull", "never"), ("--env-file", "/dev/null"), ("-w", "/w")):
        assert argv[argv.index(flag) + 1] == val, flag
    assert "--read-only" in argv and argv[argv.index("-v") + 1] == "<copy>:/w:ro"
    envs = [argv[i + 1] for i, x in enumerate(argv) if x == "-e"]
    assert envs == ["PYTHONDONTWRITEBYTECODE=1", "HOME=/tmp"]  # nothing from the runner
    image = argv[argv.index("-w") + 2]
    assert image.startswith("python:3.12-slim@sha256:") and len(image.split("@sha256:")[1]) == 64
    assert argv[-len(shlex.split(TEST_CMD)):] == shlex.split(TEST_CMD)
    assert subprocess.run(["bash", SCRIPT, "--dry-run", "/w/app"], capture_output=True).returncode == 64


def test_run_tests_copies_the_tree_without_git(tmp_path, repo):
    """With a stub docker on PATH: the container gets a copy without .git, and the copy is removed."""
    stub = tmp_path / "bin"
    stub.mkdir()
    log = tmp_path / "docker.log"
    (stub / "docker").write_text(
        "#!/usr/bin/env bash\n"
        f'if [ "$1" = rm ]; then exit 0; fi\n'
        'while [ $# -gt 0 ]; do if [ "$1" = -v ]; then src="${2%%:*}"; fi; shift; done\n'
        f'(cd "$src" && find . -type f | sort) > {shlex.quote(str(log))}\n'
        f'echo "$src" >> {shlex.quote(str(log))}\n')
    (stub / "docker").chmod(0o755)
    env = dict(os.environ, PATH=f"{stub}:{os.environ['PATH']}")
    os.makedirs(os.path.join(repo["dir"], ".bug-investigator-deploy"))
    write(repo["dir"], ".bug-investigator-deploy/x", "deploy")
    r = subprocess.run(["bash", SCRIPT, repo["dir"], *shlex.split(TEST_CMD)], capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    lines = log.read_text().splitlines()
    assert "./app/perm.py" in lines and "./tests/test_perm.py" in lines
    assert not any("/.git/" in x or x.startswith("./.git") or "bug-investigator-deploy" in x for x in lines)
    assert not os.path.exists(lines[-1])  # the copy is gone


# ------------------------------------------------------------------------------ eligibility


def findings(**kw):
    f = {"summary": "Editors cannot move assigned tasks.", "verdict": "likely_cause", "hypotheses": [],
         "evidence": [{"id": "E1", "kind": "doc", "ref": "docs/rules.md", "quote": "P4 assignee",
                       "detail": "rule", "verified": {"path": "docs/rules.md", "line": 1, "link": "https://x/docs"}}],
         "likely_cause": {"explanation": "checks the creator", "change_verified": {"number": 15, "link": "https://x/pr/15"},
                          "code_verified": {"path": "app/perm.py", "line": 2, "link": "https://x/perm#L2"}},
         "docs_rule": None}
    f.update(kw)
    return f


def test_eligibility():
    assert fix.eligibility(findings(), "full", True) is None
    assert "full mode" in fix.eligibility(findings(), "n8n", True)
    assert "turned off" in fix.eligibility(findings(), "full", False)
    assert "unclear" in fix.eligibility(findings(verdict="unclear"), "full", True)
    assert fix.eligibility(None, "full", True)
    no_code = findings(likely_cause=None)
    assert "no verified code location" in fix.eligibility(no_code, "full", True)
    no_code["evidence"].append({"id": "E2", "kind": "file", "verified": {"link": "https://x/a.py"}})
    no_code["hypotheses"] = [{"id": "H1", "status": "supported", "evidence_ids": ["E2"]}]
    assert fix.eligibility(no_code, "full", True) is None


def test_secrets_gone(tmp_path):
    tok = tmp_path / "grafana-token"
    assert fix.secrets_gone(str(tok), {}) is None
    tok.write_text("glsa_x")
    assert "still exists" in fix.secrets_gone(str(tok), {})
    assert "GRAFANA_TOKEN" in fix.secrets_gone(None, {"GRAFANA_TOKEN": "x", "GRAFANA_URL": "u"})


# ------------------------------------------------------------------------------ patch filter


def test_good_patch_passes(repo, tmp_path):
    p = patch_of(repo["dir"], GOOD, tmp_path)
    chk = fix.check_patch_text(p)
    assert chk["problems"] == [] and chk["files"] == ["app/perm.py", "tests/test_perm.py"]
    assert chk["added"] == 4 and chk["deleted"] == 1
    assert fix.check_test_integrity(chk["entries"]) == ([], ["tests/test_perm.py"])


@pytest.mark.parametrize("changes,expect", [
    ({".github/workflows/x.yml": "on: push\n"}, "protected path"),
    ({"docs/rules.md": "# P4 creator\n"}, "protected path"),
    ({"pyproject.toml": "[x]\n"}, "protected path"),
    ({"tests/conftest.py": "x = 1\n"}, "protected path"),
    ({"app/big.py": "x = 1\n" * 401}, "limit 400"),
    ({"app/perm.py": PERM_FIXED + 'TOKEN = "ghp_' + "a1B2c3D4e5F6g7H8i9J0" + '"\n'}, "secret-looking"),
    ({"app/blob.bin": "\x00\x01\x02binary"}, "binary"),
])
def test_patch_rejections(repo, tmp_path, changes, expect):
    chk = fix.check_patch_text(patch_of(repo["dir"], changes, tmp_path))
    assert any(expect in x for x in chk["problems"]), chk["problems"]


def test_patch_rejects_symlink_and_crafted_text(repo, tmp_path):
    d = repo["dir"]
    base = fix.snapshot(d, str(tmp_path / "b.index"))
    os.symlink("/etc/passwd", os.path.join(d, "app/link.py"))
    after = fix.snapshot(d, str(tmp_path / "a.index"))
    p = fix.diff_trees(d, base, after)
    fix.reset_checkout(d)
    assert any("mode 120000" in x for x in fix.check_patch_text(p)["problems"])
    assert fix.check_patch_text("")["problems"][0] == "the patch is empty"
    smuggled = ("diff --git a/app/perm.py b/app/perm.py\nindex 1..2 100644\n--- a/app/perm.py\n+++ b/app/perm.py\n"
                "@@ -1 +1 @@\n-x\n+y\n--- a/.github/workflows/ci.yml\n+++ b/.github/workflows/ci.yml\n@@ -1 +1 @@\n-a\n+b\n")
    assert any("header mismatch" in x for x in fix.check_patch_text(smuggled)["problems"])
    bad_counts = "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-x\n+y\n+z\n"
    assert fix.check_patch_text(bad_counts)["problems"]
    renamed = "diff --git a/a.py b/b.py\nsimilarity index 100%\nrename from a.py\nrename to b.py\n"
    assert any("renames" in x for x in fix.check_patch_text(renamed)["problems"])
    assert fix.check_patch_text("garbage\n" + smuggled)["problems"][0] == "text before the first file header"


def test_staged_raw_recheck():
    ok = ":100644 100644 aaa bbb M\0app/perm.py\0:000000 100644 000 ccc A\0tests/test_x.py\0"
    assert fix.check_staged_raw(ok) == []
    assert fix.check_staged_raw(":100644 100644 a b M\0.github/workflows/ci.yml\0")
    assert fix.check_staged_raw(":000000 120000 a b A\0app/link\0")


@pytest.mark.parametrize("changes,expect", [
    ({"app/perm.py": PERM_FIXED}, "adds no regression test"),
    ({"app/perm.py": PERM_FIXED, "tests/test_perm.py": None, "tests/test_new.py": "def test_x():\n    pass\n"},
     "deletes the test file"),
    ({"app/perm.py": PERM_FIXED, "tests/test_perm.py": TEST_PY.replace("def test_creator_moves", "def test_renamed")
      + NEW_TEST}, "removes or renames a test"),
    ({"app/perm.py": PERM_FIXED, "tests/test_perm.py": TEST_PY.replace(
        '        self.assertTrue(perm.can_move("ann", {"created_by": "ann", "assignee": "bob"}))\n', "        pass\n")
      + NEW_TEST}, "removes an assertion"),
    ({"app/perm.py": PERM_FIXED, "tests/test_perm.py": TEST_PY.replace("import unittest", "import unittest as ut")
      + NEW_TEST}, "changes existing test code"),
])
def test_test_integrity_rejections(repo, tmp_path, changes, expect):
    chk = fix.check_patch_text(patch_of(repo["dir"], changes, tmp_path))
    problems, _ = fix.check_test_integrity(chk["entries"])
    assert any(expect in x for x in problems), problems


def test_new_test_file_is_fine(repo, tmp_path):
    chk = fix.check_patch_text(patch_of(repo["dir"], {"app/perm.py": PERM_FIXED,
                                                      "tests/test_issue_42.py": "def test_issue_42():\n    pass\n"},
                                        tmp_path))
    assert fix.check_test_integrity(chk["entries"]) == ([], ["tests/test_issue_42.py"])


# ------------------------------------------------------------------------------ evaluate (fake sandbox)


REPORT = {"summary": "fix: Check the assignee for P4.", "root_cause": "P4 checked the creator.", "files_changed": [],
          "test_command": TEST_CMD, "tests_passed": True, "risk": "low", "notes": ""}


OLD_ID, NEW_ID = "test_perm.PermTest.test_creator_moves", "test_perm.PermTest.test_issue_42_assignee_moves"


def sandbox_of(**over):
    res = {
        "before": {"passed": True, "count": 1, "names": [OLD_ID], "failed": [], "skipped": 0, "error": False},
        "after": {"passed": True, "count": 2, "names": [OLD_ID, NEW_ID], "failed": [], "skipped": 0, "error": False},
        "regression": {"passed": False, "count": 2, "names": [OLD_ID, NEW_ID], "failed": [NEW_ID], "skipped": 0, "error": False},
    }
    for kind, changes in over.items():
        res[kind] = {**res[kind], **changes}
    calls = []

    def sb(kind):
        calls.append(kind)
        r = res[kind]
        return {"command": TEST_CMD, **r,
                "summary": f"Ran {r['count']} tests in 0.1s: {'OK' if r['passed'] else 'FAILED (failures=1)'}"}
    sb.calls = calls
    return sb


def test_evaluate_proposes_only_with_a_demonstrated_regression(repo, tmp_path):
    p = patch_of(repo["dir"], GOOD, tmp_path)
    sb = sandbox_of()
    d = fix.evaluate(REPORT, p, TEST_CMD, sb)
    assert d["status"] == "proposed" and sb.calls == ["before", "after", "regression"]
    t = d["tests"]
    assert t["count"] == 2 and t["before_count"] == 1 and t["regression_test_verified"] is True
    assert t["new_tests"] == [NEW_ID]
    # The new test passes on the unfixed code: it does not catch the bug.
    d = fix.evaluate(REPORT, p, TEST_CMD, sandbox_of(regression={"passed": True, "failed": []}))
    assert d["status"] == "rejected" and "passes on the unfixed code" in d["reason"]
    # The sandbox broke on the original-code run: proposed, but plainly unverified.
    d = fix.evaluate(REPORT, p, TEST_CMD, sandbox_of(regression={"passed": False, "count": None, "names": None,
                                                                  "error": True}))
    assert d["status"] == "proposed" and d["tests"]["regression_test_verified"] is False
    assert d["tests"]["regression_error"] is True
    # The suite already failed before and the new test is not among the new failures.
    d = fix.evaluate(REPORT, p, TEST_CMD, sandbox_of(before={"passed": False, "failed": [OLD_ID]},
                                                      regression={"failed": [OLD_ID]}))
    assert d["status"] == "rejected" and "could not show" in d["reason"]


@pytest.mark.parametrize("over,expect", [
    ({"after": {"passed": False}}, "the tests fail after the change"),
    ({"after": {"count": None}}, "could not read how many tests ran after"),
    ({"after": {"count": 0}}, "no tests ran"),
    ({"before": {"count": 2}}, "the new test did not run"),
    ({"before": {"count": None}}, "could not read how many tests ran before"),
    ({"after": {"names": None}}, "could not read the test names"),
    ({"after": {"count": 3, "names": [NEW_ID, "x.Y.test_a", "x.Y.test_b"]}}, f"{OLD_ID} ran before the change but not after"),
    ({"after": {"skipped": 1}}, "skips more tests"),
])
def test_evaluate_rejections_from_test_runs(repo, tmp_path, over, expect):
    d = fix.evaluate(REPORT, patch_of(repo["dir"], GOOD, tmp_path), TEST_CMD, sandbox_of(**over))
    assert d["status"] == "rejected" and expect in d["reason"], d["reason"]


def test_evaluate_rejections_before_running_anything(repo, tmp_path):
    p = patch_of(repo["dir"], GOOD, tmp_path)
    for report, patch, expect in ((None, p, "did not finish"),
                                  (dict(REPORT, notes="cause unclear"), "", "the agent made no change: cause unclear")):
        sb = sandbox_of()
        d = fix.evaluate(report, patch, TEST_CMD, sb)
        assert d["status"] == "rejected" and expect in d["reason"] and sb.calls == []
    no_test = patch_of(repo["dir"], {"app/perm.py": PERM_FIXED}, tmp_path)
    sb = sandbox_of()
    d = fix.evaluate(REPORT, no_test, TEST_CMD, sb)
    assert "adds no regression test" in d["reason"] and sb.calls == []  # never runs code it will reject
    sb = sandbox_of()
    d = fix.evaluate(REPORT, p, TEST_CMD, sb, source_check=lambda entries: ["changes the existing test X"])
    assert d["reason"] == "changes the existing test X" and sb.calls == []


SKIPPED_TEST = NEW_TEST.replace("    def test_issue_42", "    @unittest.skip('later')\n    def test_issue_42")


@pytest.mark.parametrize("added", [
    "    @unittest.skip('later')\n", "    @unittest.skipIf(True, 'x')\n", "    @unittest.skipUnless(False, 'x')\n",
    "    @unittest.expectedFailure\n", "        self.skipTest('x')\n", "        raise unittest.SkipTest('x')\n",
    "    @pytest.mark.skip\n", "    @pytest.mark.xfail\n",
])
def test_additions_that_skip_tests_are_rejected(repo, tmp_path, added):
    changes = {"app/perm.py": PERM_FIXED, "tests/test_perm.py": (NEW_TEST + added + "    def test_x(self):\n        pass\n",)}
    problems, _ = fix.check_test_integrity(fix.check_patch_text(patch_of(repo["dir"], changes, tmp_path))["entries"])
    assert any("skips or disables tests" in x for x in problems), problems


def test_test_sources_ast_rules():
    neutered = TEST_PY.replace('    def test_creator_moves(self):\n', '    def test_creator_moves(self):\n        return\n')
    assert fix.check_test_sources("tests/test_perm.py", TEST_PY, neutered + NEW_TEST) == [
        "changes the existing test PermTest.test_creator_moves in tests/test_perm.py"]
    redefined = TEST_PY + NEW_TEST + "\n    def test_creator_moves(self):\n        pass\n"
    assert "redefines PermTest.test_creator_moves in tests/test_perm.py" in fix.check_test_sources(
        "tests/test_perm.py", TEST_PY, redefined)
    early = TEST_PY + "\n    def test_issue_42_x(self):\n        \"\"\"Doc.\"\"\"\n        return\n"
    assert any("returns before checking anything" in x for x in fix.check_test_sources("tests/test_perm.py", TEST_PY, early))
    assert fix.check_test_sources("tests/test_perm.py", TEST_PY, TEST_PY + NEW_TEST) == []
    assert "does not parse" in fix.check_test_sources("tests/t.py", None, "def (")[0]
    assert fix.check_test_sources("tests/test_new.py", None, "def test_issue_42():\n    assert 1\n") == []


def test_source_check_on_a_real_tree(repo, tmp_path):
    d = repo["dir"]
    base = fix.snapshot(d, str(tmp_path / "b.index"))
    write(d, "tests/test_perm.py", TEST_PY.replace('    def test_creator_moves(self):\n',
                                                   '    def test_creator_moves(self):\n        return\n') + NEW_TEST)
    after = fix.snapshot(d, str(tmp_path / "a.index"))
    p = fix.diff_trees(d, base, after)
    fix.reset_checkout(d)
    entries = fix.check_patch_text(p)["entries"]
    assert fix.check_test_integrity(entries)[0] == []  # additions only: the text rules let it through
    assert fix.make_source_check(d, base, after)(entries) == [
        "changes the existing test PermTest.test_creator_moves in tests/test_perm.py"]


def test_test_results_parsing():
    out = ("test_creator_moves (test_perm.PermTest.test_creator_moves) ... ok\n"
           "test_issue_42 (test_perm.PermTest.test_issue_42)\nDoc line. ... FAIL\n"
           "test_old (test_x.T) ... ERROR\n"
           "test_skip (test_x.T.test_skip) ... skipped 'later'\n"
           "test_mod (unittest.loader._FailedTest.test_mod) ... ERROR\n\n"
           "Ran 5 tests in 0.01s\n\nFAILED (failures=1, errors=2, skipped=1)\n")
    names, failed, skipped = fix.test_results(out)
    assert names == {"test_perm.PermTest.test_creator_moves", "test_perm.PermTest.test_issue_42", "test_x.T.test_old",
                     "test_x.T.test_skip", "unittest.loader._FailedTest.test_mod"}
    assert failed == {"test_perm.PermTest.test_issue_42", "test_x.T.test_old", "unittest.loader._FailedTest.test_mod"}
    assert skipped == 1
    names, failed, skipped = fix.test_results("tests/test_a.py::test_x PASSED\ntests/test_a.py::test_y FAILED\n"
                                              "=== 1 failed, 1 passed, 2 skipped in 0.1s ===")
    assert names == {"tests/test_a.py::test_x", "tests/test_a.py::test_y"} and failed == {"tests/test_a.py::test_y"}
    assert skipped == 2
    assert fix.test_results("Ran 1 test in 0.1s\n\nOK") == (None, set(), None)
    assert fix.verbose(TEST_CMD) == TEST_CMD + " -v"
    assert fix.verbose("pytest -q tests") == "pytest -q tests -v"
    assert fix.verbose("make test") == "make test"


def test_test_count_and_summary():
    assert fix.test_count("....\n----\nRan 42 tests in 0.5s\n\nOK\n") == 42
    assert fix.test_count("Ran 0 tests in 0.000s\n\nNO TESTS RAN") == 0
    assert fix.test_count("=== 7 passed in 0.1s ===") == 7
    assert fix.test_count("nothing") is None
    assert fix.test_summary("Ran 42 tests in 0.5s\n\nOK\n", 0) == "Ran 42 tests in 0.5s: OK"
    assert fix.test_summary("Ran 3 tests in 0.1s\n\nFAILED (failures=1)\n", 1) == "Ran 3 tests in 0.1s: FAILED (failures=1)"


# ------------------------------------------------------------------------------ fix-prep / fix-check end to end


def stub_action(tmp_path):
    """An action dir whose run-tests.sh runs the command in the given dir (the real one needs docker)."""
    d = tmp_path / "action"
    d.mkdir()
    (d / "run-tests.sh").write_text('#!/usr/bin/env bash\napp="$1"; shift; cd "$app" && exec "$@"\n')
    return str(d)


def prep(repo, tmp_path, monkeypatch, **kw):
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    (work / "findings-full.json").write_text(json.dumps(kw.pop("findings", findings())))
    out = tmp_path / "gh_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    args = ["--mode", "full", "--findings", str(work / "findings-full.json"), "--issue", "42", "--repo", "o/app",
            "--app-dir", repo["dir"], "--action-path", ROOT, "--work-dir", str(work), "--deny-dir", str(tmp_path / "t"),
            "--token-file", kw.pop("token_file", str(tmp_path / "gone")), "--test-command", TEST_CMD, "--skip-pull"]
    monkeypatch.setenv("PATH", f"{os.path.dirname(sys.executable)}:{os.environ['PATH']}")  # python3 for the hook
    assert fix.prep_main(args + kw.pop("extra", [])) == 0
    return work, out.read_text()


def check(repo, tmp_path, work, monkeypatch, report=REPORT):
    monkeypatch.setenv("FIX_JSON", json.dumps(report) if report else "")
    assert fix.check_main(["--work-dir", str(work), "--app-dir", repo["dir"], "--action-path", stub_action(tmp_path),
                           "--findings", str(work / "findings-full.json"), "--issue", "42", "--repo", "o/app",
                           "--test-command", TEST_CMD]) == 0
    return json.loads((work / "fix-full.json").read_text())


def test_prep_and_check_propose_a_good_fix(repo, tmp_path, monkeypatch):
    work, outputs = prep(repo, tmp_path, monkeypatch)
    assert "eligible<<" in outputs and "\ntrue\n" in outputs
    prompt = (work / "fix-prompt.txt").read_text()
    assert "bug report #42 in o/app" in prompt and f"bash {SCRIPT} {repo['dir']} {TEST_CMD}" in prompt
    assert "app/perm.py:2" in prompt and "{{" not in prompt
    s = json.loads((work / "fix-settings.json").read_text())
    assert s["hooks"]["PreToolUse"][-1]["matcher"] == "Edit|Write|MultiEdit|NotebookEdit"
    assert not os.path.exists(work / "fix-base.gitconfig")  # the repo config copy stays out of the artifact
    for rel, text in GOOD.items():  # what Claude would do
        write(repo["dir"], rel, text[0], "a") if isinstance(text, tuple) else write(repo["dir"], rel, text)
    rec = check(repo, tmp_path, work, monkeypatch)
    assert rec["status"] == "proposed", rec["reason"]
    assert rec["summary"] == "Check the assignee for P4"
    assert rec["files"] == ["app/perm.py", "tests/test_perm.py"] and rec["base_sha"] == repo["sha"]
    t = rec["tests"]
    assert t["passed"] and t["count"] == 2 and t["before_count"] == 1 and t["regression_test_verified"] is True
    assert t["new_tests"] == ["test_perm.PermTest.test_issue_42_assignee_moves"]
    patch = (work / "fix.patch").read_text()
    assert rec["patch_sha256"] == hashlib.sha256(patch.encode()).hexdigest()
    assert rec["docs_rule"]["link"] == "https://x/docs" and rec["likely_cause"]["change"] == "PR #15"
    assert git(repo["dir"], "status", "--porcelain") == ""  # the checkout is reset


def test_check_rejects_failing_tests_and_resets(repo, tmp_path, monkeypatch):
    work, _ = prep(repo, tmp_path, monkeypatch)
    write(repo["dir"], "tests/test_perm.py", NEW_TEST, "a")  # the new test, but no fix: it fails
    write(repo["dir"], "app/new_module.py", "x = 1\n")
    rec = check(repo, tmp_path, work, monkeypatch)
    assert rec["status"] == "rejected" and "the tests fail after the change" in rec["reason"]
    assert git(repo["dir"], "status", "--porcelain") == ""


def test_check_rejects_a_changed_git_config(repo, tmp_path, monkeypatch):
    work, _ = prep(repo, tmp_path, monkeypatch)
    cfg = fix.git_config_path(repo["dir"])
    original = open(cfg).read()
    for rel, text in GOOD.items():
        write(repo["dir"], rel, text[0], "a") if isinstance(text, tuple) else write(repo["dir"], rel, text)
    with open(cfg, "a") as f:
        f.write("[core]\n\tfsmonitor = touch /tmp/pwned-by-fsmonitor\n")
    rec = check(repo, tmp_path, work, monkeypatch)
    assert rec["status"] == "rejected" and ".git/config changed" in rec["reason"]
    assert open(cfg).read() == original  # restored before any git command ran
    assert not (work / "fix.patch").exists()


def test_secret_rejection_leaves_no_patch_and_no_secret_anywhere(repo, tmp_path, monkeypatch):
    work, _ = prep(repo, tmp_path, monkeypatch)
    secret = "ghp_" + "Zq9" * 12
    write(repo["dir"], "app/perm.py", PERM_FIXED + f'TOKEN = "{secret}"\n')
    write(repo["dir"], "tests/test_perm.py", NEW_TEST, "a")
    log = tmp_path / "exec.json"
    log.write_text(json.dumps([{"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "Write", "input": {"content": f'TOKEN = "{secret}"'}}]}}]))
    (work / "fix.patch").write_text("stale")
    monkeypatch.setenv("FIX_JSON", json.dumps(dict(REPORT, notes=f"used {secret}")))
    assert fix.check_main(["--work-dir", str(work), "--app-dir", repo["dir"], "--action-path", stub_action(tmp_path),
                           "--findings", str(work / "findings-full.json"), "--issue", "42", "--repo", "o/app",
                           "--test-command", TEST_CMD, "--execution-file", str(log)]) == 0
    rec = json.loads((work / "fix-full.json").read_text())
    assert rec["status"] == "rejected" and "secret-looking string added in app/perm.py" in rec["reason"]
    assert rec["patch_sha256"] is None and {"path": "app/perm.py", "added": 2, "removed": 1} in rec["changes"]
    assert not (work / "fix.patch").exists() and not (work / "claude-execution-fix.json").exists()
    for name in os.listdir(work):
        assert secret not in (work / name).read_text(errors="replace"), name


def test_proposed_fix_keeps_a_scrubbed_log(repo, tmp_path, monkeypatch):
    work, _ = prep(repo, tmp_path, monkeypatch)
    for rel, text in GOOD.items():
        write(repo["dir"], rel, text[0], "a") if isinstance(text, tuple) else write(repo["dir"], rel, text)
    log = tmp_path / "exec.json"
    log.write_text('[{"type": "result", "note": "Bearer abcdefghijklmnopqrstuvwxyz"}]')
    monkeypatch.setenv("FIX_JSON", json.dumps(REPORT))
    fix.check_main(["--work-dir", str(work), "--app-dir", repo["dir"], "--action-path", stub_action(tmp_path),
                    "--findings", str(work / "findings-full.json"), "--issue", "42", "--repo", "o/app",
                    "--test-command", TEST_CMD, "--execution-file", str(log)])
    assert json.loads((work / "fix-full.json").read_text())["status"] == "proposed"
    kept = (work / "claude-execution-fix.json").read_text()
    assert "abcdefghijklmnop" not in kept and "[redacted]" in kept


def test_check_without_a_report_rejects(repo, tmp_path, monkeypatch):
    work, _ = prep(repo, tmp_path, monkeypatch)
    write(repo["dir"], "app/perm.py", PERM_FIXED)
    rec = check(repo, tmp_path, work, monkeypatch, report=None)
    assert rec["status"] == "rejected" and "did not finish" in rec["reason"]


def test_prep_skips_and_says_why(repo, tmp_path, monkeypatch):
    work, outputs = prep(repo, tmp_path, monkeypatch, findings=findings(verdict="unclear"))
    assert "\nfalse\n" in outputs
    assert json.loads((work / "fix-full.json").read_text()) == {"status": "skipped",
                                                                "reason": "the verdict is unclear, not a likely cause"}
    tok = tmp_path / "grafana-token"
    tok.write_text("glsa_x")
    work, outputs = prep(repo, tmp_path, monkeypatch, token_file=str(tok))
    assert "\nfalse\n" in outputs and "still exists" in json.loads((work / "fix-full.json").read_text())["reason"]
    work, outputs = prep(repo, tmp_path, monkeypatch, extra=["--enabled", "false"])
    assert "turned off" in json.loads((work / "fix-full.json").read_text())["reason"]


# ------------------------------------------------------------------------------ propose (real git, fake gh)


@pytest.fixture
def origin(tmp_path, repo):
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "clone", "-q", "--bare", repo["dir"], str(bare)], check=True)
    clone = tmp_path / "checkout"
    subprocess.run(["git", "clone", "-q", str(bare), str(clone)], check=True)
    return {"bare": str(bare), "dir": str(clone)}


def artifacts(tmp_path, repo, changes=GOOD, **over):
    p = patch_of(repo["dir"], changes, tmp_path)
    d = tmp_path / "investigation" / "bug-investigation-42-full"
    d.mkdir(parents=True, exist_ok=True)
    (d / "fix.patch").write_text(p)
    rec = {"status": "proposed", "reason": "", "summary": "Check the assignee for P4", "root_cause": "P4 checked <b>the creator</b> @team",
           "files": ["app/perm.py", "tests/test_perm.py"], "risk": "low", "notes": "",
           "tests": {"command": TEST_CMD, "passed": True, "summary": "Ran 2 tests in 0.1s: OK", "count": 2,
                     "before_count": 1, "regression_test_verified": True},
           "base_sha": repo["sha"], "patch_sha256": hashlib.sha256(p.encode()).hexdigest(),
           "docs_rule": {"rule_id": "P4", "quote": "An editor may move a task assigned to them", "path": "docs/rules.md",
                         "line": 1, "link": "https://github.com/o/app/blob/x/docs/rules.md#L1"},
           "likely_cause": {"code_path": "app/perm.py", "code_line": 2, "code_link": "https://github.com/o/app/blob/x/app/perm.py#L2",
                            "change": "PR #15", "change_link": "https://github.com/o/app/pull/15"}}
    rec.update(over)
    (d / "fix-full.json").write_text(json.dumps(rec))
    return str(tmp_path / "investigation")


def gh_for(existing_pr=None, own_comment=None):
    comments = [{"id": 5, "html_url": "https://github.com/o/app/issues/42#issuecomment-5",
                 "body": "<!-- bug-investigator mode=full -->\nfindings", "user": {"login": "github-actions[bot]", "type": "Bot"}}]
    if own_comment:
        comments.append({"id": 6, "body": "<!-- bug-investigator fix -->\nold", "user": {"login": "github-actions[bot]", "type": "Bot"}})
    return FakeGh({
        ("gh", "api", "repos/o/app", "--jq"): "main\n",
        ("gh", "api", "--paginate"): [comments],
        ("gh", "pr", "list"): [existing_pr] if existing_pr else [],
        ("gh", "label", "create"): "",
        ("gh", "pr", "create"): "https://github.com/o/app/pull/9\n",
        ("gh", "pr", "edit"): "",
        ("gh", "api", "-X"): "",
    })


def gh_calls(fake, *prefix):
    return [c for c in fake.calls if tuple(c[: len(prefix)]) == prefix]


def test_propose_opens_a_pr_then_updates_it_on_a_rerun(tmp_path, repo, origin):
    art = artifacts(tmp_path, repo)
    fake = gh_for()
    assert fix.propose("o/app", 42, art, origin["dir"], runner=fake, run_url="https://run/1") == "opened PR #9"
    log = subprocess.run(["git", "-C", origin["bare"], "log", "-1", "--format=%an|%s", "bug-investigator/issue-42"],
                         capture_output=True, text=True, check=True).stdout.strip()
    assert log == "github-actions[bot]|fix: Check the assignee for P4 (#42)"
    files = subprocess.run(["git", "-C", origin["bare"], "diff", "--name-only", f"{repo['sha']}..bug-investigator/issue-42"],
                           capture_output=True, text=True, check=True).stdout.split()
    assert files == ["app/perm.py", "tests/test_perm.py"]
    create = gh_calls(fake, "gh", "pr", "create")[0]
    assert create[create.index("--base") + 1] == "main" and create[create.index("--head") + 1] == "bug-investigator/issue-42"
    assert create[create.index("--title") + 1] == "fix: Check the assignee for P4"
    assert gh_calls(fake, "gh", "pr", "edit")[0][-2:] == ["--add-label", "bug-investigator"]
    post = gh_calls(fake, "gh", "api", "-X", "POST")[0]
    assert "repos/o/app/issues/42/comments" in post
    body = post[post.index("-f") + 1]
    assert body.startswith("body=<!-- bug-investigator fix -->\n🛠 Proposed fix: #9 — Check the assignee for P4.")
    assert "Tests: Ran 2 tests in 0.1s: OK. Review and merge to ship it." in body

    # Re-run: the open PR is updated (force-push + edit), the follow-up comment edited, no second PR.
    fake2 = gh_for(existing_pr={"number": 9, "url": "https://github.com/o/app/pull/9"}, own_comment=True)
    assert fix.propose("o/app", 42, art, origin["dir"], runner=fake2) == "updated PR #9"
    assert not gh_calls(fake2, "gh", "pr", "create")
    edit = gh_calls(fake2, "gh", "pr", "edit")[0]
    assert edit[:4] == ["gh", "pr", "edit", "9"] and "--body-file" in edit
    assert gh_calls(fake2, "gh", "api", "-X", "PATCH")[0][4] == "repos/o/app/issues/comments/6"
    assert not gh_calls(fake2, "gh", "api", "-X", "POST")
    assert not any("workflow" in c for c in fake.calls + fake2.calls)  # no CI on agent code before review


def test_propose_does_nothing_without_a_proposed_fix(tmp_path, repo, origin):
    fake = gh_for()
    assert "nothing to propose" in fix.propose("o/app", 42, str(tmp_path / "none"), origin["dir"], runner=fake)
    art = artifacts(tmp_path, repo, status="rejected", reason="the tests fail")
    assert fix.propose("o/app", 42, art, origin["dir"], runner=fake) == "no fix proposed: the tests fail"
    assert fake.calls == []


def test_propose_refuses_tampered_or_protected_patches(tmp_path, repo, origin):
    art = artifacts(tmp_path, repo, patch_sha256="0" * 64)
    with pytest.raises(fix.ProposeError, match="checksum"):
        fix.propose("o/app", 42, art, origin["dir"], runner=gh_for())
    art = artifacts(tmp_path, repo, changes={".github/workflows/x.yml": "on: push\n", **GOOD})
    fake = gh_for()
    with pytest.raises(fix.ProposeError, match="protected path"):
        fix.propose("o/app", 42, art, origin["dir"], runner=fake)
    art = artifacts(tmp_path, repo, changes={"app/perm.py": PERM_FIXED})
    with pytest.raises(fix.ProposeError, match="regression test"):
        fix.propose("o/app", 42, art, origin["dir"], runner=fake)
    assert not any(c[0] == "gh" for c in fake.calls)
    with pytest.raises(fix.ProposeError, match="bad base"):
        fix.propose("o/app", 42, artifacts(tmp_path, repo, base_sha="main"), origin["dir"], runner=gh_for())


def test_propose_main_reports_errors(tmp_path, repo, origin, capsys):
    art = artifacts(tmp_path, repo, patch_sha256="0" * 64)
    assert fix.propose_main(["--repo", "o/app", "--issue", "42", "--dir", art, "--app-dir", origin["dir"]]) == 1
    assert "no pull request opened" in capsys.readouterr().err


def test_pr_body():
    fixrec = {"summary": "Check the assignee for P4", "root_cause": "P4 checked <b>the creator</b> @team",
              "files": ["app/perm.py", "tests/test_perm.py"], "risk": "low", "notes": "Watch the archive path.",
              "tests": {"command": TEST_CMD, "passed": True, "summary": "Ran 2 tests in 0.1s: OK", "count": 2,
                        "before_count": 1, "regression_test_verified": True},
              "docs_rule": {"rule_id": "P4", "quote": "An editor may move a task assigned to them",
                            "path": "docs/rules.md", "line": 4, "link": "https://github.com/o/app/blob/x/docs/rules.md#L4"},
              "likely_cause": {"code_path": "app/perm.py", "code_line": 2, "code_link": "https://l/perm#L2",
                               "change": "PR #15", "change_link": "https://github.com/o/app/pull/15"}}
    body = fix.pr_body(fixrec, 42, "https://github.com/o/app/issues/42#issuecomment-5", "https://run/1")
    assert body.startswith("Proposed fix for #42: Check the assignee for P4.")
    assert "### What was wrong" in body and "&lt;b>the creator&lt;/b> @​team" in body
    assert "> An editor may move a task assigned to them" in body
    assert "— rule **P4**, [`docs/rules.md#L4`](https://github.com/o/app/blob/x/docs/rules.md#L4)" in body
    assert "[`app/perm.py#L2`](https://l/perm#L2), introduced by [PR #15](https://github.com/o/app/pull/15)" in body
    assert "- `app/perm.py`\n- `tests/test_perm.py`" in body
    assert "✅ passed (Ran 2 tests in 0.1s: OK; 2 tests after the change, 1 before)" in body
    assert "Tests passed in an isolated sandbox during the investigation (no network, no secrets)" in body
    assert "Regression test: ✅ fails on the original code" in body
    assert ("CI has not run on this branch: after reviewing the diff, start it from Actions → ci → Run workflow "
            "on `bug-investigator/issue-42`.") in body
    assert "- Investigation: https://github.com/o/app/issues/42#issuecomment-5" in body and "- Run: https://run/1" in body
    assert "Risk (the agent's estimate): **low**" in body and "### Notes from the agent" in body
    assert "A person must review and merge it; nothing merges automatically." in body
    assert body.rstrip().endswith("Fixes #42")
    fixrec["tests"].update(regression_test_verified=False, regression_summary="timed out after 420 s")
    body = fix.pr_body(fixrec, 42)
    assert "⚠️ **not confirmed** to fail on the original code" in body and "timed out after 420 s" in body
    assert "see #42" in body


def test_action_removes_the_token_before_the_fix_and_never_runs_tests_on_the_host():
    with open(os.path.join(ROOT, "action.yml")) as f:
        text = f.read()
    order = [text.index(x) for x in ("- name: Verify findings", "- name: Remove the Grafana token and the deploy checkout",
                                     "- name: Prepare the fix", "- name: Propose a fix with Claude",
                                     "- name: Check the fix and make the patch", "- name: Render the comment")]
    assert order == sorted(order)
    remove = text[order[1]:order[2]]
    assert 'rm -rf "$RUNNER_TEMP/bug-investigator-secret" "$DEPLOY_DIR"' in remove and "always()" in remove
    prep_step = text[order[2]:order[3]]
    assert "--token-file \"$RUNNER_TEMP/bug-investigator-secret/grafana-token\"" in prep_step
    assert "GRAFANA" not in text[order[2]:order[5]]  # no Grafana input reaches the fix steps
    assert "unittest" not in text[order[2]:order[5]].replace("TEST_COMMAND", "")


def test_run_py_dispatches_fix_commands():
    r = subprocess.run([sys.executable, "-I", RUN_PY, "propose", "--help"], capture_output=True, text=True)
    assert r.returncode == 0 and "--dir" in r.stdout and "ci-workflow" not in r.stdout
    for cmd in ("fix-prep", "fix-check"):
        assert subprocess.run([sys.executable, "-I", RUN_PY, cmd, "--help"], capture_output=True).returncode == 0
