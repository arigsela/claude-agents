"""Screenshots on GitHub: commit PNGs to the evidence branch, and the ui-check PR comment.

`Uploader` commits files to one branch, `bug-investigator-evidence`, through the Git Data API: it
reads the branch head, posts a blob per file, a tree (on the head's tree), a commit and then moves
the ref (or creates the branch, as an orphan, when it is missing). One retry follows a 422 on the
ref (another writer moved or created it first). It takes no branch argument, so it cannot write
anywhere else. It refuses anything but PNGs under a plain relative path, at most 2 MiB each and 30
per commit. `link` gives a file's URL at that commit. Errors (`EvidenceError`) never carry the token
or a request body.

    python3 -I evidence.py post-pr --repo R --pr N --results DIR [--run-url URL] [--api URL]

`post-pr` (token from GITHUB_TOKEN) reads browser.py check's DIR/summary.json. For each repro the
PR changed, it uploads DIR/<stem>/step-<n>.png as pr-<N>/<run>/<stem>/step-<n>.png (run =
GITHUB_RUN_ID, else a UTC stamp), all in one commit. It then edits, or creates, the one PR comment
whose first line is MARKER. Everything in DIR came from the PR's code, so the comment shows titles,
step texts and errors only inside capped code spans, and never the snapshot, app log or console.
Exit 0 when the comment is posted (or no repro changed: then nothing is posted), 1 when the
screenshots could not be uploaded (the comment is posted without them) or the comment could not be
posted, 2 for bad arguments, a missing token or an unreadable summary.json.
"""

from __future__ import annotations

import argparse
import base64
import http.client
import json
import os
import re
import stat
import sys
import unicodedata
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone

if __package__ in (None, ""):  # run as a script (python3 -I .../evidence.py): -I drops PYTHONPATH
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bug_investigator.util import scrub_text  # noqa: E402

BRANCH = "bug-investigator-evidence"
MARKER = "<!-- bug-investigator ui-check -->"
API = "https://api.github.com"
WEB = "https://github.com"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
MAX_BYTES = 2 * 1024 * 1024  # per file
MAX_FILES = 30  # per commit
TIMEOUT_S = 30
PATH_RE = re.compile(r"[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*\.png")
REPO_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
API_RE = re.compile(r"https://[A-Za-z0-9.-]+(:[0-9]+)?(/[A-Za-z0-9._~/-]*)?")
SHA_RE = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")

# post-pr
MAX_REPROS = 10  # shown in one comment
BODY_BUDGET = 60000  # characters; GitHub refuses a comment body over 65536
MAX_STEPS = 15
TITLE_CHARS = 120
TEXT_CHARS = 200
ERROR_CHARS = 300
MAX_JSON_BYTES = 1024 * 1024
COMMENT_PAGES = 50
STEM_RE = re.compile(r"[A-Za-z0-9_-][A-Za-z0-9._-]{0,99}")
RUN_ID_RE = re.compile(r"[0-9]{1,20}")
RUN_URL_RE = re.compile(r"https://[A-Za-z0-9.-]+(/[A-Za-z0-9._~/-]*)?")


class EvidenceError(RuntimeError):
    """A refused upload or a failed GitHub request; `status` is the HTTP status when there was one."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class _GitHub:
    """JSON calls to the GitHub REST API with a bearer token that is never logged or redirected."""

    def __init__(self, token: str, api: str, opener=None):
        if not isinstance(token, str) or not token.strip():
            raise EvidenceError("no GitHub token")
        if not isinstance(api, str) or not API_RE.fullmatch(api.rstrip("/") or "-"):
            raise EvidenceError("the GitHub API URL must be https://host[/path]")
        self._token = token
        self.base = api.rstrip("/")
        self._open = opener or urllib.request.urlopen

    def _clean(self, message: str) -> str:
        return scrub_text(message, [self._token])[:500]

    def call(self, method: str, path: str, body: dict | None = None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method)
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("X-GitHub-Api-Version", "2022-11-28")
        req.add_header("User-Agent", "bug-investigator")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        req.add_unredirected_header("Authorization", f"Bearer {self._token}")  # a redirect drops it
        try:
            with self._open(req, timeout=TIMEOUT_S) as r:
                raw = r.read()
        except urllib.error.HTTPError as e:
            try:
                detail = e.read().decode("utf-8", "replace")
            except Exception:  # noqa: BLE001 - the status alone will do
                detail = ""
            try:
                doc = json.loads(detail)
            except ValueError:
                doc = None
            if isinstance(doc, dict) and isinstance(doc.get("message"), str):
                detail = doc["message"]  # GitHub's reason; the rest of the body is noise
            detail = " ".join(detail.split())[:200]
            raise EvidenceError(self._clean(f"GitHub {method} {path}: HTTP {e.code}: {detail}"), e.code) from None
        except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError) as e:
            raise EvidenceError(self._clean(f"GitHub {method} {path}: {type(e).__name__}: {e}")) from None
        if not raw.strip():
            return None
        try:
            return json.loads(raw)
        except ValueError:
            raise EvidenceError(f"GitHub {method} {path}: the response is not JSON") from None


def _check_repo(repo) -> None:
    if not isinstance(repo, str) or not REPO_RE.fullmatch(repo) or any(p in (".", "..") for p in repo.split("/")):
        raise EvidenceError(f"not an owner/name repository: {str(repo)[:100]!r}")


def _check_path(path) -> None:
    if (not isinstance(path, str) or not PATH_RE.fullmatch(path) or ".." in path
            or any(seg == "." for seg in path.split("/"))):
        raise EvidenceError(f"refused path {str(path)[:200]!r}: a relative a/b.png path of [A-Za-z0-9._-]")


def _check_files(files) -> None:
    if not isinstance(files, dict) or not files:
        raise EvidenceError("nothing to upload")
    if len(files) > MAX_FILES:
        raise EvidenceError(f"refused {len(files)} files: at most {MAX_FILES} per commit")
    for path, data in files.items():
        _check_path(path)
        if not isinstance(data, (bytes, bytearray)) or bytes(data[:8]) != PNG_SIGNATURE:
            raise EvidenceError(f"refused {path}: not a PNG")
        if len(data) > MAX_BYTES:
            raise EvidenceError(f"refused {path}: {len(data)} bytes, at most {MAX_BYTES}")


def _sha(doc, what: str) -> str:
    sha = doc.get("sha") if isinstance(doc, dict) else None
    if not isinstance(sha, str) or not SHA_RE.fullmatch(sha):
        raise EvidenceError(f"GitHub returned no {what} SHA")
    return sha


class Uploader:
    """Commits files to BRANCH, the only ref it reads or writes."""

    def __init__(self, repo: str, token: str, *, api: str = API, opener=None):
        _check_repo(repo)
        self.repo = repo
        self._gh = _GitHub(token, api, opener)

    def _head(self) -> tuple[str | None, str | None]:
        """(head commit, its tree) of BRANCH; (None, None) when the branch does not exist."""
        try:
            ref = self._gh.call("GET", f"/repos/{self.repo}/git/ref/heads/{BRANCH}")
        except EvidenceError as e:
            if e.status == 404:
                return None, None
            raise
        if not isinstance(ref, dict) or ref.get("ref") != f"refs/heads/{BRANCH}":
            raise EvidenceError(f"GitHub returned another ref than {BRANCH}")
        head = _sha(ref.get("object"), "head commit")
        commit = self._gh.call("GET", f"/repos/{self.repo}/git/commits/{head}")
        return head, _sha(commit.get("tree") if isinstance(commit, dict) else None, "tree")

    def _post(self, kind: str, body: dict) -> str:
        return _sha(self._gh.call("POST", f"/repos/{self.repo}/git/{kind}", body), kind[:-1])

    def upload(self, files: dict[str, bytes], message: str) -> str:
        """Commit `files` ({path: PNG bytes}) on BRANCH in one commit; returns the commit SHA."""
        _check_files(files)
        if not isinstance(message, str) or not message.strip():
            raise EvidenceError("a commit message is required")
        head, base = self._head()
        blobs = [{"path": p, "mode": "100644", "type": "blob",
                  "sha": self._post("blobs", {"content": base64.b64encode(bytes(files[p])).decode("ascii"),
                                              "encoding": "base64"})}
                 for p in sorted(files)]
        for attempt in (1, 2):
            if attempt == 2:  # another writer moved (or created) the branch: build on its head, once
                head, base = self._head()
            tree = self._post("trees", {"tree": blobs, **({"base_tree": base} if base else {})})
            commit = self._post("commits", {"message": message, "tree": tree, "parents": [head] if head else []})
            try:
                if head:
                    self._gh.call("PATCH", f"/repos/{self.repo}/git/refs/heads/{BRANCH}", {"sha": commit, "force": False})
                else:
                    self._gh.call("POST", f"/repos/{self.repo}/git/refs", {"ref": f"refs/heads/{BRANCH}", "sha": commit})
            except EvidenceError as e:
                if e.status != 422:
                    raise
                if attempt == 2:
                    raise EvidenceError(f"{e} (after one retry)", e.status) from None
                continue
            return commit
        raise AssertionError("unreachable")

    def link(self, sha: str, path: str) -> str:
        """The file's URL at that commit (it renders inline in an issue or PR comment)."""
        _check_path(path)
        if not isinstance(sha, str) or not SHA_RE.fullmatch(sha):
            raise EvidenceError(f"not a commit SHA: {str(sha)[:80]!r}")
        return f"{WEB}/{self.repo}/blob/{sha}/{path}?raw=true"


# --------------------------------------------------------------------------------- post-pr


@dataclass
class _Step:
    n: int
    text: str
    ok: bool
    error: str | None


@dataclass
class _Repro:
    stem: str
    title: str
    issue: int | None
    ok: bool
    failed_at: int | None
    error: str | None
    steps: list[_Step]
    shots: dict[int, str]  # step number -> local PNG path

    @property
    def last(self) -> int | None:
        return self.steps[-1].n if self.steps else None


def _int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_file(path: str) -> bool:
    """A regular file, not a symlink (the results came from the PR's code)."""
    try:
        return stat.S_ISREG(os.lstat(path).st_mode)
    except OSError:
        return False


def _read(path: str, limit: int) -> bytes | None:
    """A regular file's bytes, at most limit + 1 of them; None when it is missing or not a regular file."""
    if not _is_file(path):
        return None
    try:
        with open(path, "rb") as f:
            return f.read(limit + 1)
    except OSError:
        return None


def _load_json(path: str):
    raw = _read(path, MAX_JSON_BYTES)
    if raw is None or len(raw) > MAX_JSON_BYTES:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except ValueError:
        return None


def _repro(results: str, stem: str, entry: dict) -> _Repro:
    folder = os.path.join(results, stem)
    doc = _load_json(os.path.join(folder, "result.json"))
    doc = doc if isinstance(doc, dict) else {}
    steps: dict[int, _Step] = {}
    for s in doc.get("steps") if isinstance(doc.get("steps"), list) else []:
        if len(steps) >= MAX_STEPS:
            break
        if isinstance(s, dict) and _int(s.get("n")) and 1 <= s["n"] <= MAX_STEPS and s["n"] not in steps:
            err = s.get("error")
            steps[s["n"]] = _Step(s["n"], str(s.get("text") or ""), s.get("ok") is True,
                                  str(err) if err not in (None, "") else None)
    shots = {n: p for n in steps if _is_file(p := os.path.join(folder, f"step-{n}.png"))}
    title = entry.get("title")
    error = entry.get("error")
    if not doc and not error:
        error = "the replay left no result"
    return _Repro(stem=stem, title=title if isinstance(title, str) and title.strip() else stem,
                  issue=entry["issue"] if _int(entry.get("issue")) and entry["issue"] > 0 else None,
                  ok=entry.get("ok") is True,
                  failed_at=entry["failed_at"] if _int(entry.get("failed_at")) else None,
                  error=str(error) if error else None, steps=[steps[n] for n in sorted(steps)], shots=shots)


def changed_repros(results: str) -> list[_Repro] | None:
    """The repros the PR changed, from DIR/summary.json; None when it cannot be read."""
    summary = _load_json(os.path.join(results, "summary.json"))
    if not isinstance(summary, dict) or not isinstance(summary.get("repros"), list):
        return None
    out: list[_Repro] = []
    seen = set()
    for e in summary["repros"]:
        if not isinstance(e, dict) or e.get("changed") is not True:
            continue
        name = e.get("file")
        stem = name[: -len(".json")] if isinstance(name, str) and name.endswith(".json") else ""
        if not STEM_RE.fullmatch(stem) or ".." in stem or stem in seen:
            print(f"skipped a repro entry with an unusable file name: {str(name)[:80]!r}", file=sys.stderr)
            continue
        seen.add(stem)
        out.append(_repro(results, stem, e))
    return out


def _code(text, cap: int) -> str:
    """Untrusted text as one inline code span: one line, no backticks, at most `cap` characters."""
    s = "".join(" " if unicodedata.category(c) in ("Cc", "Cf", "Zl", "Zp") else c for c in str(text))
    s = " ".join(s.replace("`", "\u02cb").split())  # U+02CB, not a backtick: one would end the span
    if len(s) > cap:
        s = s[: cap - 1] + "…"
    return f"`{s or '-'}`"


def _section(r: _Repro, links: dict) -> list[str]:
    if r.ok:
        verdict = "✅ every step passed"
    elif r.failed_at is not None:
        verdict = f"❌ failed at step {r.failed_at}"
    else:
        verdict = f"❌ could not be replayed: {_code(r.error or 'no result', ERROR_CHARS)}"
    issue = f" (#{r.issue})" if r.issue else ""
    out = [f"#### {_code(r.title, TITLE_CHARS)}{issue}", "", verdict, ""]
    for s in r.steps:
        line = f"{s.n}. {'✓' if s.ok else '✗'} {_code(s.text, TEXT_CHARS)}"
        if not s.ok and s.error:
            line += f" — {_code(s.error, ERROR_CHARS)}"
        out.append(line)
    if r.steps:
        out.append("")
    if (r.stem, r.last) in links:
        out += [f"![step {r.last}]({links[(r.stem, r.last)]})", ""]
    others = [n for n in sorted(r.shots) if n != r.last and (r.stem, n) in links]
    if others:
        out += ["<details><summary>All steps</summary>", ""]
        for n in others:
            out += [f"![step {n}]({links[(r.stem, n)]})", ""]
        out += ["</details>", ""]
    return out


def render_comment(repros: list[_Repro], links: dict, *, upload_error: str | None = None, left_out: int = 0,
                   hidden: int = 0, run_url: str | None = None) -> str:
    """The PR comment: MARKER, then per repro its verdict, steps and screenshots (`links`: (stem, n) -> URL)."""
    lines = [MARKER, "### UI check on this branch", ""]
    if upload_error:
        lines += [f"⚠️ screenshots could not be uploaded: {_code(upload_error, ERROR_CHARS)}", ""]
    size = sum(len(x) + 1 for x in lines) + len(run_url or "") + 300  # the footer's lines
    for i, r in enumerate(repros):
        section = _section(r, links)
        size += sum(len(x) + 1 for x in section)
        if size > BODY_BUDGET:  # results can mark every step failed, with long errors
            hidden += len(repros) - i
            break
        lines += section
    if hidden:
        lines += [f"{hidden} more changed repros are not shown.", ""]
    if left_out:
        lines += [f"{left_out} more screenshots were not uploaded (at most {MAX_FILES} per run).", ""]
    if run_url:
        lines += [f"[Workflow run]({run_url})", ""]
    return "\n".join(lines).rstrip("\n") + "\n"


def _plan(pr: int, run: str, repros: list[_Repro]) -> tuple[list[tuple[_Repro, int, str]], int]:
    """(repro, step, upload path) for at most MAX_FILES shots, each repro's last step first; and how many are left out."""
    first = [(r, r.last) for r in repros if r.last in r.shots]
    rest = [(r, n) for r in repros for n in sorted(r.shots) if n != r.last]
    chosen = (first + rest)[:MAX_FILES]
    return [(r, n, f"pr-{pr}/{run}/{r.stem}/step-{n}.png") for r, n in chosen], len(first) + len(rest) - len(chosen)


def _own(c) -> bool:
    """A comment this workflow posted: a bot's, MARKER on its first line."""
    if not isinstance(c, dict) or not _int(c.get("id")):
        return False
    user = c.get("user") if isinstance(c.get("user"), dict) else {}
    body = c.get("body") if isinstance(c.get("body"), str) else ""
    bot = user.get("type") == "Bot" or str(user.get("login", "")).endswith("[bot]")
    return bot and MARKER in body.split("\n", 1)[0]


def upsert_comment(gh: _GitHub, repo: str, pr: int, body: str) -> str:
    for page in range(1, COMMENT_PAGES + 1):
        batch = gh.call("GET", f"/repos/{repo}/issues/{pr}/comments?per_page=100&page={page}")
        if not isinstance(batch, list):
            raise EvidenceError("GitHub returned no comment list")
        for c in batch:
            if _own(c):
                gh.call("PATCH", f"/repos/{repo}/issues/comments/{c['id']}", {"body": body})
                return f"edited comment {c['id']}"
        if len(batch) < 100:
            break
    created = gh.call("POST", f"/repos/{repo}/issues/{pr}/comments", {"body": body})
    return f"created comment {created.get('id') if isinstance(created, dict) else '?'}"


def post_pr(repo: str, pr: int, results: str, *, token: str, run: str, api: str = API, opener=None,
            run_url: str | None = None) -> int:
    def fail(message: str, code: int) -> int:
        print(f"evidence.py: {scrub_text(message, [token])}", file=sys.stderr)
        return code

    if pr < 1:
        return fail("--pr must be a positive number", 2)
    try:
        uploader = Uploader(repo, token, api=api, opener=opener)
        gh = _GitHub(token, api, opener)
    except EvidenceError as e:
        return fail(str(e), 2)
    repros = changed_repros(results)
    if repros is None:
        return fail(f"cannot read {os.path.join(results, 'summary.json')}", 2)
    if not repros:
        print("no changed repro: nothing to post")
        return 0
    hidden = max(0, len(repros) - MAX_REPROS)
    repros = repros[:MAX_REPROS]
    if run_url and not RUN_URL_RE.fullmatch(run_url):
        print("evidence.py: --run-url is not a plain https URL; left out", file=sys.stderr)
        run_url = None
    plan, left_out = _plan(pr, run, repros)
    files = {}
    for r, n, path in plan:
        data = _read(r.shots[n], MAX_BYTES)
        if data is not None:
            files[path] = data
    links: dict = {}
    upload_error = None
    if files:
        try:
            sha = uploader.upload(files, f"ui-check screenshots for PR #{pr}, run {run}")
        except EvidenceError as e:
            upload_error = scrub_text(str(e), [token])
            print(f"evidence.py: screenshots could not be uploaded: {upload_error}", file=sys.stderr)
        else:
            links = {(r.stem, n): uploader.link(sha, path) for r, n, path in plan if path in files}
            print(f"uploaded {len(files)} screenshots to {BRANCH} at {sha}")
    body = render_comment(repros, links, upload_error=upload_error, left_out=left_out, hidden=hidden,
                          run_url=run_url)
    try:
        print(upsert_comment(gh, repo, pr, body))
    except EvidenceError as e:
        return fail(f"the comment could not be posted: {e}", 1)
    return 1 if upload_error else 0


def main(argv: list[str] | None = None, *, opener=None, environ=None, now: datetime | None = None) -> int:
    env = os.environ if environ is None else environ
    p = argparse.ArgumentParser(prog="evidence.py",
                                description="Screenshots on the evidence branch, and the ui-check PR comment.")
    sub = p.add_subparsers(dest="cmd", required=True)
    pp = sub.add_parser("post-pr", help="upload a ui-check run's screenshots and edit or create its PR comment")
    pp.add_argument("--repo", required=True, help="owner/name")
    pp.add_argument("--pr", type=int, required=True)
    pp.add_argument("--results", required=True, help="browser.py check's --out directory")
    pp.add_argument("--run-url", help="the workflow run, linked in the comment")
    pp.add_argument("--api", help=f"GitHub API base (default: $GITHUB_API_URL, else {API})")
    a = p.parse_args(argv)
    token = env.get("GITHUB_TOKEN", "")
    if not token.strip():
        print("evidence.py: GITHUB_TOKEN is not set", file=sys.stderr)
        return 2
    run = env.get("GITHUB_RUN_ID", "")
    if not RUN_ID_RE.fullmatch(run):
        run = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return post_pr(a.repo, a.pr, a.results, token=token, run=run, api=a.api or env.get("GITHUB_API_URL") or API,
                   opener=opener, run_url=a.run_url)


if __name__ == "__main__":
    sys.exit(main())
