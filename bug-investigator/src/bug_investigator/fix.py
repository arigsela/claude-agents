"""Automatic fix proposals. Claude never holds a write token, and no code it writes runs on the runner.

fix-prep (investigate job, full mode): decide whether to try a fix; check the Grafana token is gone;
  pull the sandbox image; record the checkout's baseline tree and .git/config; write the fix agent's
  settings (hook + denies), prompt and claude_args; self-test the fix hook.
fix-check (investigate job, no Claude): refuse if .git/config changed; snapshot the agent's changes as
  a patch; reject unsafe patches (protected paths, size, secrets, modes) and weakened tests; run the
  suite in the sandbox before and after the change, and the new tests against the original code;
  write fix-<mode>.json and fix.patch; reset the checkout.
propose (separate job with contents/pull-requests write, no Claude): re-check the patch, apply it on
  bug-investigator/issue-<N>, re-check what was applied, push, open or update the PR, post a short
  follow-up comment. It starts no CI: a person reviews the diff first, then runs CI.

Tests only ever run through run-tests.sh: a container with a copy of the tree (no .git), no network,
no runner environment, no capabilities, user nobody.
"""

from __future__ import annotations

import argparse
import ast
import glob
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from typing import Callable

from bug_investigator import scope, settings
from bug_investigator.render import inline, t
from bug_investigator.tickets import MARKER as INVESTIGATION_MARKER
from bug_investigator.util import CommandError, Runner, read_json, run, run_json, scrub, scrub_text, write_json

FIX_MARKER = "<!-- bug-investigator fix -->"
BRANCH = "bug-investigator/issue-{issue}"
LABEL = "bug-investigator"
MAX_LINES = 400
TEST_TIMEOUT = 420  # run-tests.sh stops the container after 300 s
DEFAULT_TEST_COMMAND = "python3 -m unittest discover -s tests"
DEPLOY_DIRNAME = ".bug-investigator-deploy"
ALLOWED_MODES = ("100644", "100755")
# Neither system/global config nor anything the repo config could point at runs while the scripts use git.
GIT_SAFE = ["-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null", "-c", "core.untrackedCache=false"]
GIT_ENV = {"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_TERMINAL_PROMPT": "0"}
SHA40 = re.compile(r"^[0-9a-f]{40}$")
HUNK = re.compile(r"^@@ -\d+(?:,(\d+))? \+\d+(?:,(\d+))? @@")
TEST_FILE = re.compile(r"(^|/)tests?/|(^|/)test_[^/]*\.py$|_test\.py$")
TEST_DEF = re.compile(r"^\s*(async\s+)?def\s+test\w*\s*\(")
ASSERTION = re.compile(r"\bassert\b|\bself\.assert|\bself\.fail|\bpytest\.raises\b")
# Added lines that skip or neuter tests.
SKIPPING = re.compile(r"\bskip(If|Unless)?\b|\bSkipTest\b|\bskipTest\(|\bexpectedFailure\b|"
                      r"\bpytest\.(mark\.)?(skip|xfail)\b|\bxfail\b")
UNITTEST_V = re.compile(r"^(\w+) \(([\w.]+)\)")
STATUS_LINE = re.compile(r" \.\.\. (ok|FAIL|ERROR|skipped|expected failure|unexpected success)\b")
PYTEST_V = re.compile(r"^(\S+::\S+) (PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS)\b")
BOT_NAME = "github-actions[bot]"
BOT_EMAIL = "41898282+github-actions[bot]@users.noreply.github.com"

Sandbox = Callable[[str], dict]  # "before" | "after" | "regression" -> test result


class ProposeError(RuntimeError):
    pass


# ---------------------------------------------------------------------------------- eligibility


def eligibility(findings, mode: str, enabled: bool) -> str | None:
    """None when a fix should be tried, else why not."""
    if mode != "full":
        return "fixes are proposed in full mode only"
    if not enabled:
        return "automatic fixes are turned off (input `fix: false`)"
    if not isinstance(findings, dict):
        return "there are no verified findings"
    verdict = findings.get("verdict")
    if verdict != "likely_cause":
        return f"the verdict is {verdict or 'missing'}, not a likely cause"
    lc = findings.get("likely_cause")
    if isinstance(lc, dict) and lc.get("code_verified") and not lc.get("unconfirmed"):
        return None
    files = {e.get("id") for e in findings.get("evidence") or []
             if isinstance(e, dict) and e.get("kind") == "file" and (e.get("verified") or {}).get("link")}
    for h in findings.get("hypotheses") or []:
        if isinstance(h, dict) and h.get("status") == "supported" and files & set(h.get("evidence_ids") or []):
            return None
    return "no verified code location for the cause"


def _docs_rule(f: dict) -> dict | None:
    dr = f.get("docs_rule")
    if isinstance(dr, dict) and (dr.get("verified") or {}).get("link"):
        v = dr["verified"]
        return {"rule_id": dr.get("rule_id"), "quote": dr.get("quote"), "path": v.get("path"), "line": v.get("line"),
                "link": v.get("link")}
    doc = next((e for e in f.get("evidence") or [] if isinstance(e, dict) and e.get("kind") == "doc"
                and e.get("quote") and (e.get("verified") or {}).get("link")), None)
    if doc:
        v = doc["verified"]
        return {"rule_id": None, "quote": doc["quote"], "path": v.get("path"), "line": v.get("line"), "link": v["link"]}
    return None


def findings_markdown(f: dict) -> str:
    """The verified findings, for the fix agent's prompt."""
    out = [f"**Summary:** {f.get('summary') or ''}".strip()]
    lc = f.get("likely_cause") if isinstance(f.get("likely_cause"), dict) else None
    if lc:
        out += ["", f"**Likely cause:** {lc.get('explanation') or ''}"]
        kv, cv = lc.get("code_verified") or {}, lc.get("change_verified") or {}
        if kv:
            out.append(f"- Faulty code: `{kv.get('path')}" + (f":{kv['line']}" if kv.get("line") else "") + "`")
        if cv:
            out.append("- Introduced by: " + (f"PR #{cv['number']} {cv.get('title') or ''}".strip() if cv.get("number")
                                               else f"commit {str(cv.get('sha'))[:10]}"))
    dr = _docs_rule(f)
    if dr:
        out += ["", f"**Documented rule{' ' + str(dr['rule_id']) if dr.get('rule_id') else ''}** "
                    f"(`{dr.get('path')}` line {dr.get('line')}):", f"> {dr.get('quote')}"]
    hyps = [h for h in f.get("hypotheses") or [] if isinstance(h, dict)]
    if hyps:
        out += ["", "**Hypotheses:**"] + [
            f"- {h.get('id')} ({h.get('status')}): {h.get('statement')} "
            f"[evidence: {', '.join(h.get('evidence_ids') or []) or 'none'}]" for h in hyps]
    ev = [e for e in f.get("evidence") or [] if isinstance(e, dict) and e.get("kind") in ("file", "doc")]
    if ev:
        out += ["", "**Verified code and doc evidence:**"]
        for e in ev:
            v = e.get("verified") or {}
            out.append(f"- {e.get('id')} `{v.get('path')}:{v.get('line')}`: {json.dumps(e.get('quote') or '')} — "
                       f"{e.get('detail') or ''}")
    if f.get("next_step"):
        out += ["", f"**Suggested next step:** {f['next_step']}"]
    return "\n".join(out)


def build_prompt(template: str, findings: dict, issue: int, repo: str, run_command: str) -> str:
    return (template.replace("{{ISSUE}}", str(issue)).replace("{{REPO}}", repo)
            .replace("{{RUN_TESTS}}", run_command).replace("{{FINDINGS}}", findings_markdown(findings)))


# ---------------------------------------------------------------------------------- git helpers


def _git(app_dir: str, *args: str, index: str | None = None, timeout: int = 120, binary: bool = False):
    env = dict(os.environ, **GIT_ENV)
    if index:
        env["GIT_INDEX_FILE"] = index
    try:
        r = subprocess.run(["git", "-C", app_dir, *GIT_SAFE, *args], capture_output=True, text=not binary,
                           env=env, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise CommandError(f"git {args[0]}: {e}") from e
    if r.returncode != 0:
        err = r.stderr if isinstance(r.stderr, str) else r.stderr.decode(errors="replace")
        raise CommandError(f"git {' '.join(args[:3])}: exit {r.returncode}: {err.strip()[:300]}")
    return r.stdout


def snapshot(app_dir: str, index: str) -> str:
    """The tree of the working directory as it is now (tracked and new files; ignored files and the
    deploy checkout left out), built in a private index so the real one is untouched."""
    if os.path.exists(index):
        os.remove(index)
    _git(app_dir, "read-tree", "HEAD", index=index)
    _git(app_dir, "add", "-A", "--", ".", f":(exclude){DEPLOY_DIRNAME}", index=index)
    return _git(app_dir, "write-tree", index=index).strip()


def diff_trees(app_dir: str, base: str, after: str) -> str:
    return _git(app_dir, "diff", "--no-color", "--no-ext-diff", "--no-textconv", "--no-renames", "--full-index",
                base, after)


def materialize(app_dir: str, tree: str, dest: str) -> None:
    """Write a tree's files into dest (no .git): what the sandbox tests."""
    data = _git(app_dir, "archive", "--format=tar", tree, binary=True)
    r = subprocess.run(["tar", "-x", "-C", dest], input=data, capture_output=True, timeout=120)
    if r.returncode != 0:
        raise CommandError(f"tar: {r.stderr.decode(errors='replace')[:200]}")


def state_dir(work_dir: str) -> str:
    """Beside the work dir, not in it: the work dir is uploaded as an artifact; this copy of the repo
    config (which can hold credentials) must not be."""
    return os.path.join(os.path.dirname(os.path.abspath(work_dir)), "bug-investigator-fix-state")


def git_config_path(app_dir: str) -> str:
    return os.path.join(app_dir, ".git", "config")


def file_sha256(path: str) -> str:
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return ""


def reset_checkout(app_dir: str) -> None:
    _git(app_dir, "reset", "-q", "--hard", "HEAD")
    _git(app_dir, "clean", "-fdq")


# ---------------------------------------------------------------------------------- patch checks


def check_patch_text(text: str, max_lines: int = MAX_LINES) -> dict:
    """Parse a git patch strictly. Returns {files, entries, added, deleted, problems}; no problems = acceptable.

    Anything the parser does not recognise is a problem: the patch is applied by `git apply` later,
    so this check must not be more lenient than git about where one file ends and the next begins.
    `entries` has, per file, the added and removed lines (for the test-integrity rules).
    """
    files: list[dict] = []
    problems: list[str] = []
    added = deleted = 0
    cur: dict | None = None
    old_left = new_left = 0
    in_hunk = False
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    for line in lines:
        if in_hunk:
            if line.startswith("+"):
                added += 1
                new_left -= 1
                content = line[1:]
                cur["added"].append(content)
                if scrub_text(content) != content:
                    problems.append(f"secret-looking string added in {cur['path']}")
            elif line.startswith("-"):
                deleted += 1
                old_left -= 1
                cur["removed"].append(line[1:])
            elif line.startswith(" ") or line == "":
                old_left -= 1
                new_left -= 1
            elif line.startswith("\\"):
                pass
            else:
                problems.append(f"malformed hunk in {cur['path']}")
                in_hunk = False
                continue
            if old_left < 0 or new_left < 0:
                problems.append(f"hunk line counts do not match in {cur['path']}")
                in_hunk = False
            elif old_left == 0 and new_left == 0:
                in_hunk = False
            continue
        if line.startswith("diff --git "):
            rest = line[len("diff --git "):]
            path = None
            if rest.startswith("a/"):
                body = rest[2:]
                n = (len(body) - 3) // 2
                if (len(body) - 3) % 2 == 0 and body[n:n + 3] == " b/" and body[:n] == body[n + 3:]:
                    path = body[:n]
            if path is None:
                problems.append(f"unusual file header {rest[:80]!r} (renames and quoted names are not allowed)")
                path = rest
            cur = {"path": path, "mode": None, "new": False, "deleted": False, "added": [], "removed": []}
            files.append(cur)
            continue
        if cur is None:
            problems.append("text before the first file header")
            continue
        m = HUNK.match(line)
        if m:
            old_left = int(m.group(1)) if m.group(1) is not None else 1
            new_left = int(m.group(2)) if m.group(2) is not None else 1
            in_hunk = old_left > 0 or new_left > 0
            continue
        if line.startswith("new file mode "):
            cur["new"], cur["mode"] = True, line.split()[-1]
        elif line.startswith("deleted file mode "):
            cur["deleted"] = True
        elif line.startswith("new mode "):
            cur["mode"] = line.split()[-1]
        elif line.startswith("old mode "):
            pass
        elif line.startswith("index "):
            parts = line.split()
            if len(parts) == 3 and not cur["mode"]:
                cur["mode"] = parts[2]
        elif line.startswith("--- "):
            if line[4:] not in ("/dev/null", f"a/{cur['path']}"):
                problems.append(f"file header mismatch in {cur['path']}")
        elif line.startswith("+++ "):
            if line[4:] not in ("/dev/null", f"b/{cur['path']}"):
                problems.append(f"file header mismatch in {cur['path']}")
        elif line.startswith(("Binary files ", "GIT binary patch")):
            problems.append(f"binary change in {cur['path']}")
        elif line.startswith(("similarity index", "dissimilarity index", "rename ", "copy ")):
            problems.append(f"renames and copies are not allowed ({cur['path']})")
        else:
            problems.append(f"unexpected line in the patch header of {cur['path']}: {line[:60]!r}")
    if in_hunk:
        problems.append("the patch ends inside a hunk")
    if not files:
        problems.insert(0, "the patch is empty")
    for f in files:
        reason = scope.protected_reason(f["path"])
        if reason:
            problems.append(f"touches a protected path: {reason}")
        if f["mode"] and not f["deleted"] and f["mode"] not in ALLOWED_MODES:
            problems.append(f"{f['path']} would get mode {f['mode']} (only regular files are allowed)")
    if added + deleted > max_lines:
        problems.append(f"the patch changes {added + deleted} lines (limit {max_lines})")
    return {"files": [f["path"] for f in files], "entries": files, "added": added, "deleted": deleted,
            "problems": _unique(problems)}


def _unique(xs: list[str]) -> list[str]:
    seen, out = set(), []
    for x in xs:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def is_test_file(path: str) -> bool:
    return bool(TEST_FILE.search(path))


def check_test_integrity(entries: list[dict]) -> tuple[list[str], list[str]]:
    """(problems, new test files). A fix must add at least one test function and may not delete or
    weaken existing tests: in existing test files it may only add lines."""
    problems, new_tests, test_files = [], [], []
    for f in entries:
        if not is_test_file(f["path"]):
            continue
        if f["deleted"]:
            problems.append(f"deletes the test file {f['path']}")
            continue
        test_files.append(f["path"])
        if any(TEST_DEF.match(x) for x in f["added"]):
            new_tests.append(f["path"])
        skipping = next((x for x in f["added"] if SKIPPING.search(x)), None)
        if skipping is not None:
            problems.append(f"skips or disables tests in {f['path']}: {skipping.strip()[:60]}")
        if not f["new"]:
            for x in f["removed"]:
                if TEST_DEF.match(x):
                    problems.append(f"removes or renames a test in {f['path']}: {x.strip()[:60]}")
                elif ASSERTION.search(x):
                    problems.append(f"removes an assertion in {f['path']}: {x.strip()[:60]}")
                else:
                    problems.append(f"changes existing test code in {f['path']} (only additions are allowed)")
                break
    if not new_tests:
        problems.insert(0, "adds no regression test (no new `def test_...` in a test file)")
    return _unique(problems), test_files


def _test_functions(tree: ast.Module) -> tuple[dict, list[str]]:
    """{(class or "", name): node} for test functions, and the names defined twice in one scope."""
    found, dups = {}, []
    scopes = [("", tree.body)] + [(n.name, n.body) for n in tree.body if isinstance(n, ast.ClassDef)]
    for scope_name, body in scopes:
        seen = set()
        for n in body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test"):
                if n.name in seen:
                    dups.append(f"{scope_name + '.' if scope_name else ''}{n.name}")
                seen.add(n.name)
                found[(scope_name, n.name)] = n
    return found, dups


def check_test_sources(path: str, before: str | None, after: str) -> list[str]:
    """Existing tests must be unchanged (same AST), no test may be defined twice in one scope, and no
    new test may return before it checks anything."""
    try:
        new = ast.parse(after)
    except SyntaxError as e:
        return [f"{path} does not parse: {e.msg}"]
    after_tests, dups = _test_functions(new)
    problems = [f"redefines {d} in {path}" for d in dups]
    before_tests = {}
    if before is not None:
        try:
            before_tests, _ = _test_functions(ast.parse(before))
        except SyntaxError:
            before_tests = {}
    for key, node in before_tests.items():
        name = ".".join(x for x in key if x)
        if key not in after_tests:
            problems.append(f"removes the test {name} in {path}")
        elif ast.dump(node) != ast.dump(after_tests[key]):
            problems.append(f"changes the existing test {name} in {path}")
    for key, node in after_tests.items():
        body = [b for b in node.body if not (isinstance(b, ast.Expr) and isinstance(getattr(b, "value", None), ast.Constant)
                                              and isinstance(b.value.value, str))]
        if key not in before_tests and body and isinstance(body[0], ast.Return):
            problems.append(f"the new test {'.'.join(x for x in key if x)} in {path} returns before checking anything")
    return problems


def check_staged_raw(raw: str) -> list[str]:
    """`git diff --cached --raw -z --no-renames` after `git apply --index`: paths and modes again."""
    problems = []
    parts = raw.split("\0")
    i = 0
    while i < len(parts) - 1:
        meta, path = parts[i], parts[i + 1]
        i += 2
        if not meta.startswith(":"):
            problems.append(f"cannot read the applied change list near {meta[:40]!r}")
            break
        fields = meta[1:].split()
        new_mode = fields[1] if len(fields) > 1 else "?"
        reason = scope.protected_reason(path)
        if reason:
            problems.append(f"touches a protected path: {reason}")
        if new_mode not in ALLOWED_MODES + ("000000",):
            problems.append(f"{path} would get mode {new_mode}")
    return problems


# ---------------------------------------------------------------------------------- tests


def test_count(output: str) -> int | None:
    m = list(re.finditer(r"^Ran (\d+) tests? in ", output, re.M))
    if m:
        return int(m[-1].group(1))
    m = list(re.finditer(r"\b(\d+) passed\b", output))
    if m:
        return int(m[-1].group(1))
    if re.search(r"\bno tests ran\b", output):
        return 0
    return None


def test_results(output: str) -> tuple[set | None, set, int | None]:
    """(names that ran, names that failed or errored, skipped count) from unittest -v or pytest -v output."""
    names: set = set()
    failed: set = set()
    lines = output.splitlines()
    for i, line in enumerate(lines):
        m = PYTEST_V.match(line)
        if m:
            names.add(m.group(1))
            if m.group(2) in ("FAILED", "ERROR"):
                failed.add(m.group(1))
            continue
        m = UNITTEST_V.match(line)
        if not m:
            continue
        name, where = m.group(1), m.group(2)
        sm = STATUS_LINE.search(line)
        if not sm and i + 1 < len(lines) and not UNITTEST_V.match(lines[i + 1]):
            sm = STATUS_LINE.search(lines[i + 1])  # a docstring line carries the status
        status = sm.group(1) if sm else None
        if status is None:
            continue
        tid = where if where.endswith("." + name) else f"{where}.{name}"
        names.add(tid)
        if status in ("FAIL", "ERROR", "unexpected success"):
            failed.add(tid)
    sk = list(re.finditer(r"skipped=(\d+)|\b(\d+) skipped\b", output))
    skipped = int(sk[-1].group(1) or sk[-1].group(2)) if sk else (0 if names else None)
    return (names or None), failed, skipped


def verbose(command: str) -> str:
    """The same test command with per-test names in its output (unittest and pytest)."""
    argv = shlex.split(command)
    if ("unittest" in argv or any(os.path.basename(a).startswith("pytest") for a in argv[:3])) and "-v" not in argv:
        return command + " -v"
    return command


def test_summary(output: str, returncode: int) -> str:
    lines = [ln.strip() for ln in output.splitlines() if ln.strip()]
    ran = next((ln for ln in reversed(lines) if re.match(r"^Ran \d+ tests? in ", ln)), None)
    last = lines[-1].strip("= ") if lines else f"exit {returncode}"
    s = f"{ran}: {last}" if ran and last != ran else last
    s = " ".join(s.split())
    return scrub_text(s if len(s) <= 160 else s[:159] + "…")


def run_tests(tree_dir: str, command: str, script: str, timeout: int = TEST_TIMEOUT) -> dict:
    """Run the test command in the sandbox (run-tests.sh) over a directory. Never on the runner.

    `error` is True when the sandbox itself failed (timeout, docker, no test report), as opposed to
    tests that ran and failed."""
    env = {k: os.environ[k] for k in ("PATH", "HOME", "DOCKER_HOST", "DOCKER_CONFIG", "TMPDIR") if k in os.environ}
    base = {"command": command, "passed": False, "count": None, "names": None, "failed": [], "skipped": None,
            "error": True}
    try:
        r = subprocess.run(["bash", script, tree_dir, *shlex.split(command)], capture_output=True, text=True,
                           timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        return {**base, "summary": f"timed out after {timeout} s"}
    except (OSError, ValueError) as e:
        return {**base, "summary": f"could not run: {e}"[:160]}
    out = (r.stdout or "") + "\n" + (r.stderr or "")
    names, failed, skipped = test_results(out)
    count = test_count(out)
    return {"command": command, "passed": r.returncode == 0, "count": count,
            "names": sorted(names) if names is not None else None, "failed": sorted(failed), "skipped": skipped,
            "error": count is None, "summary": test_summary(out, r.returncode)}


# ---------------------------------------------------------------------------------- fix-check


def one_line(s, limit: int) -> str:
    s = " ".join(str(s or "").split())
    return s if len(s) <= limit else s[: limit - 1].rstrip() + "…"


def clean_summary(s) -> str:
    s = one_line(s, 200)
    s = re.sub(r"^(fix(\([^)]*\))?:\s*)", "", s, flags=re.I)
    return one_line(s.rstrip("."), 72) or "restore the documented behavior"


def load_report(raw: str | None) -> dict | None:
    if not raw or not raw.strip():
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def evaluate(report: dict | None, patch: str, test_command: str, sandbox: Sandbox, max_lines: int = MAX_LINES,
             source_check: Callable[[list[dict]], list[str]] | None = None) -> dict:
    """The decision on one patch: proposed or rejected, with the reason and the test results.

    sandbox(kind) runs the suite (verbose) in the container over: "before" the original tree, "after"
    the patched tree, "regression" the original tree plus the patch's test files (the new test must
    fail there). source_check(entries) compares test files before and after (AST).
    """
    chk = check_patch_text(patch, max_lines) if patch.strip() else {"files": [], "entries": [], "added": 0,
                                                                     "deleted": 0, "problems": ["the patch is empty"]}
    out = {"files": chk["files"], "lines": {"added": chk["added"], "deleted": chk["deleted"]},
           "changes": [{"path": e["path"], "added": len(e["added"]), "removed": len(e["removed"])}
                       for e in chk["entries"]],
           "tests": {"command": test_command, "passed": None, "summary": "not run"}, "test_files": []}

    def reject(reason: str, problems: list[str] | None = None) -> dict:
        more = f" (and {len(problems) - 1} more)" if problems and len(problems) > 1 else ""
        return {**out, "status": "rejected", "reason": reason + more,
                "secret": any("secret-looking" in x for x in (problems or [reason]))}

    if report is None:
        return reject("the fix agent did not finish (no report)")
    if not patch.strip():
        why = one_line(report.get("notes") or report.get("summary") or "", 200)
        return reject("the agent made no change" + (f": {why}" if why else ""))
    if chk["problems"]:
        return reject(chk["problems"][0], chk["problems"])
    problems, test_files = check_test_integrity(chk["entries"])
    out["test_files"] = test_files
    if not problems and source_check:
        problems = source_check(chk["entries"])
    if problems:
        return reject(problems[0], problems)

    before = sandbox("before")
    after = sandbox("after")
    out["tests"] = {"command": test_command, "passed": after.get("passed"), "summary": after.get("summary"),
                    "count": after.get("count"), "before_count": before.get("count"),
                    "before_passed": before.get("passed"), "before_summary": before.get("summary"),
                    "skipped": after.get("skipped"), "before_skipped": before.get("skipped")}
    if not after.get("passed"):
        return reject(f"the tests fail after the change: {after.get('summary')}")
    if after.get("count") is None:
        return reject(f"could not read how many tests ran after the change: {after.get('summary')}")
    if after["count"] == 0:
        return reject("no tests ran after the change")
    if before.get("count") is None:
        return reject(f"could not read how many tests ran before the change: {before.get('summary')}")
    if after["count"] < before["count"] + 1:
        return reject(f"the suite ran {after['count']} tests after the change and {before['count']} before; "
                      "the new test did not run")
    if after.get("names") is None or before.get("names") is None:
        return reject("could not read the test names from the test output")
    gone = sorted(set(before["names"]) - set(after["names"]))
    if gone:
        return reject(f"{gone[0]} ran before the change but not after", [f"{g} no longer runs" for g in gone])
    if (after.get("skipped") or 0) > (before.get("skipped") or 0):
        return reject(f"the change skips more tests ({after.get('skipped')}) than before ({before.get('skipped') or 0})")
    new_ids = set(after["names"]) - set(before["names"])
    out["tests"]["new_tests"] = sorted(new_ids)

    regression = sandbox("regression")
    out["tests"]["regression_summary"] = regression.get("summary")
    if regression.get("error") or regression.get("count") is None:
        # The sandbox failed, not the test: say so; this is the only way to propose without the proof.
        out["tests"]["regression_test_verified"] = False
        out["tests"]["regression_error"] = True
        return {**out, "status": "proposed", "reason": ""}
    if regression.get("passed"):
        return reject("the regression test passes on the unfixed code, so it does not catch the bug")
    if not (set(regression.get("failed") or []) & new_ids or before.get("passed")):
        return reject("could not show that the new test fails on the unfixed code (the suite already failed before)")
    out["tests"]["regression_test_verified"] = True
    return {**out, "status": "proposed", "reason": ""}


def fix_record(decision: dict, report: dict | None, findings: dict | None, issue: int, repo: str, base_sha: str,
               patch: str) -> dict:
    report = report or {}
    f = findings if isinstance(findings, dict) else {}
    lc = f.get("likely_cause") if isinstance(f.get("likely_cause"), dict) else {}
    kv, cv = (lc or {}).get("code_verified") or {}, (lc or {}).get("change_verified") or {}
    risk = report.get("risk") if report.get("risk") in ("low", "medium", "high") else "medium"
    rec = {
        "status": decision["status"], "reason": decision.get("reason") or "",
        "summary": clean_summary(report.get("summary")), "root_cause": one_line(report.get("root_cause"), 600),
        "files": decision.get("files") or [], "test_files": decision.get("test_files") or [],
        "changes": decision.get("changes") or [],
        "lines": decision.get("lines"), "tests": decision.get("tests"),
        "agent_tests_passed": report.get("tests_passed"), "risk": risk, "notes": one_line(report.get("notes"), 800),
        "issue": issue, "repo": repo, "base_sha": base_sha,
        "patch_sha256": hashlib.sha256(patch.encode()).hexdigest() if patch else None,
        "docs_rule": _docs_rule(f),
        "likely_cause": {"explanation": lc.get("explanation"), "code_path": kv.get("path"), "code_line": kv.get("line"),
                         "code_link": kv.get("link"), "change_link": cv.get("link"),
                         "change": (f"PR #{cv['number']}" if cv.get("number") else (cv.get("sha") or "")[:10]) or None}
        if lc else None,
    }
    return scrub(rec)


def make_sandbox(app_dir: str, base_tree: str, after_tree: str, test_files: Callable[[], list[str]],
                 test_command: str, script: str) -> Sandbox:
    def sandbox(kind: str) -> dict:
        with tempfile.TemporaryDirectory(prefix="bug-investigator-tree-") as d:
            materialize(app_dir, after_tree if kind == "after" else base_tree, d)
            if kind == "regression":
                with tempfile.TemporaryDirectory(prefix="bug-investigator-after-") as a:
                    materialize(app_dir, after_tree, a)
                    for rel in test_files():
                        os.makedirs(os.path.dirname(os.path.join(d, rel)) or d, exist_ok=True)
                        shutil.copyfile(os.path.join(a, rel), os.path.join(d, rel))
            return run_tests(d, verbose(test_command), script)
    return sandbox


def make_source_check(app_dir: str, base_tree: str, after_tree: str) -> Callable[[list[dict]], list[str]]:
    def show(tree: str, path: str) -> str | None:
        try:
            return _git(app_dir, "show", f"{tree}:{path}")
        except CommandError:
            return None

    def check(entries: list[dict]) -> list[str]:
        problems = []
        for e in entries:
            if is_test_file(e["path"]) and e["path"].endswith(".py") and not e["deleted"]:
                problems += check_test_sources(e["path"], None if e["new"] else show(base_tree, e["path"]),
                                               show(after_tree, e["path"]) or "")
        return problems
    return check


def check_main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="fix-check")
    p.add_argument("--mode", default="full")
    p.add_argument("--work-dir", required=True)
    p.add_argument("--app-dir", required=True)
    p.add_argument("--action-path", required=True)
    p.add_argument("--findings")
    p.add_argument("--issue", type=int, required=True)
    p.add_argument("--repo", required=True)
    p.add_argument("--test-command", default=DEFAULT_TEST_COMMAND)
    p.add_argument("--max-lines", type=int, default=MAX_LINES)
    p.add_argument("--execution-file", help="the fix agent's log; copied scrubbed, never when a secret was found")
    a = p.parse_args(argv)
    out_path = os.path.join(a.work_dir, f"fix-{a.mode}.json")
    patch_path = os.path.join(a.work_dir, "fix.patch")
    report = load_report(os.environ.get("FIX_JSON"))
    findings = read_json(a.findings) if a.findings and os.path.isfile(a.findings) else None
    script = os.path.join(a.action_path, "run-tests.sh")
    base: dict = {}
    patch = ""
    decision: dict | None = None
    try:
        base = read_json(os.path.join(a.work_dir, "fix-base.json"))
        saved_config = os.path.join(state_dir(a.work_dir), "gitconfig")
        if file_sha256(git_config_path(a.app_dir)) != base.get("git_config_sha256"):
            # Nothing should be able to change it (writes under .git are blocked); if it changed, put the
            # original back before any git command reads it, and propose nothing.
            shutil.copyfile(saved_config, git_config_path(a.app_dir))
            decision = {"status": "rejected", "reason": "the checkout's .git/config changed during the fix",
                        "files": []}
        else:
            with tempfile.TemporaryDirectory() as tmp:
                after = snapshot(a.app_dir, os.path.join(tmp, "index"))
            patch = diff_trees(a.app_dir, base["tree"], after)
            holder: dict = {}

            def test_files() -> list[str]:
                return holder.get("test_files") or []

            sandbox = make_sandbox(a.app_dir, base["tree"], after, test_files, a.test_command, script)
            if patch.strip():
                holder["test_files"] = check_test_integrity(check_patch_text(patch, a.max_lines)["entries"])[1]
            decision = evaluate(report, patch, a.test_command, sandbox, a.max_lines,
                                make_source_check(a.app_dir, base["tree"], after))
    except Exception as e:  # any failure here means no PR
        decision = {"status": "rejected", "reason": f"could not check the fix: {e}"[:300], "files": []}
    finally:
        try:
            reset_checkout(a.app_dir)
        except CommandError as e:
            print(f"::warning::could not reset the checkout: {e}", file=sys.stderr)
    decision.setdefault("tests", {"command": a.test_command, "passed": None, "summary": "not run"})
    proposed = decision.get("status") == "proposed"
    rec = fix_record(decision, report, findings, a.issue, a.repo, base.get("head") or "", patch if proposed else "")
    write_json(out_path, rec)
    # Only a proposed patch is kept: a rejected one may hold anything (a secret, say). Its file list,
    # line counts and the reason are in fix-<mode>.json.
    if proposed:
        with open(patch_path, "w") as f:
            f.write(patch)
    elif os.path.exists(patch_path):
        os.remove(patch_path)
    if a.execution_file and os.path.isfile(a.execution_file) and not decision.get("secret"):
        with open(a.execution_file, errors="replace") as f:
            log = scrub_text(f.read())
        with open(os.path.join(a.work_dir, "claude-execution-fix.json"), "w") as f:
            f.write(log)
    print(f"fix-check: {rec['status']}" + (f" ({rec['reason']})" if rec["reason"] else "")
          + f"; files {rec['files']}; tests {json.dumps(rec['tests'])}; patch sha256 {rec['patch_sha256']}")
    return 0


# ---------------------------------------------------------------------------------- fix-prep


def selftest_fix_hook(hook_cmd: str, app_dir: str, run_command: str, test_command: str) -> list[str]:
    """The fix hook must block protected and outside writes, host test runs, other commands and MCP,
    and allow the exact sandboxed test command and ordinary source and test edits."""
    cases = [
        ({"tool_name": "Write", "tool_input": {"file_path": os.path.join(app_dir, ".github/workflows/x.yml")}}, 2),
        ({"tool_name": "Edit", "tool_input": {"file_path": os.path.join(app_dir, "docs/x.md")}}, 2),
        ({"tool_name": "Write", "tool_input": {"file_path": os.path.join(app_dir, ".git", "config")}}, 2),
        ({"tool_name": "Write", "tool_input": {"file_path": os.path.join(app_dir, "pyproject.toml")}}, 2),
        ({"tool_name": "Write", "tool_input": {"file_path": "/etc/passwd"}}, 2),
        ({"tool_name": "Bash", "tool_input": {"command": test_command}}, 2),  # never on the runner
        ({"tool_name": "Bash", "tool_input": {"command": "python3 -m unittest"}}, 2),
        ({"tool_name": "Bash", "tool_input": {"command": run_command + " -k x"}}, 2),
        ({"tool_name": "Bash", "tool_input": {"command": "curl https://example.com"}}, 2),
        ({"tool_name": "mcp__grafana__query_loki_logs", "tool_input": {}}, 2),
        ({"tool_name": "Bash", "tool_input": {"command": run_command}}, 0),
        ({"tool_name": "Bash", "tool_input": {"command": "git diff"}}, 0),
        ({"tool_name": "Write", "tool_input": {"file_path": os.path.join(app_dir, "tests/test_bug_investigator_x.py")}}, 0),
    ]
    problems = []
    for payload, want in cases:
        r = subprocess.run(["bash", "-c", hook_cmd], input=json.dumps(payload), capture_output=True, text=True,
                           timeout=30)
        if r.returncode != want:
            problems.append(f"fix hook returned {r.returncode}, want {want}, for {payload['tool_name']} "
                            f"{json.dumps(payload['tool_input'])[:80]}: {r.stderr.strip()[:200]}")
    return problems


def install_run_tests(action_path: str, app_dir: str, test_command: str, work_dir: str) -> str:
    """Write the `run-tests` wrapper into a bin dir under RUNNER_TEMP (Claude may not read or edit
    there) and put that dir on PATH for the later steps through GITHUB_PATH. Returns the wrapper's path."""
    # Never inside work_dir: that folder is uploaded as the run's artifact.
    base = os.environ.get("RUNNER_TEMP") or os.path.dirname(os.path.abspath(work_dir))
    bin_dir = os.path.join(base, "bug-investigator-bin")
    os.makedirs(bin_dir, exist_ok=True)
    path = os.path.join(bin_dir, settings.RUN_TESTS)
    if os.path.exists(path):
        os.chmod(path, 0o755)
    with open(path, "w") as f:
        f.write(settings.run_tests_wrapper(action_path, app_dir, test_command))
    os.chmod(path, 0o555)
    gh_path = os.environ.get("GITHUB_PATH")
    if gh_path:
        with open(gh_path, "a") as f:
            f.write(bin_dir + "\n")
    return path


def secrets_gone(token_file: str | None, env: dict) -> str | None:
    """The fix agent starts only after the Grafana token is deleted and in no environment variable."""
    if token_file and os.path.exists(token_file):
        return "the Grafana token file still exists"
    leaked = sorted(k for k in env if "GRAFANA" in k.upper() and "TOKEN" in k.upper())
    if leaked:
        return f"Grafana token variables are set: {', '.join(leaked)}"
    return None


def prep_main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="fix-prep")
    p.add_argument("--mode", required=True)
    p.add_argument("--enabled", default="true")
    p.add_argument("--findings", required=True)
    p.add_argument("--issue", type=int, required=True)
    p.add_argument("--repo", required=True)
    p.add_argument("--app-dir", required=True)
    p.add_argument("--action-path", required=True)
    p.add_argument("--work-dir", required=True)
    p.add_argument("--deny-dir", action="append", default=[])
    p.add_argument("--token-file", help="where the Grafana token was; it must be gone")
    p.add_argument("--model", default="claude-sonnet-5-5")
    p.add_argument("--max-turns", type=int, default=30)
    p.add_argument("--test-command", default=DEFAULT_TEST_COMMAND)
    p.add_argument("--skip-pull", action="store_true", help="tests only")
    a = p.parse_args(argv)
    out = os.environ.get("GITHUB_OUTPUT")
    findings = None
    if os.path.isfile(a.findings):
        try:
            findings = read_json(a.findings)
        except (OSError, ValueError):
            findings = None
    enabled = str(a.enabled).strip().lower() in ("true", "1", "yes")
    reason = eligibility(findings, a.mode, enabled) or settings.check_test_command(a.test_command)
    run_py = os.path.join(a.action_path, "run.py")
    script = os.path.join(a.action_path, "run-tests.sh")
    roots = [a.app_dir]
    run_command = ""
    if not reason:
        reason = secrets_gone(a.token_file, dict(os.environ))
    if not reason:
        try:
            run_command = settings.run_tests_command(a.action_path, a.app_dir, a.test_command)
            install_run_tests(a.action_path, a.app_dir, a.test_command, a.work_dir)
        except (ValueError, OSError) as e:
            reason = str(e)
    if not reason and not a.skip_pull:
        r = subprocess.run(["bash", script, "--pull"], capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            reason = f"could not pull the test sandbox image: {r.stderr.strip()[:200]}"
    if not reason:
        # The repo's own agent settings never apply (they were removed before the investigation too).
        for rel in (".claude/settings.json", ".claude/settings.local.json", ".mcp.json"):
            try:
                os.remove(os.path.join(a.app_dir, rel))
            except FileNotFoundError:
                pass
        try:
            head = _git(a.app_dir, "rev-parse", "HEAD").strip()
            sdir = state_dir(a.work_dir)
            os.makedirs(sdir, mode=0o700, exist_ok=True)
            tree = snapshot(a.app_dir, os.path.join(sdir, "base.index"))
            shutil.copyfile(git_config_path(a.app_dir), os.path.join(sdir, "gitconfig"))
            write_json(os.path.join(a.work_dir, "fix-base.json"),
                       {"head": head, "tree": tree, "git_config_sha256": file_sha256(git_config_path(a.app_dir))})
        except (CommandError, OSError) as e:
            reason = f"could not record the checkout's state: {e}"[:300]
    if not reason:
        hook_cmd = settings.hook_command(run_py, "fix", roots, scope.NAMESPACE, (run_command,))
        problems = selftest_fix_hook(hook_cmd, a.app_dir, run_command, a.test_command)
        if problems:
            for x in problems:
                print(f"fix-prep: {x}", file=sys.stderr)
            reason = "the fix hook self-test failed"
    if reason:
        if a.mode == "full":
            write_json(os.path.join(a.work_dir, f"fix-{a.mode}.json"), {"status": "skipped", "reason": reason})
        settings.set_output(out, "eligible", "false")
        print(f"fix-prep: no fix attempt: {reason}")
        return 0

    deny = [a.action_path, a.work_dir] + a.deny_dir
    settings_path = os.path.join(a.work_dir, "fix-settings.json")
    write_json(settings_path, settings.build_settings(run_py, "fix", roots, scope.NAMESPACE, deny, run_command))
    with open(os.path.join(a.action_path, "fix.schema.json")) as f:
        schema = json.load(f)
    claude_args = settings.build_claude_args("fix", a.model, a.max_turns, schema, None, [], run_command)
    with open(os.path.join(a.action_path, "fix_prompt.md")) as f:
        prompt = build_prompt(f.read(), findings, a.issue, a.repo, run_command)
    with open(os.path.join(a.work_dir, "fix-prompt.txt"), "w") as f:
        f.write(prompt)
    settings.set_output(out, "eligible", "true")
    settings.set_output(out, "settings", settings_path)
    settings.set_output(out, "claude_args", claude_args)
    settings.set_output(out, "prompt", prompt)
    print(f"fix-prep: trying a fix; prompt {len(prompt)} chars; tests: {run_command}")
    return 0


# ---------------------------------------------------------------------------------- propose


def pr_title(fix: dict) -> str:
    return f"fix: {clean_summary(fix.get('summary'))}"


def pr_body(fix: dict, issue: int, comment_url: str = "", run_url: str = "") -> str:
    tests = fix.get("tests") if isinstance(fix.get("tests"), dict) else {}
    out = [f"Proposed fix for #{issue}: {inline(clean_summary(fix.get('summary')))}.", "",
           "### What was wrong", "", t(fix.get("root_cause") or "(not given)"), ""]
    lc = fix.get("likely_cause") if isinstance(fix.get("likely_cause"), dict) else None
    if lc and lc.get("code_link"):
        where = f"{lc.get('code_path')}" + (f"#L{lc['code_line']}" if lc.get("code_line") else "")
        intro = f", introduced by [{inline(lc['change'])}]({lc['change_link']})" if lc.get("change_link") else ""
        out += [f"The investigation traced it to [`{inline(where)}`]({lc['code_link']}){intro}.", ""]
    dr = fix.get("docs_rule") if isinstance(fix.get("docs_rule"), dict) else None
    if dr and dr.get("link"):
        quote = "\n".join("> " + t(x) for x in str(dr.get("quote") or "").strip().splitlines())
        rid = f"rule **{inline(dr['rule_id'])}**, " if dr.get("rule_id") else ""
        out += ["### The documented rule it restores", "", quote, "",
                f"— {rid}[`{inline(dr.get('path'))}#L{dr.get('line')}`]({dr['link']})", ""]
    out += ["### Files changed", ""] + [f"- `{inline(x)}`" for x in fix.get("files") or []] + [""]
    status = "✅ passed" if tests.get("passed") else "❌ failed"
    counts = ""
    if tests.get("count") is not None and tests.get("before_count") is not None:
        counts = f"; {tests['count']} tests after the change, {tests['before_count']} before"
    out += ["### Tests", "",
            f"- `{inline(tests.get('command'))}`: {status} ({inline(tests.get('summary'))}{counts}).",
            "- Tests passed in an isolated sandbox during the investigation (no network, no secrets), on exactly "
            "this patch.",
            ("- Regression test: ✅ fails on the original code and passes with the fix."
             if tests.get("regression_test_verified") else
             "- Regression test: ⚠️ **not confirmed** to fail on the original code: the sandbox run on the original "
             f"code did not complete ({inline(tests.get('regression_summary') or 'not run')}). Check it by hand."),
            f"- CI has not run on this branch: after reviewing the diff, start it from Actions → ci → Run workflow "
            f"on `{BRANCH.format(issue=issue)}`.", ""]
    out += ["### Context", ""]
    out.append(f"- Investigation: {comment_url}" if comment_url else f"- Investigation: see #{issue}")
    if run_url:
        out.append(f"- Run: {run_url}")
    out += [f"- Risk (the agent's estimate): **{inline(fix.get('risk') or 'medium')}**", ""]
    if fix.get("notes"):
        out += ["### Notes from the agent", "", t(fix["notes"]), ""]
    out += ["---", "Opened by the bug investigator. A person must review and merge it; nothing merges automatically.",
            "", f"Fixes #{issue}", ""]
    return scrub_text("\n".join(out))


def followup_body(fix: dict, number: int) -> str:
    tests = fix.get("tests") if isinstance(fix.get("tests"), dict) else {}
    return scrub_text(f"{FIX_MARKER}\n🛠 Proposed fix: #{number} — {inline(clean_summary(fix.get('summary')))}. "
                      f"Tests: {inline(tests.get('summary') or 'passed')}. Review and merge to ship it.\n")


def _bot_comment(comments: list[dict], marker: str) -> dict | None:
    for c in comments:
        user = c.get("user") or {}
        if marker in (c.get("body") or "") and (user.get("type") == "Bot" or str(user.get("login", "")).endswith("[bot]")):
            return c
    return None


def find_fix(art_dir: str) -> str | None:
    found = sorted(glob.glob(os.path.join(art_dir, "**", "fix-full.json"), recursive=True))
    return found[0] if found else None


def propose(repo: str, issue: int, art_dir: str, app_dir: str, runner: Runner = run, label: str = LABEL,
            run_url: str = "", max_lines: int = MAX_LINES) -> str:
    """Open or update the fix PR. Returns what happened; raises ProposeError when it refuses.

    It starts no CI: agent-written code runs in CI only after a person has read it and started CI."""
    path = find_fix(art_dir)
    if not path:
        return "no fix-full.json; nothing to propose"
    fix = read_json(path)
    if not isinstance(fix, dict) or fix.get("status") != "proposed":
        return f"no fix proposed: {fix.get('reason') if isinstance(fix, dict) else 'unreadable fix file'}"
    patch_path = os.path.join(os.path.dirname(path), "fix.patch")
    if not os.path.isfile(patch_path):
        raise ProposeError("fix.patch is missing")
    with open(patch_path) as f:
        patch = f.read()
    if hashlib.sha256(patch.encode()).hexdigest() != fix.get("patch_sha256"):
        raise ProposeError("fix.patch does not match the checksum recorded by the investigation job")
    chk = check_patch_text(patch, max_lines)
    problems = chk["problems"] + check_test_integrity(chk["entries"])[0]
    if problems:
        raise ProposeError("the patch failed the re-check: " + "; ".join(problems[:3]))
    base = str(fix.get("base_sha") or "")
    if not SHA40.match(base):
        raise ProposeError(f"bad base commit {base!r}")
    branch = BRANCH.format(issue=issue)

    def git(*args: str) -> str:
        return runner(["git", "-C", app_dir, *GIT_SAFE, *args])

    try:
        git("cat-file", "-e", f"{base}^{{commit}}")
    except CommandError:
        git("fetch", "--no-tags", "--quiet", "origin", base)
    git("checkout", "-q", "-B", branch, base)
    git("apply", "--index", "--whitespace=nowarn", os.path.abspath(patch_path))
    problems = check_staged_raw(git("diff", "--cached", "--raw", "-z", "--no-renames", "--no-abbrev", "HEAD"))
    if problems:
        raise ProposeError("the applied patch failed the re-check: " + "; ".join(problems[:3]))
    git("-c", f"user.name={BOT_NAME}", "-c", f"user.email={BOT_EMAIL}", "commit", "-q", "--no-verify",
        "-m", f"{pr_title(fix)} (#{issue})")
    git("push", "--force", "--quiet", "origin", f"HEAD:refs/heads/{branch}")

    default = (runner(["gh", "api", f"repos/{repo}", "--jq", ".default_branch"]) or "").strip() or "main"
    pages = run_json(runner, ["gh", "api", "--paginate", "--slurp", f"repos/{repo}/issues/{issue}/comments?per_page=100"]) or []
    comments = [c for page in pages for c in (page if isinstance(page, list) else [page]) if isinstance(c, dict)]
    inv = _bot_comment(comments, INVESTIGATION_MARKER.format(mode="full"))
    comment_url = (inv or {}).get("html_url") or ""

    body = pr_body(fix, issue, comment_url, run_url)
    existing = run_json(runner, ["gh", "pr", "list", "--repo", repo, "--head", branch, "--state", "open",
                                 "--json", "number,url"]) or []
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as bf:
        bf.write(body)
    try:
        if existing:
            number = int(existing[0]["number"])
            runner(["gh", "pr", "edit", str(number), "--repo", repo, "--title", pr_title(fix), "--body-file", bf.name])
            action = f"updated PR #{number}"
        else:
            try:
                runner(["gh", "label", "create", label, "--repo", repo, "--color", "5319E7",
                        "--description", "Opened by the bug investigator", "--force"])
            except CommandError as e:
                print(f"::warning::could not create label {label}: {e}", file=sys.stderr)
            url = runner(["gh", "pr", "create", "--repo", repo, "--base", default, "--head", branch,
                          "--title", pr_title(fix), "--body-file", bf.name]).strip().splitlines()[-1]
            m = re.search(r"/pull/(\d+)", url)
            if not m:
                raise ProposeError(f"could not read the new PR number from {url!r}")
            number = int(m.group(1))
            action = f"opened PR #{number}"
        try:
            runner(["gh", "pr", "edit", str(number), "--repo", repo, "--add-label", label])
        except CommandError as e:
            print(f"::warning::could not label PR #{number}: {e}", file=sys.stderr)
    finally:
        os.unlink(bf.name)

    note = followup_body(fix, number)
    own = _bot_comment(comments, FIX_MARKER)
    if own:
        runner(["gh", "api", "-X", "PATCH", f"repos/{repo}/issues/comments/{own['id']}", "-f", f"body={note}", "--silent"])
    else:
        runner(["gh", "api", "-X", "POST", f"repos/{repo}/issues/{issue}/comments", "-f", f"body={note}", "--silent"])
    return action


def propose_main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="propose")
    p.add_argument("--repo", required=True)
    p.add_argument("--issue", type=int, required=True)
    p.add_argument("--dir", required=True, help="downloaded artifacts (fix-full.json and fix.patch, searched recursively)")
    p.add_argument("--app-dir", default=os.environ.get("GITHUB_WORKSPACE") or ".")
    p.add_argument("--label", default=LABEL)
    a = p.parse_args(argv)
    server, repo_env, run_id = (os.environ.get(k) for k in ("GITHUB_SERVER_URL", "GITHUB_REPOSITORY", "GITHUB_RUN_ID"))
    run_url = f"{server}/{repo_env}/actions/runs/{run_id}" if server and repo_env and run_id else ""
    try:
        print("propose: " + propose(a.repo, a.issue, a.dir, a.app_dir, label=a.label, run_url=run_url))
    except (ProposeError, CommandError, ValueError, KeyError, OSError) as e:
        print(f"::error::no pull request opened: {e}", file=sys.stderr)
        return 1
    return 0
