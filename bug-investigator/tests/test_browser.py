"""The replay engine against a small fixture app.

Tests that need Chromium skip without Playwright; run them in the Playwright image (natively: an
amd64 Chromium crashes under QEMU on an arm64 Mac):

    docker run --rm -v "$PWD":/w -w /w/bug-investigator mcr.microsoft.com/playwright/python:v1.64.0-noble \
      sh -c 'pip install -q --break-system-packages playwright==1.64.0 pytest && python3 -m pytest -q -m browser'

The engine gives the app only a fixed environment, so a test passes FIXTURE_* settings through a
three-line server.py that sets them and runs the fixture.
"""

import base64
import fcntl
import json
import os
import signal
import subprocess
import time
import sys
from pathlib import Path

import pytest

from bug_investigator import browser

try:
    import playwright.sync_api  # noqa: F401

    HAVE_PLAYWRIGHT = True
except ImportError:
    HAVE_PLAYWRIGHT = False

needs_chromium = pytest.mark.skipif(not HAVE_PLAYWRIGHT, reason="needs Playwright and Chromium (the Playwright image)")

FIXTURE = Path(__file__).parent / "fixtures" / "ui-app" / "server.py"
ENGINE = Path(browser.__file__)
PNG = b"\x89PNG\r\n\x1a\n"
PRICING, COOKIE = "Write copy for the pricing page", "Update the cookie banner copy"
STATUS = {"role": "status"}
AS_DANA = {"do": "select", "target": {"label": "User"}, "value": "dana (editor)"}
START = {"do": "click", "target": {"role": "button", "name": "Start", "within": {"css": ".card", "text": PRICING}}}
DONE = {"do": "click", "target": {"role": "button", "name": "Done", "within": {"css": ".card", "text": COOKIE}}}
STARTED = {"do": "expect_text", "target": STATUS, "value": "moved to in progress by dana"}


def make_app(tmp_path, **env) -> str:
    """An app dir whose server.py sets env and runs the fixture."""
    d = tmp_path / "app"
    d.mkdir(parents=True)
    (d / "server.py").write_text(
        f"import os, runpy\nos.environ.update({env!r})\nrunpy.run_path({str(FIXTURE)!r}, run_name='__main__')\n"
    )
    return str(d)


# ------------------------------------------------------------------------- no browser needed


def test_invalid_steps_raise_before_anything_starts(tmp_path):
    for bad in ([{"do": "goto", "value": "//other.invalid"}], [{"do": "goto", "value": "/\\other.invalid"}], []):
        with pytest.raises(ValueError):
            browser.replay(str(tmp_path / "nowhere"), bad)
    with pytest.raises(ValueError, match="shots"):
        browser.replay(str(tmp_path / "nowhere"), [START], shots="some")


def test_lock_busy_is_browser_error(tmp_path, monkeypatch):
    monkeypatch.setattr(browser, "LOCK_WAIT_S", 0.3)
    with open(browser._lock_path(), "a") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        with pytest.raises(browser.BrowserError, match="lock"):
            browser.replay(str(tmp_path), [START])


def test_to_json():
    r = browser.Replay(
        ok=False, failed_at=2, commit="abc", seconds=1.5, snapshot="- heading", app_log=["l"], console=["c"],
        steps=[browser.StepResult(1, "click x", True, None, None),
               browser.StepResult(2, "click y", False, "no", PNG, "missing")],
    )
    doc = r.to_json()
    assert doc == {
        "ok": False, "failed_at": 2, "commit": "abc", "seconds": 1.5, "snapshot": "- heading",
        "app_log": ["l"], "console": ["c"],
        "steps": [{"n": 1, "text": "click x", "ok": True, "error": None, "failure": None},
                  {"n": 2, "text": "click y", "ok": False, "error": "no", "failure": "missing"}],
    }
    json.dumps(doc)
    with_png = r.to_json(include_png=True)["steps"]
    assert with_png[0]["png"] is None and base64.b64decode(with_png[1]["png"]) == PNG


# ------------------------------------------------------------------------------ in Chromium


@needs_chromium
@pytest.mark.browser
def test_all_steps_pass_on_fixture(tmp_path):
    steps = [
        AS_DANA, START, STARTED,
        {"do": "fill", "target": {"placeholder": "New task"}, "value": "Buy milk"},
        {"do": "press", "target": {"placeholder": "New task"}, "value": "Enter"},
        {"do": "expect_text", "target": STATUS, "value": "added Buy milk"},
        {"do": "goto", "value": "/nope"},  # a 404 is a page like any other
        {"do": "expect_visible", "target": {"text": "not found"}},
        {"do": "goto", "value": "/"},
        {"do": "expect_visible", "target": {"role": "button", "name": "Done", "within": {"css": ".card", "text": COOKIE}}},
        {"do": "expect_absent", "target": {"text": "Buy milk"}},
    ]
    r = browser.replay(make_app(tmp_path), steps, commit="abc123", shots="none")
    assert r.ok and r.failed_at is None, r.to_json()
    assert [(s.n, s.ok, s.error, s.failure, s.screenshot) for s in r.steps] == [
        (n, True, None, None, None) for n in range(1, 12)]
    assert r.steps[1].text == 'click button "Start" in .card "Write copy for the pricing page"'
    assert r.commit == "abc123" and 0 < r.seconds < 60
    assert 'heading "Fixture board"' in r.snapshot and len(r.snapshot) <= browser.SNAPSHOT_CHARS


@needs_chromium
@pytest.mark.browser
def test_missing_button_fails_at_that_step(tmp_path):
    r = browser.replay(make_app(tmp_path, FIXTURE_BROKEN="1"), [AS_DANA, DONE, STARTED], shots="none")
    assert not r.ok and r.failed_at == 2
    assert len(r.steps) == 2 and r.steps[0].ok  # the first failing step ends the run
    assert r.steps[1].error == 'no button "Done" in .card "Update the cookie banner copy" (0 matches)'
    assert r.steps[1].failure == "missing" and r.steps[0].failure is None


@needs_chromium
@pytest.mark.browser
def test_two_matches_fail_not_click(tmp_path):
    click_any_start = {"do": "click", "target": {"role": "button", "name": "Start"}}
    r = browser.replay(make_app(tmp_path), [AS_DANA, click_any_start], shots="none")
    assert r.failed_at == 2 and r.steps[1].error == 'button "Start" matched 2 elements'
    assert r.steps[1].failure == "ambiguous"
    assert not any("/api/act" in line for line in r.app_log), r.app_log  # nothing was clicked
    two_cards = {"do": "click", "target": {"role": "button", "name": "Start", "within": {"css": ".card", "text": "copy"}}}
    r = browser.replay(make_app(tmp_path / "2"), [two_cards], shots="none")
    assert r.failed_at == 1 and r.steps[0].error == '.card "copy" matched 2 elements'
    assert r.steps[0].failure == "ambiguous"


@needs_chromium
@pytest.mark.browser
def test_absent_waits_for_render(tmp_path):
    # The cards' data answers 800 ms late: checked at "load", no Start button exists yet.
    r = browser.replay(make_app(tmp_path, FIXTURE_DELAY_MS="800"),
                       [{"do": "expect_absent", "target": {"role": "button", "name": "Start"}}], shots="none")
    assert r.failed_at == 1 and r.steps[0].error == 'expected no button "Start", found 2'
    assert r.steps[0].failure == "mismatch"


@needs_chromium
@pytest.mark.browser
def test_waits_for_the_network_after_an_action(tmp_path):
    # /api/act answers 800 ms late: checked right after the click, the status is still empty.
    absent = {"do": "expect_absent", "target": {"text": "moved to in progress"}}
    r = browser.replay(make_app(tmp_path, FIXTURE_ACT_DELAY_MS="800"), [START, absent], shots="none")
    assert r.failed_at == 2 and r.steps[1].failure == "mismatch", r.to_json()
    assert r.steps[1].error == 'expected no text "moved to in progress", found 1'


@needs_chromium
@pytest.mark.browser
def test_checks_pass_on_any_match(tmp_path):
    # After Start, the pricing card's title and the status line both contain its title.
    title = {"text": PRICING}
    steps = [AS_DANA, START,
             {"do": "expect_visible", "target": title},
             {"do": "expect_text", "target": title, "value": "moved to in progress by dana"},
             {"do": "expect_visible", "target": {"role": "button", "name": "Start"}}]  # two cards, two Starts
    r = browser.replay(make_app(tmp_path), steps, shots="none")
    assert r.ok, r.to_json()


@needs_chromium
@pytest.mark.browser
def test_check_failures_say_why(tmp_path):
    def first_failure(steps, name):
        r = browser.replay(make_app(tmp_path / name), steps, shots="none")
        return r.failed_at, r.steps[-1].failure, r.steps[-1].error

    nope = {"do": "expect_visible", "target": {"role": "button", "name": "Nope"}}
    assert first_failure([nope], "missing") == (1, "missing", 'no button "Nope" (0 matches)')
    wrong = {"do": "expect_text", "target": {"text": PRICING}, "value": "moved to done"}
    assert first_failure([AS_DANA, START, wrong], "mismatch") == (
        3, "mismatch",
        f'no match for the text "{PRICING}" contains "moved to done" '
        f'(2 matches; the first reads "{PRICING} moved to in progress by dana")')  # the status line
    in_both = {"do": "expect_visible", "target": {"role": "button", "name": "Start",
                                                  "within": {"css": ".card", "text": "copy"}}}
    assert first_failure([in_both], "ambiguous") == (1, "ambiguous", '.card "copy" matched 2 elements')


@needs_chromium
@pytest.mark.browser
def test_malformed_steps_fail_invalid(tmp_path):
    # Ruling R13: a step that cannot run on any page is `invalid`, never `error` or `missing`, so verify never
    # counts it as a reproduction (the reviewer's probe: step 2 claimed).
    def second(step, name):
        r = browser.replay(make_app(tmp_path / name), [AS_DANA, step], shots="none")
        return r.failed_at, r.steps[-1].failure, r.steps[-1].error

    def within(css):
        return {"do": "click", "target": {"role": "button", "name": "Start", "within": {"css": css, "text": PRICING}}}

    failed_at, failure, error = second(within(".card["), "css")
    assert (failed_at, failure) == (2, "invalid"), error
    assert error.startswith('within css ".card[" is not a valid selector (Locator.count: Unexpected token'), error
    for name, css in (("xpath", "xpath=//div"), ("text", "text=Pricing"), ("nth", ".card:nth-match(x)")):
        assert second(within(css), name)[:2] == (2, "invalid"), css  # css= first: another engine does not parse
    press = {"do": "press", "target": {"placeholder": "New task"}, "value": "Entr"}
    assert second(press, "key") == (2, "invalid", '"Entr" is not a key Playwright can press '
                                                  '(Keyboard.press: Unknown key: "Entr")')
    nowhere = {"do": "press", "target": {"placeholder": "Nowhere"}, "value": "Control+Entr"}
    assert second(nowhere, "key-first")[:2] == (2, "invalid")  # the key is checked before the target is looked for
    assert second(dict(nowhere, value="Enter"), "missing")[:2] == (2, "missing")


@needs_chromium
@pytest.mark.browser
def test_replay_deadline_counts_app_start_and_load(tmp_path, monkeypatch):
    # Ruling R14: the whole replay has REPLAY_S, from Chromium's launch on. The board's data answers 4 s late and
    # the replay has 2 s, so the time is up before step 1: it fails `error`, and no later step runs.
    monkeypatch.setattr(browser, "REPLAY_S", 2)
    r = browser.replay(make_app(tmp_path, FIXTURE_DELAY_MS="4000"), [AS_DANA, START, STARTED], shots="none")
    assert r.failed_at == 1 and len(r.steps) == 1, r.to_json()
    assert (r.steps[0].failure, r.steps[0].error) == ("error", "the replay took longer than 2 s")
    assert r.seconds < 2 + 4  # the load's wait for the network stopped at the deadline too


@needs_chromium
@pytest.mark.browser
def test_replay_deadline_cuts_the_current_step_short(tmp_path, monkeypatch):
    # /api/act does not answer within the replay's 8 s: Start's click goes through, the network never settles,
    # and the status check runs out of time: step 3 fails `error` (not `mismatch`), step 4 never runs.
    monkeypatch.setattr(browser, "REPLAY_S", 8)
    steps = [AS_DANA, START, STARTED, {"do": "expect_visible", "target": {"role": "heading", "name": "Fixture board"}}]
    r = browser.replay(make_app(tmp_path, FIXTURE_ACT_DELAY_MS="30000"), steps, shots="none")
    assert r.failed_at == 3 and len(r.steps) == 3 and r.steps[1].ok, r.to_json()
    assert (r.steps[2].failure, r.steps[2].error) == ("error", "the replay took longer than 8 s")
    assert r.seconds < 8 + 5


@needs_chromium
@pytest.mark.browser
def test_other_origin_request_aborted(tmp_path):
    steps = [{"do": "click", "target": {"role": "link", "name": "Elsewhere"}},
             {"do": "expect_visible", "target": {"role": "heading", "name": "Fixture board"}}]
    r = browser.replay(make_app(tmp_path), steps, shots="none")
    assert r.ok, r.to_json()  # the page stayed on the app
    assert any("other.invalid" in line for line in r.console), r.console


@needs_chromium
@pytest.mark.browser
def test_shots_modes(tmp_path):
    passing = browser.replay(make_app(tmp_path / "a"), [AS_DANA, START], shots="failure")
    assert [s.n for s in passing.steps if s.screenshot] == [2]  # the last step
    assert passing.steps[1].screenshot.startswith(PNG)
    archive_all = {"do": "click", "target": {"role": "button", "name": "Archive all"}}  # disabled
    failing = browser.replay(make_app(tmp_path / "b"), [AS_DANA, archive_all, START], shots="failure")
    assert failing.failed_at == 2 and [s.n for s in failing.steps if s.screenshot] == [2]
    error = failing.steps[1].error  # a sentence, with Playwright's own words in parentheses
    assert error.startswith('button "Archive all" is not enabled (Locator.click: Timeout '), error
    assert failing.steps[1].failure == "error"
    every = browser.replay(make_app(tmp_path / "c"), [AS_DANA, START], shots="all")
    assert all(s.screenshot and s.screenshot.startswith(PNG) for s in every.steps)


@needs_chromium
@pytest.mark.browser
def test_app_log_captured(tmp_path, monkeypatch):
    monkeypatch.setenv("SECRET_TOKEN", "not for the app")
    r = browser.replay(make_app(tmp_path), [AS_DANA, START], commit="abc123", shots="none")
    lines = [json.loads(line) for line in r.app_log]
    start = lines[0]
    assert start["event"] == "start" and start["commit"] == "abc123"
    # Only the engine's fixed environment (Python may add LC_CTYPE when it coerces the C locale).
    allowed = {"PATH", "HOME", "PORT", "DB_PATH", "PYTHONDONTWRITEBYTECODE", "TASKBOARD_COMMIT", "LC_CTYPE"}
    assert set(start["env"]) <= allowed, start["env"]
    assert {"method": "GET", "path": "/api/cards", "status": 200} in lines
    assert {"method": "POST", "path": "/api/act", "status": 200} in lines
    assert len(r.app_log) <= browser.APP_LOG_LINES


@needs_chromium
@pytest.mark.browser
def test_app_not_starting_raises(tmp_path, monkeypatch):
    with pytest.raises(browser.BrowserError, match="server.py"):
        browser.replay(str(tmp_path), [START])
    crashing = tmp_path / "crashing"
    crashing.mkdir()
    (crashing / "server.py").write_text("print('boom: no config')\nraise SystemExit(3)\n")
    with pytest.raises(browser.BrowserError, match=r"exited with code 3.*boom: no config"):
        browser.replay(str(crashing), [START])
    monkeypatch.setattr(browser, "APP_START_S", 1)
    silent = tmp_path / "silent"
    silent.mkdir()
    (silent / "server.py").write_text("import time\ntime.sleep(60)\n")
    with pytest.raises(browser.BrowserError, match="healthz"):
        browser.replay(str(silent), [START])


@needs_chromium
@pytest.mark.browser
def test_browser_gone_is_browser_error_not_a_failing_step(tmp_path, monkeypatch):
    # A crashed or closed browser must never pass for "the step fails" (verify compares failed_at).
    do = browser._Session._do

    def closing_do(self, step):
        if step is START:
            self.page.close()
        return do(self, step)

    monkeypatch.setattr(browser._Session, "_do", closing_do)
    with pytest.raises(browser.BrowserError, match="during step 2"):
        browser.replay(make_app(tmp_path), [AS_DANA, START], shots="none")


@needs_chromium
@pytest.mark.browser
def test_app_process_group_stopped(tmp_path):
    r = browser.replay(make_app(tmp_path, FIXTURE_CHILD="1"), [AS_DANA], shots="none")
    pid = next(json.loads(line)["pid"] for line in r.app_log if '"child"' in line)
    deadline = time.monotonic() + 5
    while True:  # gone, or a zombie nobody reaps (orphans in a container)
        try:
            state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
        except FileNotFoundError:
            break
        if state == "Z" or time.monotonic() > deadline:
            assert state == "Z", f"the app's child {pid} is still running ({state})"
            break
        time.sleep(0.1)


def _state(pid: int) -> str | None:
    """The process's state letter (Z: a zombie), or None when it is gone."""
    if Path("/proc/self/stat").exists():
        try:
            return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
        except FileNotFoundError:
            return None
    try:  # no /proc (macOS): is it there at all, then ask ps for its state
        os.kill(pid, 0)
    except ProcessLookupError:
        return None
    except PermissionError:
        pass  # there, someone else's
    out = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
    return out[:1] or "?"


def test_app_stop_kills_a_child_that_ignores_sigterm(tmp_path):
    # SIGTERM to the app's process group, then always SIGKILL: a grandchild that ignores SIGTERM must not outlive
    # the replay. No browser needed.
    home = tmp_path / "home"
    home.mkdir()
    app = browser._App(make_app(tmp_path, FIXTURE_CHILD="ignore-term"), str(home), None)
    app.start()
    pid = None
    try:
        deadline = time.monotonic() + 10
        while not any('"child-ready"' in line for line in app.log):  # it ignores SIGTERM from here on
            assert time.monotonic() < deadline, list(app.log)
            time.sleep(0.05)
        pid = next(json.loads(line)["pid"] for line in app.log if '"child"' in line)
        app.stop()
        deadline = time.monotonic() + 5
        while _state(pid) not in (None, "Z"):  # gone, or a zombie nobody reaps (orphans in a container)
            assert time.monotonic() < deadline, f"the app's child {pid} survived stop() ({_state(pid)})"
            time.sleep(0.1)
    finally:
        if pid and _state(pid) not in (None, "Z"):
            os.kill(pid, signal.SIGKILL)


def _cli(*args):
    return subprocess.run([sys.executable, "-I", str(ENGINE), *args], capture_output=True, text=True, timeout=300)


def test_check_cli_exit_2_only_for_bad_arguments(tmp_path):
    p = _cli("check", "--app-dir", str(tmp_path), "--repros", str(tmp_path / "missing"), "--out", str(tmp_path / "o"))
    assert p.returncode == 2 and "cannot list --repros" in p.stderr, p.stderr
    assert _cli("check", "--app-dir", str(tmp_path)).returncode == 2  # usage


@needs_chromium
@pytest.mark.browser
def test_replay_cli(tmp_path):
    steps = tmp_path / "steps.json"
    steps.write_text(json.dumps([AS_DANA, START, STARTED]))
    out = tmp_path / "out"
    p = _cli("replay", "--app-dir", make_app(tmp_path), "--steps", str(steps), "--commit", "abc", "--out", str(out))
    assert p.returncode == 0, p.stdout + p.stderr
    result = json.loads((out / "result.json").read_text())
    assert result["ok"] and result["commit"] == "abc" and [s["n"] for s in result["steps"]] == [1, 2, 3]
    assert all((out / f"step-{n}.png").read_bytes().startswith(PNG) for n in (1, 2, 3))


@needs_chromium
@pytest.mark.browser
def test_check_cli_summary(tmp_path):
    repros = tmp_path / "repros"
    repros.mkdir()
    (repros / "good.json").write_text(json.dumps({"title": "Dana starts her task", "issue": 7,
                                                  "steps": [AS_DANA, START, STARTED]}))
    archive = {"do": "click", "target": {"role": "button", "name": "Archive", "within": {"css": ".card", "text": COOKIE}}}
    (repros / "broken.json").write_text(json.dumps({"title": "Archive the cookie card", "issue": 12,
                                                    "steps": [AS_DANA, archive]}))
    (repros / "bad.json").write_text(json.dumps({"title": "No steps", "steps": []}))
    (repros / "notes.txt").write_text("not a repro")
    out = tmp_path / "out"
    p = _cli("check", "--app-dir", make_app(tmp_path), "--repros", str(repros), "--out", str(out),
             "--changed", "ui-tests/repros/broken.json,bad.json")
    assert p.returncode == 1, p.stdout + p.stderr
    summary = json.loads((out / "summary.json").read_text())
    assert [{k: e[k] for k in ("file", "title", "issue", "ok", "failed_at", "changed")} for e in summary["repros"]] == [
        {"file": "bad.json", "title": None, "issue": None, "ok": False, "failed_at": None, "changed": True},
        {"file": "broken.json", "title": "Archive the cookie card", "issue": 12, "ok": False, "failed_at": 2,
         "changed": True},
        {"file": "good.json", "title": "Dana starts her task", "issue": 7, "ok": True, "failed_at": None,
         "changed": False},
    ]
    assert "steps must be a non-empty list" in summary["repros"][0]["error"]
    bad = json.loads((out / "bad" / "result.json").read_text())
    replay_keys = set(browser.Replay(False, None, [], "", [], [], None, 0.0).to_json())
    assert set(bad) == replay_keys | {"title", "issue", "error"} and not bad["ok"] and bad["steps"] == []
    good = json.loads((out / "good" / "result.json").read_text())
    assert good["title"] == "Dana starts her task" and good["issue"] == 7 and good["ok"]
    assert [s["n"] for s in good["steps"]] == [1, 2, 3]
    assert all((out / "good" / f"step-{n}.png").read_bytes().startswith(PNG) for n in (1, 2, 3))
    broken = json.loads((out / "broken" / "result.json").read_text())
    assert broken["failed_at"] == 2 and "0 matches" in broken["steps"][1]["error"]
    assert broken["steps"][1]["failure"] == "missing"
    assert (out / "broken" / "step-2.png").exists()
