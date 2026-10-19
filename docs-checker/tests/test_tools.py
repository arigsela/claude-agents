import json

import pytest
from langchain_core.tools import StructuredTool, ToolException

from docs_checker.gate import GateResult, RecordingGate
from docs_checker.tools import (
    READ_ONLY_TOOLS,
    ToolBelt,
    _approved,
    cap,
    evidence_for,
    project_catalog_entity,
    stable_call_id,
    to_text,
)
from tests.fakes import FAKE_BINDINGS, fake_tools_by_server


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


def test_belt_exposes_only_allowlisted_tools_bound_in_the_template():
    bindings = {"agent-docs-mcp": ("search_code", "delete_file")}
    belt = ToolBelt(fake_tools_by_server(), RecordingGate(), bindings=bindings)
    assert [t.name for t in belt.tools_for("docs")] == ["search_code"]
    assert belt.tools_for("catalog") == []  # its server is not bound at all
    assert "delete_file" not in READ_ONLY_TOOLS


async def test_a_binding_on_one_server_never_authorizes_another_servers_tool():
    # agent-docs binds get_file_contents but does not offer it; a second server
    # offers a tool of that name without binding it. Nothing may be called.
    log: list = []
    tools = {"agent-docs-mcp": [], "rogue-mcp": [file_reader("rogue-mcp", log)]}
    bindings = {"agent-docs-mcp": ("get_file_contents",), "rogue-mcp": ()}
    belt = ToolBelt(tools, RecordingGate(), bindings=bindings)
    _, event = await belt.call(
        "get_file_contents",
        IN_REPO,
        specialist="docs",
        intent="i",
        workflow="docs",
    )
    assert event["decision"] == "deny" and log == []


async def test_a_tool_runs_on_the_server_whose_binding_authorized_it():
    log: list = []
    tools = {
        "agent-docs-mcp": [file_reader("agent-docs-mcp", log)],
        "rogue-mcp": [file_reader("rogue-mcp", log)],
    }
    bindings = {"agent-docs-mcp": ("get_file_contents",)}  # rogue-mcp unbound
    belt = ToolBelt(tools, RecordingGate(), bindings=bindings)
    text, event = await belt.call(
        "get_file_contents",
        IN_REPO,
        specialist="docs",
        intent="i",
        workflow="docs",
    )
    assert log == [("agent-docs-mcp", "a.yaml")]
    assert event["server"] == "agent-docs-mcp" and text == "agent-docs-mcp: a.yaml"


async def test_a_name_bound_on_two_servers_is_ambiguous_and_refused():
    log: list = []
    tools = {
        "agent-docs-mcp": [file_reader("agent-docs-mcp", log)],
        "other-mcp": [file_reader("other-mcp", log)],
    }
    bindings = {"agent-docs-mcp": ("get_file_contents",), "other-mcp": ("get_file_contents",)}
    belt = ToolBelt(tools, RecordingGate(), bindings=bindings)
    assert belt.ambiguous == {"get_file_contents"}
    _, event = await belt.call(
        "get_file_contents",
        IN_REPO,
        specialist="docs",
        intent="i",
        workflow="docs",
    )
    assert event["decision"] == "deny" and log == []


async def test_a_refused_call_never_reaches_the_tool():
    log = []
    belt = ToolBelt(fake_tools_by_server(log), RefuseGate(), bindings=FAKE_BINDINGS)
    text, event = await belt.call(
        "search_code", {"query": "vault"}, specialist="docs", intent="i", workflow="docs"
    )
    assert log == []
    assert event["decision"] == "refuse" and text.startswith("error: refused")


async def test_a_tool_out_of_the_specialists_scope_is_denied_before_the_gate():
    gate = RecordingGate()
    belt = ToolBelt(fake_tools_by_server(), gate, bindings=FAKE_BINDINGS)
    _, event = await belt.call(
        "get-catalog-entity",
        {"kind": "c", "namespace": "d", "name": "v"},
        specialist="docs",
        intent="i",
        workflow="docs",
    )
    assert event["decision"] == "deny"
    assert gate.seen == []  # authorization runs first


def test_catalog_entities_are_projected_to_a_few_fields():
    entity = {
        "kind": "Component",
        "metadata": {"name": "vault", "annotations": {"x": "y" * 1000}},
        "spec": {"owner": "group:default/platform", "dependsOn": ["resource:default/pg"]},
        "relations": [{"type": "ownedBy"}] * 100,
    }
    projected = json.loads(project_catalog_entity(json.dumps(entity)))
    assert projected == {
        "kind": "Component",
        "name": "vault",
        "owner": "group:default/platform",
        "dependsOn": ["resource:default/pg"],
    }
    assert project_catalog_entity("not json") == "not json"


def test_cap_keeps_head_and_tail():
    text = "a" * 3000 + "b" * 3000
    capped = cap(text, 1000)
    assert capped.startswith("a" * 750) and capped.endswith("b" * 250)
    assert "5000 chars omitted" in capped


def test_to_text_handles_mcp_content_blocks():
    assert to_text([{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]) == "a\nb"
    assert to_text(("content", {"artifact": 1})) == "content"


async def test_only_a_successful_read_is_evidence():
    async def broken(owner: str, repo: str, path: str) -> str:
        raise RuntimeError("upstream 502")

    tools = {
        "agent-docs-mcp": [
            StructuredTool.from_function(
                coroutine=broken, name="get_file_contents", description="Read a file"
            )
        ]
    }
    belt = ToolBelt(tools, RecordingGate(), bindings={"agent-docs-mcp": ("get_file_contents",)})
    text, event = await belt.call(
        "get_file_contents",
        IN_REPO,
        specialist="docs",
        intent="i",
        workflow="docs",
    )
    assert text.startswith("error: RuntimeError")
    assert event["ok"] is False and event["evidence"] == []


def test_evidence_is_what_was_read_not_what_was_searched():
    assert evidence_for("get_file_contents", {"path": "/base-apps/vault/values.yaml"}) == [
        "base-apps/vault/values.yaml"
    ]
    assert evidence_for(
        "get-catalog-entity", {"kind": "Component", "namespace": "default", "name": "Vault"}
    ) == ["component:default/vault"]
    assert evidence_for("search_code", {"query": "vault"}) == []


CALL = stable_call_id("docs", "get_file_contents", {"path": "a.yaml"})
OTHER = stable_call_id("docs", "get_file_contents", {"path": "b.yaml"})


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
    return await belt.call(
        "get_file_contents", args, specialist="docs", intent="i", workflow="docs"
    )


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
    _, event = await read(docs_belt(log), args)
    assert log == [] and event["decision"] == "deny" and event["ok"] is False


async def test_missing_owner_and_repo_are_filled_with_the_configured_repository():
    log: list = []
    _, event = await read(docs_belt(log), {"path": "base-apps/vault/values.yaml"})
    assert log == [("get_file_contents", "base-apps/vault/values.yaml")]
    assert event["args"]["owner"] == "arigsela" and event["args"]["repo"] == "kubernetes"


@pytest.mark.parametrize(
    "query",
    ["vault repo:evil/stuff", "vault org:anthropic", "vault user:someone", "x owner:a"],
)
async def test_a_search_naming_another_scope_is_denied(query):
    log: list = []
    _, event = await docs_belt(log).call(
        "search_code", {"query": query}, specialist="docs", intent="i", workflow="docs"
    )
    assert log == [] and event["decision"] == "deny"


async def test_an_unscoped_search_is_confined_to_the_repository():
    log: list = []
    belt = docs_belt(log)
    await belt.call("search_code", {"query": "vault"}, specialist="docs", intent="i", workflow="d")
    await belt.call(
        "search_code",
        {"query": "vault repo:arigsela/kubernetes"},
        specialist="docs",
        intent="i",
        workflow="d",
    )
    assert log == [
        ("search_code", "vault repo:arigsela/kubernetes"),
        ("search_code", "vault repo:arigsela/kubernetes"),
    ]


# --- secrets ----------------------------------------------------------------


async def test_tool_results_are_redacted_before_any_model_sees_them():
    async def leaky(owner: str, repo: str, path: str) -> str:
        return (
            "env:\n  - name: AWS_ACCESS_KEY_ID\n    value: AKIAABCDEFGHIJKLMNOP\n"
            "password: hunter2hunter2\nchart: vault\n"
        )

    tools = {
        "agent-docs-mcp": [
            StructuredTool.from_function(
                coroutine=leaky, name="get_file_contents", description="Read a file"
            )
        ]
    }
    belt = ToolBelt(tools, RecordingGate(), bindings={"agent-docs-mcp": ("get_file_contents",)})
    text, event = await read(belt, IN_REPO)
    assert "AKIAABCDEFGHIJKLMNOP" not in text and "hunter2hunter2" not in text
    assert "chart: vault" in text and event["ok"] is True


# --- MCP errors that do not raise ------------------------------------------


async def test_an_mcp_error_returned_as_content_is_not_a_successful_read():
    # langchain-mcp-adapters' default: an isError result comes back as content,
    # with ToolMessage.status "error", instead of raising.
    async def not_found(owner: str, repo: str, path: str) -> str:
        raise ToolException("404 Not Found")

    tool = StructuredTool.from_function(
        coroutine=not_found,
        name="get_file_contents",
        description="Read a file",
        handle_tool_error=True,
    )
    belt = ToolBelt(
        {"agent-docs-mcp": [tool]},
        RecordingGate(),
        bindings={"agent-docs-mcp": ("get_file_contents",)},
    )
    text, event = await read(belt, IN_REPO)
    assert text.startswith("error: the tool failed")
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
    _, event = await docs_belt(log).call(
        "search_code", {"query": query}, specialist="docs", intent="i", workflow="docs"
    )
    assert log == [] and event["decision"] == "deny"


async def test_a_search_always_carries_exactly_one_scope():
    log: list = []
    await docs_belt(log).call(
        "search_code",
        {"query": "repo:ARIGSELA/kubernetes chart"},
        specialist="docs",
        intent="i",
        workflow="docs",
    )
    assert log == [("search_code", "chart repo:arigsela/kubernetes")]
