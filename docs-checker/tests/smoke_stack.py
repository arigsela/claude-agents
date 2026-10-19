"""The image smoke test's stack: one real A2A task, end to end, with no key and no cluster.

What docs-checker meets in a cluster, faked just enough for ``check base-apps/kagent/docs.md``:

- the controller: ``tests.fake_controller`` (the alpha14 TaskStore), which the runtime
  reaches at ``runtime.control_plane_url`` with its projected identity;
- the agent-docs MCP server: the four read tools over streamable HTTP, answered by
  ``evals.localrepo`` from ``tests/fixtures/smoke-repo``, committed at a fixed date and
  author so the commit, and with it every model request, is the same everywhere;
- the model: the runtime replays ``tests/fixtures/cassettes-smoke`` through
  ``DOCS_CHECKER_REPLAY_DIR`` (replay only: nothing is sent). ``record`` writes those
  cassettes from the hand-written answers below (``SyntheticAPI``), never from the API.

Three uses:

- ``python -m tests.smoke_stack sidecar``: the controller and the agent-docs fake in a
  container next to the image, then the client: wait for /readyz, send the task over A2A
  gRPC, check what the controller holds (``scripts/smoke.sh`` runs it there).
- ``tests/test_smoke_stack.py``: the same task with the runtime in process on the same
  seam, so a change that alters a model request fails in the unit tests first.
- ``python -m tests.smoke_stack record``: rewrite the cassettes after such a change.

The sidecar has the runtime's packages only (the image's build stage), so nothing here
imports pytest or the other test helpers.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from collections import Counter
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import grpc
import httpx2
import uvicorn
from a2a.types import a2a_pb2, a2a_pb2_grpc
from google.protobuf.json_format import MessageToDict
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.routing import Route

from docs_checker import prompts
from docs_checker.evals.localrepo import TOOLS, LocalRepoSession
from docs_checker.executor import LEDGER_KEY, REPORT_KEY
from docs_checker.tools import READ_ONLY_TOOLS
from tests.fake_controller import TASK_STORE_SERVICE, FakeTaskStore, start_controller

HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "fixtures" / "smoke-repo"
CASSETTES = HERE / "fixtures" / "cassettes-smoke"

DOC = "base-apps/kagent/docs.md"
REQUEST = f"check {DOC}"
STALE_LINE = 11
FIXED_LINE = "The Argo CD Application pins the kagent chart at `targetRevision: 0.7.1`."
# The fixture as ``commit_fixture`` commits it. The model requests' data fences derive
# their tokens from it, so the cassettes hold only for this commit.
FIXTURE_COMMIT = "e4227523951abda0804e1ef10b3a5d28bbdfdcde"
_WHEN = "1792324800 +0000"  # 2026-10-18T12:00:00Z
_GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "docs-checker smoke",
    "GIT_AUTHOR_EMAIL": "smoke@docs-checker.invalid",
    "GIT_AUTHOR_DATE": _WHEN,
    "GIT_COMMITTER_NAME": "docs-checker smoke",
    "GIT_COMMITTER_EMAIL": "smoke@docs-checker.invalid",
    "GIT_COMMITTER_DATE": _WHEN,
}

ATESPACE = "kagent"
ACTOR_UID = "smoke-actor-uid"
# In the docker smoke: the network aliases scripts/smoke.sh gives the containers.
CONTROLLER_PORT = 8083
MCP_PORT = 8090
A2A_PORT = 80
READY_PORT = 8081


class SmokeFailure(Exception):
    """A check failed; the message says which and what was found."""


# --- the repository ------------------------------------------------------------------


def commit_fixture(dest: Path) -> str:
    """``tests/fixtures/smoke-repo`` as a one-commit repository at ``dest`` (which must not
    exist); returns its sha, which must be ``FIXTURE_COMMIT``. No user or system git
    config is read, and file modes and line endings are not taken from the checkout."""
    shutil.copytree(FIXTURE, dest)
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(_GIT_IDENTITY, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
    config = ("-c", "core.fileMode=false", "-c", "core.autocrlf=false")

    def git(*args: str) -> str:
        done = subprocess.run(
            ["git", "-C", str(dest), *config, *args],
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )
        return done.stdout

    git("init", "-q", "-b", "main")
    git("add", "-A")
    git("commit", "-q", "--no-gpg-sign", "-m", "smoke fixture")
    sha = git("rev-parse", "HEAD").strip()
    if sha != FIXTURE_COMMIT:
        raise SmokeFailure(
            f"the fixture committed as {sha}, not {FIXTURE_COMMIT}: tests/fixtures/smoke-repo "
            "changed (update FIXTURE_COMMIT and re-record: python -m tests.smoke_stack record)"
        )
    return sha


class CountingSession:
    """A ``LocalRepoSession`` that counts the tool calls it answers."""

    def __init__(self, session: LocalRepoSession):
        self.session = session
        self.calls: Counter[str] = Counter()

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None, **kw: Any):
        self.calls[name] += 1
        return await self.session.call_tool(name, arguments, **kw)


class _MCPEndpoint:
    """The streamable HTTP endpoint as a plain ASGI app (a Route treats a function as a
    request handler, so this is a class)."""

    def __init__(self, manager: StreamableHTTPSessionManager):
        self.manager = manager

    async def __call__(self, scope, receive, send) -> None:
        await self.manager.handle_request(scope, receive, send)


def mcp_app(session: CountingSession) -> Starlette:
    """The agent-docs server's four read tools at ``/mcp``, stateless, JSON responses."""
    server: Server = Server("agent-docs-mcp")

    @server.list_tools()
    async def list_tools():
        return list(TOOLS)

    @server.call_tool(validate_input=False)
    async def call_tool(name: str, arguments: dict[str, Any]):
        return await session.call_tool(name, arguments)

    manager = StreamableHTTPSessionManager(app=server, json_response=True, stateless=True)

    @asynccontextmanager
    async def lifespan(_app):
        async with manager.run():
            yield

    return Starlette(routes=[Route("/mcp", endpoint=_MCPEndpoint(manager))], lifespan=lifespan)


async def serve_http(app: Starlette, host: str, port: int) -> tuple[uvicorn.Server, Any, int]:
    """``app`` served by uvicorn on ``host:port`` (0 picks a port); the server, its task
    and the bound port."""
    server = uvicorn.Server(
        uvicorn.Config(app, host=host, port=port, log_level="warning", access_log=False)
    )
    task = asyncio.ensure_future(server.serve())
    while not server.started:
        if task.done():
            task.result()  # raises what stopped it
            raise SmokeFailure(f"the agent-docs fake did not start on {host}:{port}")
        await asyncio.sleep(0.02)
    bound = server.servers[0].sockets[0].getsockname()[1]
    return server, task, bound


async def stop_http(server: uvicorn.Server, task: Any) -> None:
    server.should_exit = True
    await task


# --- the runtime's configuration -----------------------------------------------------


def adk_config(controller_url: str, mcp_url: str) -> dict:
    """The ADKConfig the alpha14 BYO compiler would hand the runtime: the controller,
    and the agent-docs server bound with the four read tools."""
    return {
        "runtime": {
            "control_plane_url": controller_url,
            "gateway_url": controller_url,
            "name": "docs-checker",
            "namespace": ATESPACE,
            "log_level": "info",
            "port": A2A_PORT,
        },
        "agent": {
            "model": {"model": "claude-haiku-5-5", "anthropic": {"prompt_caching": True}},
            "description": "docs-checker smoke",
            "http_tools": [{"params": {"url": mcp_url}, "tools": sorted(READ_ONLY_TOOLS)}],
        },
    }


def write_identity(directory: Path, session: str) -> str:
    """The files Substrate projects under /run/kagent/identity; the identity header the
    runtime must send with them."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "name").write_text(f"session-{session}\n")
    (directory / "atespace").write_text(f"{ATESPACE}\n")
    (directory / "uid").write_text(f"{ACTOR_UID}\n")
    return f"{ATESPACE}/session-{session}/{ACTOR_UID}"


# --- the model, for ``record`` only ----------------------------------------------------

_EXTRACT_ANSWER = {
    "claims": [
        {
            "line_start": 9,
            "line_end": 9,
            "text": "kagent runs in the `kagent` namespace.",
            "kind": "namespace",
            "keys": ["namespace"],
            "values": ["kagent"],
            "source_hint": "base-apps/kagent.yaml",
        },
        {
            "line_start": STALE_LINE,
            "line_end": STALE_LINE,
            "text": "The Argo CD Application pins the kagent chart at `targetRevision: 0.6.0`.",
            "kind": "chart",
            "keys": ["targetRevision"],
            "values": ["0.6.0"],
            "source_hint": "base-apps/kagent.yaml",
        },
    ]
}


def _judge_answer(user: str) -> dict:
    if "0.6.0" in user:
        return {
            "verdict": "stale",
            "confidence": 0.95,
            "reason": "Window 0 (base-apps/kagent.yaml) sets targetRevision: 0.7.1.",
            "window_index": 0,
        }
    return {
        "verdict": "supported",
        "confidence": 0.95,
        "reason": "Window 0 shows the claimed value.",
        "window_index": 0,
    }


_ANSWERS = {
    prompts.EXTRACT: ("extract", lambda user: _EXTRACT_ANSWER),
    prompts.JUDGE: ("judge", _judge_answer),
    prompts.FIX: ("fix", lambda user: {"replacement": FIXED_LINE}),
}


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    return "".join(block.get("text", "") for block in content if isinstance(block, dict))


class SyntheticAPI(httpx2.AsyncBaseTransport):
    """The hand-written model for ``record``: a Messages API answer per request, picked
    by the node's system prompt. It never reaches the network."""

    def __init__(self) -> None:
        self.calls: Counter[str] = Counter()

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        body = json.loads(await request.aread())
        system = _text(body.get("system") or "")
        if system not in _ANSWERS:
            raise SmokeFailure(f"no synthetic answer for this system prompt: {system[:80]!r}")
        node, answer = _ANSWERS[system]
        self.calls[node] += 1
        tag = f"smoke_{node}_{self.calls[node]}"
        message = {
            "id": f"msg_{tag}",
            "type": "message",
            "role": "assistant",
            "model": body["model"],
            "content": [
                {"type": "text", "text": json.dumps(answer(_text(body["messages"][-1]["content"])))}
            ],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {
                "input_tokens": len(json.dumps(body)) // 4,
                "output_tokens": 60,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
            },
        }
        headers = {"request-id": f"req_{tag}", "content-type": "application/json"}
        return httpx2.Response(200, headers=headers, json=message, request=request)


# --- the client and the checks --------------------------------------------------------


async def wait_ready(host: str, port: int, timeout_s: float) -> None:
    """Until ``GET /readyz`` on ``host:port`` answers 200, for at most ``timeout_s``: each
    attempt (connect, request, status line) is bounded too, so a listener that accepts
    and never answers cannot hold the smoke."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    last = "no answer"
    while True:
        try:
            async with asyncio.timeout(max(0.1, min(5.0, deadline - loop.time()))):
                reader, writer = await asyncio.open_connection(host, port)
                try:
                    writer.write(f"GET /readyz HTTP/1.1\r\nHost: {host}\r\n\r\n".encode())
                    await writer.drain()
                    status = (await reader.readline()).decode(errors="replace").strip()
                finally:
                    writer.close()
            if status.split(" ")[1:2] == ["200"]:
                return
            last = status or "an empty answer"
        except TimeoutError:
            last = "no answer within 5 s"
        except OSError as error:
            last = f"{type(error).__name__}: {error}"
        if loop.time() >= deadline:
            raise SmokeFailure(
                f"/readyz on {host}:{port} did not answer 200 in {timeout_s:g} s ({last})"
            )
        await asyncio.sleep(0.5)


async def send_check(target: str, timeout_s: float) -> a2a_pb2.Task:
    """One ``SendMessage`` with the request as text, as the kagent gateway sends it."""
    message = a2a_pb2.Message(
        message_id=str(uuid.uuid4()),
        role=a2a_pb2.Role.ROLE_USER,
        parts=[a2a_pb2.Part(text=REQUEST)],
    )
    try:
        async with asyncio.timeout(timeout_s + 5):  # the RPC's deadline, and a backstop
            async with grpc.aio.insecure_channel(target) as channel:
                stub = a2a_pb2_grpc.A2AServiceStub(channel)
                response = await stub.SendMessage(
                    a2a_pb2.SendMessageRequest(message=message), timeout=timeout_s
                )
    except TimeoutError as error:
        raise SmokeFailure(f"the task did not end in {timeout_s:g} s") from error
    return response.task


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SmokeFailure(message)


def _data_parts(task: a2a_pb2.Task) -> dict[str, Any]:
    found: dict[str, Any] = {}
    for artifact in task.artifacts:
        for part in artifact.parts:
            if part.HasField("data"):
                value = MessageToDict(part.data)
                if isinstance(value, dict):
                    found.update(value)
    return found


def _texts(task: a2a_pb2.Task) -> list[str]:
    return [part.text for a in task.artifacts for part in a.parts if part.HasField("text")]


def verify(
    store: FakeTaskStore,
    task: a2a_pb2.Task,
    *,
    identity: str,
    session: CountingSession,
    replayed: bool,
) -> list[str]:
    """Check the task the controller holds; one line per check that passed."""
    lines = []
    state = a2a_pb2.TaskState.Name(task.status.state)
    reason = " ".join(p.text for p in task.status.message.parts if p.text)[:500]
    _require(state == "TASK_STATE_COMPLETED", f"the task ended {state}: {reason}")

    _require(task.id in store.tasks, f"the controller holds no task {task.id}")
    stored, version = store.tasks[task.id]
    stored_state = a2a_pb2.TaskState.Name(stored.status.state)
    _require(stored_state == "TASK_STATE_COMPLETED", f"the controller holds it {stored_state}")
    _require(store.log[0][0] == "create", f"the first TaskStore call was {store.log[0]}")
    versions = [entry[2] for entry in store.log]
    _require(versions == list(range(1, len(versions) + 1)), f"versions skipped: {versions}")
    _require(store.settled == [(task.id, version)], f"settled: {store.settled}, version {version}")
    lines.append(
        f"ok: the controller holds task {task.id} COMPLETED at version {version} "
        f"(created, {version - 1} updates, settled at the final version)"
    )

    off_service = sorted(
        m for m in store.wire.methods if not m.startswith(f"/{TASK_STORE_SERVICE}/")
    )
    _require(not off_service, f"calls outside {TASK_STORE_SERVICE}: {off_service}")
    _require(store.identities == {identity}, f"identities sent: {sorted(store.identities)}")
    lines.append(f"ok: every TaskStore call went to {TASK_STORE_SERVICE} as {identity}")

    data = _data_parts(stored)
    texts = _texts(stored)
    _require(
        any(DOC in text for text in texts), "the stored task has no report text naming the doc"
    )
    _require(REPORT_KEY in data, f"no {REPORT_KEY} data part; parts: {sorted(data)}")
    _require(LEDGER_KEY in data, f"no {LEDGER_KEY} data part; parts: {sorted(data)}")
    lines.append(
        f"ok: the stored task carries the report (Markdown text and {REPORT_KEY}) "
        f"and the ledger ({LEDGER_KEY})"
    )

    report = data[REPORT_KEY]
    failed, incomplete = report.get("failed") or [], report.get("incomplete") or []
    _require(
        not failed and not incomplete,
        f"the run did not check the doc: failed {failed}, incomplete {incomplete}",
    )
    stale = [
        f
        for f in report.get("findings") or []
        if f.get("doc") == DOC
        and int(f.get("line_start", 0)) == STALE_LINE
        and f.get("verdict") == "stale"
    ]
    _require(len(stale) == 1, f"no stale finding at {DOC}:{STALE_LINE}: {report.get('findings')}")
    _require(stale[0].get("replacement") == FIXED_LINE, f"the fix: {stale[0].get('replacement')!r}")
    lines.append(f"ok: the report finds {DOC}:{STALE_LINE} stale, fixed to 0.7.1")

    ledger = data[LEDGER_KEY]
    calls = int(ledger.get("calls", 0))
    nodes = set(ledger.get("by_node") or {})
    _require(calls > 0 and {"extract", "judge", "fix"} <= nodes, f"ledger: {ledger}")
    _require(int(ledger.get("unknown_calls", 0)) == 0, f"calls of unknown usage: {ledger}")
    if replayed:
        _require(float(ledger.get("cash_cost_usd", -1)) == 0.0, f"cash spent: {ledger}")
        lines.append(
            f"ok: ledger: {calls} model calls ({', '.join(sorted(nodes))}), all replayed "
            f"(cash $0, workload ${float(ledger['workload_cost_usd']):.6f})"
        )
    else:
        lines.append(f"ok: ledger: {calls} model calls ({', '.join(sorted(nodes))})")

    reads = dict(session.calls)
    _require(reads.get("get_file_contents", 0) > 0, f"agent-docs fake calls: {reads}")
    lines.append(f"ok: the agent read the repo through the agent-docs fake ({reads})")
    return lines


# --- in process: the unit test and ``record`` ----------------------------------------


@dataclass
class Stack:
    store: FakeTaskStore
    session: CountingSession
    identity: str
    a2a: str
    ready: tuple[str, int]


@asynccontextmanager
async def in_process(
    workdir: Path, *, env: Mapping[str, str] | None = None, models: Any = None
) -> AsyncIterator[Stack]:
    """The whole stack in this process: the fixture, the fake controller, the agent-docs
    fake and the runtime as ``main`` builds it, from ``env`` (plus the stack's own
    ``KAGENT_CONFIG_JSON`` and data dir). ``models`` replaces the production models."""
    from docs_checker.config import load_settings
    from docs_checker.server import (
        build_agent_card,
        build_request_handler,
        open_executor,
        start,
    )

    session = CountingSession(LocalRepoSession(workdir / "repo", commit_fixture(workdir / "repo")))
    controller, store, controller_port = await start_controller("127.0.0.1:0")
    http, http_task, mcp_port = await serve_http(mcp_app(session), "127.0.0.1", 0)
    identity = write_identity(workdir / "identity", str(uuid.uuid4()))
    config = adk_config(f"http://127.0.0.1:{controller_port}", f"http://127.0.0.1:{mcp_port}/mcp")
    settings = load_settings(
        {
            **(env or {}),
            "KAGENT_CONFIG_JSON": json.dumps(config),
            "DOCS_CHECKER_DATA_DIR": str(workdir / "data"),
        }
    )
    try:
        overrides = {"models": models} if models is not None else {}
        async with open_executor(settings, **overrides) as executor:
            handler, client = build_request_handler(
                settings,
                executor,
                build_agent_card(settings),
                identity_path=workdir / "identity" / "name",
            )
            running = await start(
                handler,
                a2a_address="127.0.0.1:0",
                ready_port=0,
                ready_host="127.0.0.1",
                controller=client,
            )
            try:
                yield Stack(
                    store=store,
                    session=session,
                    identity=identity,
                    a2a=f"127.0.0.1:{running.a2a_port}",
                    ready=("127.0.0.1", running.ready_port),
                )
            finally:
                await running.stop(grace=0)
    finally:
        await stop_http(http, http_task)
        await controller.stop(grace=0)


async def run_in_process(
    workdir: Path,
    *,
    env: Mapping[str, str] | None = None,
    models: Any = None,
    replayed: bool = True,
    timeout_s: float = 120.0,
) -> list[str]:
    async with in_process(workdir, env=env, models=models) as stack:
        await wait_ready(*stack.ready, timeout_s)
        task = await send_check(stack.a2a, timeout_s)
        return verify(
            stack.store, task, identity=stack.identity, session=stack.session, replayed=replayed
        )


async def record() -> list[str]:
    """Rewrite ``tests/fixtures/cassettes-smoke`` from ``SyntheticAPI``: the runtime runs
    in process with a recording transport over it, so every request is the one the
    runtime makes. Nothing reaches the network, and no key is read."""
    from docs_checker.config import load_settings
    from docs_checker.evals.replay import ReplayTransport
    from docs_checker.llm import request_id_hook
    from docs_checker.models import AnthropicModels

    # The request a cassette is keyed by carries no key and no host: a placeholder key
    # (the one kagent sets) and no base-URL path prefix make it the image's request.
    os.environ["ANTHROPIC_API_KEY"] = "kagent-credential-injected"
    os.environ.pop("ANTHROPIC_BASE_URL", None)
    shutil.rmtree(CASSETTES, ignore_errors=True)
    CASSETTES.mkdir(parents=True)
    settings = load_settings({})
    api = SyntheticAPI()
    models = AnthropicModels(
        settings.node_models,
        settings.levers,
        http_timeout_s=settings.http_timeout_s,
        on_response=request_id_hook,
        transport=ReplayTransport(api, CASSETTES, "record-missing"),
    )
    with tempfile.TemporaryDirectory() as workdir:
        lines = await run_in_process(Path(workdir), models=models, replayed=False)
    lines.append(f"recorded {sum(api.calls.values())} answers ({dict(api.calls)}) in {CASSETTES}")
    return lines


# --- the sidecar ---------------------------------------------------------------------


async def sidecar(agent: str, identity: str, timeout_s: float) -> list[str]:
    """The controller and the agent-docs fake on every interface (the containers' network
    aliases ``controller`` and ``agent-docs-mcp``), then the client against ``agent``."""
    workdir = Path(tempfile.mkdtemp(prefix="smoke-"))
    commit = commit_fixture(workdir / "repo")
    session = CountingSession(LocalRepoSession(workdir / "repo", commit))
    controller, store, _ = await start_controller(f"0.0.0.0:{CONTROLLER_PORT}")
    http, http_task, _ = await serve_http(mcp_app(session), "0.0.0.0", MCP_PORT)
    print(
        f"sidecar: fake controller on :{CONTROLLER_PORT}, agent-docs fake on :{MCP_PORT}/mcp, "
        f"fixture commit {commit[:12]}",
        flush=True,
    )
    try:
        await wait_ready(agent, READY_PORT, timeout_s)
        print(f"ok: /readyz on {READY_PORT} answered 200", flush=True)
        task = await send_check(f"{agent}:{A2A_PORT}", timeout_s)
        return verify(store, task, identity=identity, session=session, replayed=True)
    finally:
        await stop_http(http, http_task)
        await controller.stop(grace=0)


def config_json(controller: str, mcp: str) -> str:
    return json.dumps(adk_config(controller, mcp), separators=(",", ":"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tests.smoke_stack")
    commands = parser.add_subparsers(dest="command", required=True)
    side = commands.add_parser("sidecar", help="serve the fakes, send the task, check it")
    side.add_argument("--agent", required=True, help="the runtime's host name")
    side.add_argument("--identity", required=True, help="atespace/name/uid it must send")
    side.add_argument("--timeout", type=float, default=300.0, help="seconds per wait")
    conf = commands.add_parser("config", help="print the runtime's KAGENT_CONFIG_JSON")
    conf.add_argument("--controller", default=f"http://controller:{CONTROLLER_PORT}")
    conf.add_argument("--mcp", default=f"http://agent-docs-mcp:{MCP_PORT}/mcp")
    commands.add_parser("record", help="rewrite tests/fixtures/cassettes-smoke (no API)")
    args = parser.parse_args(argv)

    if args.command == "config":
        print(config_json(args.controller, args.mcp))
        return 0
    try:
        if args.command == "record":
            lines = asyncio.run(record())
        else:
            lines = asyncio.run(sidecar(args.agent, args.identity, args.timeout))
    except (SmokeFailure, grpc.aio.AioRpcError) as error:
        print(f"smoke FAILED: {error}", file=sys.stderr, flush=True)
        return 1
    for line in lines:
        print(line, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
