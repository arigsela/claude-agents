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
"""

from __future__ import annotations

import asyncio
import logging
import signal
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypedDict

import grpc
from a2a.server.request_handlers import DefaultRequestHandlerV2
from a2a.server.request_handlers.grpc_handler import (
    DefaultGrpcServerCallContextBuilder,
    GrpcHandler,
)
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import a2a_pb2, a2a_pb2_grpc
from grpc_health.v1 import health, health_pb2, health_pb2_grpc
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from docs_checker import prompts
from docs_checker.config import Settings, load_settings
from docs_checker.executor import DocsCheckerExecutor
from docs_checker.gate import RecordingGate
from docs_checker.llm import request_id_hook
from docs_checker.models import AnthropicModels

logger = logging.getLogger(__name__)

A2A_SERVICE = a2a_pb2.DESCRIPTOR.services_by_name["A2AService"].full_name


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
                description=(
                    "Reports doc lines that no longer match the manifests they describe, "
                    "with the corrected line."
                ),
                tags=["gitops", "docs", "read-only"],
                examples=["check base-apps/kagent/docs.md", "check all docs"],
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


NOT_WIRED = "docs-checker is not wired yet"


class _PlaceholderState(TypedDict, total=False):
    question: str
    answer: str
    outcome: str


async def _refuse(state: _PlaceholderState) -> dict:
    return {"answer": NOT_WIRED, "outcome": "refused"}


def placeholder_graph() -> Any:
    """What ``main`` serves until the docs-checker graph exists: a graph that refuses
    every request, without a model or tool call."""
    graph = StateGraph(_PlaceholderState)
    graph.add_node("refuse", _refuse)
    graph.add_edge(START, "refuse")
    graph.add_edge("refuse", END)
    return graph.compile(checkpointer=InMemorySaver())


def build_executor(
    settings: Settings, *, graph: Any, models=None, tools=None, gate=None
) -> DocsCheckerExecutor:
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
        models=models
        or AnthropicModels(
            settings.node_models,
            settings.levers,
            http_timeout_s=settings.http_timeout_s,
            on_response=request_id_hook,
        ),
        tools=tools or default_tools,
        gate=gate or RecordingGate(),
    )


async def serve(settings: Settings | None = None) -> None:
    settings = settings or load_settings()
    card = build_agent_card(settings)
    executor = build_executor(settings, graph=placeholder_graph())
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
