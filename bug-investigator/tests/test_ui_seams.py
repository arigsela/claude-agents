"""Cross-seam tests, no browser: the pieces wired the way the trigger and the ui-check workflow wire them.

1. verify's path: browser_server's tools/call result for a Replay, served over Streamable HTTP by the fake MCP
   server of test_mcp_client, read by mcp_client.replay_via_mcp, judged by verify.check_ui.
2. ui-check's path: `browser.py check` (replay canned) writes its results; evidence.post_pr uploads the
   screenshots to a fake GitHub and posts the one PR comment.
"""

import io
import json

import pytest

from bug_investigator import browser, browser_server, evidence, mcp_client
from bug_investigator import steps as stepfmt
from bug_investigator import verify as V
from test_browser import AS_DANA, PNG, START, STARTED
from test_evidence import API, REPO, TOKEN, FakeGitHub, bot_comments
from test_mcp_client import Fake

STEPS = [AS_DANA, START, STARTED]
ERROR = 'button "Start" in .card "Write copy for the pricing page" matched 2 elements'


def shot(n: int) -> bytes:
    return PNG + bytes([n])


def canned(steps, failed_at=None, failure="missing", error=ERROR) -> browser.Replay:
    """What browser.replay returns: steps up to the first failure, a PNG for each."""
    ran = steps[:failed_at] if failed_at else steps
    return browser.Replay(
        ok=failed_at is None, failed_at=failed_at, commit="abc123", seconds=1.0, snapshot="- heading", app_log=[],
        console=[], steps=[browser.StepResult(n, stepfmt.describe(s), n != failed_at,
                                              error if n == failed_at else None, shot(n),
                                              failure if n == failed_at else None)
                           for n, s in enumerate(ran, 1)])


@pytest.fixture
def mcp(tmp_path):
    """Serve browser_server's answer for one canned Replay over the fake HTTP MCP server; yields a ui_replay."""
    app_dir = tmp_path / "taskboard"
    app_dir.mkdir()
    (app_dir / ".source-commit").write_text("abc123")
    fakes, calls = [], []

    def make(replay: browser.Replay):
        def ui_replay(steps, fails_at):
            srv = browser_server.BrowserServer(app_dir=str(app_dir), replay=lambda *a, **k: replay, out=io.StringIO())
            args = {"steps": steps, "screenshots": "all", **({"fails_at": fails_at} if fails_at else {})}
            served = srv.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                 "params": {"name": browser_server.TOOL_NAME, "arguments": args}})["result"]
            fake = Fake(tool_result=served)
            fakes.append(fake)
            out = mcp_client.replay_via_mcp(fake.url, steps, fails_at, timeout=5)
            sent = [b for _, _, _, b in fake.log if b and b.get("method") == "tools/call"][0]["params"]["arguments"]
            calls.append((sent, json.loads(served["content"][0]["text"])))
            return out

        return ui_replay

    yield make, calls
    for f in fakes:
        f.close()


def ctx_with(ui_replay, tmp_path) -> V.Ctx:
    return V.Ctx(mode="full", repo="o/app", app_dir=str(tmp_path), runner=lambda cmd: "0" * 40, ui_replay=ui_replay)


@pytest.mark.parametrize("failure, reason", [
    ("ambiguous", f"step 2 failed only because its target matched more than one element: {ERROR}"),
    ("invalid", f"step 2 failed only because the step itself is invalid: {ERROR}"),
    ("timeout", f"step 2 failed only because the replay ran out of time: {ERROR}"),
    ("missing", None),
], ids=["ambiguous", "invalid", "timeout", "missing"])
def test_server_result_through_the_mcp_client_into_verify(tmp_path, mcp, failure, reason):
    make, calls = mcp
    ctx = ctx_with(make(canned(STEPS, failed_at=2, failure=failure)), tmp_path)
    item = {"id": "E1", "kind": "ui", "ref": "dana starts her task", "steps": STEPS, "fails_at": 2}
    got, extra = V.check_ui(ctx, item)
    (sent, served), = calls
    assert sent == {"steps": STEPS, "screenshots": "all", "fails_at": 2}
    assert served["matches_claim"] is (reason is None)  # the server and verify agree
    assert got == reason
    if reason:
        assert extra == {} and ctx.ui_shots == {}
    else:
        assert extra["commit"] == "abc123" and extra["failed_at"] == 2
        assert [(s["n"], s["ok"], s["failure"]) for s in extra["steps"]] == [(1, True, None), (2, False, "missing")]
        assert ctx.ui_shots == {"E1": [(1, shot(1)), (2, shot(2))]}  # the images paired with their steps


def test_check_results_into_the_pr_comment(tmp_path, monkeypatch):
    repros = tmp_path / "repros"
    repros.mkdir()
    (repros / "issue-42.json").write_text(json.dumps({"title": "Dana starts her task", "issue": 42, "steps": STEPS}))
    board = [{"do": "goto", "value": "/"}]
    (repros / "board.json").write_text(json.dumps({"title": "The board loads", "issue": None, "steps": board}))
    no_status = 'no match for status contains "moved to in progress by dana"'
    results = {len(STEPS): canned(STEPS, failed_at=3, failure="mismatch", error=no_status), len(board): canned(board)}

    def replay(app_dir, steps, *, commit=None, shots="all"):
        assert shots == "all" and app_dir == str(tmp_path / "app")
        return results[len(steps)]

    monkeypatch.setattr(browser, "replay", replay)
    out = tmp_path / "out"
    assert browser.main(["check", "--app-dir", str(tmp_path / "app"), "--repros", str(repros), "--out", str(out),
                         "--changed", "ui-tests/repros/issue-42.json"]) == 1  # one repro fails

    gh = FakeGitHub()
    assert evidence.post_pr(REPO, 5, str(out), token=TOKEN, run="777", api=API, opener=gh) == 0
    sha = gh.refs[evidence.BRANCH]
    assert gh.files_at(sha) == {f"pr-5/777/issue-42/step-{n}.png": shot(n) for n in (1, 2, 3)}  # changed repro only
    (comment,) = bot_comments(gh)
    body = comment["body"]

    def link(n):
        return f"https://github.com/{REPO}/blob/{sha}/pr-5/777/issue-42/step-{n}.png?raw=true"

    assert body.splitlines()[0] == evidence.MARKER
    assert "`Dana starts her task` (#42)" in body and "❌ failed at step 3" in body
    assert '1. ✓ `select "dana (editor)" in the field labelled "User"`' in body
    assert '2. ✓ `click button "Start" in .card "Write copy for the pricing page"`' in body
    assert f'3. ✗ `expect status to contain "moved to in progress by dana"` — `{no_status}`' in body
    assert f"![step 3]({link(3)})" in body  # the failing step inline, the others folded
    details = body[body.index("<details>"): body.index("</details>")]
    assert f"![step 1]({link(1)})" in details and f"![step 2]({link(2)})" in details
    assert "The board loads" not in body  # not changed by this PR
