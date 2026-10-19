"""The AgentCore Runtime contract: A2A JSON-RPC on /, the Agent Card, /ping, and a pause
that outlives the process (session storage keeps the task store and the checkpoints)."""

import dataclasses
import uuid

import httpx
from a2a.types import a2a_pb2
from google.protobuf import struct_pb2
from google.protobuf.json_format import MessageToDict, ParseDict

from docs_checker.agentcore import HITL_EXTENSION_URI, open_app
from docs_checker.evals.localrepo import local_repo_tools
from docs_checker.executor import REPORT_KEY
from docs_checker.gate import RecordingGate
from docs_checker.server import build_agent_card, build_executor
from tests.fake_graph import TEST_ANSWER, build_test_graph
from tests.fakes import FakeModels, fake_settings
from tests.test_graph import (
    CLAIMS,
    FILES,
    NAMES,
    VAULT_DOC,
    VAULT_FIXED,
    VERDICTS,
    asking_gate,
    extract_model,
    fix_model,
    judge_model,
)
from tests.test_restart import models_after_restart
from tests.test_scope import make_tree
from tests.test_server import _tools, scripted_models


def agentcore_settings(tmp_path):
    data_dir = tmp_path / "workspace" / "docs-checker"
    return dataclasses.replace(
        fake_settings(),
        runtime="agentcore",
        sqlite_nolock=True,
        a2a_port=9000,
        data_dir=str(data_dir),
        checkpoint_db=str(data_dir / "checkpoints.sqlite"),
    )


def client_for(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://agent")


def message(text: str = "", data=None, **ids) -> a2a_pb2.Message:
    parts = [a2a_pb2.Part(text=text)] if text else []
    if data is not None:
        parts.append(a2a_pb2.Part(data=ParseDict(data, struct_pb2.Value())))
    return a2a_pb2.Message(
        message_id=str(uuid.uuid4()), role=a2a_pb2.Role.ROLE_USER, parts=parts, **ids
    )


async def send(client: httpx.AsyncClient, msg: a2a_pb2.Message) -> dict:
    params = MessageToDict(a2a_pb2.SendMessageRequest(message=msg))
    response = await client.post(
        "/", json={"jsonrpc": "2.0", "id": "1", "method": "SendMessage", "params": params}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert "error" not in body, body
    return body["result"]["task"]


def data_values(task: dict) -> list:
    return [p["data"] for a in task.get("artifacts", []) for p in a["parts"] if "data" in p]


async def test_agent_card_served(tmp_path):
    async with (
        open_app(agentcore_settings(tmp_path), tools=_tools) as app,
        client_for(app) as client,
    ):
        response = await client.get("/.well-known/agent-card.json")
    assert response.status_code == 200
    (interface,) = response.json()["supportedInterfaces"]
    assert interface["protocolBinding"] == "JSONRPC"
    assert interface["url"] == "http://127.0.0.1:9000/"


async def test_ping(tmp_path):
    async with (
        open_app(agentcore_settings(tmp_path), tools=_tools) as app,
        client_for(app) as client,
    ):
        response = await client.get("/ping")
    assert response.status_code == 200 and response.json() == {"status": "Healthy"}


async def test_message_send_completes(tmp_path):
    settings = agentcore_settings(tmp_path)
    executor = build_executor(
        settings,
        graph=build_test_graph(),
        models=scripted_models(),
        tools=_tools,
        gate=RecordingGate(),
    )
    async with open_app(settings, executor=executor) as app, client_for(app) as client:
        task = await send(client, message("Which chart version does vault run?"))
    assert task["status"]["state"] == "TASK_STATE_COMPLETED"
    assert task["status"]["message"]["parts"][0]["text"] == TEST_ANSWER
    # Tasks are on session storage, not in memory.
    assert (tmp_path / "workspace" / "docs-checker" / "tasks.sqlite").is_file()


async def test_pause_survives_restart(tmp_path):
    repo, commit = make_tree(tmp_path, FILES)
    settings = agentcore_settings(tmp_path)

    async def tools():
        return local_repo_tools(repo, commit)

    before = FakeModels(
        names=NAMES,
        extract=extract_model(CLAIMS),
        judge=judge_model(VERDICTS),
        fix=fix_model({"Vault runs chart vault version 0.30.1.": VAULT_FIXED}),
    )
    request = message("", {"scope": [VAULT_DOC], "mode": "interactive"})
    async with (
        open_app(settings, models=before, tools=tools, fix_gate=asking_gate()) as app,
        client_for(app) as client,
    ):
        paused = await send(client, request)
    assert paused["status"]["state"] == "TASK_STATE_INPUT_REQUIRED"
    status_message = paused["status"]["message"]
    assert HITL_EXTENSION_URI in status_message["extensions"]
    (ask,) = status_message["metadata"][HITL_EXTENSION_URI]["tools"]

    # A new microVM on the same session storage: new process, stores and models.
    approval = message("decision", task_id=paused["id"], context_id=paused["contextId"])
    approval.extensions.append(HITL_EXTENSION_URI)
    approval.metadata.CopyFrom(
        ParseDict(
            {
                HITL_EXTENSION_URI: {
                    "type": "tool_approval_response",
                    "approvals": [{"id": ask["id"], "approved": True}],
                }
            },
            struct_pb2.Struct(),
        )
    )
    async with (
        open_app(
            settings, models=models_after_restart(), tools=tools, fix_gate=asking_gate()
        ) as app,
        client_for(app) as client,
    ):
        done = await send(client, approval)

    assert done["status"]["state"] == "TASK_STATE_COMPLETED"
    (report,) = [d[REPORT_KEY] for d in data_values(done) if REPORT_KEY in d]
    (finding,) = report["findings"]
    assert finding["replacement"] == VAULT_FIXED
    text = "".join(p.get("text", "") for a in done["artifacts"] for p in a["parts"])
    assert "lower bound" not in text  # the ledger survived: no restart note


def test_kagent_card_unchanged():
    settings = fake_settings()
    assert build_agent_card(settings) == build_agent_card(
        settings, url=f"http://127.0.0.1:{settings.a2a_port}", binding="GRPC"
    )
    (interface,) = build_agent_card(settings).supported_interfaces
    assert (interface.url, interface.protocol_binding) == ("http://127.0.0.1:80", "GRPC")


def test_hitl_uri_is_kagents():
    from kagent.core.a2a import HITL_EXTENSION_URI as KAGENT_URI

    assert HITL_EXTENSION_URI == KAGENT_URI
