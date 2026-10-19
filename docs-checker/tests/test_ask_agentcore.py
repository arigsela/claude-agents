import importlib.util
import json
from pathlib import Path

import httpx

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "ask_agentcore.py"
spec = importlib.util.spec_from_file_location("ask_agentcore", SCRIPT)
ask = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ask)

ARN = "arn:aws:bedrock-agentcore:us-west-2:414696729697:runtime/docs_checker_bedrock-V3II5y2qYe"
HITL = "https://kagent.dev/extensions/hitl/v1"


def test_new_session_id_length():
    one, two = ask.new_session_id(), ask.new_session_id()
    assert one.startswith("docs-checker-") and len(one) >= 33 and one != two


def test_url_encodes_arn():
    url = ask.invocation_url(ARN, "us-west-2")
    assert url == (
        "https://bedrock-agentcore.us-west-2.amazonaws.com/runtimes/"
        "arn%3Aaws%3Abedrock-agentcore%3Aus-west-2%3A414696729697%3Aruntime%2F"
        "docs_checker_bedrock-V3II5y2qYe/invocations?qualifier=DEFAULT"
    )


def test_approval_message_shape():
    payload = ask.approval_payload("task-1", "ctx-1", approve=["a1"], reject=["r1"])
    assert payload["method"] == "SendMessage"
    message = payload["params"]["message"]
    assert (message["taskId"], message["contextId"]) == ("task-1", "ctx-1")
    assert HITL in message["extensions"]
    reply = message["metadata"][HITL]
    assert reply == {
        "type": "tool_approval_response",
        "approvals": [{"id": "a1", "approved": True}, {"id": "r1", "approved": False}],
    }


def test_approval_reaches_the_executor_as_a_resume():
    """The same shape executor.resume_map reads, through kagent's own parser."""
    from a2a.types import a2a_pb2
    from google.protobuf.json_format import ParseDict
    from kagent.core.a2a import get_hitl_payload

    payload = ask.approval_payload("task-1", "ctx-1", approve=["a1"], reject=[])
    message = ParseDict(payload["params"]["message"], a2a_pb2.Message())
    assert get_hitl_payload(message)["approvals"] == [{"id": "a1", "approved": True}]


async def test_send_signs_and_carries_the_session(monkeypatch):
    for name in ("AWS_PROFILE", "AWS_DEFAULT_PROFILE", "AWS_SESSION_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKID")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "secret")
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        task = {"id": "t", "contextId": "c", "status": {"state": "TASK_STATE_COMPLETED"}}
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": "1", "result": {"task": task}})

    session = ask.new_session_id()
    task = await ask.send(
        ARN,
        "us-west-2",
        session,
        ask.text_payload("check docs/USAGE.md"),
        profile=None,
        transport=httpx.MockTransport(handler),
    )
    (request,) = seen
    assert task["id"] == "t"
    assert request.headers["x-amzn-bedrock-agentcore-runtime-session-id"] == session
    assert request.headers["authorization"].startswith("AWS4-HMAC-SHA256")
    assert request.headers["a2a-version"] == "1.0"
    assert json.loads(request.content)["params"]["message"]["parts"] == [
        {"text": "check docs/USAGE.md"}
    ]


def test_summary_lists_pending_approvals():
    task = {
        "id": "t",
        "contextId": "c",
        "status": {
            "state": "TASK_STATE_INPUT_REQUIRED",
            "message": {
                "parts": [{"text": "Approval is required"}],
                "metadata": {
                    HITL: {
                        "tools": [
                            {
                                "id": "fix-1",
                                "name": "propose_fix",
                                "args": {"doc": "docs/USAGE.md", "replacement": "new"},
                            }
                        ]
                    }
                },
            },
        },
    }
    text = ask.summary(task, "docs-checker-" + "0" * 32)
    assert "INPUT_REQUIRED" in text and "fix-1" in text and "propose_fix" in text
    assert "--task t" in text and "--approve fix-1" in text


def test_summary_reads_the_executors_ledger():
    from docs_checker.executor import LEDGER_KEY

    assert ask.LEDGER_KEY == LEDGER_KEY
    ledger = {"calls": 4, "cost_usd_known": 0.0123, "complete": True, "cache_hit_rate": 0.5}
    task = {
        "id": "t",
        "contextId": "c",
        "status": {"state": "TASK_STATE_COMPLETED"},
        "artifacts": [{"parts": [{"text": "report"}, {"data": {LEDGER_KEY: ledger}}]}],
    }
    text = ask.summary(task, "s" * 33)
    assert "report" in text and "ledger: 4 model calls, $0.0123 known" in text
