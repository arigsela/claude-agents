"""The third part of the BYO contract: tasks persist through the controller's TaskStore.

A fake ``kagent.runtime.v1.TaskStoreService`` (the v1.0.0-alpha14 proto, from
kagent-proto at 673d181e; ``tests/fake_controller.py``) stands in for the controller.
The runtime finds it through the ADKConfig's ``runtime.control_plane_url``, reads its
projected actor identity from files, as Substrate provides them under
/run/kagent/identity, and must create the task, version every update, and settle
the final boundary so the gateway can publish it and the lifecycle worker can
suspend the actor.
"""

import uuid

import grpc
import pytest
from a2a.types import a2a_pb2, a2a_pb2_grpc

from docs_checker.gate import RecordingGate
from docs_checker.server import (
    build_agent_card,
    build_executor,
    build_request_handler,
    start,
)
from tests.fake_controller import TASK_STORE_SERVICE, start_controller
from tests.fake_graph import build_test_graph
from tests.fakes import FakeModels, ScriptedModel, fake_settings, fake_tools_by_server, reply


@pytest.fixture
async def controller():
    server, store, port = await start_controller("127.0.0.1:0")
    yield store, f"http://127.0.0.1:{port}"
    await server.stop(grace=0)


@pytest.fixture
def identity(tmp_path):
    session = str(uuid.uuid4())
    (tmp_path / "name").write_text(f"session-{session}\n")
    (tmp_path / "atespace").write_text("kagent\n")
    (tmp_path / "uid").write_text("actor-uid-1\n")
    return tmp_path / "name", session


async def _tools():
    return fake_tools_by_server()


def models():
    return FakeModels(worker=ScriptedModel([reply("done")]))


async def test_a_task_is_created_versioned_and_settled_through_the_controller(controller, identity):
    store, api_url = controller
    identity_path, session = identity
    settings = fake_settings(runtime={"control_plane_url": api_url, "name": "docs-checker"})
    executor = build_executor(
        settings, graph=build_test_graph(), models=models(), tools=_tools, gate=RecordingGate()
    )
    handler, client = build_request_handler(
        settings, executor, build_agent_card(settings), identity_path=identity_path
    )
    assert client is not None  # in-cluster mode: the kagent TaskStore, not memory
    server = await start(
        handler, a2a_address="127.0.0.1:0", ready_port=0, ready_host="127.0.0.1", controller=client
    )
    try:
        async with grpc.aio.insecure_channel(f"127.0.0.1:{server.a2a_port}") as channel:
            response = await a2a_pb2_grpc.A2AServiceStub(channel).SendMessage(
                a2a_pb2.SendMessageRequest(
                    message=a2a_pb2.Message(
                        message_id=str(uuid.uuid4()),
                        role=a2a_pb2.Role.ROLE_USER,
                        parts=[a2a_pb2.Part(text="Who owns vault?")],
                    )
                )
            )
    finally:
        await server.stop(grace=0)

    task = response.task
    assert task.status.state == a2a_pb2.TaskState.TASK_STATE_COMPLETED

    # Persisted at the controller: created first, then versioned updates, ending completed.
    assert store.log[0][0] == "create"
    assert [entry[2] for entry in store.log] == list(range(1, len(store.log) + 1))
    assert store.log[-1][1] == "TASK_STATE_COMPLETED"
    stored, version = store.tasks[task.id]
    assert stored.status.state == a2a_pb2.TaskState.TASK_STATE_COMPLETED

    # The boundary was settled at the final version.
    assert store.settled == [(task.id, version)]

    # On the wire, the alpha14 service (the controller routes by full method name;
    # alpha11's kagent.api.v1alpha1 is gone).
    assert store.wire.methods >= {
        f"/{TASK_STORE_SERVICE}/{method}" for method in ("CreateTask", "UpdateTask", "SettleTask")
    }
    assert all(method.startswith(f"/{TASK_STORE_SERVICE}/") for method in store.wire.methods)

    # Every call was scoped to the actor's session and carried its identity.
    assert store.sessions == {session}
    assert store.identities == {"kagent/session-" + session + "/actor-uid-1"}
