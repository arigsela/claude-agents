"""evidence.py: the evidence-branch uploader and the ui-check PR comment, against an in-memory GitHub."""
import base64
import email.message
import hashlib
import inspect
import io
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit

import pytest

from bug_investigator import evidence
from bug_investigator.evidence import BRANCH, MARKER, EvidenceError, Uploader

API = "https://api.test"
REPO = "o/r"
TOKEN = "ghs_" + "Ab1" * 12
PNG = b"\x89PNG\r\n\x1a\n" + b"pixels"
RUN_URL = "https://github.com/o/r/actions/runs/777"


def _sha(*parts) -> str:
    return hashlib.sha1(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()


class Resp:
    def __init__(self, status, body):
        self.status, self._body, self.headers = status, body, {}

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def http_error(url, status, raw: bytes):
    return urllib.error.HTTPError(url, status, "error", email.message.Message(), io.BytesIO(raw))


class FakeGitHub:
    """A small in-memory GitHub (git objects, refs, issue comments) that records every request."""

    def __init__(self, files=None, comments=None):
        self.requests = []
        self.blobs, self.trees, self.commits, self.refs = {}, {}, {}, {}
        self.comments = [dict(c) for c in comments or []]
        self.racers = 0  # another writer moves the branch just before this many of our ref updates
        self.fail = {}  # (method, path suffix) -> (status, raw body)
        self.next_id = 1000
        if files is not None:
            self.refs[BRANCH] = self.write(files)

    def write(self, files, parent=None) -> str:
        """Another writer's commit of `files` on top of `parent` (a new root when None)."""
        tree = dict(self.trees[self.commits[parent]["tree"]]) if parent else {}
        for p, data in files.items():
            b = _sha("blob", data.hex())
            self.blobs[b] = data
            tree[p] = b
        t = _sha("tree", tree)
        self.trees[t] = tree
        c = _sha("commit", t, parent, len(self.commits))
        self.commits[c] = {"tree": t, "parents": [parent] if parent else [], "message": "other writer"}
        return c

    def ancestors(self, sha) -> set:
        seen, todo = set(), [sha]
        while todo:
            s = todo.pop()
            if s not in seen:
                seen.add(s)
                todo += self.commits[s]["parents"]
        return seen

    def files_at(self, sha) -> dict:
        return {p: self.blobs[b] for p, b in self.trees[self.commits[sha]["tree"]].items()}

    def __call__(self, req, timeout=None):
        u = urlsplit(req.full_url)
        body = json.loads(req.data) if req.data else None
        rec = {"method": req.get_method(), "path": u.path, "query": parse_qs(u.query), "url": req.full_url,
               "headers": {k.lower(): v for k, v in req.header_items()},
               "unredirected": {k.lower() for k in req.unredirected_hdrs}, "body": body, "timeout": timeout}
        self.requests.append(rec)
        for (m, suffix), (status, raw) in self.fail.items():
            if rec["method"] == m and rec["path"].endswith(suffix):
                raise http_error(req.full_url, status, raw)
        status, out = self.route(rec["method"], rec["path"], rec["query"], body)
        raw = json.dumps(out).encode()
        if status >= 400:
            raise http_error(req.full_url, status, raw)
        return Resp(status, raw)

    def route(self, method, path, query, body):
        base = f"/repos/{REPO}"
        one_ref, refs = f"{base}/git/ref/heads/", f"{base}/git/refs"
        if method == "GET" and path.startswith(one_ref):
            name = path[len(one_ref):]
            if name not in self.refs:
                return 404, {"message": "Not Found"}
            return 200, {"ref": f"refs/heads/{name}", "object": {"sha": self.refs[name], "type": "commit"}}
        if method == "GET" and path.startswith(f"{base}/git/commits/"):
            sha = path.rsplit("/", 1)[1]
            if sha not in self.commits:
                return 404, {"message": "Not Found"}
            return 200, {"sha": sha, "tree": {"sha": self.commits[sha]["tree"]}}
        if method == "POST" and path == f"{base}/git/blobs":
            assert body["encoding"] == "base64"
            data = base64.b64decode(body["content"])
            b = _sha("blob", data.hex())
            self.blobs[b] = data
            return 201, {"sha": b}
        if method == "POST" and path == f"{base}/git/trees":
            base_tree = body.get("base_tree")
            if base_tree is not None and base_tree not in self.trees:
                return 422, {"message": "base_tree is not a tree"}
            tree = dict(self.trees.get(base_tree, {}))
            for e in body["tree"]:
                assert e["mode"] == "100644" and e["type"] == "blob" and e["sha"] in self.blobs
                tree[e["path"]] = e["sha"]
            t = _sha("tree", tree)
            self.trees[t] = tree
            return 201, {"sha": t}
        if method == "POST" and path == f"{base}/git/commits":
            assert body["tree"] in self.trees and all(p in self.commits for p in body["parents"])
            c = _sha("commit", body["tree"], body["parents"], len(self.commits))
            self.commits[c] = {"tree": body["tree"], "parents": list(body["parents"]), "message": body["message"]}
            return 201, {"sha": c}
        if method in ("POST", "PATCH") and path.startswith(refs):
            if self.racers:
                self.racers -= 1
                self.refs[BRANCH] = self.write({f"other/{len(self.commits)}.png": PNG}, self.refs.get(BRANCH))
            if method == "POST":
                assert path == refs
                name = body["ref"].removeprefix("refs/heads/")
                if name in self.refs:
                    return 422, {"message": "Reference already exists"}
                self.refs[name] = body["sha"]
                return 201, {"ref": body["ref"], "object": {"sha": body["sha"]}}
            name = path.removeprefix(refs + "/heads/")
            if name not in self.refs:
                return 422, {"message": "Reference does not exist"}
            if not body.get("force") and self.refs[name] not in self.ancestors(body["sha"]):
                return 422, {"message": "Update is not a fast forward"}
            self.refs[name] = body["sha"]
            return 200, {"ref": f"refs/heads/{name}", "object": {"sha": body["sha"]}}
        m = re.fullmatch(rf"{base}/issues/(\d+)/comments", path)
        if m and method == "GET":
            per, page = int(query["per_page"][0]), int(query.get("page", ["1"])[0])
            return 200, self.comments[(page - 1) * per: page * per]
        if m and method == "POST":
            self.next_id += 1
            c = {"id": self.next_id, "body": body["body"], "user": {"login": "github-actions[bot]", "type": "Bot"}}
            self.comments.append(c)
            return 201, c
        m = re.fullmatch(rf"{base}/issues/comments/(\d+)", path)
        if m and method == "PATCH":
            for c in self.comments:
                if c["id"] == int(m.group(1)):
                    c["body"] = body["body"]
                    return 200, c
        return 404, {"message": "Not Found"}


def up(fake, token=TOKEN):
    return Uploader(REPO, token, api=API, opener=fake)


def calls(fake):
    return [(r["method"], r["path"].removeprefix(f"/repos/{REPO}")) for r in fake.requests]


def ref_calls(fake):
    return [c for c in calls(fake) if c[1].startswith("/git/ref")]


GET_REF = ("GET", f"/git/ref/heads/{BRANCH}")
PATCH_REF = ("PATCH", f"/git/refs/heads/{BRANCH}")
POST_REF = ("POST", "/git/refs")


# ---------------------------------------------------------------------------------- Uploader


def test_upload_creates_orphan_branch():
    fake = FakeGitHub()
    sha = up(fake).upload({"a/step-1.png": PNG, "a/step-2.png": PNG + b"2"}, "shots")
    assert calls(fake) == [GET_REF, ("POST", "/git/blobs"), ("POST", "/git/blobs"), ("POST", "/git/trees"),
                           ("POST", "/git/commits"), POST_REF]
    assert "base_tree" not in fake.requests[3]["body"]
    assert fake.requests[4]["body"]["parents"] == []
    assert fake.requests[4]["body"]["message"] == "shots"
    assert fake.requests[5]["body"] == {"ref": f"refs/heads/{BRANCH}", "sha": sha}
    assert fake.refs == {BRANCH: sha}
    assert fake.files_at(sha) == {"a/step-1.png": PNG, "a/step-2.png": PNG + b"2"}
    for r in fake.requests:
        assert r["url"].startswith(API + "/")
        assert r["headers"]["authorization"] == f"Bearer {TOKEN}"
        assert "authorization" in r["unredirected"]  # never forwarded on a redirect
        assert r["headers"]["accept"] == "application/vnd.github+json"
        assert r["timeout"]


def test_upload_appends_to_existing_branch():
    fake = FakeGitHub(files={"old/step-1.png": PNG})
    head = fake.refs[BRANCH]
    sha = up(fake).upload({"new/step-1.png": PNG + b"n"}, "more")
    assert calls(fake) == [GET_REF, ("GET", f"/git/commits/{head}"), ("POST", "/git/blobs"), ("POST", "/git/trees"),
                           ("POST", "/git/commits"), PATCH_REF]
    assert fake.requests[3]["body"]["base_tree"] == fake.commits[head]["tree"]
    assert fake.requests[4]["body"]["parents"] == [head]
    assert fake.requests[5]["body"] == {"sha": sha, "force": False}
    assert fake.refs[BRANCH] == sha
    assert fake.files_at(sha) == {"old/step-1.png": PNG, "new/step-1.png": PNG + b"n"}


def test_retry_once_on_non_fast_forward():
    fake = FakeGitHub(files={"old/step-1.png": PNG})
    fake.racers = 1
    sha = up(fake).upload({"new/step-1.png": PNG}, "m")
    assert calls(fake).count(("POST", "/git/blobs")) == 1  # blobs are reused on the retry
    assert ref_calls(fake) == [GET_REF, PATCH_REF, GET_REF, PATCH_REF]
    assert fake.refs[BRANCH] == sha
    theirs = fake.commits[sha]["parents"][0]
    assert any(p.startswith("other/") for p in fake.files_at(theirs))
    assert set(fake.files_at(sha)) == set(fake.files_at(theirs)) | {"new/step-1.png"}


def test_retry_when_the_reference_already_exists():
    fake = FakeGitHub()  # missing at our GET; another writer creates it before our POST /git/refs
    fake.racers = 1
    sha = up(fake).upload({"new/step-1.png": PNG}, "m")
    assert ref_calls(fake) == [GET_REF, POST_REF, GET_REF, PATCH_REF]
    theirs = fake.commits[sha]["parents"][0]
    tree_bodies = [r["body"] for r in fake.requests if r["path"].endswith("/git/trees")]
    assert "base_tree" not in tree_bodies[0] and tree_bodies[1]["base_tree"] == fake.commits[theirs]["tree"]
    assert set(fake.files_at(sha)) == set(fake.files_at(theirs)) | {"new/step-1.png"}


def test_a_second_ref_failure_raises():
    fake = FakeGitHub(files={"old/step-1.png": PNG})
    fake.racers = 2
    with pytest.raises(EvidenceError) as e:
        up(fake).upload({"new/step-1.png": PNG}, "m")
    assert e.value.status == 422 and "fast forward" in str(e.value)
    assert ref_calls(fake) == [GET_REF, PATCH_REF, GET_REF, PATCH_REF]
    assert calls(fake).count(("POST", "/git/blobs")) == 1
    assert "new/step-1.png" not in fake.files_at(fake.refs[BRANCH])


def test_every_ref_is_the_evidence_branch():
    assert list(inspect.signature(Uploader).parameters) == ["repo", "token", "api", "opener"]
    assert list(inspect.signature(Uploader.upload).parameters) == ["self", "files", "message"]
    fakes = [FakeGitHub(), FakeGitHub(files={"x.png": PNG}), FakeGitHub(files={"x.png": PNG}), FakeGitHub()]
    fakes[2].racers = fakes[3].racers = 1
    for fake in fakes:
        up(fake).upload({"a/step-1.png": PNG}, "m")
    touched = [r for fake in fakes for r in fake.requests if "/git/ref" in r["path"]]
    assert len(touched) == 12
    for r in touched:
        path = r["path"].removeprefix(f"/repos/{REPO}")
        if path == "/git/refs":
            assert r["method"] == "POST" and r["body"]["ref"] == f"refs/heads/{BRANCH}"
        else:
            assert path in (f"/git/ref/heads/{BRANCH}", f"/git/refs/heads/{BRANCH}")
    assert all(set(fake.refs) == {BRANCH} for fake in fakes)


def test_refuses_bad_paths_and_non_png():
    fake = FakeGitHub()
    u = up(fake)
    for path in ["../x.png", "a/../x.png", "x..png", "/abs.png", "a//b.png", "a/./b.png", "a b.png", "a\\b.png",
                 "x.jpg", "x.PNG", "x.png/", "x.png\n", ".png", "a/.png", "", None]:
        with pytest.raises(EvidenceError):
            u.upload({path: PNG}, "m")
    for data in [b"GIF89a....", "not bytes", b"", PNG + b"0" * evidence.MAX_BYTES]:
        with pytest.raises(EvidenceError):
            u.upload({"a/step-1.png": data}, "m")
    with pytest.raises(EvidenceError):
        u.upload({f"a/step-{n}.png": PNG for n in range(31)}, "m")
    with pytest.raises(EvidenceError):
        u.upload({}, "m")
    assert fake.requests == []  # refused before any request
    big = PNG + b"0" * (evidence.MAX_BYTES - len(PNG))
    u.upload({**{f"a/step-{n}.png": PNG for n in range(29)}, "a/big.png": big}, "m")  # the limits themselves pass
    for repo in ["o", "o/r/x", "../r", "o/..", "o/r?x=1", "o /r"]:
        with pytest.raises(EvidenceError):
            Uploader(repo, TOKEN, api=API, opener=fake)
    for api in ["http://api.test", "ftp://x", "https://"]:
        with pytest.raises(EvidenceError):
            Uploader(REPO, TOKEN, api=api, opener=fake)
    with pytest.raises(EvidenceError):
        Uploader(REPO, "", api=API, opener=fake)


def test_link_format():
    u = up(FakeGitHub())
    sha = "0123456789abcdef0123456789abcdef01234567"
    assert u.link(sha, "pr-5/777/issue-42/step-3.png") == \
        f"https://github.com/o/r/blob/{sha}/pr-5/777/issue-42/step-3.png?raw=true"
    with pytest.raises(EvidenceError):
        u.link(sha, "../x.png")
    with pytest.raises(EvidenceError):
        u.link("main", "x.png")


@pytest.mark.parametrize("token", [TOKEN, "plain-token-value-123"])
def test_token_never_in_errors(token, tmp_path, capsys):
    def failing(status, raw):
        fake = FakeGitHub()
        fake.fail[("GET", f"/git/ref/heads/{BRANCH}")] = (status, raw)
        with pytest.raises(EvidenceError) as e:
            up(fake, token).upload({"x.png": PNG}, "m")
        return e.value

    err = failing(401, json.dumps({"message": f"Bad credentials {token}"}).encode())
    assert err.status == 401 and "401" in str(err) and "Bad credentials" in str(err) and token not in str(err)
    err = failing(500, f"<html>{token}</html>".encode())
    assert token not in str(err)

    def broken(req, timeout=None):
        raise urllib.error.URLError(f"proxy said Authorization: Bearer {token}")

    with pytest.raises(EvidenceError) as e:
        Uploader(REPO, token, api=API, opener=broken).upload({"x.png": PNG}, "m")
    assert token not in str(e.value)

    fake = FakeGitHub()  # a refused blob: GitHub's message only, never the request body
    fake.fail[("POST", "/git/blobs")] = (422, b'{"message": "Invalid request"}')
    with pytest.raises(EvidenceError) as e:
        up(fake, token).upload({"x.png": PNG}, "m")
    assert base64.b64encode(PNG).decode() not in str(e.value) and "Invalid request" in str(e.value)

    results = write_results(tmp_path / "out", FAILING)
    fake = FakeGitHub()
    fake.fail[("POST", "/git/blobs")] = (403, json.dumps({"message": f"no access for {token}"}).encode())
    assert post(results, fake, env={"GITHUB_TOKEN": token, "GITHUB_RUN_ID": "1"}) == 1
    assert len(fake.comments) == 1 and token not in fake.comments[0]["body"]
    out = capsys.readouterr()
    assert token not in out.out + out.err


def test_redirects_drop_the_token():
    fake = FakeGitHub()
    up(fake).upload({"x.png": PNG}, "m")
    req = urllib.request.Request(fake.requests[0]["url"])
    req.add_unredirected_header("Authorization", f"Bearer {TOKEN}")  # as the uploader adds it
    assert fake.requests[0]["unredirected"] == {"authorization"}
    moved = urllib.request.HTTPRedirectHandler().redirect_request(
        req, io.BytesIO(), 307, "moved", email.message.Message(), "https://elsewhere.test/x")
    assert not moved.has_header("Authorization")


# ---------------------------------------------------------------------------------- post-pr


def write_results(root, *repros):
    """browser.py check's output: summary.json, and per repro <stem>/result.json and step-<n>.png."""
    root.mkdir(exist_ok=True)
    entries = []
    for r in repros:
        r = dict(r)
        steps, shots, extra = r.pop("steps", []), r.pop("shots", None), r.pop("result", {})
        entry = {"file": r["file"], "title": r.get("title"), "issue": r.get("issue"), "ok": r.get("ok", False),
                 "failed_at": r.get("failed_at"), "changed": r.get("changed", True)}
        if "error" in r:
            entry["error"] = r["error"]
        entries.append(entry)
        d = root / r["file"].removesuffix(".json")
        d.mkdir()
        doc = {"title": entry["title"], "issue": entry["issue"], "ok": entry["ok"], "failed_at": entry["failed_at"],
               "commit": None, "seconds": 1.0,
               "steps": [{"n": i, "text": t, "ok": ok, "error": err, "failure": None if ok else "missing"}
                         for i, (t, ok, err) in enumerate(steps, 1)],
               "snapshot": "SNAPSHOT-SENTINEL", "app_log": ["APPLOG-SENTINEL"], "console": ["CONSOLE-SENTINEL"],
               **extra}
        (d / "result.json").write_text(json.dumps(doc))
        for n in shots if shots is not None else range(1, len(steps) + 1):
            (d / f"step-{n}.png").write_bytes(PNG + bytes([n]))
    (root / "summary.json").write_text(json.dumps({"repros": entries}))
    return str(root)


FAILING = {"file": "issue-42.json", "title": "Dana starts her task", "issue": 42, "ok": False, "failed_at": 3,
           "steps": [("open /", True, None), ('click button "Start"', True, None),
                     ('expect the text "In progress" to be visible', False, 'no text "In progress" (0 matches)')]}
UNCHANGED = {"file": "board-loads.json", "title": "The board loads", "issue": None, "ok": True, "changed": False,
             "steps": [("open /", True, None)]}


def post(results, fake, *extra, env=None, now=None):
    environ = {"GITHUB_TOKEN": TOKEN, "GITHUB_RUN_ID": "777"} if env is None else env
    return evidence.main(["post-pr", "--repo", REPO, "--pr", "5", "--results", results, "--api", API, *extra],
                         opener=fake, environ=environ, now=now)


def bot_comments(fake):
    return [c for c in fake.comments if c["user"]["type"] == "Bot"]


def test_post_pr_upserts_one_comment(tmp_path):
    results = write_results(tmp_path / "out", FAILING, UNCHANGED)
    human = {"id": 1, "body": f"{MARKER}\ncopied the marker", "user": {"login": "dana", "type": "User"}}
    fake = FakeGitHub(comments=[human])
    assert post(results, fake, "--run-url", RUN_URL) == 0
    sha = fake.refs[BRANCH]
    assert set(fake.files_at(sha)) == {f"pr-5/777/issue-42/step-{n}.png" for n in (1, 2, 3)}
    assert fake.files_at(sha)["pr-5/777/issue-42/step-3.png"] == PNG + bytes([3])
    assert len(bot_comments(fake)) == 1 and fake.comments[0] == human
    body = bot_comments(fake)[0]["body"]
    assert body.splitlines()[0] == MARKER
    assert "### UI check on this branch" in body.splitlines()

    def link(n, run="777"):
        return f"https://github.com/{REPO}/blob/{fake.refs[BRANCH]}/pr-5/{run}/issue-42/step-{n}.png?raw=true"

    assert "`Dana starts her task` (#42)" in body and "❌" in body and "board loads" not in body
    assert "1. ✓ `open /`" in body and '2. ✓ `click button "Start"`' in body
    assert '3. ✗ `expect the text "In progress" to be visible` — `no text "In progress" (0 matches)`' in body
    assert f"![step 3]({link(3)})" in body
    details = body[body.index("<details><summary>All steps</summary>"): body.index("</details>")]
    assert f"![step 1]({link(1)})" in details and f"![step 2]({link(2)})" in details and "step 3" not in details
    assert body.index("![step 3]") < body.index("<details>")
    assert f"[Workflow run]({RUN_URL})" in body
    listed = [r for r in fake.requests if r["method"] == "GET" and r["path"].endswith("/issues/5/comments")]
    assert listed and listed[0]["query"]["per_page"] == ["100"]

    assert post(results, fake, env={"GITHUB_TOKEN": TOKEN, "GITHUB_RUN_ID": "778"}) == 0  # a re-run edits it
    mine = bot_comments(fake)
    assert len(mine) == 1 and f"![step 3]({link(3, '778')})" in mine[0]["body"]
    writes = [(r["method"], r["path"]) for r in fake.requests if "/comments" in r["path"] and r["method"] != "GET"]
    assert writes == [("POST", f"/repos/{REPO}/issues/5/comments"),
                      ("PATCH", f"/repos/{REPO}/issues/comments/{mine[0]['id']}")]
    assert fake.comments[0] == human
    assert "[Workflow run]" not in mine[0]["body"]  # no --run-url this time


def test_post_pr_finds_its_comment_on_a_later_page(tmp_path):
    results = write_results(tmp_path / "out", FAILING)
    noise = [{"id": i, "body": "lgtm", "user": {"login": "dana", "type": "User"}} for i in range(1, 151)]
    old = {"id": 151, "body": f"{MARKER}\nold", "user": {"login": "github-actions[bot]", "type": "Bot"}}
    fake = FakeGitHub(comments=noise + [old])
    assert post(results, fake) == 0
    pages = [r["query"].get("page") for r in fake.requests if r["method"] == "GET" and "/comments" in r["path"]]
    assert pages == [["1"], ["2"]]
    assert len(fake.comments) == 151 and fake.comments[-1]["body"].startswith(MARKER + "\n")
    assert "Dana starts her task" in fake.comments[-1]["body"]


def test_post_pr_without_changed_repros_posts_nothing(tmp_path, capsys):
    results = write_results(tmp_path / "out", UNCHANGED, {**FAILING, "changed": False})
    fake = FakeGitHub()
    assert post(results, fake) == 0
    assert fake.requests == []
    assert "no changed repro" in capsys.readouterr().out


@pytest.mark.parametrize("failure", ["no contents write", "racing writer"])
def test_post_pr_upload_failure_still_comments(failure, tmp_path, capsys):
    results = write_results(tmp_path / "out", FAILING)
    fake = FakeGitHub(files={"x.png": PNG})
    if failure == "no contents write":
        fake.fail[("POST", "/git/blobs")] = (403, b'{"message": "Resource not accessible by integration"}')
        reason = "Resource not accessible by integration"
    else:
        fake.racers = 2
        reason = "Update is not a fast forward"
    assert post(results, fake) == 1
    body = bot_comments(fake)[0]["body"]
    assert body.splitlines()[0] == MARKER
    assert "screenshots could not be uploaded:" in body and reason in body
    assert "![step" not in body and "<details>" not in body
    assert '3. ✗ `expect the text "In progress" to be visible`' in body
    err = capsys.readouterr().err
    assert "screenshots could not be uploaded" in err and reason in err


def test_post_pr_escapes_untrusted_text(tmp_path):
    hostile = "x` <img src=x onerror=alert(1)> @octocat **bold** #7\n\n# Injected\n</details>\n<!-- y"
    results = write_results(
        tmp_path / "out",
        {"file": "issue-9.json", "title": "T " + hostile, "issue": 9, "ok": False, "failed_at": 2,
         "steps": [("open / " + hostile, True, None), ("click " + "z" * 5000, False, "E " + hostile + "e" * 5000)]},
        {"file": "broken.json", "title": "Broken", "issue": True, "ok": False, "error": "cannot start: " + hostile})
    fake = FakeGitHub()
    assert post(results, fake) == 0
    body = bot_comments(fake)[0]["body"]
    for sentinel in ("SNAPSHOT-SENTINEL", "APPLOG-SENTINEL", "CONSOLE-SENTINEL"):
        assert sentinel not in body
    for line in body.splitlines():
        assert line.count("`") % 2 == 0, line
        assert not line.startswith(("# ", "</details>\n", "<!-- y")), line
    outside = re.sub(r"`[^`\n]*`", "", body)  # the text outside code spans
    for bad in ("<img", "@octocat", "**bold**", "Injected", "<!-- y", "#7", "onerror"):
        assert bad not in outside, bad
    assert outside.count("<details>") == outside.count("</details>") == 1
    assert "could not be replayed" in body and "#True" not in body and "(#9)" in body
    assert max(len(line) for line in body.splitlines()) < 1000  # capped


def test_post_pr_caps_repros_and_uploads(tmp_path):
    m = evidence.MAX_REPROS
    repros = [{"file": f"r{i:02}.json", "title": f"repro {i}", "issue": i + 1, "ok": False, "failed_at": 15,
               "steps": [("open /", True, None)] * 14 + [("expect no error", False, "found 1")]}
              for i in range(m + 3)]
    results = write_results(tmp_path / "out", *repros)
    fake = FakeGitHub()
    assert post(results, fake) == 0
    uploaded = set(fake.files_at(fake.refs[BRANCH]))
    assert len(uploaded) == evidence.MAX_FILES
    assert {f"pr-5/777/r{i:02}/step-15.png" for i in range(m)} <= uploaded  # every shown repro's last step first
    assert not any(p.startswith(f"pr-5/777/r{m:02}/") for p in uploaded)
    body = bot_comments(fake)[0]["body"]
    assert f"(#{m})" in body and f"(#{m + 1})" not in body
    assert "3 more changed repros are not shown" in body
    assert f"{m * 15 - evidence.MAX_FILES} more screenshots were not uploaded" in body


def test_comment_stays_under_githubs_limit(tmp_path):
    long = "w" * 2000  # results the PR's code wrote: every step failed, with a long error
    repros = [{"file": f"r{i:02}.json", "title": long, "issue": i + 1, "ok": False, "failed_at": 1,
               "steps": [(long, False, long)] * 15} for i in range(evidence.MAX_REPROS)]
    results = write_results(tmp_path / "out", *repros)
    fake = FakeGitHub()
    assert post(results, fake, "--run-url", RUN_URL) == 0
    body = bot_comments(fake)[0]["body"]
    assert len(body) < 65536
    assert "more changed repros are not shown" in body and "(#1)" in body
    assert body.rstrip().endswith(f"[Workflow run]({RUN_URL})")


def test_post_pr_run_id_falls_back_to_a_utc_stamp(tmp_path):
    results = write_results(tmp_path / "out", FAILING)
    fake = FakeGitHub()
    now = datetime(2026, 10, 29, 12, 3, 4, tzinfo=timezone.utc)
    assert post(results, fake, env={"GITHUB_TOKEN": TOKEN}, now=now) == 0
    assert "pr-5/20261029T120304Z/issue-42/step-1.png" in fake.files_at(fake.refs[BRANCH])


def test_post_pr_bad_inputs_exit_2(tmp_path, capsys):
    results = write_results(tmp_path / "out", FAILING)
    fake = FakeGitHub()
    assert post(results, fake, env={"GITHUB_RUN_ID": "1"}) == 2
    assert "GITHUB_TOKEN" in capsys.readouterr().err
    assert post(str(tmp_path / "missing"), fake) == 2
    assert evidence.main(["post-pr", "--repo", "o/r/../x", "--pr", "5", "--results", results, "--api", API],
                         opener=fake, environ={"GITHUB_TOKEN": TOKEN}) == 2
    assert fake.requests == []


def test_post_pr_runs_as_an_isolated_script(tmp_path):
    results = write_results(tmp_path / "out", UNCHANGED)
    cmd = [sys.executable, "-I", evidence.__file__, "post-pr", "--repo", REPO, "--pr", "5", "--results", results]
    r = subprocess.run(cmd, capture_output=True, text=True, check=False, env={"GITHUB_TOKEN": TOKEN}, timeout=60)
    assert r.returncode == 0, r.stderr
    assert "no changed repro" in r.stdout
    r = subprocess.run(cmd, capture_output=True, text=True, check=False, env={}, timeout=60)
    assert r.returncode == 2 and "GITHUB_TOKEN" in r.stderr
