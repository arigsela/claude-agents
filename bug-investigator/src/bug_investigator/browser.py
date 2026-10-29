"""Replay UI steps in headless Chromium against a throwaway copy of the app.

Every replay starts the app (`python3 server.py` in its directory) on a free port, with a fresh
database and HOME in a temporary directory and a fixed environment, loads `/`, runs the steps
(steps.py's format) and tears everything down. The browser may talk only to that app: a request,
navigation or WebSocket to any other origin is aborted and noted in `console`. One replay runs at a
time on a machine (a lock in $TMPDIR). Only this module imports Playwright, lazily, from $DEPS_DIR
(default /deps). A replay has REPLAY_S (75 s) from Chromium's launch, app start and load included:
when it runs out, the current step fails (`timeout`, "the replay took longer than 75 s") and no
later step runs, so a call answers within agentgateway's 90 s.

    python3 -I browser.py replay --app-dir D --steps F [--commit SHA] --out DIR
    python3 -I browser.py check --app-dir D --repros DIR --out DIR [--changed a.json,b.json]

`replay` (F = a list of steps or a repro file) writes DIR/result.json and DIR/step-<n>.png. Exit 0
when every step passed, 1 when one failed, 2 for bad arguments, invalid steps or a replay that could
not be set up. `check` replays every DIR/*.json repro (each must pass) into DIR/<stem>/result.json
and DIR/<stem>/step-<n>.png and writes DIR/summary.json. Exit 0 when every repro passed, 1 when any
failed or could not be replayed (an invalid file, the app or Chromium not starting), 2 only for bad
arguments: a usage error or a --repros directory that cannot be listed.

Actions (click, fill, select, press) and `within` need exactly one match; checks pass on any match
(expect_visible: one is visible; expect_text: one contains the value; expect_absent: none). A failed
step says why in `failure`: ambiguous (an action target or `within` matched more than one element),
missing (nothing matched), mismatch (expect_text found no match with the value; expect_absent found
some), invalid (the step cannot run on any page: `within.css` is not a CSS selector, read as
`css=<css>` so another selector engine does not parse either, or `press` names a key Playwright does
not know; the key is checked before the target is looked for), timeout (the replay's REPLAY_S ran
out during or before the step), error (anything else, such as a disabled button).
"""

from __future__ import annotations

import argparse
import base64
import collections
import contextlib
import fcntl
import http.client
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlsplit

if __package__ in (None, ""):  # run as a script (python3 -I .../browser.py): -I drops PYTHONPATH
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bug_investigator import steps as stepfmt  # noqa: E402

APP_START_S = 15  # the app must answer GET /healthz within this
LOCK_WAIT_S = 120
STEP_S = 3  # actions, expect_visible and expect_text wait this long for their target
IDLE_S = 5  # after load and after every action: wait (at most this) for the network to go idle
# The whole replay, from Chromium's launch through app start, load and every step (ruling R14): under the
# 90 s timeout of the server's RemoteMCPServer and mcp_client's 120 s. Real replays take 10-20 s.
REPLAY_S = 75
QUIET_S = 0.5  # idle = no request in flight for this long
VIEWPORT = {"width": 1100, "height": 760}
SNAPSHOT_CHARS = 6000
APP_LOG_LINES = 50
CONSOLE_LINES = 50
SHOTS = ("all", "failure", "none")
FAILURES = ("ambiguous", "missing", "mismatch", "invalid", "timeout", "error")  # a failed StepResult's `failure`
# Playwright's words when the step itself is malformed, whatever the page: a selector that does not parse
# (its own CSS parser, an engine after >>, a pseudo-class's arguments, the browser's querySelectorAll) or a
# key its keyboard does not know.
MALFORMED = ("while parsing css selector", "while parsing selector", "is not a valid selector", '" engine expects ',
             "Unknown key: ")
# Defence in depth behind the request fence: the browser resolves no host name at all.
RESOLVER_RULES = "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1"
# The texts expect_text reads: a field's value, a select's chosen label, otherwise the rendered text.
# evaluate_all never waits for an element, so the step's own deadline bounds it.
TEXTS_JS = """els => els.map(e => String((e.matches('input, textarea') ? e.value
  : e.matches('select') ? Array.from(e.selectedOptions, o => o.label).join(', ') : e.innerText) ?? ''))"""
# Call-log lines that only narrate; the last other one is why an action timed out.
ROUTINE = ("waiting", "retrying", "attempting", "locator resolved", "scrolling", "done", "performing",
           "element is visible")


class BrowserError(RuntimeError):
    """The replay could not be set up: the app did not start, Chromium did not launch, the lock was busy."""


class _StepFailed(Exception):
    """A step did not pass; the message is its error, `failure` its kind."""

    def __init__(self, error: str, failure: str):
        super().__init__(error)
        self.failure = failure


@dataclass
class StepResult:
    n: int
    text: str
    ok: bool
    error: str | None = None
    screenshot: bytes | None = None
    failure: str | None = None  # one of FAILURES; None when the step passed


@dataclass
class Replay:
    ok: bool
    failed_at: int | None
    steps: list[StepResult]
    snapshot: str
    app_log: list[str]
    console: list[str]
    commit: str | None
    seconds: float

    def to_json(self, include_png: bool = False) -> dict:
        def step(s: StepResult) -> dict:
            d = {"n": s.n, "text": s.text, "ok": s.ok, "error": s.error, "failure": s.failure}
            if include_png:
                d["png"] = base64.b64encode(s.screenshot).decode() if s.screenshot else None
            return d

        return {"ok": self.ok, "failed_at": self.failed_at, "commit": self.commit, "seconds": self.seconds,
                "steps": [step(s) for s in self.steps], "snapshot": self.snapshot,
                "app_log": list(self.app_log), "console": list(self.console)}


def _first_line(e: BaseException) -> str:
    lines = str(e).strip().splitlines()
    return (lines[0] if lines else type(e).__name__)[:300]


def _step_error(e: BaseException, step: dict) -> str:
    """A sentence from Playwright's error and its call log's reason, Playwright's words in parentheses."""
    head = _first_line(e).rstrip(".")
    lines = [line.strip() for line in str(e).splitlines()[1:]]
    reasons = [line[2:][:150] for line in lines if line.startswith("- ") and not line[2:].startswith(ROUTINE)]
    reason = reasons[-1] if reasons else None
    what = stepfmt.phrase(step["target"]) if "target" in step else None
    if what and reason and reason.startswith("element is not "):  # enabled, visible, editable, stable
        return f"{what} is not {reason.removeprefix('element is not ')} ({head})"
    if what and reason == "did not find some options":
        return f'{what} has no option "{step["value"]}" ({head})'
    if what and reason and reason.endswith(" intercepts pointer events"):
        return f"{what} is covered by {reason.removesuffix(' intercepts pointer events')} ({head})"
    because = f": {reason}" if reason else ""
    return f"could not {stepfmt.describe(step)}{because} ({head})"


def _overtime() -> str:
    return f"the replay took longer than {REPLAY_S} s"


def _malformed(e: BaseException) -> bool:
    """Did Playwright refuse the step itself (MALFORMED), rather than fail on the page?"""
    head = _first_line(e)
    return any(m in head for m in MALFORMED)


def _invalid_error(e: BaseException, step: dict) -> str:
    head = _first_line(e)
    w = (step.get("target") or {}).get("within")
    if w and "Unknown key" not in head:  # the one selector built from the step's own text, unescaped
        return f'within css "{w["css"]}" is not a valid selector ({head})'
    return f"the step cannot run on any page ({head})"


def _lock_path() -> str:
    return os.path.join(tempfile.gettempdir(), "bug-investigator-browser.lock")


@contextlib.contextmanager
def _lock():
    """One replay at a time on this machine: Chromium and the app are heavy."""
    try:
        fd = os.open(_lock_path(), os.O_RDWR | os.O_CREAT, 0o600)
    except OSError as e:
        raise BrowserError(f"cannot open the replay lock: {e}") from e
    try:
        deadline = time.monotonic() + LOCK_WAIT_S
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise BrowserError(f"another replay held the lock for {LOCK_WAIT_S} s") from None
                time.sleep(0.2)
        yield
    finally:
        os.close(fd)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _App:
    """The app under test: `python3 server.py` in its directory, with its own port, database and HOME."""

    def __init__(self, app_dir: str, tmp: str, commit: str | None):
        self.dir = os.path.abspath(app_dir)
        self.port = _free_port()
        self.origin = f"http://127.0.0.1:{self.port}"
        self.log: collections.deque[str] = collections.deque(maxlen=APP_LOG_LINES)
        self.env = {"PATH": os.environ.get("PATH", os.defpath), "HOME": tmp, "PORT": str(self.port),
                    "DB_PATH": os.path.join(tmp, "app.db"), "PYTHONDONTWRITEBYTECODE": "1"}
        if commit:
            self.env["TASKBOARD_COMMIT"] = commit
        self.proc: subprocess.Popen | None = None
        self.reader: threading.Thread | None = None

    def start(self) -> None:
        if not os.path.isfile(os.path.join(self.dir, "server.py")):
            raise BrowserError(f"no server.py in {self.dir}")
        # Not -I: Taskboard's server.py imports its sibling modules. Its own process group, so stop()
        # also ends anything it started.
        self.proc = subprocess.Popen([sys.executable, "server.py"], cwd=self.dir, env=self.env,
                                     stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     text=True, encoding="utf-8", errors="replace", start_new_session=True)
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # never via a proxy
        deadline = time.monotonic() + APP_START_S
        while True:
            code = self.proc.poll()
            if code is not None:
                self.reader.join(2)
                raise BrowserError(f"the app exited with code {code} before answering /healthz{self._tail()}")
            try:
                with opener.open(self.origin + "/healthz", timeout=1) as resp:
                    if resp.status == 200:
                        return
            except (OSError, http.client.HTTPException):
                pass
            if time.monotonic() >= deadline:
                raise BrowserError(f"the app did not answer /healthz within {APP_START_S} s{self._tail()}")
            time.sleep(0.1)

    def _read(self) -> None:
        with contextlib.suppress(OSError, ValueError):
            for line in self.proc.stdout:
                self.log.append(line.rstrip("\n")[:2000])

    def _tail(self, n: int = 5) -> str:
        lines = list(self.log)[-n:]
        return ": " + " | ".join(lines) if lines else ""

    def _signal_group(self, sig: int) -> None:
        # ProcessLookupError: the whole group is gone already. PermissionError: macOS's answer for a group
        # whose last members are zombies.
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(self.proc.pid, sig)

    def stop(self) -> None:
        if self.proc is None:
            return
        self._signal_group(signal.SIGTERM)
        with contextlib.suppress(subprocess.TimeoutExpired):
            self.proc.wait(5)
        # Always, not only when the app outlived SIGTERM: a grandchild that ignores it must not outlive the replay.
        self._signal_group(signal.SIGKILL)
        with contextlib.suppress(subprocess.TimeoutExpired):
            self.proc.wait(5)
        self.reader.join(2)
        if not self.reader.is_alive():  # a grandchild may still hold the pipe; never block on it
            self.proc.stdout.close()


def _playwright():
    deps = os.environ.get("DEPS_DIR", "/deps")
    if deps and os.path.isdir(deps) and deps not in sys.path:
        sys.path.append(deps)  # appended: the pinned wheels never shadow the standard library
    try:
        import playwright.sync_api as api
    except ImportError as e:
        raise BrowserError(f"Playwright is not installed (DEPS_DIR={deps}): {e}") from e
    return api


def _locator(scope, t: dict):
    if "role" in t:
        return scope.get_by_role(t["role"], name=t["name"], exact=True) if t.get("name") else scope.get_by_role(t["role"])
    if "label" in t:
        # An exact get_by_label compares the label's whole text, which for <label>User <select>…</select>
        # </label> includes every option; a select's accessible name is just "User".
        loc = scope.get_by_label(t["label"], exact=True)
        for role in ("combobox", "listbox"):
            loc = loc.or_(scope.get_by_role(role, name=t["label"], exact=True))
        return loc
    if "placeholder" in t:
        return scope.get_by_placeholder(t["placeholder"], exact=True)
    return scope.get_by_text(t["text"])


def _no(what: str) -> str:
    return "no " + what.removeprefix("the ")  # 'no field labelled "User"', 'no button "Done"'


def _count_error(what: str, n: int) -> str:
    return f"{_no(what)} (0 matches)" if n == 0 else f"{what} matched {n} elements"


def _mismatch(what: str, value: str, texts: list[str]) -> str:
    first = texts[0].strip()[:120] if texts else ""
    if len(texts) == 1:
        return f'{what} does not contain "{value}" (it reads "{first}")'
    return f'no match for {what} contains "{value}" ({len(texts)} matches; the first reads "{first}")'


class _Session:
    """One page on the app: the origin fence, the console, the requests in flight, the steps."""

    def __init__(self, api, browser, origin: str, deadline: float):
        self.api = api
        self.browser = browser
        self.deadline = deadline  # time.monotonic() when the replay's REPLAY_S runs out
        self.crashed = False
        self.origin = origin
        self.netloc = urlsplit(origin).netloc
        self.console: list[str] = []
        self.blank = None  # a page of its own on about:blank, where press steps' keys are tried
        self.pending: set = set()
        self.last = time.monotonic()
        self.context = browser.new_context(viewport=VIEWPORT, service_workers="block")
        self.context.route("**/*", self._route)
        self.context.route_web_socket(lambda url: urlsplit(url).netloc != self.netloc, self._block_ws)
        self.page = self.context.new_page()
        self.page.set_default_timeout(STEP_S * 1000)
        self.page.on("request", self._started)
        self.page.on("requestfinished", self._ended)
        self.page.on("requestfailed", self._ended)
        self.page.on("console", lambda m: self._note(f"{m.type}: {m.text}"))
        self.page.on("pageerror", lambda e: self._note(f"pageerror: {e}"))
        self.page.on("crash", lambda _: setattr(self, "crashed", True))

    # -- the fence, the console, network idle

    def _note(self, line: str) -> None:
        if len(self.console) < CONSOLE_LINES:
            self.console.append(line[:500])

    def _route(self, route) -> None:
        url = route.request.url
        u = urlsplit(url)
        with contextlib.suppress(self.api.Error):  # the page may be closing
            if u.scheme == "http" and u.netloc == self.netloc:
                route.continue_()
            else:
                self._note(f"replay: blocked a request to another origin: {url[:200]}")
                route.abort("aborted")  # "aborted": a blocked navigation leaves the page where it was

    def _block_ws(self, ws) -> None:
        # Not connecting it is the block: the page talks to a mock that never reaches the network.
        self._note(f"replay: blocked a WebSocket to another origin: {ws.url[:200]}")

    def _started(self, request) -> None:
        self.pending.add(request)
        self.last = time.monotonic()

    def _ended(self, request) -> None:
        self.pending.discard(request)
        self.last = time.monotonic()

    def _settle(self, after: str) -> None:
        """Wait until no request has been in flight for QUIET_S, at most IDLE_S, and never past the deadline."""
        start = time.monotonic()
        self.last = max(self.last, start)  # a click's fetch may start a moment after the click
        while self.pending or time.monotonic() - self.last < QUIET_S:
            if time.monotonic() >= self.deadline:
                self._note(f"replay: time ran out while the network was still busy after {after}")
                return
            if time.monotonic() - start >= IDLE_S:
                self._note(f"replay: the network was still busy {IDLE_S} s after {after}")
                return
            self.page.wait_for_timeout(50)

    # -- finding targets

    def _look(self, t: dict):
        """(visible matches, count, failure, error); failure is set when `within` is not exactly one element."""
        scope = self.page
        w = t.get("within")
        if w:
            # css=: an engine prefix in the step (xpath=, text=) is then a parse error, `invalid`.
            scope = self.page.locator("css=" + w["css"]).filter(has_text=w["text"])
            n = scope.count()
            if n != 1:
                return None, 0, "ambiguous" if n else "missing", _count_error(f'{w["css"]} "{w["text"]}"', n)
        loc = _locator(scope, t).filter(visible=True)
        return loc, loc.count(), None, None

    def _one(self, t: dict, deadline: float):
        """An action's target: wait (until deadline) for exactly one element; two or more fail at once."""
        while True:
            loc, n, failure, error = self._look(t)
            if failure is None and n == 1:
                return loc
            if failure is None:
                failure = "ambiguous" if n else "missing"
                error = _count_error(stepfmt.phrase(t), n)
            if failure == "ambiguous" or time.monotonic() >= deadline:
                raise _StepFailed(error, failure)
            self.page.wait_for_timeout(100)

    def _check(self, do: str, t: dict, v: str | None, deadline: float) -> None:
        """Checks pass on any match; expect_absent looks once (the page has settled)."""
        what = stepfmt.phrase(t)
        while True:
            loc, n, failure, error = self._look(t)
            if failure is None and do == "expect_absent":
                if n:
                    raise _StepFailed(f"expected {_no(what)}, found {n}", "mismatch")
                return
            if failure is None and n == 0:
                failure, error = "missing", _count_error(what, 0)
            elif failure is None and do == "expect_visible":
                return
            elif failure is None:
                texts = loc.evaluate_all(TEXTS_JS)
                if any(v in text for text in texts):
                    return
                failure, error = "mismatch", _mismatch(what, v, texts)
            if failure == "ambiguous" or do == "expect_absent" or time.monotonic() >= deadline:
                raise _StepFailed(error, failure)
            self.page.wait_for_timeout(100)

    def _check_key(self, key: str) -> None:
        """`invalid` for a key Playwright cannot press, before the target is looked for: a missing target must
        not hide a step that could never pass. The key is pressed on a blank page, never the app's."""
        if self.blank is None:
            self.blank = self.browser.new_page()  # its own context on about:blank: no app, no network
        try:
            self.blank.keyboard.press(key)
        except self.api.Error as e:
            if not _malformed(e):
                raise
            raise _StepFailed(f'"{key}" is not a key Playwright can press ({_first_line(e)})', "invalid") from None

    # -- the steps

    def load(self) -> None:
        try:
            self.page.goto(self.origin + "/", wait_until="load", timeout=IDLE_S * 1000)
        except self.api.Error as e:
            raise BrowserError(f"the app's page / did not load: {_first_line(e)}") from e
        self._settle("loading /")

    def _do(self, step: dict) -> None:
        do, t, v = step["do"], step.get("target"), step.get("value")
        deadline = min(time.monotonic() + STEP_S, self.deadline)
        if do == "goto":  # whatever the app serves (a 404 page too) is the page the next step sees
            self.page.goto(self.origin + v, wait_until="load",
                           timeout=max(100, round((deadline - time.monotonic()) * 1000)))
            self._settle(f"opening {v}")
        elif do in stepfmt.CHECKS:
            self._check(do, t, v, deadline)
        else:
            if do == "press":
                self._check_key(v)
            loc = self._one(t, deadline)
            ms = max(100, round((deadline - time.monotonic()) * 1000))
            if do == "click":
                loc.click(timeout=ms)
            elif do == "fill":
                loc.fill(v, timeout=ms)
            elif do == "select":
                loc.select_option(label=v, timeout=ms)
            elif do == "press":
                loc.press(v, timeout=ms)
            self._settle(stepfmt.describe(step))

    def run(self, steps: list[dict], shots: str) -> tuple[list[StepResult], int | None]:
        results: list[StepResult] = []
        for n, step in enumerate(steps, 1):
            error = failure = None
            try:
                if time.monotonic() >= self.deadline:
                    raise _StepFailed(_overtime(), "timeout")
                self._do(step)
            except _StepFailed as e:
                error, failure = str(e), e.failure
            except self.api.Error as e:  # a Playwright timeout or a bad selector, unless the browser went away
                if self.crashed or self.page.is_closed() or not self.browser.is_connected():
                    raise BrowserError(f"the browser went away during step {n}: {_first_line(e)}") from e
                if _malformed(e):
                    error, failure = _invalid_error(e, step), "invalid"
                else:
                    error, failure = _step_error(e, step), "error"
            if failure in ("missing", "mismatch", "error") and time.monotonic() >= self.deadline:
                # Its wait was cut short at the deadline, so its own reason says nothing about the page.
                # (ambiguous and invalid are known at once and stand.)
                error, failure = _overtime(), "timeout"
            last = error is not None or n == len(steps)
            shot = self._screenshot() if shots == "all" or (shots == "failure" and last) else None
            results.append(StepResult(n, stepfmt.describe(step), error is None, error, shot, failure))
            if error is not None:
                return results, n
        return results, None

    def _screenshot(self) -> bytes | None:
        try:
            return self.page.screenshot(type="png")
        except self.api.Error as e:
            self._note(f"replay: no screenshot: {_first_line(e)}")
            return None

    def snapshot(self) -> str:
        try:
            return self.page.locator("body").aria_snapshot()[:SNAPSHOT_CHARS]
        except self.api.Error as e:
            self._note(f"replay: no snapshot: {_first_line(e)}")
            return ""


def replay(app_dir: str, steps: list[dict], *, commit: str | None = None, shots: str = "all") -> Replay:
    """Start a fresh copy of the app, load /, run the steps; the first failing step ends the run.

    ValueError: invalid steps or shots. BrowserError: the replay could not be set up.
    `shots`: all (every step), failure (the failing step, or the last one), none.
    """
    if shots not in SHOTS:
        raise ValueError(f"shots must be one of {', '.join(SHOTS)}")
    problems = stepfmt.validate(steps)
    if problems:
        raise ValueError("; ".join(problems))
    with _lock(), tempfile.TemporaryDirectory(prefix="bug-investigator-replay-") as tmp:
        started = time.monotonic()
        deadline = started + REPLAY_S  # Chromium's launch, app start and load count against it
        api = _playwright()
        pw = browser = app = None
        try:
            try:
                pw = api.sync_playwright().start()
                browser = pw.chromium.launch(headless=True, args=[RESOLVER_RULES])
            except Exception as e:  # a missing browser, libraries, CPU features: all one setup failure
                detail = " | ".join(line.strip() for line in str(e).splitlines() if line.strip())
                raise BrowserError(f"Chromium did not launch: {detail[:1500]}") from e
            app = _App(app_dir, tmp, commit)
            app.start()
            try:
                session = _Session(api, browser, app.origin, deadline)
                session.load()
                results, failed_at = session.run(steps, shots)
                snapshot, console = session.snapshot(), session.console
            except api.Error as e:  # outside a step: the browser itself failed
                raise BrowserError(f"the browser failed: {_first_line(e)}") from e
        finally:
            for close in (browser and browser.close, pw and pw.stop, app and app.stop):
                if close:
                    with contextlib.suppress(Exception):
                        close()
    return Replay(ok=failed_at is None, failed_at=failed_at, steps=results, snapshot=snapshot,
                  app_log=list(app.log), console=console, commit=commit,
                  seconds=round(time.monotonic() - started, 2))


# --------------------------------------------------------------------------------------- CLI


def _write(out_dir: str, doc: dict, shots: list[StepResult]) -> None:
    os.makedirs(out_dir, exist_ok=True)
    for name in os.listdir(out_dir):  # no stale screenshots from an earlier run
        if name.startswith("step-") and name.endswith(".png"):
            os.remove(os.path.join(out_dir, name))
    with open(os.path.join(out_dir, "result.json"), "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)
        f.write("\n")
    for s in shots:
        if s.screenshot:
            with open(os.path.join(out_dir, f"step-{s.n}.png"), "wb") as f:
                f.write(s.screenshot)


def _report(name: str, r: Replay) -> str:
    if r.ok:
        return f"PASS {name} ({len(r.steps)} steps, {r.seconds} s)"
    bad = r.steps[-1]
    return f"FAIL {name}: step {bad.n} ({bad.text}): {bad.error}"


def _cmd_replay(args) -> int:
    with open(args.steps, encoding="utf-8") as f:
        doc = json.load(f)
    steps = doc.get("steps") if isinstance(doc, dict) else doc
    r = replay(args.app_dir, steps, commit=args.commit, shots="all")
    _write(args.out, r.to_json(), r.steps)
    print(_report(os.path.basename(args.steps), r))
    return 0 if r.ok else 1


def _cmd_check(args) -> int:
    changed = {os.path.basename(p.strip()) for p in (args.changed or "").split(",") if p.strip()}
    try:
        files = sorted(n for n in os.listdir(args.repros) if n.endswith(".json"))
    except OSError as e:
        print(f"browser.py: cannot list --repros: {e}", file=sys.stderr)
        return 2
    entries = []
    for name in files:
        entry = {"file": name, "title": None, "issue": None, "ok": False, "failed_at": None, "changed": name in changed}
        out_dir = os.path.join(args.out, name[: -len(".json")])
        try:
            doc = stepfmt.load_repro(os.path.join(args.repros, name))
            entry.update(title=doc["title"], issue=doc["issue"])
            r = replay(args.app_dir, doc["steps"], shots="all")
        except (ValueError, OSError, BrowserError) as e:  # an invalid file, or a replay that could not start
            entry["error"] = str(e)
            empty = Replay(ok=False, failed_at=None, steps=[], snapshot="", app_log=[], console=[], commit=None,
                           seconds=0.0)
            _write(out_dir, {"title": entry["title"], "issue": entry["issue"], **empty.to_json(), "error": str(e)}, [])
            print(f"ERROR {name}: {e}")
        else:
            entry.update(ok=r.ok, failed_at=r.failed_at)
            _write(out_dir, {"title": doc["title"], "issue": doc["issue"], **r.to_json()}, r.steps)
            print(_report(name, r))
        entries.append(entry)
    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "summary.json"), "w", encoding="utf-8") as f:
        json.dump({"repros": entries}, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return 0 if all(e["ok"] for e in entries) else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="browser.py", description="Replay UI steps against a throwaway copy of the app.")
    sub = p.add_subparsers(dest="cmd", required=True)
    rp = sub.add_parser("replay", help="replay one list of steps")
    rp.add_argument("--app-dir", required=True)
    rp.add_argument("--steps", required=True, help="a JSON list of steps, or a repro file")
    rp.add_argument("--commit")
    rp.add_argument("--out", required=True)
    ck = sub.add_parser("check", help="replay every repro file; each must pass")
    ck.add_argument("--app-dir", required=True)
    ck.add_argument("--repros", required=True)
    ck.add_argument("--out", required=True)
    ck.add_argument("--changed", help="comma-separated repro paths or file names changed by this PR")
    args = p.parse_args(argv)
    if args.cmd == "check":
        return _cmd_check(args)
    try:
        return _cmd_replay(args)
    except (ValueError, OSError, BrowserError) as e:
        print(f"browser.py: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
