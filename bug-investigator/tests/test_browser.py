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
import subprocess
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
        steps=[browser.StepResult(1, "click x", True, None, None), browser.StepResult(2, "click y", False, "no", PNG)],
    )
    doc = r.to_json()
    assert doc == {
        "ok": False, "failed_at": 2, "commit": "abc", "seconds": 1.5, "snapshot": "- heading",
        "app_log": ["l"], "console": ["c"],
        "steps": [{"n": 1, "text": "click x", "ok": True, "error": None},
                  {"n": 2, "text": "click y", "ok": False, "error": "no"}],
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
        {"do": "goto", "value": "/"},
        {"do": "expect_visible", "target": {"role": "button", "name": "Done", "within": {"css": ".card", "text": COOKIE}}},
        {"do": "expect_absent", "target": {"text": "Buy milk"}},
    ]
    r = browser.replay(make_app(tmp_path), steps, commit="abc123", shots="none")
    assert r.ok and r.failed_at is None, r.to_json()
    assert [(s.n, s.ok, s.error, s.screenshot) for s in r.steps] == [(n, True, None, None) for n in range(1, 10)]
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


@needs_chromium
@pytest.mark.browser
def test_two_matches_fail_not_click(tmp_path):
    click_any_start = {"do": "click", "target": {"role": "button", "name": "Start"}}
    r = browser.replay(make_app(tmp_path), [AS_DANA, click_any_start], shots="none")
    assert r.failed_at == 2 and r.steps[1].error == 'button "Start" matched 2 elements'
    assert not any("/api/act" in line for line in r.app_log), r.app_log  # nothing was clicked
    two_cards = {"do": "click", "target": {"role": "button", "name": "Start", "within": {"css": ".card", "text": "copy"}}}
    r = browser.replay(make_app(tmp_path / "2"), [two_cards], shots="none")
    assert r.failed_at == 1 and r.steps[0].error == '.card "copy" matched 2 elements'


@needs_chromium
@pytest.mark.browser
def test_absent_waits_for_render(tmp_path):
    # The cards' data answers 800 ms late: checked at "load", no Start button exists yet.
    r = browser.replay(make_app(tmp_path, FIXTURE_DELAY_MS="800"),
                       [{"do": "expect_absent", "target": {"role": "button", "name": "Start"}}], shots="none")
    assert r.failed_at == 1 and r.steps[0].error == 'expected no button "Start", found 2'


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
    assert failing.steps[1].error.endswith("(element is not enabled)"), failing.steps[1].error  # the call log's reason
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


def _cli(*args):
    return subprocess.run([sys.executable, "-I", str(ENGINE), *args], capture_output=True, text=True, timeout=300)


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
    good = json.loads((out / "good" / "result.json").read_text())
    assert good["title"] == "Dana starts her task" and good["issue"] == 7 and good["ok"]
    assert [s["n"] for s in good["steps"]] == [1, 2, 3]
    assert all((out / "good" / f"step-{n}.png").read_bytes().startswith(PNG) for n in (1, 2, 3))
    broken = json.loads((out / "broken" / "result.json").read_text())
    assert broken["failed_at"] == 2 and "0 matches" in broken["steps"][1]["error"]
    assert (out / "broken" / "step-2.png").exists()
