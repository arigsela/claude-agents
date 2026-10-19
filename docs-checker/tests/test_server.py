"""The BYO contract, end to end over real sockets: gRPC A2A, /readyz, gRPC health.

The client side is what the kagent gateway does: an ``lf.a2a.v1.A2AService``
stub over plaintext gRPC (the Atenet router carries it to the actor's port).
"""

import asyncio
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
    NOT_WIRED,
    build_agent_card,
    build_executor,
    build_request_handler,
    placeholder_graph,
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


async def test_the_placeholder_graph_refuses_every_request_without_a_model_call():
    # main() serves it until the docs-checker graph is wired in.
    settings = fake_settings()
    models = FakeModels()  # no models: any model call would fail the task
    executor = build_executor(
        settings, graph=placeholder_graph(), models=models, tools=_tools, gate=RecordingGate()
    )
    handler, _ = build_request_handler(settings, executor, build_agent_card(settings))
    server = await start(handler, a2a_address="127.0.0.1:0", ready_port=0, ready_host="127.0.0.1")
    try:
        async with grpc.aio.insecure_channel(f"127.0.0.1:{server.a2a_port}") as channel:
            response = await a2a_pb2_grpc.A2AServiceStub(channel).SendMessage(
                a2a_pb2.SendMessageRequest(message=user_message("check all docs"))
            )
    finally:
        await server.stop(grace=0)

    task = response.task
    assert task.status.state == a2a_pb2.TaskState.TASK_STATE_COMPLETED
    assert task.status.message.parts[0].text == NOT_WIRED
    data = [MessageToDict(p) for p in task.artifacts[0].parts if p.HasField("data")]
    ledger = next(d["data"][LEDGER_KEY] for d in data if LEDGER_KEY in d["data"])
    assert ledger["outcome"] == "refused" and ledger["calls"] == 0
