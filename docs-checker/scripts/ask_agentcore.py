"""Talk to docs-checker on AgentCore Runtime: one A2A JSON-RPC SendMessage per call.

    python scripts/ask_agentcore.py --runtime <arn> "check docs/USAGE.md"
    python scripts/ask_agentcore.py --runtime <arn> --session <id> --task <id> \\
        --context <id> --approve <call id>[,...] [--reject <call id>[,...]]

Requests are SigV4 signed (service bedrock-agentcore) as ``--profile`` (default
sb-asela). A new session id is ``docs-checker-`` plus 32 hex characters (AgentCore
needs at least 33); reuse it with ``--session`` so an approval reaches the same session
storage. Prints the report, any pending approvals with the command that answers them,
and the ledger summary. Never prints credentials.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from typing import Any
from urllib.parse import quote

import httpx

from docs_checker.aws_auth import SigV4Auth

HITL = "https://kagent.dev/extensions/hitl/v1"
SESSION_HEADER = "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id"
LEDGER_KEY = "docs-checker/cost-run"  # executor.LEDGER_KEY
REQUEST_TIMEOUT_S = 900.0  # AgentCore's own request limit is 15 minutes


def new_session_id() -> str:
    return f"docs-checker-{uuid.uuid4().hex}"


def invocation_url(arn: str, region: str) -> str:
    return (
        f"https://bedrock-agentcore.{region}.amazonaws.com/runtimes/"
        f"{quote(arn, safe='')}/invocations?qualifier=DEFAULT"
    )


def _rpc(message: dict) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": "SendMessage",
        "params": {"message": message},
    }


def text_payload(text: str, *, task_id: str = "", context_id: str = "") -> dict:
    message: dict[str, Any] = {
        "messageId": str(uuid.uuid4()),
        "role": "ROLE_USER",
        "parts": [{"text": text}],
    }
    if task_id:
        message["taskId"] = task_id
    if context_id:
        message["contextId"] = context_id
    return _rpc(message)


def approval_payload(
    task_id: str, context_id: str, *, approve: list[str], reject: list[str]
) -> dict:
    approvals = [{"id": i, "approved": True} for i in approve] + [
        {"id": i, "approved": False} for i in reject
    ]
    payload = text_payload("decision", task_id=task_id, context_id=context_id)
    message = payload["params"]["message"]
    message["extensions"] = [HITL]
    message["metadata"] = {HITL: {"type": "tool_approval_response", "approvals": approvals}}
    return payload


async def send(
    arn: str,
    region: str,
    session: str,
    payload: dict,
    *,
    profile: str | None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict:
    auth = SigV4Auth(service="bedrock-agentcore", region=region, profile=profile)
    headers = {SESSION_HEADER: session, "A2A-Version": "1.0", "Accept": "application/json"}
    async with httpx.AsyncClient(
        auth=auth, timeout=REQUEST_TIMEOUT_S, transport=transport
    ) as client:
        response = await client.post(invocation_url(arn, region), json=payload, headers=headers)
    if response.status_code != 200:
        raise SystemExit(f"HTTP {response.status_code}: {response.text[:2000]}")
    body = response.json()
    if "error" in body:
        raise SystemExit(f"JSON-RPC error: {json.dumps(body['error'])[:2000]}")
    return body["result"]["task"]


def _texts(task: dict) -> list[str]:
    return [p["text"] for a in task.get("artifacts", []) for p in a["parts"] if "text" in p]


def summary(task: dict, session: str) -> str:
    status = task.get("status") or {}
    state = status.get("state", "?").removeprefix("TASK_STATE_")
    lines = [f"state: {state}", f"session: {session}", f"task: {task.get('id')}"]
    lines.append(f"context: {task.get('contextId')}")
    lines += ["", *_texts(task)]
    message = status.get("message") or {}
    if state != "COMPLETED":
        lines += [p["text"] for p in message.get("parts", []) if "text" in p]
    tools = ((message.get("metadata") or {}).get(HITL) or {}).get("tools") or []
    if tools:
        lines += ["", "pending approvals:"]
        for tool in tools:
            lines.append(f"- {tool['id']}: {tool['name']} {json.dumps(tool.get('args'))}")
        ids = ",".join(t["id"] for t in tools)
        lines += [
            "",
            "answer with:",
            (
                f"  --session {session} --task {task.get('id')} "
                f"--context {task.get('contextId')} --approve {ids}   (or --reject {ids})"
            ),
        ]
    for artifact in task.get("artifacts", []):
        for part in artifact["parts"]:
            data = part.get("data")
            if isinstance(data, dict) and LEDGER_KEY in data:
                ledger = data[LEDGER_KEY]
                lines += [
                    "",
                    (
                        f"ledger: {ledger.get('calls')} model calls, "
                        f"${float(ledger.get('cost_usd_known', 0)):.4f} known "
                        f"(complete: {ledger.get('complete')}, "
                        f"cache hit {ledger.get('cache_hit_rate')})"
                    ),
                ]
    return "\n".join(lines)


def _ids(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ask_agentcore.py")
    parser.add_argument("--runtime", required=True, help="the agent runtime ARN")
    parser.add_argument("--region", default="us-west-2")
    parser.add_argument("--profile", default="sb-asela")
    parser.add_argument("--session", default="", help="reuse an AgentCore session id")
    parser.add_argument("--task", default="")
    parser.add_argument("--context", default="")
    parser.add_argument("--approve", default="", help="call ids to approve, comma separated")
    parser.add_argument("--reject", default="", help="call ids to reject, comma separated")
    parser.add_argument("text", nargs="?", default="")
    args = parser.parse_args(argv)

    session = args.session or new_session_id()
    if len(session) < 33:
        parser.error("--session must be at least 33 characters")
    if args.approve or args.reject:
        if not (args.session and args.task and args.context):
            parser.error("--approve/--reject need --session, --task and --context")
        payload = approval_payload(
            args.task, args.context, approve=_ids(args.approve), reject=_ids(args.reject)
        )
    elif args.text:
        payload = text_payload(args.text, task_id=args.task, context_id=args.context)
    else:
        parser.error("give a request text, or --approve/--reject")
    task = asyncio.run(send(args.runtime, args.region, session, payload, profile=args.profile))
    print(summary(task, session))
    return 0


if __name__ == "__main__":
    sys.exit(main())
