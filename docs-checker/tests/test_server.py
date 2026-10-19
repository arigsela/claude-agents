"""The BYO contract, end to end over real sockets: gRPC A2A, /readyz, gRPC health.

The client side is what the kagent gateway does: an ``lf.a2a.v1.A2AService``
stub over plaintext gRPC (the Atenet router carries it to the actor's port).
"""

import asyncio
import logging
import uuid

import grpc
import pytest
from a2a.types import a2a_pb2, a2a_pb2_grpc
from google.protobuf.json_format import MessageToDict
from grpc_health.v1 import health_pb2, health_pb2_grpc

from docs_checker.config import load_settings
from docs_checker.gate import RecordingGate
from docs_checker.server import (
    A2A_SERVICE,
    build_agent_card,
    build_executor,
    build_request_handler,
    start,
)
from tests.fake_graph import TEST_ANSWER, build_test_graph
from tests.fakes import (
    FakeModels,
    ScriptedModel,
    fake_settings,
    fake_tools_by_server,
    reply,
    tool_call,
)

LEDGER_KEY = "docs-checker/cost-run"


def scripted_models():
    read_vault = tool_call(
        "get_file_contents",
        {"owner": "arigsela", "repo": "kubernetes", "path": "base-apps/vault/values.yaml"},
    )
    return FakeModels(
        worker=ScriptedModel(
            [
                reply(tool_calls=[read_vault], uncached=300, write_5m=600, output=60),
                reply("done", uncached=120, read=2000, output=80),
            ]
        ),
    )


async def _tools():
    return fake_tools_by_server()


def user_message(text: str, **ids) -> a2a_pb2.Message:
    return a2a_pb2.Message(
        message_id=str(uuid.uuid4()),
        role=a2a_pb2.Role.ROLE_USER,
        parts=[a2a_pb2.Part(text=text)],
        **ids,
    )


@pytest.fixture
async def running():
    settings = fake_settings()
    executor = build_executor(
        settings,
        graph=build_test_graph(),
        models=scripted_models(),
        tools=_tools,
        gate=RecordingGate(),
    )
    handler, controller = build_request_handler(settings, executor, build_agent_card(settings))
    assert controller is None  # no runtime.control_plane_url: in-memory store
    server = await start(handler, a2a_address="127.0.0.1:0", ready_port=0, ready_host="127.0.0.1")
    yield server
    await server.stop(grace=0)


async def test_send_message_over_grpc_returns_a_completed_task(running):
    async with grpc.aio.insecure_channel(f"127.0.0.1:{running.a2a_port}") as channel:
        stub = a2a_pb2_grpc.A2AServiceStub(channel)
        response = await stub.SendMessage(
            a2a_pb2.SendMessageRequest(message=user_message("Which chart version does vault run?"))
        )

    task = response.task
    assert task.status.state == a2a_pb2.TaskState.TASK_STATE_COMPLETED
    assert task.status.message.parts[0].text == TEST_ANSWER
    artifact = task.artifacts[0]
    texts = [p.text for p in artifact.parts if p.HasField("text")]
    data = [MessageToDict(p) for p in artifact.parts if p.HasField("data")]
    assert texts == [TEST_ANSWER]

    calls = [
        d["data"]
        for d in data
        if d.get("metadata", {}).get("kagent.dev/a2a/part-type") == "function_call"
    ]
    assert calls == [
        {
            "name": "get_file_contents",
            "args": {
                "owner": "arigsela",
                "repo": "kubernetes",
                "path": "base-apps/vault/values.yaml",
            },
        }
    ]

    ledger = next(d["data"][LEDGER_KEY] for d in data if LEDGER_KEY in d["data"])
    assert ledger["outcome"] == "verified"
    assert ledger["calls"] == 2 and ledger["unknown_calls"] == 0
    assert ledger["cache_read"] == 2000 and ledger["cache_write"] == 600
    assert ledger["cost_usd_known"] > 0

    usage = MessageToDict(artifact.metadata)["kagent.dev/a2a/usage"]
    assert usage["totalTokenCount"] == usage["promptTokenCount"] + usage["candidatesTokenCount"]


async def test_streaming_send_ends_with_the_completed_status(running):
    async with grpc.aio.insecure_channel(f"127.0.0.1:{running.a2a_port}") as channel:
        stub = a2a_pb2_grpc.A2AServiceStub(channel)
        events = [
            e
            async for e in stub.SendStreamingMessage(
                a2a_pb2.SendMessageRequest(
                    message=user_message("Which chart version does vault run?")
                )
            )
        ]

    kinds = [e.WhichOneof("payload") for e in events]
    assert kinds[0] == "task"
    assert "artifact_update" in kinds
    assert events[-1].status_update.status.state == a2a_pb2.TaskState.TASK_STATE_COMPLETED


async def test_readyz_answers_200_on_its_own_port_and_404_elsewhere(running):
    async def get(path: str) -> bytes:
        reader, writer = await asyncio.open_connection("127.0.0.1", running.ready_port)
        writer.write(f"GET {path} HTTP/1.1\r\nHost: x\r\n\r\n".encode())
        await writer.drain()
        data = await reader.read()
        writer.close()
        return data

    assert (await get("/readyz")).startswith(b"HTTP/1.1 200 OK")
    assert (await get("/healthz")).startswith(b"HTTP/1.1 404")


async def test_grpc_health_reports_the_a2a_service_serving(running):
    assert A2A_SERVICE == "lf.a2a.v1.A2AService"
    async with grpc.aio.insecure_channel(f"127.0.0.1:{running.a2a_port}") as channel:
        stub = health_pb2_grpc.HealthStub(channel)
        result = await stub.Check(health_pb2.HealthCheckRequest(service=A2A_SERVICE))
    assert result.status == health_pb2.HealthCheckResponse.SERVING


def test_agent_card_advertises_grpc_on_the_runtime_port():
    card = build_agent_card(load_settings({}))
    interface = card.supported_interfaces[0]
    assert (interface.url, interface.protocol_binding) == ("http://127.0.0.1:80", "GRPC")
    assert "https://kagent.dev/extensions/hitl/v1" in [e.uri for e in card.capabilities.extensions]


async def test_a_failed_run_logs_a_redacted_traceback(caplog):
    import logging

    leaky = RuntimeError("upstream 400 echo: Authorization: Bearer sk-ant-api03-SECRETSECRETSECRET")
    models = FakeModels(worker=ScriptedModel([leaky]))
    settings = fake_settings()
    executor = build_executor(
        settings, graph=build_test_graph(), models=models, tools=_tools, gate=RecordingGate()
    )
    handler, _ = build_request_handler(settings, executor, build_agent_card(settings))
    server = await start(handler, a2a_address="127.0.0.1:0", ready_port=0, ready_host="127.0.0.1")
    try:
        with caplog.at_level(logging.INFO):
            async with grpc.aio.insecure_channel(f"127.0.0.1:{server.a2a_port}") as channel:
                stub = a2a_pb2_grpc.A2AServiceStub(channel)
                response = await stub.SendMessage(
                    a2a_pb2.SendMessageRequest(message=user_message("Which chart does vault run?"))
                )
    finally:
        await server.stop(grace=0)

    assert response.task.status.state == a2a_pb2.TaskState.TASK_STATE_FAILED
    assert "run failed" in caplog.text and "RuntimeError" in caplog.text
    assert "SECRETSECRET" not in caplog.text


def test_agent_card_describes_the_docs_check():
    (skill,) = build_agent_card(load_settings({})).skills
    assert skill.id == "docs-check" and "read-only" in skill.tags
    text = skill.description
    assert "Read-only" in text and "stale" in text
    for form in ('"check all"', '"check <path>[, <path>...]"', "data part", '"scope"'):
        assert form in text
    assert "check all" in skill.examples and any("," in e for e in skill.examples)


async def test_the_production_tool_gate_keeps_nothing():
    # RecordingGate keeps every call it sees (for calibration); the gate production
    # builds must not grow for the life of the process.
    from docs_checker.gate import ToolCallContext

    executor = build_executor(fake_settings(), graph=build_test_graph(), models=FakeModels())
    gate = executor._gate
    assert not isinstance(gate, RecordingGate)
    call = ToolCallContext(
        intent="i", action="read a", tool="get_file_contents", args={}, workflow="load"
    )
    for _ in range(100):
        assert (await gate.check(call)).decision == "allow"
    assert vars(gate) == {}


class _Served(Exception):
    """Ends ``main()`` once the served executor has been checked."""


def test_main_serves_the_docs_checker_graph(tmp_path, monkeypatch):
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    from docs_checker import server
    from docs_checker.executor import DocsCheckerExecutor
    from docs_checker.gate import FixGate
    from docs_checker.paused import PausedTasks
    from tests.test_executor import a2a_message, send

    data_dir = tmp_path / "data" / "docs-checker"
    monkeypatch.setenv("DOCS_CHECKER_DATA_DIR", str(data_dir))
    monkeypatch.delenv("KAGENT_CONFIG_JSON", raising=False)
    seen: dict = {}

    async def fake_start(handler, **kwargs):
        executor = handler.agent_executor
        assert isinstance(executor, DocsCheckerExecutor)
        graph = executor._graph
        seen["nodes"] = set(graph.get_graph().nodes) - {"__start__", "__end__"}
        seen["saver"] = graph.checkpointer
        seen["fix_gate"] = executor._fix_gate
        seen["paused"] = executor._paused
        # A real request through the served graph: no MCP server is bound locally,
        # so the ref cannot be resolved and the run fails, without a model call.
        queue = await send(executor, a2a_message("", {"scope": "all"}))
        seen["reason"] = queue.last_status().message.parts[0].text
        raise _Served

    monkeypatch.setattr(server, "start", fake_start)
    root = logging.getLogger()
    monkeypatch.setattr(root, "handlers", root.handlers[:])  # main reconfigures the root logger
    with pytest.raises(SystemExit) as exited:  # main logs the error and exits 1
        server.main()
    assert exited.value.code == 1

    assert seen["nodes"] == {"intake", "scope", "dispatch", "doc", "collect", "report"}
    assert isinstance(seen["saver"], AsyncSqliteSaver)
    assert (data_dir / "checkpoints.sqlite").is_file()  # under the data dir (C#5)
    assert type(seen["fix_gate"]) is FixGate  # build_fix_gate: the rules gate
    assert isinstance(seen["paused"], PausedTasks) and seen["paused"].durable
    assert seen["reason"].startswith("docs-checker failed: ")
    assert "main" in seen["reason"]


# --- DOCS_CHECKER_REPLAY_DIR: the replay-only seam the image smoke test uses ------------


def _files(directory) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sorted(directory.iterdir())}


def test_production_models_go_to_the_api_unless_replay_is_set(caplog):
    from docs_checker.server import build_models

    with caplog.at_level("WARNING", logger="docs_checker.server"):
        models = build_models(load_settings({}))
    assert models._transport is None  # the SDK's own transport: the API
    assert "replay" not in caplog.text


async def test_the_replay_dir_serves_recordings_and_never_records(tmp_path, caplog):
    import anthropic
    import httpx2
    from langchain_core.messages import HumanMessage

    from docs_checker.evals.replay import ReplayTransport
    from docs_checker.models import AnthropicModels
    from docs_checker.server import build_models
    from tests.test_llm import message_body

    settings = load_settings({"DOCS_CHECKER_REPLAY_DIR": str(tmp_path)})
    # One recording, made the way the eval harness makes them (a mock stands in for the API).
    api = httpx2.MockTransport(lambda request: httpx2.Response(200, json=message_body("ok")))
    recorder = ReplayTransport(api, tmp_path, "record-missing")
    judge = AnthropicModels(
        settings.node_models, settings.levers, http_timeout_s=60.0, transport=recorder
    ).get("judge")
    await judge.ainvoke([HumanMessage("q")])
    recorded = _files(tmp_path)
    assert len(recorded) == 1

    with caplog.at_level("WARNING", logger="docs_checker.server"):
        models = build_models(settings)
    assert f"model replay is active: every response comes from {tmp_path}" in caplog.text

    answer = await models.get("judge").ainvoke([HumanMessage("q")])
    assert answer.content == "ok"
    # A request with no recording fails its call: nothing is sent and nothing is written.
    with pytest.raises(anthropic.APIConnectionError):
        await models.get("judge").ainvoke([HumanMessage("never recorded")])
    transport = models._transport
    assert transport.mode == "replay"
    assert (transport.sent, transport.live, len(transport.misses)) == (0, 0, 1)
    assert _files(tmp_path) == recorded


async def test_the_replay_seam_sends_nothing(tmp_path):
    # Belt and braces: the transport under the seam's replay refuses every request, so
    # even a record-missing transport built over it could not send anything.
    import httpx2

    from docs_checker.evals.replay import Offline, replay_only

    transport = replay_only(tmp_path)
    assert transport.mode == "replay" and isinstance(transport.inner, Offline)
    with pytest.raises(RuntimeError, match="replay-only"):
        await transport.inner.handle_async_request(
            httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
        )


@pytest.mark.parametrize("runtime", ["agentcore", "local"])
async def test_gateway_tools_are_sigv4_signed_on_agentcore(monkeypatch, runtime):
    import dataclasses

    import langchain_mcp_adapters.client as mcp_client

    from docs_checker.aws_auth import SigV4Auth
    from docs_checker.config import McpServer
    from docs_checker.server import load_mcp_tools

    seen: dict = {}

    class Capture:
        def __init__(self, connections, **_):
            seen.update(connections)

        async def get_tools(self, server_name):
            return []

    monkeypatch.setattr(mcp_client, "MultiServerMCPClient", Capture)

    async def gateway(name, connection):
        seen[name] = connection
        return []

    monkeypatch.setattr("docs_checker.gateway_tools.load_gateway_tools", gateway)
    settings = dataclasses.replace(
        load_settings({}),
        runtime=runtime,
        aws_region="us-west-2",
        mcp_servers=(McpServer(name="github", url="https://gw.example/mcp"),),
    )
    await load_mcp_tools(settings)
    auth = seen["github"].get("auth")
    assert isinstance(auth, SigV4Auth) if runtime == "agentcore" else auth is None
