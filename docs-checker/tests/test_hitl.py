"""The drift seam's "ask": a paused tool call becomes kagent HITL input-required, and resumes.

This is the path the drift check will use. LangGraph re-runs the interrupted
node from its start on resume; the task's replay memo makes that re-run reuse
the model replies and tool results it already has, so nothing is paid twice.
"""

import uuid

import grpc
import pytest
from a2a.types import a2a_pb2, a2a_pb2_grpc
from google.protobuf import struct_pb2
from google.protobuf.json_format import MessageToDict, ParseDict
from langgraph.types import Command

from docs_checker.executor import LEDGER_KEY
from docs_checker.gate import GateResult
from docs_checker.graph import RunDeps, run_config
from docs_checker.ledger import CostLedger
from docs_checker.levers import Levers
from docs_checker.server import build_agent_card, build_executor, build_request_handler, start
from docs_checker.tools import ToolBelt
from tests.fake_graph import TEST_ANSWER, build_test_graph
from tests.fakes import (
    FAKE_BINDINGS,
    FakeModels,
    KeyedModel,
    ScriptedModel,
    fake_settings,
    fake_tools_by_server,
    reply,
    tool_call,
)

HITL = "https://kagent.dev/extensions/hitl/v1"
QUESTION = "Which chart version does vault run?"
READ_VAULT = tool_call(
    "get_file_contents",
    {"owner": "arigsela", "repo": "kubernetes", "path": "base-apps/vault/values.yaml"},
)


class AskGate:
    async def check(self, call):
        return GateResult(decision="ask", angle_deg=56.0, reason="56.0 deg vs ask 45 / refuse 70")


@pytest.fixture
async def setup():
    tool_log: list = []
    worker = ScriptedModel([reply(tool_calls=[READ_VAULT]), reply("done")])

    async def tools():
        return fake_tools_by_server(tool_log)

    settings = fake_settings()
    executor = build_executor(
        settings,
        graph=build_test_graph(),
        models=FakeModels(worker=worker),
        tools=tools,
        gate=AskGate(),
    )
    handler, _ = build_request_handler(settings, executor, build_agent_card(settings))
    server = await start(handler, a2a_address="127.0.0.1:0", ready_port=0, ready_host="127.0.0.1")
    yield server, tool_log, worker
    await server.stop(grace=0)


ACTIVATED = (("a2a-extensions", HITL),)


async def ask(stub, text: str = QUESTION) -> a2a_pb2.Task:
    first = await stub.SendMessage(
        a2a_pb2.SendMessageRequest(
            message=a2a_pb2.Message(
                message_id=str(uuid.uuid4()),
                role=a2a_pb2.Role.ROLE_USER,
                parts=[a2a_pb2.Part(text=text)],
            )
        ),
        metadata=ACTIVATED,
    )
    return first.task


async def decide(stub, paused: a2a_pb2.Task, approvals: list[dict]) -> a2a_pb2.Task:
    decision = a2a_pb2.Message(
        message_id=str(uuid.uuid4()),
        role=a2a_pb2.Role.ROLE_USER,
        task_id=paused.id,
        context_id=paused.context_id,
        parts=[a2a_pb2.Part(text="decision")],
        extensions=[HITL],
    )
    decision.metadata.CopyFrom(
        ParseDict(
            {HITL: {"type": "tool_approval_response", "approvals": approvals}},
            struct_pb2.Struct(),
        )
    )
    second = await stub.SendMessage(
        a2a_pb2.SendMessageRequest(message=decision), metadata=ACTIVATED
    )
    return second.task


def ledger_of(task: a2a_pb2.Task) -> dict:
    for artifact in task.artifacts:
        for part in artifact.parts:
            if part.HasField("data"):
                data = MessageToDict(part.data)
                if isinstance(data, dict) and LEDGER_KEY in data:
                    return data[LEDGER_KEY]
    raise AssertionError("no ledger part in the task's artifacts")


async def test_ask_pauses_with_a_hitl_request_and_approval_resumes(setup):
    server, tool_log, worker = setup
    async with grpc.aio.insecure_channel(f"127.0.0.1:{server.a2a_port}") as channel:
        stub = a2a_pb2_grpc.A2AServiceStub(channel)
        paused = await ask(stub)
        assert paused.status.state == a2a_pb2.TaskState.TASK_STATE_INPUT_REQUIRED
        assert HITL in paused.status.message.extensions
        request = MessageToDict(paused.status.message.metadata)[HITL]
        assert request["type"] == "tool_approval_request"
        assert request["tools"][0]["name"] == "get_file_contents"
        assert tool_log == []  # nothing ran before the human decided

        done = await decide(stub, paused, [{"id": request["tools"][0]["id"], "approved": True}])

    assert done.status.state == a2a_pb2.TaskState.TASK_STATE_COMPLETED
    assert done.status.message.parts[0].text == TEST_ANSWER
    assert tool_log == [("get_file_contents", "base-apps/vault/values.yaml")]
    # The resume replayed the worker's first reply instead of calling again.
    assert len(worker.calls) == 2
    # The completed task's ledger covers the whole run, the call before the pause
    # included: 1 before + 1 after.
    ledger = ledger_of(done)
    assert ledger["calls"] == 2
    assert set(ledger["by_node"]) == {"worker"}
    assert ledger["outcome"] == "verified"


async def test_an_approval_for_another_id_does_not_run_the_call(setup):
    server, tool_log, _ = setup
    async with grpc.aio.insecure_channel(f"127.0.0.1:{server.a2a_port}") as channel:
        stub = a2a_pb2_grpc.A2AServiceStub(channel)
        paused = await ask(stub)
        assert paused.status.state == a2a_pb2.TaskState.TASK_STATE_INPUT_REQUIRED
        done = await decide(stub, paused, [{"id": "some-other-call", "approved": True}])

    assert done.status.state == a2a_pb2.TaskState.TASK_STATE_COMPLETED
    assert tool_log == []  # a single decision for another id is not an approval
    assert ledger_of(done)["outcome"] == "unverified"


SEARCH_VAULT = tool_call("search_code", {"query": "vault chart"}, call_id="toolu_s")
TWO_BRANCHES = "load: Which chart version does vault run?\nlocate: Where is the vault chart set?"


@pytest.fixture
async def parallel():
    """Two parallel branches; each one's first tool call asks."""
    tool_log: list = []
    # Each branch: the call that pauses, then its last reply (the resume replays
    # the first reply from the task's memo).
    worker = KeyedModel(
        {
            "load": [reply(tool_calls=[READ_VAULT]), reply("done")],
            "locate": [reply(tool_calls=[SEARCH_VAULT]), reply("done")],
        }
    )

    async def tools():
        return fake_tools_by_server(tool_log)

    settings = fake_settings()
    executor = build_executor(
        settings,
        graph=build_test_graph(),
        models=FakeModels(worker=worker),
        tools=tools,
        gate=AskGate(),
    )
    handler, _ = build_request_handler(settings, executor, build_agent_card(settings))
    server = await start(handler, a2a_address="127.0.0.1:0", ready_port=0, ready_host="127.0.0.1")
    yield server, tool_log
    await server.stop(grace=0)


async def test_parallel_asks_become_one_request_listing_every_call(parallel):
    server, tool_log = parallel
    async with grpc.aio.insecure_channel(f"127.0.0.1:{server.a2a_port}") as channel:
        stub = a2a_pb2_grpc.A2AServiceStub(channel)
        paused = await ask(stub, TWO_BRANCHES)
        assert paused.status.state == a2a_pb2.TaskState.TASK_STATE_INPUT_REQUIRED
        request = MessageToDict(paused.status.message.metadata)[HITL]
        names = sorted(t["name"] for t in request["tools"])
        assert names == ["get_file_contents", "search_code"]

        approvals = [{"id": t["id"], "approved": True} for t in request["tools"]]
        done = await decide(stub, paused, approvals)

    assert done.status.state == a2a_pb2.TaskState.TASK_STATE_COMPLETED
    assert sorted(tool_log) == [
        ("get_file_contents", "base-apps/vault/values.yaml"),
        ("search_code", "vault chart repo:arigsela/kubernetes"),
    ]
    assert ledger_of(done)["outcome"] == "verified"


async def test_approving_one_of_two_parallel_calls_runs_only_that_one(parallel):
    server, tool_log = parallel
    async with grpc.aio.insecure_channel(f"127.0.0.1:{server.a2a_port}") as channel:
        stub = a2a_pb2_grpc.A2AServiceStub(channel)
        paused = await ask(stub, TWO_BRANCHES)
        request = MessageToDict(paused.status.message.metadata)[HITL]
        read = next(t for t in request["tools"] if t["name"] == "get_file_contents")
        search = next(t for t in request["tools"] if t["name"] == "search_code")
        done = await decide(
            stub,
            paused,
            [{"id": read["id"], "approved": True}, {"id": search["id"], "approved": False}],
        )

    assert done.status.state == a2a_pb2.TaskState.TASK_STATE_COMPLETED
    assert tool_log == [("get_file_contents", "base-apps/vault/values.yaml")]


def deps_for(model, gate, tool_log: list, *, replay: dict | None) -> RunDeps:
    belt = ToolBelt(fake_tools_by_server(tool_log), gate, bindings=FAKE_BINDINGS)
    ledger = CostLedger("run-1", "ctx-1", emit=False)
    return RunDeps(models=FakeModels(worker=model), belt=belt, ledger=ledger, replay=replay)


def approve(request: dict) -> dict:
    return {
        "type": "tool_approval_response",
        "approvals": [{"id": request["id"], "approved": True}],
    }


async def test_an_approval_never_carries_over_to_a_different_call_after_resume():
    # Before the pause the model asked to read values.yaml; on resume LangGraph
    # re-runs the worker and (with no replay memo) the model now asks for a
    # different file. The human approved the first call only, so the second
    # must not run.
    tool_log: list = []
    read_secrets = tool_call(
        "get_file_contents",
        {"owner": "arigsela", "repo": "kubernetes", "path": "base-apps/vault/secrets.yaml"},
    )
    worker = ScriptedModel(
        [reply(tool_calls=[READ_VAULT]), reply(tool_calls=[read_secrets]), reply("done")]
    )
    deps = deps_for(worker, AskGate(), tool_log, replay=None)
    graph = build_test_graph()
    config = run_config("task-hitl", fake_settings(), Levers.all_on())

    paused = await graph.ainvoke({"text": QUESTION}, config, context=deps)
    request = paused["__interrupt__"][0].value["action_requests"][0]
    assert request["args"]["path"] == "base-apps/vault/values.yaml"

    result = await graph.ainvoke(Command(resume=approve(request)), config, context=deps)

    assert tool_log == []  # neither file was read
    assert [e["decision"] for e in result["events"]] == ["ask-rejected"]
    assert result["events"][0]["args"]["path"] == "base-apps/vault/secrets.yaml"
    assert result["outcome"] == "unverified"


class AskForReadsGate:
    """Allows listing commits, asks before reading a file."""

    async def check(self, call):
        if call.tool == "get_file_contents":
            return GateResult(decision="ask", angle_deg=56.0, reason="56 deg")
        return GateResult(decision="allow", angle_deg=10.0, reason="10 deg")


async def test_a_resume_replays_earlier_work_instead_of_repeating_it():
    # List commits (allowed, runs), then read (asks, pauses). On resume the node
    # re-runs from its start: the first two model replies and the listing come from
    # the task's memo, so only the approved read and the final reply are new.
    tool_log: list = []
    history = tool_call("list_commits", {"path": "base-apps/vault/values.yaml"}, call_id="toolu_l")
    worker = ScriptedModel(
        [reply(tool_calls=[history]), reply(tool_calls=[READ_VAULT]), reply("done")]
    )
    deps = deps_for(worker, AskForReadsGate(), tool_log, replay={})
    graph = build_test_graph()
    config = run_config("task-replay", fake_settings(), Levers.all_on())

    paused = await graph.ainvoke({"text": QUESTION}, config, context=deps)
    request = paused["__interrupt__"][0].value["action_requests"][0]
    assert tool_log == [("list_commits", "base-apps/vault/values.yaml")]

    result = await graph.ainvoke(Command(resume=approve(request)), config, context=deps)

    assert tool_log == [
        ("list_commits", "base-apps/vault/values.yaml"),
        ("get_file_contents", "base-apps/vault/values.yaml"),
    ]  # the listing ran once
    assert len(worker.calls) == 3  # not 3 + 2 replayed
    assert [e.node for e in deps.ledger.entries].count("worker") == 3
    assert result["outcome"] == "verified"
