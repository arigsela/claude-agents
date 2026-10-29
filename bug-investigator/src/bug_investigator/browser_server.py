"""Taskboard's browser as a stdio MCP server: one tool, replay_ui_steps.

Each call replays a list of UI steps (steps.py's format) with browser.replay: a fresh copy of the
app in APP_DIR (the live code; its commit is APP_DIR/.source-commit) on a fresh database with the
demo data, headless Chromium that cannot leave it, and everything torn down afterwards. The result
is the replay as JSON (content item 0), then a `step <n>` text item and an image item per screenshot.
A step that fails is a normal result (`ok: false`); invalid input and a replay that cannot be set up
(`BrowserError`: Chromium does not launch, the app does not start) are results with isError: true.

A tool server that fails at `initialize` fails every agent bound to it, so nothing here imports
Playwright or starts Chromium before a tool call: browser.py imports Playwright inside replay(),
from DEPS_DIR (default /deps).

Transport: mcp_server.StdioServer's loop (agentgateway serves it as Streamable HTTP). stdin is read
on a background thread and tool calls run on the main thread, one at a time (replays take a
machine-wide lock anyway). SIGTERM raises SystemExit there, so a running replay unwinds through its
finally blocks, which close Chromium and stop the app's process group, before the process exits.

    python3 -I /core/src/bug_investigator/browser_server.py      # env APP_DIR, DEPS_DIR
"""

from __future__ import annotations

import json
import os
import queue
import signal
import sys
import threading

if __package__ in (None, ""):  # run as a script (python3 -I .../browser_server.py): -I drops PYTHONPATH
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bug_investigator import browser  # noqa: E402  (stdlib only at import; Playwright inside replay())
from bug_investigator import steps as stepfmt  # noqa: E402
from bug_investigator.mcp_server import StdioServer, ToolError  # noqa: E402

SERVER_NAME = "taskboard-browser"
SERVER_VERSION = "0.1.0"
TOOL_NAME = "replay_ui_steps"
DEFAULT_APP_DIR = "/taskboard"
SCREENSHOTS = ("none", "failure", "all")
DEFAULT_SCREENSHOTS = "failure"
APP_LOG_LINES = 20
ARGUMENTS = ("steps", "fails_at", "screenshots")

DESCRIPTION = (
    "Replay UI steps in headless Chromium on a throwaway copy of Taskboard. Each call starts the code that "
    "is live (the result reports its commit) on a fresh database with the demo data, loads /, runs the steps "
    "in order and stops at the first step that fails; nothing persists between calls, and the browser cannot "
    "leave the app. An action (click, fill, select, press) needs a target that matches exactly one element: "
    "add `within` to pick one card. A check (expect_visible, expect_absent, expect_text) passes when any match "
    "satisfies it. A step is {do, target, value, note}: `do` is one of click, fill, select, press, goto, "
    "expect_visible, expect_absent, expect_text; `target` has exactly one of role (an ARIA role Playwright "
    "knows, such as button, link, textbox, heading, status; with an optional exact name), label, placeholder "
    "or text, plus an optional within {css, text} that must match one element (css is one CSS selector); "
    "`value` is the text to fill, the option label to select, the key to press (a Playwright key name such as "
    "Enter, Escape, Control+a), the path to goto (it starts with /; goto has no target) or the text "
    f"expect_text looks for; at most {stepfmt.MAX_STEPS} steps. A failed step says why in `failure`: "
    "`ambiguous` (an action target or within matched more than one element), `missing` (nothing matched), "
    "`mismatch` (no match had the text; for expect_absent, something matched), `invalid` (the step cannot run "
    "on any page: a css that does not parse, a key Playwright does not know), `error` (anything else, such as "
    "a disabled button). Set `fails_at` to the step you expect to fail and the result says whether it matches "
    "(`matches_claim`); an `ambiguous` or `invalid` failure never matches a claim, since it shows a badly "
    "written step, not a bug; omit `fails_at` when you expect every step to pass, and read `ok`. "
    "`screenshots`: failure (the default: the failing "
    "step, or the last one), all, or none. The result holds each step's outcome, the page's accessibility "
    "snapshot, the app's last log lines and the browser console, then the screenshots."
)

TOOL = {
    "name": TOOL_NAME,
    "description": DESCRIPTION,
    "annotations": {"readOnlyHint": True, "openWorldHint": False},
    "inputSchema": {
        "type": "object",
        "properties": {
            # The step grammar is steps.validate's job; the schema only says "a list of objects". One plain
            # JSON type per property (no type arrays, no anyOf): a schema kagent's Go ADK cannot load fails
            # the whole agent (ruling R10). So fails_at is an optional integer; null is accepted as absent.
            "steps": {"type": "array", "items": {"type": "object"}, "minItems": 1, "maxItems": stepfmt.MAX_STEPS,
                      "description": "The steps, in order: {do, target, value, note} (see the tool description)."},
            "fails_at": {"type": "integer", "minimum": 1,
                         "description": "The 1-based step you expect to fail; the result then says whether it "
                                        "matches. Omit it when you expect every step to pass (read `ok`) or are "
                                        "only exploring."},
            "screenshots": {"type": "string", "enum": list(SCREENSHOTS), "default": DEFAULT_SCREENSHOTS,
                            "description": "Which steps get a screenshot: none, failure (the failing step, or "
                                           "the last one) or all."},
        },
        "required": ["steps"],
        "additionalProperties": False,
    },
}

INSTRUCTIONS = (f"One tool, {TOOL_NAME}: it replays UI steps in headless Chromium on a throwaway copy of the live "
                "Taskboard (a fresh database with the demo data). Nothing persists between calls.")

NOT_EVIDENCE = ("ambiguous", "invalid")  # a badly written step (rulings R8, R13), never a reproduction


def matches_claim(r: browser.Replay, fails_at: int) -> bool:
    """Did the replay fail at the step the caller named? An ambiguous or invalid step is never evidence."""
    if r.failed_at != fails_at:
        return False
    failed = next((s for s in r.steps if s.n == fails_at), None)
    return failed is not None and failed.failure not in NOT_EVIDENCE


def content(r: browser.Replay, fails_at: int | None = None) -> list[dict]:
    """The tool result: the replay as JSON (with matches_claim only for a fails_at), then `step <n>` and the
    PNG for each screenshot, in step order."""
    d = r.to_json(include_png=True)
    pngs = [(s["n"], s.pop("png")) for s in d["steps"]]  # each step entry: {n, text, ok, error, failure}
    doc = {"ok": d["ok"], "failed_at": d["failed_at"]}
    if fails_at is not None:
        doc["matches_claim"] = matches_claim(r, fails_at)
    doc.update(commit=d["commit"], steps=d["steps"], snapshot=d["snapshot"], app_log=d["app_log"][-APP_LOG_LINES:],
               console=d["console"])
    items = [{"type": "text", "text": json.dumps(doc, ensure_ascii=False)}]
    for n, png in pngs:
        if png:
            items += [{"type": "text", "text": f"step {n}"}, {"type": "image", "data": png, "mimeType": "image/png"}]
    return items


class BrowserServer(StdioServer):
    """replay_ui_steps over StdioServer's loop. `replay` is browser.replay (tests pass a fake)."""

    def __init__(self, *, app_dir: str | None = None, replay=None, out=None, pool=None):
        self.app_dir = app_dir or os.environ.get("APP_DIR") or DEFAULT_APP_DIR
        self.replay = replay or browser.replay
        super().__init__(SERVER_NAME, SERVER_VERSION, [TOOL], self._call, instructions=INSTRUCTIONS, out=out,
                         pool=pool)

    def commit(self) -> str | None:
        """The live commit: APP_DIR/.source-commit (written by gen-taskboard-configmap.py); None if absent."""
        try:
            with open(os.path.join(self.app_dir, ".source-commit"), encoding="utf-8") as f:
                return f.read().strip() or None
        except OSError:
            return None

    def ready(self) -> str:
        return (f"ready (app {self.app_dir}, commit {self.commit() or 'unknown'}, "
                f"deps {os.environ.get('DEPS_DIR', '/deps')})")

    def _call(self, name, args) -> list[dict]:
        if name != TOOL_NAME:
            raise ToolError(f"unknown tool {name!r}; available: {TOOL_NAME}")
        if args is None:
            args = {}
        if not isinstance(args, dict):
            raise ToolError("arguments must be an object")
        problems = []
        unknown = sorted(set(args) - set(ARGUMENTS))
        if unknown:
            problems.append(f"unknown arguments: {', '.join(unknown)}")
        steps, fails_at = args.get("steps"), args.get("fails_at")
        problems += stepfmt.validate(steps, fails_at)
        shots = args.get("screenshots")
        if shots is None:
            shots = DEFAULT_SCREENSHOTS
        elif shots not in SCREENSHOTS:
            problems.append(f"screenshots must be one of {', '.join(SCREENSHOTS)}")
        if problems:
            raise ToolError("; ".join(problems))
        try:
            r = self.replay(self.app_dir, steps, commit=self.commit(), shots=shots)
        except browser.BrowserError as e:
            raise ToolError(f"browser unavailable: {e}") from None
        return content(r, fails_at)  # null and absent alike: no claim


class MainThreadCalls:
    """StdioServer's pool, but every call runs on the thread that calls run(): the main thread.

    Python runs signal handlers on the main thread only, so this is what lets SIGTERM's SystemExit
    unwind a running replay. Calls run one at a time, in order; shutdown() lets the calls already
    submitted run, then run() returns.
    """

    def __init__(self):
        self._calls: queue.SimpleQueue = queue.SimpleQueue()

    def submit(self, fn) -> None:
        self._calls.put(fn)

    def shutdown(self, wait: bool = True) -> None:
        self._calls.put(None)

    def run(self, log) -> None:
        while True:
            fn = self._calls.get()
            if fn is None:
                return
            try:
                fn()
            except Exception as e:  # e.g. stdout gone: log it, keep serving (SystemExit passes through)
                log(f"a call failed outside the tool: {e!r}")


def _terminate(signum, frame) -> None:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)  # a second SIGTERM must not cut the teardown short
    raise SystemExit(128 + signum)


def main(argv: list[str] | None = None, *, replay=None) -> int:
    calls = MainThreadCalls()
    server = BrowserServer(replay=replay, pool=calls)
    signal.signal(signal.SIGTERM, _terminate)

    def read() -> None:
        try:
            server.serve()  # at EOF it shuts the pool down: run() returns after the calls already read
        finally:
            calls.shutdown()  # also when reading fails, so the main thread never waits forever

    threading.Thread(target=read, name="stdin", daemon=True).start()
    calls.run(server.log)
    return 0


if __name__ == "__main__":
    sys.exit(main())
