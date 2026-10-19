import asyncio
import itertools
import json
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from langchain_core.tools import StructuredTool, ToolException
from langchain_mcp_adapters.tools import convert_mcp_tool_to_langchain_tool
from mcp.shared.exceptions import McpError
from mcp.types import CallToolResult, ErrorData, Tool

from docs_checker.config import load_settings
from docs_checker.gate import GateResult, RecordingGate
from docs_checker.levers import Levers
from docs_checker.redact import redact_obj
from docs_checker.tools import (
    MODEL_TEXT_CHARS,
    NODE_TOOLS,
    READ_ONLY_TOOLS,
    ToolBelt,
    ToolResult,
    _approved,
    evidence_for,
    model_text,
    stable_call_id,
    to_text,
)
from tests.fakes import DOCS_SERVER, FAKE_BINDINGS, fake_tools_by_server

FIXTURES = Path(__file__).parent / "fixtures" / "mcp"
SETTINGS = load_settings({})


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


class RefuseGate:
    async def check(self, call):
        return GateResult(decision="refuse", angle_deg=80.0, reason="80 deg")


IN_REPO = {"owner": "arigsela", "repo": "kubernetes", "path": "a.yaml"}


def file_reader(server: str, log: list) -> StructuredTool:
    async def get_file_contents(owner: str, repo: str, path: str) -> str:
        log.append((server, path))
        return f"{server}: {path}"

    return StructuredTool.from_function(
        coroutine=get_file_contents, name="get_file_contents", description="Read a file"
    )


def one_tool_belt(tool, *, settings=None, **kwargs) -> ToolBelt:
    return ToolBelt(
        {DOCS_SERVER: [tool]},
        RecordingGate(),
        bindings={DOCS_SERVER: (tool.name,)},
        settings=settings,
        **kwargs,
    )


# --- the captured server (tests/fixtures/mcp) --------------------------------


class FixtureSession:
    """Stands in for an MCP ClientSession: answers every call with one captured result."""

    def __init__(self, result: dict):
        self.result = CallToolResult.model_validate(result)
        self.calls: list[tuple[str, dict]] = []

    async def call_tool(self, name, arguments=None, progress_callback=None, **_):
        self.calls.append((name, arguments))
        return self.result


def adapter_tool(tool: str, result: dict, *, handle_tool_errors: bool = False):
    """The real langchain-mcp-adapters tool for the captured schema of ``tool``.

    ``handle_tool_errors=False`` is what ``server.load_mcp_tools`` uses (an isError
    result raises a ToolException); True returns it as a ToolMessage with
    status "error". The belt must read both.
    """
    schema = Tool.model_validate(fixture("tools_list")["tools"][tool])
    session = FixtureSession(result)
    converted = convert_mcp_tool_to_langchain_tool(
        session, schema, server_name=DOCS_SERVER, handle_tool_errors=handle_tool_errors
    )
    return converted, session


NODE_OF = {
    "get_file_contents": "load",
    "list_commits": "load",
    "get_commit": "scope",
    "search_code": "locate",
}


async def replay(name: str, *, handle_tool_errors: bool = False, settings=None):
    captured = fixture(name)
    tool, session = adapter_tool(
        captured["tool"], captured["result"], handle_tool_errors=handle_tool_errors
    )
    belt = one_tool_belt(tool, settings=settings)
    # A search runs in this repository whatever the capture asked (the belt would
    # refuse search_code_hits' own user: qualifier).
    args = {"query": "vault"} if captured["tool"] == "search_code" else captured["arguments"]
    result, event = await belt.call(
        captured["tool"], args, node=NODE_OF[captured["tool"]], intent="i"
    )
    return result, event, session


def test_fixtures_are_captured_live_and_redacted():
    names = sorted(p.stem for p in FIXTURES.glob("*.json"))
    assert "tools_list" in names and len(names) > 10
    for name in names:
        captured = fixture(name)
        assert captured["synthetic"] is False, name
        assert redact_obj(captured) == captured, f"{name} was written unredacted"
    tools = fixture("tools_list")["tools"]
    assert set(tools) == READ_ONLY_TOOLS
    params = {name: set(tool["inputSchema"]["properties"]) for name, tool in tools.items()}
    # Task 6 reads at one commit through these parameters.
    assert {"path", "ref", "sha"} <= params["get_file_contents"]
    assert {"path", "sha", "page", "perPage"} <= params["list_commits"]
    assert {"sha", "page"} <= params["get_commit"]
    assert {"query", "page", "perPage"} <= params["search_code"]


@pytest.mark.parametrize("handle_tool_errors", [False, True])
@pytest.mark.parametrize(
    "name, status",
    [
        ("get_file_contents_file", "ok"),
        ("get_file_contents_dir", "ok"),
        # the contents API 404s, the tree fallback finds no such path
        ("get_file_contents_absent", "absent"),
        # not an MCP error at all: the tree fallback lists paths that only end with it
        ("get_file_contents_suffix_match", "absent"),
        # a 422 about the sha, not a not-found
        ("get_file_contents_bad_sha", "error"),
        ("get_commit_main", "ok"),
        ("get_commit_absent", "absent"),
        ("list_commits_path", "ok"),
        ("list_commits_absent_path", "ok"),  # an empty list: no error
        ("list_commits_bad_ref", "absent"),
        # not indexed by GitHub code search: no items, which is not an error
        ("search_code_repo", "ok"),
        ("search_code_hits", "ok"),
    ],
)
async def test_each_captured_result_gets_its_status(name, status, handle_tool_errors):
    result, event, session = await replay(name, handle_tool_errors=handle_tool_errors)
    assert session.calls, "the tool was called"
    assert result.status == status
    assert event["status"] == status and event["ok"] is (status == "ok")
    if status != "ok":
        assert event["evidence"] == []


SUFFIX = fixture("get_file_contents_suffix_match")["result"]["content"][0]["text"]


def answering(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": False}


@pytest.mark.parametrize(
    "path, text, status",
    [
        # The worded shapes below are github-mcp-server v1.14.0's own format strings
        # (pkg/github/repositories.go); none is an error result, none is the file.
        (
            "big.bin",
            (
                "File big.bin is too large to display (2097152 bytes). Use the download URL to "
                "fetch the content: https://raw.githubusercontent.com/x (SHA: abc)"
            ),
            "error",
        ),
        ("logo.png", "successfully downloaded binary file (SHA: abc)", "error"),
        (
            "a.yaml",
            (
                "successfully downloaded text file (SHA: abc) Note: the provided ref 'main' does "
                "not exist, default branch 'refs/heads/master' was used instead.\nchart: vault"
            ),
            "error",
        ),
        # the captured suffix match, asked for the path it lists: it exists, the read failed
        ("base-apps/vault/docs.md", SUFFIX, "transient"),
        ("vault/docs.md", SUFFIX, "absent"),
        # the fallback's limit of three paths, none of them this one: proves nothing
        (
            "docs.md",
            SUFFIX.replace('["base-apps/vault/docs.md"]', '["a/docs.md","b/docs.md","c/docs.md"]'),
            "error",
        ),
        ("a.yaml", "successfully downloaded text file (SHA: abc)\nchart: vault", "ok"),
    ],
)
async def test_file_results_that_are_not_the_file_are_not_ok(path, text, status):
    tool, _ = adapter_tool("get_file_contents", answering(text))
    result, event = await one_tool_belt(tool).call(
        "get_file_contents", {"path": path, "sha": "abc"}, node="load", intent="i"
    )
    assert result.status == status and event["ok"] is (status == "ok")
    assert event["evidence"] == ([path] if status == "ok" else [])


# The captured 404, in go-github's "<what failed>: GET <url>: <code> <message> []".
NOT_FOUND = fixture("list_commits_bad_ref")["result"]["content"][0]["text"]


def failing(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": True}


async def test_a_404_is_absent_a_403_is_denied_a_timeout_is_transient():
    absent, _, _ = await replay("list_commits_bad_ref")
    assert "404 Not Found" in NOT_FOUND and absent.status == "absent"

    forbidden = NOT_FOUND.replace("404 Not Found", "403 Resource not accessible by integration")
    tool, _ = adapter_tool("list_commits", failing(forbidden))
    denied, event = await one_tool_belt(tool).call(
        "list_commits", {"sha": "main"}, node="load", intent="i"
    )
    assert denied.status == "denied" and event["ok"] is False

    async def hangs(owner: str, repo: str, path: str) -> str:
        await asyncio.sleep(30)
        return "never"

    slow = StructuredTool.from_function(coroutine=hangs, name="get_file_contents", description="d")
    belt = one_tool_belt(slow, settings=replace(SETTINGS, tool_timeout_s=0.05))
    timed_out, event = await belt.call("get_file_contents", IN_REPO, node="load", intent="i")
    assert timed_out.status == "transient" and "timed out" in timed_out.text
    assert event["ok"] is False and event["evidence"] == []


def with_status(code_and_message: str) -> str:
    return NOT_FOUND.replace("404 Not Found", code_and_message)


@pytest.mark.parametrize(
    "tool, text, status",
    [
        ("list_commits", with_status("401 Bad credentials"), "denied"),
        # go-github's primary rate limit is a 403; it is a wait, not a denial
        (
            "list_commits",
            with_status("403 API rate limit exceeded for user ID 1. [rate reset in 4m59s]"),
            "transient",
        ),
        (
            "list_commits",
            "failed to list commits: GitHub API rate limit exceeded. Retry after 5m0s.",
            "transient",
        ),
        (
            "search_code",
            "failed to search code: GitHub secondary rate limit exceeded. Wait before retrying.",
            "transient",
        ),
        ("list_commits", with_status("502 Bad Gateway"), "transient"),
        ("list_commits", with_status("429 Too Many Requests"), "transient"),
        ("list_commits", "failed to list commits: unexpected status 503: upstream", "transient"),
        (
            "get_commit",
            'failed to get commit: main: Get "https://api.github.com/x": dial tcp: i/o timeout',
            "transient",
        ),
        ("search_code", with_status("422 Validation Failed"), "error"),
        # in get_file_contents a 404 is never about the path: the server sends the
        # contents API's 404 to its tree fallback, so a 404 here is the tree or ref
        (
            "get_file_contents",
            (
                "failed to get git tree: GET https://api.github.com/repos/arigsela/kubernetes"
                "/git/trees/abc?recursive=1: 404 Not Found []"
            ),
            "error",
        ),
        ("get_file_contents", "failed to get file contents", "error"),
        # a 404 in the URL is not the status: this is a 500 for docs/404.md
        (
            "list_commits",
            (
                "failed to list commits: abc: GET https://api.github.com/repos/arigsela/kubernetes"
                "/commits?path=docs%2F404.md: 500 Internal Server Error []"
            ),
            "transient",
        ),
    ],
)
async def test_tool_errors_are_classified_conservatively(tool, text, status):
    adapter, _ = adapter_tool(tool, failing(text))
    args = {"query": "x"} if tool == "search_code" else {"path": "a.yaml", "sha": "main"}
    result, _ = await one_tool_belt(adapter).call(tool, args, node=NODE_OF[tool], intent="i")
    assert result.status == status


def http_error(code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "http://agent-docs-mcp.kagent:3000/mcp")
    return httpx.HTTPStatusError(
        "x", request=request, response=httpx.Response(code, request=request)
    )


@pytest.mark.parametrize(
    "error, status",
    [
        (httpx.ConnectError("connection refused"), "transient"),
        (httpx.ReadTimeout("read timed out"), "transient"),
        (http_error(503), "transient"),
        (http_error(403), "denied"),
        # the MCP endpoint was not found, not the file: never "absent"
        (http_error(404), "error"),
        (ExceptionGroup("session", [ValueError("x"), httpx.ConnectError("reset")]), "transient"),
        (ValueError("Unknown MCP content type"), "error"),
    ],
)
async def test_transport_failures_are_transient_never_absent(error, status):
    async def broken(owner: str, repo: str, path: str) -> str:
        raise error

    tool = StructuredTool.from_function(coroutine=broken, name="get_file_contents", description="d")
    result, event = await one_tool_belt(tool).call(
        "get_file_contents", IN_REPO, node="load", intent="i"
    )
    assert result.status == status and event["ok"] is False


async def test_only_the_servers_error_result_can_say_absent():
    # The same 404 words from the MCP session (e.g. the gateway's JSON-RPC error)
    # are not the server's answer about the commit.
    async def gateway(owner: str, repo: str, sha: str = "") -> str:
        raise McpError(ErrorData(code=-32603, message=NOT_FOUND))

    tool = StructuredTool.from_function(coroutine=gateway, name="list_commits", description="d")
    result, _ = await one_tool_belt(tool).call(
        "list_commits", {"sha": "x"}, node="load", intent="i"
    )
    assert result.status == "error"

    adapter, _ = adapter_tool("list_commits", failing(NOT_FOUND))
    result, _ = await one_tool_belt(adapter).call(
        "list_commits", {"sha": "x"}, node="load", intent="i"
    )
    assert result.status == "absent"


async def test_the_text_is_parsed_before_any_cap():
    captured = fixture("get_file_contents_dir")
    listing = captured["result"]["content"][0]["text"]
    result, event, _ = await replay("get_file_contents_dir")

    assert len(listing) > MODEL_TEXT_CHARS
    # the caller gets the whole listing, so it parses
    assert [e["path"] for e in json.loads(result.text)] == [e["path"] for e in json.loads(listing)]
    assert result.raw_chars == len(listing) and event["result_chars"] == len(result.text)
    # only model_text caps it
    assert len(model_text(result, Levers.all_on())) <= MODEL_TEXT_CHARS


async def test_a_file_comes_back_whole_after_the_servers_status_line():
    captured = fixture("get_file_contents_file")
    status_line = captured["result"]["content"][0]["text"]
    body = captured["result"]["content"][1]["resource"]["text"]
    result, event, _ = await replay("get_file_contents_file")
    assert result.status == "ok"
    assert result.text == f"{status_line}\n{body}"
    assert event["evidence"] == ["base-apps/vault/docs.md"]


def numbered(count: int, width: int = 90) -> list[str]:
    return [f"line {i}: " + "x" * width for i in range(count)]


def test_model_text_caps_on_line_boundaries():
    lines = numbered(300)
    text = "\n".join(lines)
    result = ToolResult(text=text, status="ok", raw_chars=len(text))

    shrunk = model_text(result, Levers.all_on())
    assert len(shrunk) <= MODEL_TEXT_CHARS
    *kept, marker = shrunk.split("\n")
    assert kept and kept == lines[: len(kept)]  # whole lines only, in order
    assert f"{len(lines) - len(kept)} more lines" in marker

    # lever 7 off: the whole text; short text is never touched
    assert model_text(result, Levers.without("shrink_results")) == text
    short = ToolResult(text="a\nb", status="ok", raw_chars=3)
    assert model_text(short, Levers.all_on()) == "a\nb"


def test_model_text_cuts_a_single_overlong_line_and_says_so():
    text = "y" * (3 * MODEL_TEXT_CHARS)
    shrunk = model_text(ToolResult(text=text, status="ok", raw_chars=len(text)), Levers.all_on())
    assert len(shrunk) <= MODEL_TEXT_CHARS
    first, marker = shrunk.split("\n")
    assert set(first) == {"y"} and "omitted" in marker


def test_model_text_redacts_whatever_it_is_given():
    text = "password: hunter2hunter2\nchart: vault"
    shrunk = model_text(ToolResult(text=text, status="ok", raw_chars=len(text)), Levers.all_on())
    assert "hunter2hunter2" not in shrunk and "chart: vault" in shrunk


class FakeClock:
    def __init__(self):
        self.now = 1000.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds
        await asyncio.sleep(0)


async def test_searches_are_paced_and_capped():
    clock = FakeClock()
    started: list[tuple[float, str]] = []

    async def search_code(query: str) -> str:
        started.append((clock(), query))
        return '{"total_count":0,"incomplete_results":false,"items":[]}'

    tool = StructuredTool.from_function(coroutine=search_code, name="search_code", description="s")
    settings = replace(SETTINGS, max_searches=3, search_interval_s=6.0)
    belt = one_tool_belt(tool, settings=settings, clock=clock, sleep=clock.sleep)
    memo: dict = {}

    results = await asyncio.gather(
        *(
            belt.call("search_code", {"query": f"v{i}"}, node="locate", intent="i", memo=memo)
            for i in range(4)
        )
    )

    assert sorted(result.status for result, _ in results) == ["denied", "ok", "ok", "ok"]
    assert len(started) == 3  # past the cap, nothing is called
    times = [at for at, _ in started]
    assert all(later - earlier >= 6.0 for earlier, later in itertools.pairwise(times))
    assert clock.slept == [6.0, 6.0]
    over = next(event for result, event in results if result.status == "denied")
    assert over["decision"] == "deny" and over["ok"] is False

    # A replayed search (same call, same memo) returns its result: no call, no wait.
    first_query = started[0][1]
    again, _ = await belt.call(
        "search_code", {"query": first_query}, node="locate", intent="i", memo=memo
    )
    assert again.status == "ok" and len(started) == 3 and clock.slept == [6.0, 6.0]


def test_node_tools_are_the_read_tools_split_by_node():
    assert READ_ONLY_TOOLS == {"get_file_contents", "search_code", "list_commits", "get_commit"}
    assert NODE_TOOLS == {
        "intake": {"get_commit", "list_commits"},
        "scope": {"get_file_contents", "list_commits", "get_commit"},
        "load": {"get_file_contents", "list_commits"},
        "locate": {"search_code"},
    }


def test_tools_on_demand_decides_which_schemas_a_model_carries():
    on = ToolBelt(fake_tools_by_server(), RecordingGate(), bindings=FAKE_BINDINGS)
    assert [t.name for t in on.schemas_for("load")] == ["get_file_contents", "list_commits"]
    assert [t.name for t in on.schemas_for("locate")] == ["search_code"]
    assert on.schemas_for("judge") == []

    settings = replace(SETTINGS, levers=Levers.without("tools_on_demand"))
    off = ToolBelt(
        fake_tools_by_server(), RecordingGate(), bindings=FAKE_BINDINGS, settings=settings
    )
    every = ["get_commit", "get_file_contents", "list_commits", "search_code"]
    for node in ("judge", "load", "locate", "extract"):
        assert [t.name for t in off.schemas_for(node)] == every


def test_belt_exposes_only_allowlisted_tools_bound_in_the_template():
    bindings = {DOCS_SERVER: ("search_code", "delete_file")}
    belt = ToolBelt(fake_tools_by_server(), RecordingGate(), bindings=bindings)
    assert [t.name for t in belt.schemas_for("locate")] == ["search_code"]
    assert belt.schemas_for("load") == []  # get_file_contents is not bound
    assert "delete_file" not in READ_ONLY_TOOLS


async def test_a_binding_on_one_server_never_authorizes_another_servers_tool():
    # agent-docs binds get_file_contents but does not offer it; a second server
    # offers a tool of that name without binding it. Nothing may be called.
    log: list = []
    tools = {DOCS_SERVER: [], "rogue-mcp": [file_reader("rogue-mcp", log)]}
    bindings = {DOCS_SERVER: ("get_file_contents",), "rogue-mcp": ()}
    belt = ToolBelt(tools, RecordingGate(), bindings=bindings)
    result, event = await belt.call("get_file_contents", IN_REPO, node="load", intent="i")
    assert event["decision"] == "deny" and result.status == "denied" and log == []


async def test_a_tool_runs_on_the_server_whose_binding_authorized_it():
    log: list = []
    tools = {
        DOCS_SERVER: [file_reader(DOCS_SERVER, log)],
        "rogue-mcp": [file_reader("rogue-mcp", log)],
    }
    bindings = {DOCS_SERVER: ("get_file_contents",)}  # rogue-mcp unbound
    belt = ToolBelt(tools, RecordingGate(), bindings=bindings)
    result, event = await belt.call("get_file_contents", IN_REPO, node="load", intent="i")
    assert log == [(DOCS_SERVER, "a.yaml")]
    assert event["server"] == DOCS_SERVER and result.text == f"{DOCS_SERVER}: a.yaml"


async def test_a_name_bound_on_two_servers_is_ambiguous_and_refused():
    log: list = []
    tools = {
        DOCS_SERVER: [file_reader(DOCS_SERVER, log)],
        "other-mcp": [file_reader("other-mcp", log)],
    }
    bindings = {DOCS_SERVER: ("get_file_contents",), "other-mcp": ("get_file_contents",)}
    belt = ToolBelt(tools, RecordingGate(), bindings=bindings)
    assert belt.ambiguous == {"get_file_contents"}
    _, event = await belt.call("get_file_contents", IN_REPO, node="load", intent="i")
    assert event["decision"] == "deny" and log == []


async def test_a_refused_call_never_reaches_the_tool():
    log: list = []
    belt = ToolBelt(fake_tools_by_server(log), RefuseGate(), bindings=FAKE_BINDINGS)
    result, event = await belt.call("search_code", {"query": "vault"}, node="locate", intent="i")
    assert log == []
    assert event["decision"] == "refuse" and result.status == "denied"
    assert result.text.startswith("error: refused")


@pytest.mark.parametrize(
    "name, node",
    [
        ("search_code", "load"),  # load reads, it does not search
        ("get_file_contents", "locate"),
        ("get_commit", "load"),
        ("get_file_contents", "judge"),  # a model node calls no tool
    ],
)
async def test_a_tool_out_of_the_nodes_scope_is_denied_before_the_gate(name, node):
    gate = RecordingGate()
    log: list = []
    belt = ToolBelt(fake_tools_by_server(log), gate, bindings=FAKE_BINDINGS)
    result, event = await belt.call(name, {"query": "q", "path": "a.yaml"}, node=node, intent="i")
    assert event["decision"] == "deny" and result.status == "denied"
    assert gate.seen == [] and log == []  # authorization runs first


def test_to_text_handles_mcp_content_blocks():
    assert to_text([{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]) == "a\nb"
    assert to_text(("content", {"artifact": 1})) == "content"


async def test_only_a_successful_read_is_evidence():
    async def broken(owner: str, repo: str, path: str) -> str:
        raise RuntimeError("upstream 502")

    tool = StructuredTool.from_function(coroutine=broken, name="get_file_contents", description="d")
    result, event = await one_tool_belt(tool).call(
        "get_file_contents", IN_REPO, node="load", intent="i"
    )
    assert result.text.startswith("error: RuntimeError")
    assert event["ok"] is False and event["evidence"] == []


def test_evidence_is_what_was_read_not_what_was_searched():
    assert evidence_for("get_file_contents", {"path": "/base-apps/vault/values.yaml"}) == [
        "base-apps/vault/values.yaml"
    ]
    assert evidence_for("search_code", {"query": "vault"}) == []
    assert evidence_for("list_commits", {"path": "base-apps/vault/values.yaml"}) == []


CALL = stable_call_id("load", "get_file_contents", {"path": "a.yaml"})
OTHER = stable_call_id("load", "get_file_contents", {"path": "b.yaml"})


def response(*approvals: dict) -> dict:
    return {"type": "tool_approval_response", "approvals": list(approvals)}


@pytest.mark.parametrize(
    "reply, expected",
    [
        (response({"id": CALL, "approved": True}), True),
        # a decision for another call never approves this one, even when it is the only one
        (response({"id": OTHER, "approved": True}), False),
        # only the boolean True approves
        (response({"id": CALL, "approved": "false"}), False),
        (response({"id": CALL, "approved": "true"}), False),
        (response({"id": CALL, "approved": 1}), False),
        (response({"id": CALL}), False),
        (response({"id": CALL, "approved": False}), False),
        # unknown or duplicate ids fail the whole response, like kagent-core does
        (response({"id": CALL, "approved": True}, {"id": OTHER, "approved": True}), False),
        (response({"id": CALL, "approved": True}, {"id": CALL, "approved": True}), False),
        # not a tool approval response at all
        ({"approvals": [{"id": CALL, "approved": True}]}, False),
        ({"type": "ask_user_response", "approvals": [{"id": CALL, "approved": True}]}, False),
        (True, False),
        ("approved", False),
    ],
)
def test_approval_needs_this_calls_id_and_a_boolean_true(reply, expected):
    assert _approved(reply, CALL) is expected


# --- the repository boundary ----------------------------------------------


def docs_belt(log: list) -> ToolBelt:
    return ToolBelt(fake_tools_by_server(log), RecordingGate(), bindings=FAKE_BINDINGS)


async def read(belt: ToolBelt, args: dict):
    return await belt.call("get_file_contents", args, node="load", intent="i")


@pytest.mark.parametrize(
    "args",
    [
        {"owner": "someone-else", "repo": "kubernetes", "path": "a.yaml"},
        {"owner": "arigsela", "repo": "private-repo", "path": "a.yaml"},
        {"owner": "arigsela", "repo": "kubernetes", "path": "../../etc/passwd"},
        {"owner": "arigsela", "repo": "kubernetes", "path": "base-apps/../../x"},
        {"owner": "arigsela", "repo": "kubernetes", "path": "https://evil.example/x"},
    ],
)
async def test_reads_outside_the_repository_are_denied_before_the_tool(args):
    log: list = []
    result, event = await read(docs_belt(log), args)
    assert log == [] and event["decision"] == "deny" and event["ok"] is False
    assert result.status == "denied"


async def test_missing_owner_and_repo_are_filled_with_the_configured_repository():
    log: list = []
    _, event = await read(docs_belt(log), {"path": "base-apps/vault/values.yaml"})
    assert log == [("get_file_contents", "base-apps/vault/values.yaml")]
    assert event["args"]["owner"] == "arigsela" and event["args"]["repo"] == "kubernetes"


@pytest.mark.parametrize(
    "name, args",
    [
        ("list_commits", {"owner": "someone-else", "repo": "kubernetes"}),
        ("list_commits", {"owner": "arigsela", "repo": "other-repo", "path": "a.yaml"}),
        ("list_commits", {"path": "../../etc/passwd"}),
        ("get_commit", {"owner": "someone-else", "repo": "kubernetes", "sha": "main"}),
        ("get_commit", {"repo": "other-repo", "sha": "main"}),
    ],
)
async def test_list_commits_for_another_repo_is_denied(name, args):
    log: list = []
    result, event = await docs_belt(log).call(name, args, node="scope", intent="i")
    assert log == [] and result.status == "denied" and event["decision"] == "deny"


async def test_commit_tools_are_filled_with_the_configured_repository():
    log: list = []
    belt = docs_belt(log)
    _, listed = await belt.call("list_commits", {"path": "a.yaml"}, node="scope", intent="i")
    _, got = await belt.call("get_commit", {"sha": "main"}, node="intake", intent="i")
    assert log == [("list_commits", "a.yaml"), ("get_commit", "main")]
    for event in (listed, got):
        assert (event["args"]["owner"], event["args"]["repo"]) == ("arigsela", "kubernetes")


@pytest.mark.parametrize(
    "query",
    ["vault repo:evil/stuff", "vault org:anthropic", "vault user:someone", "x owner:a"],
)
async def test_a_search_naming_another_scope_is_denied(query):
    log: list = []
    _, event = await docs_belt(log).call("search_code", {"query": query}, node="locate", intent="i")
    assert log == [] and event["decision"] == "deny"


async def test_an_unscoped_search_is_confined_to_the_repository():
    log: list = []
    belt = one_search_belt(log)
    await belt.call("search_code", {"query": "vault"}, node="locate", intent="i")
    await belt.call(
        "search_code", {"query": "vault repo:arigsela/kubernetes"}, node="locate", intent="i"
    )
    assert log == [
        ("search_code", "vault repo:arigsela/kubernetes"),
        ("search_code", "vault repo:arigsela/kubernetes"),
    ]


def one_search_belt(log: list) -> ToolBelt:
    """The fake tools, with search pacing that does not really wait."""
    clock = FakeClock()
    return ToolBelt(
        fake_tools_by_server(log),
        RecordingGate(),
        bindings=FAKE_BINDINGS,
        clock=clock,
        sleep=clock.sleep,
    )


# --- secrets ----------------------------------------------------------------


async def test_tool_results_are_redacted_before_any_model_sees_them():
    async def leaky(owner: str, repo: str, path: str) -> str:
        return (
            "env:\n  - name: AWS_ACCESS_KEY_ID\n    value: AKIAABCDEFGHIJKLMNOP\n"
            "password: hunter2hunter2\nchart: vault\n"
        )

    tool = StructuredTool.from_function(coroutine=leaky, name="get_file_contents", description="d")
    result, event = await read(one_tool_belt(tool), IN_REPO)
    assert "AKIAABCDEFGHIJKLMNOP" not in result.text and "hunter2hunter2" not in result.text
    assert "chart: vault" in result.text and event["ok"] is True
    assert result.text.count("\n") == 5  # line numbers stay true


# --- MCP errors that do not raise ------------------------------------------


async def test_an_mcp_error_returned_as_content_is_not_a_successful_read():
    # langchain-mcp-adapters' default: an isError result comes back as content,
    # with ToolMessage.status "error", instead of raising.
    async def not_found(owner: str, repo: str, path: str) -> str:
        raise ToolException("something failed")

    tool = StructuredTool.from_function(
        coroutine=not_found,
        name="get_file_contents",
        description="Read a file",
        handle_tool_error=True,
    )
    result, event = await read(one_tool_belt(tool), IN_REPO)
    assert result.text.startswith("error: the tool failed") and result.status == "error"
    assert event["ok"] is False and event["evidence"] == []


@pytest.mark.parametrize(
    "query",
    [
        "vault repo:arigsela/kubernetes (repo:evil/x)",
        "vault repo:arigsela/kubernetes OR foo",
        "vault NOT chart",
        "vault -repo:arigsela/kubernetes",
        'vault "repo:evil/y"',
        "vault (org:anthropic)",
    ],
)
async def test_search_expressions_that_could_leave_the_repository_are_denied(query):
    log: list = []
    _, event = await docs_belt(log).call("search_code", {"query": query}, node="locate", intent="i")
    assert log == [] and event["decision"] == "deny"


async def test_a_search_always_carries_exactly_one_scope():
    log: list = []
    await docs_belt(log).call(
        "search_code", {"query": "repo:ARIGSELA/kubernetes chart"}, node="locate", intent="i"
    )
    assert log == [("search_code", "chart repo:arigsela/kubernetes")]
