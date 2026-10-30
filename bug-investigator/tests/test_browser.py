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
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest

from bug_investigator import browser
from bug_investigator import steps as stepfmt

try:
    import playwright.sync_api  # noqa: F401

    HAVE_PLAYWRIGHT = True
except ImportError:
    HAVE_PLAYWRIGHT = False

needs_chromium = pytest.mark.skipif(not HAVE_PLAYWRIGHT, reason="needs Playwright and Chromium (the Playwright image)")
# Linux only (/proc, prctl): marked `browser` too, so these run in the Playwright image.
linux_only = pytest.mark.skipif(not Path("/proc/self/stat").exists(), reason="needs Linux (the Playwright image)")

FIXTURE = Path(__file__).parent / "fixtures" / "ui-app" / "server.py"
ENGINE = Path(browser.__file__)
PNG = b"\x89PNG\r\n\x1a\n"
PRICING, REPORT = "Write copy for the pricing page", "Review the quarterly report"
STATUS = {"role": "status"}
AS_DANA = {"do": "select", "target": {"label": "User"}, "value": "dana (editor)"}
START = {"do": "click", "target": {"role": "button", "name": "Start", "within": {"css": ".card", "text": PRICING}}}
DONE = {"do": "click", "target": {"role": "button", "name": "Done", "within": {"css": ".card", "text": REPORT}}}
STARTED = {"do": "expect_text", "target": STATUS, "value": "moved to in progress by dana"}


@pytest.fixture(autouse=True)
def engine_tmpdir(tmp_path, monkeypatch) -> Path:
    """The engine's $TMPDIR (its lock, its pgid file, its temp dirs) in this test's own directory."""
    d = tmp_path / "tmpdir"
    d.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(d))
    return d


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
        {"do": "expect_visible",
         "target": {"role": "button", "name": "Done", "within": {"css": ".card", "text": REPORT}}},
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
    assert r.steps[1].error == 'no button "Done" in .card "Review the quarterly report" (0 matches)'
    assert r.steps[1].failure == "missing" and r.steps[0].failure is None


@needs_chromium
@pytest.mark.browser
def test_two_matches_fail_not_click(tmp_path):
    click_any_start = {"do": "click", "target": {"role": "button", "name": "Start"}}
    r = browser.replay(make_app(tmp_path), [AS_DANA, click_any_start], shots="none")
    assert r.failed_at == 2 and r.steps[1].error == 'button "Start" matched 2 elements'
    assert r.steps[1].failure == "ambiguous"
    assert not any("/api/act" in line for line in r.app_log), r.app_log  # nothing was clicked
    two_cards = {"do": "click",
                 "target": {"role": "button", "name": "Start", "within": {"css": ".card", "text": "the"}}}
    r = browser.replay(make_app(tmp_path / "2"), [two_cards], shots="none")
    assert r.failed_at == 1 and r.steps[0].error == '.card "the" matched 2 elements'
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
                                                  "within": {"css": ".card", "text": "the"}}}
    assert first_failure([in_both], "ambiguous") == (1, "ambiguous", '.card "the" matched 2 elements')


def within(css: str) -> dict:
    """Start on the pricing card, picked by a `within` with this css."""
    return {"do": "click", "target": {"role": "button", "name": "Start", "within": {"css": css, "text": PRICING}}}


BAD_KEY = {"do": "press", "target": {"placeholder": "New task"}, "value": "Entr"}


def native(css: str) -> str:
    """Chromium's words for a css its document.querySelector refuses."""
    return f"Failed to execute 'querySelector' on 'Document': '{css}' is not a valid selector."


def unforgiving(css: str) -> str:
    """The engine's words for a css querySelector forgives but the browser's unforgiving parse refuses."""
    return f"CSS.supports('selector(:is({css}))') is false"


@needs_chromium
@pytest.mark.browser
def test_malformed_steps_fail_invalid(tmp_path):
    # Ruling R13: a step that cannot run on any page is `invalid`, never `error` or `missing`, so verify never
    # counts it as a reproduction (the reviewer's probe: step 2 claimed). Ruling R16: every step is checked before
    # the run, so the replay stops there and the result holds that step alone.
    def second(step, name):
        r = browser.replay(make_app(tmp_path / name), [AS_DANA, step], shots="none")
        if r.steps[-1].failure == "invalid":
            assert [s.n for s in r.steps] == [2] and r.app_log == [], r.to_json()  # nothing ran
        return r.failed_at, r.steps[-1].failure, r.steps[-1].error

    assert second(within(".card["), "css") == (
        2, "invalid", f'within css ".card[" is not a valid CSS selector, so no step ran ({native(".card[")})')
    for name, css in (("xpath", "xpath=//div"), ("text", "text=Pricing"), ("nth", ".card:nth-match(x)"),
                      ("visible", ".card:visible"), ("has-text", ".card:has-text('x')")):
        # css= first, so another engine does not parse; nor do Playwright's own pseudo-classes: the browser's
        # document.querySelector is the judge.
        assert second(within(css), name) == (
            2, "invalid", f'within css "{css}" is not a valid CSS selector, so no step ran ({native(css)})'), css
    # querySelector reads a pseudo-element; the unforgiving parse does not (ruling R23).
    after = ".card::after"
    assert second(within(after), "pseudo-element") == (
        2, "invalid", f'within css "{after}" is not a valid CSS selector, so no step ran ({unforgiving(after)})')
    # Both of the browser's parses read a namespace wildcard; Playwright's parser does not. Also tried before the run.
    failed_at, failure, error = second(within("*|div"), "namespace")
    assert (failed_at, failure) == (2, "invalid"), error
    assert error.startswith('within css "*|div" is not a valid selector, so no step ran (Locator.count: '
                            'Unexpected token "|" while parsing css selector "*|div"'), error
    assert second(BAD_KEY, "key") == (2, "invalid", '"Entr" is not a key Playwright can press, so no step ran '
                                                    '(Keyboard.press: Unknown key: "Entr")')
    nowhere = {"do": "press", "target": {"placeholder": "Nowhere"}, "value": "Control+Entr"}
    assert second(nowhere, "key-first")[:2] == (2, "invalid")  # the key is checked before the target is looked for
    assert second(dict(nowhere, value="Enter"), "missing")[:2] == (2, "missing")


@needs_chromium
@pytest.mark.browser
def test_lazy_selectors_fail_invalid_before_anything_runs(tmp_path):
    # Ruling R16, the reviewer's probe: Playwright reads :nth-match's arguments, and a pseudo-class it does not
    # know, only when the elements to their right exist. On a page without them these read `missing`, so a claim
    # of the step verified. The browser's own document.querySelector, tried on a blank page before any step,
    # refuses them: the replay stops at that step, `invalid`, and nothing runs (the app is not even started).
    # Ruling R23: querySelector forgives a malformed argument inside :is() and :where() (it matches nothing), so
    # these passed it and read `missing`; the browser's unforgiving parse, CSS.supports('selector(:is(<css>))'),
    # refuses them too.
    for name, css, why in (("nth-match", ".nosuch:nth-match(x)", native),
                           ("unknown-pseudo", "#board:foo .nosuch", native),
                           ("is", ".nosuch:is(:bogus)", unforgiving),
                           ("where", ".nosuch:where(:contains('x'))", unforgiving)):
        r = browser.replay(make_app(tmp_path / name), [START, within(css)], shots="all")
        assert (r.ok, r.failed_at, [s.n for s in r.steps]) == (False, 2, [2]), r.to_json()
        bad = r.steps[0]
        assert (bad.ok, bad.failure, bad.screenshot) == (False, "invalid", None)
        assert bad.error == f'within css "{css}" is not a valid CSS selector, so no step ran ({why(css)})'
        assert bad.text == stepfmt.describe(within(css))
        assert r.app_log == [] and r.snapshot == ""  # Start was never clicked
        assert any("no step ran" in line for line in r.console), r.console


@needs_chromium
@pytest.mark.browser
def test_standard_selectors_pass_the_check_before_the_run(tmp_path):
    # The check refuses only what is not CSS: attribute selectors, `of S`, :not(), :has(), :is() and selector lists
    # still reach the page, where each picks the pricing card's Start button.
    steps = [within(css) for css in (
        "div.card", "#board > .card", "[class='card' i]", ".card:nth-child(1 of .card)", ".card:not(.x, .y)",
        "div:has(> span)", ".card:is(div, section)", ".card:where(:first-child)", ".nosuch, .card",
    )]
    r = browser.replay(make_app(tmp_path), steps, shots="none")  # the board stays as it is after each click
    assert r.ok and [s.ok for s in r.steps] == [True] * len(steps), r.to_json()


@needs_chromium
@pytest.mark.browser
def test_malformed_step_after_a_failing_step_is_found_first(tmp_path):
    # Ruling R16: on the broken app step 2 fails `missing`, and step 3 can never run on any page. Run in order, the
    # claim of step 2 would verify and its repro would stay red on every fix; checked first, step 3 ends the replay.
    for name, bad in (("key", BAD_KEY), ("css", within(".card:has-text('x')"))):
        r = browser.replay(make_app(tmp_path / name, FIXTURE_BROKEN="1"), [AS_DANA, DONE, bad], shots="none")
        assert (r.failed_at, [s.n for s in r.steps], r.steps[0].failure) == (3, [3], "invalid"), r.to_json()
    r = browser.replay(make_app(tmp_path / "valid", FIXTURE_BROKEN="1"), [AS_DANA, DONE, START], shots="none")
    assert (r.failed_at, r.steps[-1].failure) == (2, "missing")  # the same replay with a valid step 3


@needs_chromium
@pytest.mark.browser
def test_steps_still_fail_invalid_without_the_precheck(tmp_path, monkeypatch):
    # Defence in depth: the run loop still turns Playwright's parse errors and unknown keys into `invalid`.
    monkeypatch.setattr(browser, "_precheck", lambda *a, **k: None)

    def second(step, name):
        r = browser.replay(make_app(tmp_path / name), [AS_DANA, step], shots="none")
        assert r.steps[0].ok, r.to_json()  # step 1 ran
        return r.failed_at, r.steps[-1].failure, r.steps[-1].error

    failed_at, failure, error = second(within(".card["), "css")
    assert (failed_at, failure) == (2, "invalid"), error
    assert error.startswith('within css ".card[" is not a valid selector (Locator.count: Unexpected token'), error
    assert second(within(".card:nth-match(x)"), "nth")[:2] == (2, "invalid")
    assert second(BAD_KEY, "key") == (2, "invalid", '"Entr" is not a key Playwright can press '
                                                    '(Keyboard.press: Unknown key: "Entr")')


@needs_chromium
@pytest.mark.browser
def test_replay_deadline_counts_app_start_and_load(tmp_path, monkeypatch):
    # Ruling R14: the whole replay has REPLAY_S, from Chromium's launch on. The board's data answers 4 s late and
    # the replay has 2 s, so the time is up before step 1: it fails `timeout`, and no later step runs.
    monkeypatch.setattr(browser, "REPLAY_S", 2)
    r = browser.replay(make_app(tmp_path, FIXTURE_DELAY_MS="4000"), [AS_DANA, START, STARTED], shots="none")
    assert r.failed_at == 1 and len(r.steps) == 1, r.to_json()
    assert (r.steps[0].failure, r.steps[0].error) == ("timeout", "the replay took longer than 2 s")
    assert r.seconds < 2 + 4  # the load's wait for the network stopped at the deadline too


@needs_chromium
@pytest.mark.browser
def test_replay_deadline_cuts_the_current_step_short(tmp_path, monkeypatch):
    # /api/act does not answer within the replay's 8 s: Start's click goes through, the network never settles,
    # and the status check runs out of time: step 3 fails `timeout` (not `mismatch`), step 4 never runs.
    monkeypatch.setattr(browser, "REPLAY_S", 8)
    steps = [AS_DANA, START, STARTED, {"do": "expect_visible", "target": {"role": "heading", "name": "Fixture board"}}]
    r = browser.replay(make_app(tmp_path, FIXTURE_ACT_DELAY_MS="30000"), steps, shots="none")
    assert r.failed_at == 3 and len(r.steps) == 3 and r.steps[1].ok, r.to_json()
    assert (r.steps[2].failure, r.steps[2].error) == ("timeout", "the replay took longer than 8 s")
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
        pgid = Path(browser._pgid_path())
        assert pgid.read_text().split()[0] == str(app.proc.pid)  # recorded at start (ruling R19)
        deadline = time.monotonic() + 10
        while not any('"child-ready"' in line for line in app.log):  # it ignores SIGTERM from here on
            assert time.monotonic() < deadline, list(app.log)
            time.sleep(0.05)
        pid = next(json.loads(line)["pid"] for line in app.log if '"child"' in line)
        app.stop()
        assert not pgid.exists()  # and removed once the group is stopped
        deadline = time.monotonic() + 5
        while _state(pid) not in (None, "Z"):  # gone, or a zombie nobody reaps (orphans in a container)
            assert time.monotonic() < deadline, f"the app's child {pid} survived stop() ({_state(pid)})"
            time.sleep(0.1)
    finally:
        if pid and _state(pid) not in (None, "Z"):
            os.kill(pid, signal.SIGKILL)


def _stop_after_the_lock(monkeypatch) -> None:
    """replay() takes the lock (and clears what an earlier replay left), then fails before Chromium."""
    def no_browser():
        raise browser.BrowserError("stopped after the lock")

    monkeypatch.setattr(browser, "_playwright", no_browser)


@linux_only
@pytest.mark.browser
def test_a_stale_app_group_is_killed_at_the_next_replay(tmp_path, monkeypatch, engine_tmpdir):
    # Ruling R19: a replay whose server was killed mid-call leaves the app's process group (recorded in the pgid
    # file) and its temp dir behind. The next replay, holding the lock, kills that group and removes the engine's
    # own leftover temp dirs, and nothing else. No browser needed; Linux only, since the record needs the group
    # leader's start time from /proc (ruling R23).
    sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True)
    try:
        browser._record_app(sleeper.pid)
        assert Path(browser._pgid_path()).parent == engine_tmpdir
        stale = engine_tmpdir / "bug-investigator-replay-k1lled"
        (stale / "nested").mkdir(parents=True)
        (stale / "app.db").write_text("demo data")
        others = [engine_tmpdir / "bug-investigator-tests.abc", engine_tmpdir / "bug-investigator-replay-a-file"]
        others[0].mkdir()
        others[1].write_text("not a directory")
        _stop_after_the_lock(monkeypatch)
        with pytest.raises(browser.BrowserError, match="stopped after the lock"):
            browser.replay(make_app(tmp_path), [START])
        assert sleeper.wait(5) == -signal.SIGKILL
        assert not Path(browser._pgid_path()).exists() and not stale.exists()
        assert all(p.exists() for p in others)
        with pytest.raises(browser.BrowserError, match="stopped after the lock"):  # nothing recorded: nothing to do
            browser.replay(make_app(tmp_path / "again"), [START])
    finally:
        if sleeper.poll() is None:
            sleeper.kill()
            sleeper.wait()


# The tests below need no browser and run on the host and, marked `browser`, in the Playwright image too.


@pytest.mark.browser
def test_a_record_without_a_start_time_is_never_killed(tmp_path, monkeypatch, engine_tmpdir):
    # Ruling R23: without the leader's start time (no /proc: macOS) nothing tells our group from an id reused since,
    # so the group is left alone. The record is still forgotten and the leftover temp dirs still removed.
    sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True)
    try:
        Path(browser._pgid_path()).write_text(f"{sleeper.pid} -\n")
        stale = engine_tmpdir / "bug-investigator-replay-k1lled"
        stale.mkdir()
        _stop_after_the_lock(monkeypatch)
        with pytest.raises(browser.BrowserError, match="stopped after the lock"):
            browser.replay(make_app(tmp_path), [START])
        time.sleep(0.3)
        assert sleeper.poll() is None
        assert not Path(browser._pgid_path()).exists() and not stale.exists()
    finally:
        sleeper.kill()
        sleeper.wait()


def _open_fds() -> int:
    return len(os.listdir("/dev/fd"))


@pytest.mark.browser
def test_odd_things_at_the_record_path_never_stop_or_block_a_replay(tmp_path, monkeypatch, engine_tmpdir):
    # Ruling R23: clearing up is best effort. A directory at the record path is not read (and its descriptor not
    # leaked); a FIFO is opened without blocking (no writer would ever come, and the lock is held); a pgid too big
    # for a pid_t is not an OverflowError. Each replay still gets past the lock.
    _stop_after_the_lock(monkeypatch)
    record = Path(browser._pgid_path())

    def replay_once(name):
        done = []

        def run():
            with pytest.raises(browser.BrowserError, match="stopped after the lock"):
                browser.replay(make_app(tmp_path / name), [START])
            done.append(True)

        t = threading.Thread(target=run, daemon=True)
        t.start()
        t.join(10)
        return t, done

    record.mkdir()
    before = _open_fds()
    t, done = replay_once("directory")
    assert done and _open_fds() == before
    record.rmdir()

    os.mkfifo(record)
    try:
        t, done = replay_once("fifo")
        assert not t.is_alive(), "the replay blocked opening a FIFO at the record path"
        assert done and not record.exists()  # a FIFO is no record: forgotten
    finally:
        if t.is_alive():  # unblock the reader so the thread ends
            os.close(os.open(record, os.O_WRONLY | os.O_NONBLOCK))
            t.join(5)

    record.write_text("99999999999999999999 12345\n")  # with a start time, so the kill is tried
    t, done = replay_once("huge")
    assert done and not record.exists()


@pytest.mark.browser
def test_a_failure_while_clearing_up_is_logged_and_the_rest_still_runs(tmp_path, monkeypatch, engine_tmpdir, capfd):
    # Ruling R23: whatever goes wrong while clearing up is logged to stderr (stdout is the MCP channel), the record is
    # forgotten anyway, and one temp dir that cannot be removed does not stop the others being removed.
    Path(browser._pgid_path()).write_text("4242 12345\n")
    stale = [engine_tmpdir / f"bug-investigator-replay-{n}" for n in ("a", "b", "c")]
    for d in stale:
        d.mkdir()

    def broken_start_time(pid):
        raise RuntimeError("no /proc today")

    rmtree = browser.shutil.rmtree

    def rmtree_fails_on_b(path, **kw):
        if path.endswith("-b"):
            raise PermissionError(1, "Operation not permitted", path)
        rmtree(path, **kw)

    monkeypatch.setattr(browser, "_start_time", broken_start_time)
    monkeypatch.setattr(browser.shutil, "rmtree", rmtree_fails_on_b)
    _stop_after_the_lock(monkeypatch)
    with pytest.raises(browser.BrowserError, match="stopped after the lock"):
        browser.replay(make_app(tmp_path), [START])
    out, err = capfd.readouterr()
    assert out == "" and "no /proc today" in err, (out, err)
    assert not Path(browser._pgid_path()).exists()
    assert [d.exists() for d in stale] == [False, True, False]


@pytest.mark.browser
def test_a_record_that_cannot_be_read_or_removed_never_stops_a_replay(tmp_path, monkeypatch):
    # Clearing up is best effort: a malformed record, or one that cannot be removed (another user's file in a
    # shared /tmp), must not fail the replay that found it.
    Path(browser._pgid_path()).write_text("not a pgid\n")
    _stop_after_the_lock(monkeypatch)
    with pytest.raises(browser.BrowserError, match="stopped after the lock"):
        browser.replay(make_app(tmp_path), [START])
    assert not Path(browser._pgid_path()).exists()

    def cannot_remove(path):
        raise PermissionError(1, "Operation not permitted", path)

    Path(browser._pgid_path()).write_text("4242 -\n")
    monkeypatch.setattr(browser.os, "remove", cannot_remove)
    monkeypatch.setattr(browser.os, "killpg", lambda *a: None)
    with pytest.raises(browser.BrowserError, match="stopped after the lock"):
        browser.replay(make_app(tmp_path / "again"), [START])


@linux_only
@pytest.mark.browser
def test_a_recorded_group_whose_id_was_reused_is_left_alone(tmp_path, monkeypatch):
    # The recorded group is gone and its id now names another process (a different start time): never killed.
    sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True)
    try:
        Path(browser._pgid_path()).write_text(f"{sleeper.pid} 1\n")  # started 1 clock tick after boot: not it
        _stop_after_the_lock(monkeypatch)
        with pytest.raises(browser.BrowserError, match="stopped after the lock"):
            browser.replay(make_app(tmp_path), [START])
        time.sleep(0.3)
        assert sleeper.poll() is None and not Path(browser._pgid_path()).exists()
    finally:
        sleeper.kill()
        sleeper.wait()


PARENT = """\
import os, sys, time
sys.path.insert(0, {src!r})
from bug_investigator import browser
app = browser._App({app!r}, {home!r}, None)
app.start()
print(app.proc.pid, flush=True)
if {exits!r}:
    os._exit(0)  # without stopping the app
time.sleep(60)
"""


@linux_only
@pytest.mark.browser
@pytest.mark.parametrize("how", ["killed", "exits"])
def test_the_app_dies_with_the_process_that_started_it(tmp_path, engine_tmpdir, how):
    # Ruling R19, the reviewer's repro: a session deleted mid-call makes agentgateway kill browser_server.py, whose
    # finally blocks never run; the app, in a session of its own, was reparented and kept running. Its parent-death
    # signal (PR_SET_PDEATHSIG = SIGKILL) now ends it with the process that started it. No browser needed.
    home = tmp_path / "home"
    home.mkdir()
    code = PARENT.format(src=str(ENGINE.parents[1]), app=make_app(tmp_path), home=str(home), exits=how == "exits")
    parent = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True,
                              env=dict(os.environ, TMPDIR=str(engine_tmpdir)))
    app_pid = None
    try:
        app_pid = int(parent.stdout.readline())
        assert _state(app_pid) not in (None, "Z")  # the app is up
        if how == "killed":
            parent.kill()
        parent.wait(10)
        deadline = time.monotonic() + 5
        while _state(app_pid) not in (None, "Z"):  # gone, or a zombie nobody reaps (orphans in a container)
            assert time.monotonic() < deadline, f"the app {app_pid} outlived its parent ({_state(app_pid)})"
            time.sleep(0.1)
        # The parent never stopped it, so its record is left for the next replay to reap.
        assert (engine_tmpdir / "bug-investigator-browser.pgid").read_text().split()[0] == str(app_pid)
    finally:
        if parent.poll() is None:
            parent.kill()
            parent.wait()
        if app_pid and _state(app_pid) not in (None, "Z"):
            os.killpg(app_pid, signal.SIGKILL)


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
    archive = {"do": "click",
               "target": {"role": "button", "name": "Archive", "within": {"css": ".card", "text": REPORT}}}
    (repros / "broken.json").write_text(json.dumps({"title": "Archive the report card", "issue": 12,
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
        {"file": "broken.json", "title": "Archive the report card", "issue": 12, "ok": False, "failed_at": 2,
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
