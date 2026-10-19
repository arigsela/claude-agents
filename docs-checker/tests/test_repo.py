"""RepoReader (one commit per run) and the local git fake of the agent-docs server.

The reader is checked against the captured server answers (tests/fixtures/mcp),
and the fake against the same captures, using this repository's own history at
a pinned commit: the reader must parse both the same way.
"""

import asyncio
import json
import os
import re
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest
from langchain_core.tools import StructuredTool
from mcp.types import CallToolResult

from docs_checker.config import load_settings
from docs_checker.evals.localrepo import SERVER, LocalRepoSession, go_json, local_repo_tools
from docs_checker.gate import RecordingGate
from docs_checker.redact import redact
from docs_checker.repo import ReadResult, RefError, RepoReader, resolve_commit
from docs_checker.tools import READ_ONLY_TOOLS, ToolBelt
from tests.fakes import DOCS_SERVER, adapter_tool, fixture

SETTINGS = load_settings({})
# The commit the captures were made at (arigsela/kubernetes main on 2026-10-18).
CAPTURED = "fc7552ef84cdff34b462aeae8e4f27da980a9290"
REPO = {"owner": "arigsela", "repo": "kubernetes"}

# This repository (claude-agents), served by the fake as if it were the docs repo.
REPO_ROOT = Path(__file__).resolve().parents[2]


def git(*args: str, cwd: Path = REPO_ROOT, stdin: str | None = None, env=None) -> str:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=True,
        capture_output=True,
        text=True,
        input=stdin,
        env=env,
    ).stdout


PINNED = "f4b7735b6d45753f007a4180b9c13e94096dd1cb"  # feat(explainer): ... (#91), on main
EARLIER = git("rev-parse", f"{PINNED}^").strip()
LATER = git("rev-parse", "HEAD").strip()  # this branch, after PINNED


def belt_of(tools_by_server: dict, *, settings=None) -> ToolBelt:
    return ToolBelt(
        tools_by_server,
        RecordingGate(),
        bindings={server: sorted(READ_ONLY_TOOLS) for server in tools_by_server},
        settings=settings,
    )


def captured_belt(name: str):
    """A belt whose one tool answers with the captured result ``name``."""
    capture = fixture(name)
    tool, session = adapter_tool(capture["tool"], capture["result"])
    return belt_of({DOCS_SERVER: [tool]}), session, capture


def local_belt(commit: str = PINNED, *, clone: Path = REPO_ROOT, overlays=None) -> ToolBelt:
    return belt_of(local_repo_tools(clone, commit, overlays=overlays))


def dump(result: CallToolResult | dict) -> dict:
    if isinstance(result, dict):
        result = CallToolResult.model_validate(result)
    return result.model_dump(mode="json", exclude_none=True)


def failing(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": True}


# --- the reader on the captured server ------------------------------------------

FILE = fixture("get_file_contents_file")["result"]["content"][1]["resource"]["text"]
VAULT_LISTING = "\n".join(
    f"base-apps/vault/{name}"
    for name in (
        "catalog-info.yaml",
        "certificate.yaml",
        "cluster_role_bindings.yaml",
        "configmaps.yaml",
        "docs.md",
        "docs/",  # a directory; in git's order, after docs.md
        "httproute-internal.yaml",
        "httproute.yaml",
        "mkdocs.yml",
        "namespace.yaml",
        "reference-grant.yaml",
        "runbook.md",
        "service_accounts.yaml",
        "services.yaml",
        "statefulsets.yaml",
    )
)
GONE = "base-apps/vault/does-not-exist.yaml"
NO_SUCH_SHA = "0000000000000000000000000000000000000001"


@pytest.mark.parametrize(
    "name, commit, call, expected, asks_as_captured",
    [
        (
            "get_file_contents_file",
            CAPTURED,
            lambda r: r.read("base-apps/vault/docs.md"),
            ReadResult(
                "base-apps/vault/docs.md",
                "found",
                FILE,  # the file alone: the server's status line is gone
                "790ab964850cf54ee3b40812030698d5a6864313",  # the blob, from that status line
            ),
            True,
        ),
        (
            "get_file_contents_dir",
            CAPTURED,
            lambda r: r.list_dir("base-apps/vault"),
            ReadResult("base-apps/vault", "found", VAULT_LISTING, None),
            True,
        ),
        # a directory is not a file, and a file is not a directory
        (
            "get_file_contents_dir",
            CAPTURED,
            lambda r: r.read("base-apps/vault"),
            ReadResult("base-apps/vault", "error", None, None),
            True,
        ),
        (
            "get_file_contents_file",
            CAPTURED,
            lambda r: r.list_dir("base-apps/vault/docs.md"),
            ReadResult("base-apps/vault/docs.md", "error", None, None),
            True,
        ),
        (
            "get_file_contents_absent",
            CAPTURED,
            lambda r: r.read(GONE),
            ReadResult(GONE, "absent", None, None),
            True,
        ),
        # not an error result: the tree fallback lists the paths it ends, not this one
        (
            "get_file_contents_suffix_match",
            CAPTURED,
            lambda r: r.read("vault/docs.md"),
            ReadResult("vault/docs.md", "absent", None, None),
            True,
        ),
        (
            "get_file_contents_bad_sha",
            NO_SUCH_SHA,
            lambda r: r.read("README.md"),
            ReadResult("README.md", "error", None, None),
            True,
        ),
        (
            "list_commits_path",
            CAPTURED,
            lambda r: r.latest_commit("base-apps/vault/docs.md"),
            "5b4d814e6a041840d0973cf2e2426aac678ec1f7",
            True,
        ),
        ("list_commits_absent_path", CAPTURED, lambda r: r.latest_commit(GONE), None, True),
        (
            "list_commits_bad_ref",
            CAPTURED,
            lambda r: r.latest_commit("base-apps/vault/docs.md"),
            None,
            False,
        ),
        # not in GitHub's code-search index: no items, incomplete. Unknown, not "no hits".
        ("search_code_repo", CAPTURED, lambda r: r.search("vault"), None, False),
        (
            "search_code_hits",
            CAPTURED,
            lambda r: r.search("vault"),
            ["docs/architecture/postgres_database_info.md", ".claude/agents/devops-engineer.md"],
            False,
        ),
    ],
)
async def test_reader_maps_each_fixture(name, commit, call, expected, asks_as_captured):
    belt, session, capture = captured_belt(name)
    reader = RepoReader(belt, commit, search_allowed=True)
    assert await call(reader) == expected
    assert len(session.calls) == 1
    if asks_as_captured:
        # The same arguments the capture used: the commit as sha (never ref, which
        # falls back to the default branch), owner and repo from the belt.
        assert session.calls[0] == (capture["tool"], capture["arguments"])


async def test_file_text_lines_are_the_files_lines():
    belt, _, _ = captured_belt("get_file_contents_file")
    doc = await RepoReader(belt, CAPTURED).read("/base-apps/vault/docs.md")
    assert doc.path == "base-apps/vault/docs.md"
    assert doc.text.split("\n")[:2] == ["---", 'type: "Kubernetes App Guide"']
    assert "successfully downloaded" not in doc.text


async def test_each_call_hands_its_tool_event_to_the_caller():
    belt, _, _ = captured_belt("get_file_contents_file")
    events: list = []
    await RepoReader(belt, CAPTURED).read("base-apps/vault/docs.md", events=events)
    assert [(e["name"], e["status"], e["evidence"]) for e in events] == [
        ("get_file_contents", "ok", ["base-apps/vault/docs.md"])
    ]


TREE_URL = f"https://api.github.com/repos/arigsela/kubernetes/git/trees/{CAPTURED}?recursive=1"
SUFFIX = fixture("get_file_contents_suffix_match")["result"]


async def hangs(owner: str, repo: str, path: str, sha: str = "") -> str:
    await asyncio.sleep(30)
    return "never"


@pytest.mark.parametrize(
    "path, answer, status",
    [
        # the only two ways a path is confirmed absent at the commit
        (GONE, fixture("get_file_contents_absent")["result"], "absent"),
        ("vault/docs.md", SUFFIX, "absent"),
        # the tree lists this very path: it exists and its read failed
        ("base-apps/vault/docs.md", SUFFIX, "transient"),
        (
            "a.yaml",
            failing(f"failed to get git tree: GET {TREE_URL}: 503 Service Unavailable []"),
            "transient",
        ),
        (
            "a.yaml",
            failing("failed to get git tree: GitHub API rate limit exceeded. Retry after 5m0s."),
            "transient",
        ),
        (
            "a.yaml",
            failing(f"failed to get git tree: GET {TREE_URL}: 403 Resource not accessible []"),
            "denied",
        ),
        # a 404 from get_file_contents is the tree's or the ref's, never the path's
        ("a.yaml", failing(f"failed to get git tree: GET {TREE_URL}: 404 Not Found []"), "error"),
        ("README.md", fixture("get_file_contents_bad_sha")["result"], "error"),
        ("a.yaml", hangs, "transient"),  # a timeout
    ],
)
async def test_absent_vs_transient_are_distinct(path, answer, status):
    """Review Focus 1: a read that fails is not a deleted file."""
    if callable(answer):
        tool = StructuredTool.from_function(
            coroutine=answer, name="get_file_contents", description="d"
        )
    else:
        tool, _ = adapter_tool("get_file_contents", answer)
    belt = belt_of({DOCS_SERVER: [tool]}, settings=replace(SETTINGS, tool_timeout_s=0.05))
    reader = RepoReader(belt, CAPTURED)
    for got in (await reader.read(path), await reader.list_dir(path)):
        assert got == ReadResult(path, status, None, None)


# --- one commit per run ---------------------------------------------------------


async def test_resolve_commit_returns_full_sha():
    belt, session, capture = captured_belt("get_commit_main")
    assert await resolve_commit(belt, "main") == CAPTURED
    assert session.calls == [("get_commit", capture["arguments"])]

    # the fake: main is its commit, and a short sha names the full one
    belt = local_belt(PINNED)
    assert await resolve_commit(belt, "main") == PINNED
    assert await resolve_commit(belt, "f4b7735") == PINNED
    assert await resolve_commit(belt, EARLIER[:12]) == EARLIER
    assert await resolve_commit(belt, f" {EARLIER} ") == EARLIER


@pytest.mark.parametrize(
    "ref, status",
    [
        ("no-such-branch", "absent"),
        (LATER, "absent"),  # after the fake's main: not in the repository it serves
        ("--output=/tmp/x", "absent"),  # never reaches git as an option
        ("", "error"),
    ],
)
async def test_unresolvable_refs_raise_ref_error(ref, status):
    with pytest.raises(RefError) as raised:
        await resolve_commit(local_belt(PINNED), ref)
    assert raised.value.ref == ref and raised.value.status == status


async def test_a_failed_resolve_says_why():
    belt, _, _ = captured_belt("get_commit_absent")
    with pytest.raises(RefError) as raised:
        await resolve_commit(belt, NO_SUCH_SHA)
    assert raised.value.status == "absent"

    tool, _ = adapter_tool(
        "get_commit", failing(f"failed to get commit: main: GET {TREE_URL}: 502 x []")
    )
    with pytest.raises(RefError) as raised:
        await resolve_commit(belt_of({DOCS_SERVER: [tool]}), "main")
    assert raised.value.status == "transient"


def test_the_reader_reads_one_resolved_commit():
    belt, _, _ = captured_belt("get_commit_main")
    for ref in ("main", "f4b7735", "", PINNED.upper()):
        with pytest.raises(ValueError):
            RepoReader(belt, ref)
    assert RepoReader(belt, PINNED).commit == PINNED


# --- the local fake ----------------------------------------------------------------


def test_the_fake_is_the_docs_server():
    tools = local_repo_tools(REPO_ROOT, PINNED)
    assert SERVER == DOCS_SERVER == "agent-docs-mcp"
    assert sorted(t.name for t in tools[SERVER]) == sorted(READ_ONLY_TOOLS)


async def test_local_search_is_unavailable_at_a_historical_commit():
    # Ruling S1: GitHub does not index arigsela/kubernetes, so the fake answers
    # every search exactly as the server did, at any commit.
    capture = fixture("search_code_repo")
    answer = await LocalRepoSession(REPO_ROOT, PINNED).call_tool(
        "search_code", capture["arguments"]
    )
    assert dump(answer) == dump(capture["result"])

    events: list = []
    allowed = RepoReader(local_belt(PINNED), PINNED, search_allowed=True)
    assert await allowed.search("CLAUDE.md", events=events) is None  # unknown, not "no hits"
    assert [e["status"] for e in events] == ["ok"]

    events = []
    assert await RepoReader(local_belt(PINNED), PINNED).search("CLAUDE.md", events=events) is None
    assert events == []  # a reader not allowed to search never calls the tool


async def test_overlay_replaces_file_text():
    planted = "# planted\nversion: 9.9.9\n"
    blob = git("hash-object", "--stdin", stdin=planted).strip()
    belt = local_belt(PINNED, overlays={"CLAUDE.md": planted})
    reader = RepoReader(belt, PINNED)
    assert await reader.read("CLAUDE.md") == ReadResult("CLAUDE.md", "found", planted, blob)
    # nothing else changes
    assert (await reader.read("README.md")).text == git("show", f"{PINNED}:README.md")
    # the listing carries the planted blob
    root = await LocalRepoSession(REPO_ROOT, PINNED, {"CLAUDE.md": planted}).call_tool(
        "get_file_contents", {**REPO, "path": "", "sha": PINNED}
    )
    entry = next(e for e in json.loads(root.content[0].text) if e["path"] == "CLAUDE.md")
    assert (entry["sha"], entry["size"]) == (blob, len(planted.encode()))
    # overlays belong to the fake's commit: an earlier commit reads as it was
    earlier = await RepoReader(belt, EARLIER).read("CLAUDE.md")
    assert earlier.text == git("show", f"{EARLIER}:CLAUDE.md")


@pytest.mark.parametrize("path", ["no/such.md", "pr-triage", "../CLAUDE.md", ""])
def test_an_overlay_must_replace_a_file_at_the_commit(path):
    with pytest.raises(ValueError):
        local_repo_tools(REPO_ROOT, PINNED, overlays={path: "x"})


def template(text: str, **values: str) -> str:
    """``text`` with each value replaced by ``{name}``, in the order given."""
    for name, value in values.items():
        text = text.replace(value, "{" + name + "}")
    return text


def entry_shape(entry: dict, ref: str) -> dict:
    """A directory entry with its own path, sha, name and the ref made placeholders."""
    return {
        key: (
            template(value, path=entry["path"], sha=entry["sha"], ref=ref, name=entry["name"])
            if isinstance(value, str)
            else type(value).__name__
        )
        for key, value in entry.items()
    }


def commit_shape(commit: dict) -> dict:
    """The keys of a commit, and the formats of its values."""
    people = {role: p for role, p in commit["commit"].items() if role != "message"}
    return {
        "keys": list(commit),
        "commit_keys": list(commit["commit"]),
        "people": {role: list(p) for role, p in people.items()},
        "html_url": template(commit["html_url"], sha=commit["sha"]),
        "dates_utc": [
            bool(re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", p["date"]))
            for p in people.values()
        ],
    }


GITHUB_USER_KEYS = ("author", "committer")  # GitHub logins; a local clone has none


def without_users(commit: dict) -> dict:
    return {k: v for k, v in commit.items() if k not in GITHUB_USER_KEYS}


# Captures whose answer does not depend on the repository's content: the fake must
# give them word for word (the captured commit becomes the pinned one).
VERBATIM = [
    "get_file_contents_absent",
    "get_file_contents_bad_sha",
    "get_commit_absent",
    "list_commits_absent_path",
    "list_commits_bad_ref",
    "search_code_repo",
]


@pytest.mark.parametrize("name", VERBATIM)
async def test_local_repo_matches_fixture_shapes_verbatim(name):
    capture = fixture(name)
    args = {k: (PINNED if v == CAPTURED else v) for k, v in capture["arguments"].items()}
    answer = await LocalRepoSession(REPO_ROOT, PINNED).call_tool(capture["tool"], args)
    assert dump(answer) == dump(capture["result"])


async def test_local_repo_matches_fixture_shapes():
    session = LocalRepoSession(REPO_ROOT, PINNED)

    async def ask(name: str, **args) -> tuple[dict, dict]:
        capture = fixture(name)
        answer = await session.call_tool(capture["tool"], {**capture["arguments"], **args})
        return dump(answer), dump(capture["result"])

    # a file: a status line naming the blob, then the file as an embedded text resource
    got, want = await ask("get_file_contents_file", path="CLAUDE.md", sha=PINNED)
    blob = git("rev-parse", f"{PINNED}:CLAUDE.md").strip()
    assert [c["type"] for c in got["content"]] == [c["type"] for c in want["content"]]
    assert template(got["content"][0]["text"], sha=blob) == template(
        want["content"][0]["text"], sha="790ab964850cf54ee3b40812030698d5a6864313"
    )
    got_file, want_file = got["content"][1]["resource"], want["content"][1]["resource"]
    assert got_file["mimeType"] == want_file["mimeType"]
    assert template(got_file["uri"], commit=PINNED, path="CLAUDE.md") == template(
        want_file["uri"], commit=CAPTURED, path="base-apps/vault/docs.md"
    )
    assert got_file["text"] == git("show", f"{PINNED}:CLAUDE.md")
    assert got["isError"] is want["isError"] is False

    # a directory: one compact JSON array, entries keyed and linked like GitHub's
    got, want = await ask("get_file_contents_dir", path="pr-triage", sha=PINNED)
    got_text, want_text = got["content"][0]["text"], want["content"][0]["text"]
    assert go_json(json.loads(want_text)) == want_text  # the encoder is the server's
    assert go_json(json.loads(got_text)) == got_text
    got_shapes = {json.dumps(entry_shape(e, PINNED)) for e in json.loads(got_text)}
    want_shapes = {json.dumps(entry_shape(e, CAPTURED)) for e in json.loads(want_text)}
    assert got_shapes == want_shapes  # one file shape, one dir shape
    assert [e["path"] for e in json.loads(got_text)] == git(
        "ls-tree", "--name-only", PINNED, "--", "pr-triage/"
    ).split()

    # a path that only ends another: the tree fallback's non-error answer
    got, want = await ask("get_file_contents_suffix_match", path="triage/README.md", sha=PINNED)
    assert template(
        got["content"][0]["text"], commit=PINNED, files='["pr-triage/README.md"]'
    ) == template(want["content"][0]["text"], commit=CAPTURED, files='["base-apps/vault/docs.md"]')
    assert got["isError"] is want["isError"] is False
    # it lists at most three, the first in the tree's order
    got, _ = await ask("get_file_contents_suffix_match", path="ME.md", sha=PINNED)
    tree = git("ls-tree", "-r", "-t", "--name-only", PINNED).split("\n")
    first_three = [path for path in tree if path.endswith("ME.md")][:3]
    assert f"matching files: {go_json(first_three)})." in got["content"][0]["text"]

    # a commit, and the latest commit that touched a path
    got, want = await ask("get_commit_main")
    got_commit, want_commit = json.loads(got["content"][0]["text"]), json.loads(
        want["content"][0]["text"]
    )
    assert go_json(want_commit) == want["content"][0]["text"]
    assert got_commit["sha"] == PINNED
    assert commit_shape(got_commit) == commit_shape(without_users(want_commit))
    # dates in UTC, as GitHub gives them (git's own rendering, in UTC)
    utc = git(
        "log",
        "-1",
        "--date=iso-strict-local",
        "--format=%ad|%cd",
        PINNED,
        env={**os.environ, "TZ": "UTC"},
    ).strip()
    people = got_commit["commit"]
    assert f'{people["author"]["date"]}|{people["committer"]["date"]}' == utc.replace("+00:00", "Z")

    got, want = await ask("list_commits_path", path="CLAUDE.md", sha=PINNED)
    got_list, want_list = json.loads(got["content"][0]["text"]), json.loads(
        want["content"][0]["text"]
    )
    assert go_json(want_list) == want["content"][0]["text"]
    assert [c["sha"] for c in got_list] == [
        git("log", "-1", "--format=%H", PINNED, "--", "CLAUDE.md").strip()
    ]
    assert [commit_shape(c) for c in got_list] == [
        commit_shape(without_users(c)) for c in want_list
    ]
    message = git("log", "-1", "--format=%B", got_list[0]["sha"]).rstrip("\n")
    assert got_list[0]["commit"]["message"] == message


async def test_reader_reads_the_local_repo_as_it_reads_the_server():
    reader = RepoReader(local_belt(PINNED), PINNED)
    claude = await reader.read("CLAUDE.md")
    assert claude == ReadResult(
        "CLAUDE.md",
        "found",
        redact(git("show", f"{PINNED}:CLAUDE.md")),
        git("rev-parse", f"{PINNED}:CLAUDE.md").strip(),
    )
    listing = await reader.list_dir("pr-triage")
    assert listing.text.split("\n") == [
        "pr-triage/README.md",
        "pr-triage/action.yml",
        "pr-triage/calibration/",
        "pr-triage/pyproject.toml",
        "pr-triage/src/",
        "pr-triage/uv.lock",
    ]
    root = await reader.list_dir("")
    assert ".claude-plugin/" in root.text.split("\n") and "CLAUDE.md" in root.text.split("\n")
    assert (
        await reader.latest_commit("CLAUDE.md")
        == git("log", "-1", "--format=%H", PINNED, "--", "CLAUDE.md").strip()
    )
    assert await reader.latest_commit("no/such/path.md") is None
    assert (await reader.read("triage/README.md")).status == "absent"  # ends a real path
    assert (await reader.read("no/such/path.md")).status == "absent"
    assert (await reader.read("pr-triage")).status == "error"
    assert (await reader.list_dir("CLAUDE.md")).status == "error"
    # the belt refuses a path out of the repository before the tool runs
    assert (await reader.read("../CLAUDE.md")).status == "denied"


def make_repo(root: Path) -> tuple[Path, str]:
    """A one-commit repository with a CRLF file, an empty file and a binary file."""
    repo = root / "repo"
    repo.mkdir()
    git("init", "-q", cwd=repo)
    (repo / "crlf.yaml").write_bytes(b"a: 1\r\nb: 2\r\n")
    (repo / "empty.yaml").write_bytes(b"")
    (repo / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR")
    git("-c", "core.autocrlf=false", "add", "-A", cwd=repo)
    git(
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.com",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-qm",
        "one",
        cwd=repo,
    )
    return repo, git("rev-parse", "HEAD", cwd=repo).strip()


async def test_local_repo_serves_file_bytes_as_github_does(tmp_path):
    repo, commit = make_repo(tmp_path)
    reader = RepoReader(local_belt(commit, clone=repo), commit)
    # no newline translation: line N of the text is line N of the file, byte for byte
    assert (await reader.read("crlf.yaml")).text == "a: 1\r\nb: 2\r\n"
    empty_blob = "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"
    assert await reader.read("empty.yaml") == ReadResult("empty.yaml", "found", "", empty_blob)
    assert (await reader.read("logo.png")).status == "error"  # binary: no text came back


@pytest.mark.parametrize(
    "tool, args, says",
    [
        ("get_file_contents", {"path": "../outside"}, "inside the repository"),
        ("get_file_contents", {"path": "a/../../outside"}, "inside the repository"),
        ("list_commits", {"path": "../outside"}, "inside the repository"),
        ("get_file_contents", {"path": "crlf.yaml", "sha": "--output=x"}, "failed to get git tree"),
        ("list_commits", {"sha": "--output=x"}, "404 Not Found"),
        ("get_commit", {"sha": "--output=x"}, "No commit found"),
    ],
)
async def test_local_repo_refuses_paths_out_and_options(tmp_path, monkeypatch, tool, args, says):
    repo, _ = make_repo(tmp_path)
    session = LocalRepoSession(repo, "HEAD")
    argvs: list[list[str]] = []
    run = subprocess.run

    def spy(argv, *a, **kw):
        argvs.append(list(argv))
        return run(argv, *a, **kw)

    monkeypatch.setattr("docs_checker.evals.localrepo.subprocess.run", spy)
    answer = await session.call_tool(tool, {**REPO, **args})
    assert answer.isError and says in answer.content[0].text
    # nothing from the call reached git: not as an option, not as a path
    assert not any("--output" in arg or ".." in arg for argv in argvs for arg in argv)
