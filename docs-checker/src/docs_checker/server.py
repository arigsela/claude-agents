"""The kagent 1.0 BYO runtime contract, served for a LangGraph graph.

What the controller (v1.0.0-alpha14) and Agent Substrate expect of a BYO image:

1. A2A v1 over gRPC (service ``lf.a2a.v1.A2AService``) on the ADKConfig's
   ``runtime.port``, 80. The gateway dials the actor through the Atenet router
   with gRPC only; a JSON-RPC-only server is never reached.
2. ``GET /readyz`` answering 200 on 8081, a separate listener (Substrate's
   wake-up probe). Substrate may snapshot the actor as soon as it succeeds, so
   the A2A port binds first.
3. The private TaskStore at ``runtime.control_plane_url`` (gRPC
   ``kagent.runtime.v1.TaskStoreService``): tasks are created, versioned and
   settled there, identified by the projected actor identity under
   /run/kagent/identity. An in-memory store is not enough in-cluster.

kagent-adk's Python ``KAgentApp`` implements all three for Google ADK agents;
kagent-langgraph (1.0.0a11 through a14) serves FastAPI JSON-RPC only. This
module is the missing piece: kagent-adk's listener shape, with kagent-core's
TaskStore and request handler, around a LangGraph executor.

``main`` serves the docs-checker graph (``graph.build_graph``) on the
``AsyncSqliteSaver`` at ``settings.checkpoint_db``, opened once for the server's
lifetime under the data dir that Substrate snapshots (/data), with paused tasks'
ledgers and memos in the same db and the production fix gate.
"""

from __future__ import annotations

import asyncio
import logging
import signal
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import grpc
from a2a.server.request_handlers import DefaultRequestHandlerV2
from a2a.server.request_handlers.grpc_handler import (
    DefaultGrpcServerCallContextBuilder,
    GrpcHandler,
)
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import a2a_pb2, a2a_pb2_grpc
from grpc_health.v1 import health, health_pb2, health_pb2_grpc

from docs_checker import prompts
from docs_checker.config import Settings, load_settings
from docs_checker.executor import DocsCheckerExecutor
from docs_checker.gate import AllowGate, FixGate, build_fix_gate
from docs_checker.graph import build_graph, open_checkpointer
from docs_checker.llm import request_id_hook
from docs_checker.models import AnthropicModels
from docs_checker.paused import PausedTasks

logger = logging.getLogger(__name__)

A2A_SERVICE = a2a_pb2.DESCRIPTOR.services_by_name["A2AService"].full_name


SKILL_DESCRIPTION = (
    "Read-only audit of the arigsela/kubernetes docs that list their sources: finds stale "
    "lines (doc lines that no longer match the manifests they cite) and missing sources, "
    "with a corrected line where the evidence shows one. It never writes. Ask "
    '"check all" or "check <path>[, <path>...]" (optionally "at <ref>": a branch or '
    'commit), or send a data part {"scope": "all" | [paths], "ref", "mode": '
    '"interactive" | "scheduled", "memory"}. The task returns the report as text and the '
    "findings, memory snapshot, Slack digest and report as data parts."
)


def build_agent_card(settings: Settings) -> a2a_pb2.AgentCard:
    card = a2a_pb2.AgentCard(
        name=settings.agent_name.replace("-", "_"),
        description=prompts.AGENT_DESCRIPTION,
        version="0.1.0",
        default_input_modes=["text"],
        default_output_modes=["text"],
        supported_interfaces=[
            a2a_pb2.AgentInterface(
                url=f"http://127.0.0.1:{settings.a2a_port}",
                protocol_binding="GRPC",
                protocol_version="1.0",
            )
        ],
        skills=[
            a2a_pb2.AgentSkill(
                id="docs-check",
                name="Docs drift check",
                description=SKILL_DESCRIPTION,
                tags=["gitops", "docs", "read-only"],
                examples=[
                    "check all",
                    "check base-apps/vault/docs.md",
                    "check base-apps/vault/docs.md, docs/runbook.md at main",
                ],
            )
        ],
    )
    card.capabilities.streaming = True
    try:
        from kagent.core.a2a import attach_hitl_agent_extension

        attach_hitl_agent_extension(card)
    except ImportError:
        pass
    return card


def build_request_handler(
    settings: Settings,
    executor: Any,
    card: a2a_pb2.AgentCard,
    identity_path: Path | None = None,
):
    """kagent's TaskStore and settling handler in-cluster; in-memory locally.

    ``identity_path`` defaults to /run/kagent/identity/name, which Substrate
    projects (and rebinds on restore); tests point it at a temp directory.
    """
    if settings.under_kagent:
        from kagent.core import AsyncControllerClient
        from kagent.core.a2a import KAgentRequestContextBuilder
        from kagent.core.a2a._task_store import KAgentRequestHandler, KAgentTaskStore

        client = AsyncControllerClient(settings.kagent_api_url, agent_name=settings.agent_name)
        store = (
            KAgentTaskStore(client, identity_path=identity_path)
            if identity_path
            else KAgentTaskStore(client)
        )
        handler = KAgentRequestHandler(
            agent_executor=executor,
            task_store=store,
            agent_card=card,
            request_context_builder=KAgentRequestContextBuilder(task_store=store),
        )
        return handler, client
    return (
        DefaultRequestHandlerV2(
            agent_executor=executor, task_store=InMemoryTaskStore(), agent_card=card
        ),
        None,
    )


def _call_context_builder():
    try:
        from kagent.core.a2a import KAgentGrpcServerCallContextBuilder

        return KAgentGrpcServerCallContextBuilder()  # keeps gateway metadata (x-user-id, ...)
    except ImportError:
        return DefaultGrpcServerCallContextBuilder()


async def _readyz(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    request = await reader.readline()
    status = b"200 OK" if request.startswith(b"GET /readyz ") else b"404 Not Found"
    writer.write(b"HTTP/1.1 " + status + b"\r\nContent-Length: 2\r\nConnection: close\r\n\r\nOK")
    await writer.drain()
    writer.close()
    await writer.wait_closed()


@dataclass
class RunningServer:
    grpc_server: grpc.aio.Server
    ready_server: asyncio.Server
    health: health.aio.HealthServicer
    a2a_port: int
    ready_port: int
    controller: Any = None

    async def stop(self, grace: float = 5.0) -> None:
        self.ready_server.close()
        await self.ready_server.wait_closed()
        await self.health.enter_graceful_shutdown()
        await self.grpc_server.stop(grace=grace)
        if self.controller is not None:
            await self.controller.close()


async def start(
    handler: Any,
    *,
    a2a_address: str,
    ready_port: int,
    ready_host: str | None = None,
    controller: Any = None,
) -> RunningServer:
    """Bind A2A gRPC first, then readiness (Substrate may snapshot right after /readyz)."""
    server = grpc.aio.server()
    a2a_pb2_grpc.add_A2AServiceServicer_to_server(
        GrpcHandler(handler, context_builder=_call_context_builder()), server
    )
    health_servicer = health.aio.HealthServicer()
    await health_servicer.set(A2A_SERVICE, health_pb2.HealthCheckResponse.SERVING)
    health_pb2_grpc.add_HealthServicer_to_server(health_servicer, server)
    port = server.add_insecure_port(a2a_address)
    if port == 0:
        raise RuntimeError(f"failed to bind A2A gRPC to {a2a_address}")
    await server.start()
    # host=None binds every interface on every family: Substrate probes an IPv4
    # address, and an IPv6-only socket refused it (a kagent-adk lesson).
    ready = await asyncio.start_server(_readyz, host=ready_host, port=ready_port)
    bound_ready = ready.sockets[0].getsockname()[1]
    logger.info("A2A gRPC on %s (port %d), /readyz on %d", a2a_address, port, bound_ready)
    return RunningServer(server, ready, health_servicer, port, bound_ready, controller)


async def load_mcp_tools(settings: Settings) -> dict[str, list[Any]]:
    """Discover tools per server, so each keeps the identity of its server."""
    if not settings.mcp_servers:
        return {}
    from langchain_mcp_adapters.client import MultiServerMCPClient

    client = MultiServerMCPClient(
        {
            server.name: {
                "transport": "streamable_http",
                "url": server.url,
                "headers": server.headers,
            }
            for server in settings.mcp_servers
        },
        # An MCP error result (isError) raises instead of coming back as content,
        # so it can never be mistaken for a successful read.
        handle_tool_errors=False,
    )
    return {
        server.name: await client.get_tools(server_name=server.name)
        for server in settings.mcp_servers
    }


def build_models(settings: Settings) -> AnthropicModels:
    """The models production serves: Anthropic through the SDK's own transport.

    ``settings.replay_dir`` (``DOCS_CHECKER_REPLAY_DIR``, unset in production) is a
    test seam: every response then comes from the cassettes there, in ``replay`` mode
    over a transport that refuses to send, so nothing is recorded, nothing reaches the
    API, and a request with no recording fails its call. The image smoke test runs a
    real task on it without a key (``scripts/smoke.sh``)."""
    transport = None
    if settings.replay_dir:
        from docs_checker.evals.replay import replay_only

        transport = replay_only(settings.replay_dir)
        logger.warning(
            "model replay is active: every response comes from %s; nothing is recorded "
            "and nothing reaches the API (DOCS_CHECKER_REPLAY_DIR)",
            settings.replay_dir,
        )
    return AnthropicModels(
        settings.node_models,
        settings.levers,
        http_timeout_s=settings.http_timeout_s,
        on_response=request_id_hook,
        transport=transport,
    )


def build_executor(
    settings: Settings,
    *,
    graph: Any,
    models=None,
    tools=None,
    gate=None,
    fix_gate: FixGate | None = None,
    paused: PausedTasks | None = None,
) -> DocsCheckerExecutor:
    """The executor production serves; tests inject fakes. Every proposed fix goes
    through ``fix_gate``, which defaults to the one production runs (C#10). Paused
    tasks wait in memory unless ``paused`` keeps them in a db (``open_executor``)."""
    cached: dict[str, list[Any]] | None = None

    async def default_tools() -> dict[str, list[Any]]:
        # Discovered on first use, not at startup: the golden snapshot is taken
        # right after /readyz, and sessions start from it.
        nonlocal cached
        if cached is None:
            cached = await load_mcp_tools(settings)
        return cached

    return DocsCheckerExecutor(
        graph=graph,
        settings=settings,
        models=models or build_models(settings),
        tools=tools or default_tools,
        gate=gate or AllowGate(),
        fix_gate=build_fix_gate(settings) if fix_gate is None else fix_gate,
        paused=paused,
    )


@asynccontextmanager
async def open_executor(settings: Settings, **overrides: Any) -> AsyncIterator[DocsCheckerExecutor]:
    """The executor ``main`` serves, open for the server's lifetime: the docs-checker
    graph on the ``AsyncSqliteSaver`` at ``settings.checkpoint_db`` (ruling A1), and
    paused tasks' ledgers and memos in the same db, written under the checkpointer's
    lock. A new process on the same db resumes what an earlier one paused.
    ``overrides`` go to ``build_executor`` (tests inject models and tools)."""
    async with open_checkpointer(settings.checkpoint_db) as checkpointer:
        await checkpointer.setup()
        paused = PausedTasks(checkpointer.conn, lock=checkpointer.lock)
        await paused.setup()
        graph = build_graph(checkpointer=checkpointer)
        yield build_executor(settings, graph=graph, paused=paused, **overrides)


async def serve(settings: Settings | None = None) -> None:
    settings = settings or load_settings()
    card = build_agent_card(settings)
    async with open_executor(settings) as executor:
        handler, controller = build_request_handler(settings, executor, card)
        running = await start(
            handler,
            a2a_address=f"[::]:{settings.a2a_port}",
            ready_port=settings.ready_port,
            controller=controller,
        )
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stop.set)
        await stop.wait()
        await running.stop()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(serve())
