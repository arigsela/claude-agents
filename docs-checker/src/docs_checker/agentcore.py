"""The Amazon Bedrock AgentCore Runtime contract, served for the same LangGraph executor.

What AgentCore expects of an A2A container (protocol ``A2A``):

1. A2A JSON-RPC 2.0 over HTTP at ``/`` on ``0.0.0.0:9000``, and the Agent Card at
   ``/.well-known/agent-card.json``. AgentCore signs the caller in (SigV4) and routes
   each session (``X-Amzn-Bedrock-AgentCore-Runtime-Session-Id``) to its own microVM.
2. ``GET /ping`` answering ``{"status": "Healthy"}``.
3. Only the session storage mount (``/mnt/workspace``) outlives a microVM: an idle
   stop or the maximum lifetime ends the process, and the session's next request
   starts a new one on the same storage. So the A2A task store and the checkpoints
   both live there, in SQLite opened without file locks (the mount has none). A fix
   approval that arrives after a restart finds its task ``input-required`` and its
   checkpoint, and resumes.

There is no kagent controller here: tasks are settled by a2a-sdk's
``DefaultRequestHandlerV2`` on a ``DatabaseTaskStore``. HITL still uses kagent's
hitl/v1 extension (the executor's request and reply shapes). AgentCore forwards only
allowlisted headers, so neither the ``A2A-Extensions`` opt-in nor ``A2A-Version`` can be
relied on: every request is treated as opted in to HITL and as A2A 1.0, since the only
caller is ``scripts/ask_agentcore.py``.

``main`` logs every startup phase to stdout, which AgentCore ships to CloudWatch.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any

from a2a.server.request_handlers import DefaultRequestHandlerV2
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.routes.common import DefaultServerCallContextBuilder
from a2a.server.tasks import InMemoryTaskStore
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from docs_checker.config import Settings, load_settings
from docs_checker.server import build_agent_card, open_executor

logger = logging.getLogger(__name__)

HITL_EXTENSION_URI = "https://kagent.dev/extensions/hitl/v1"
EXTENSIONS_HEADER = "a2a-extensions"
VERSION_HEADER = "a2a-version"
DEFAULT_RUNTIME_URL = "http://127.0.0.1:9000/"
# Same budget as the checkpoint db: a blocked mount must not keep /ping from answering.
TASK_STORE_OPEN_TIMEOUT_S = 10.0


class AgentCoreCallContextBuilder(DefaultServerCallContextBuilder):
    """The default context, opted in to HITL and on A2A 1.0 whatever headers reached
    the container (a2a-sdk reads a missing ``A2A-Version`` as 0.3 and refuses it)."""

    def build(self, request: Any) -> Any:
        context = super().build(request)
        headers = context.state.setdefault("headers", {})
        if not headers.get(VERSION_HEADER):
            headers[VERSION_HEADER] = "1.0"
        present = [v.strip() for v in str(headers.get(EXTENSIONS_HEADER, "")).split(",")]
        if HITL_EXTENSION_URI not in present:
            headers[EXTENSIONS_HEADER] = ", ".join([*filter(None, present), HITL_EXTENSION_URI])
        return context


async def open_task_store(stack: AsyncExitStack, settings: Settings) -> Any:
    """a2a-sdk's ``DatabaseTaskStore`` in ``<data_dir>/tasks.sqlite``, or an in-memory
    store with a warning when the db cannot be opened in time (the agent still serves;
    a pause then does not outlive this process)."""

    async def durable() -> Any:
        from pathlib import Path

        from a2a.server.tasks import DatabaseTaskStore
        from sqlalchemy import event
        from sqlalchemy.ext.asyncio import create_async_engine

        path = Path(settings.data_dir) / "tasks.sqlite"
        path.parent.mkdir(parents=True, exist_ok=True)
        query = "?nolock=1&uri=true" if settings.sqlite_nolock else ""
        # nolock tells SQLite that no other connection exists, so the engine holds
        # exactly one and concurrent saves queue for it: a pool of several overwrote
        # each other's pages ("database or disk is full" on session storage).
        engine = create_async_engine(
            f"sqlite+aiosqlite:///file:{path}{query}", pool_size=1, max_overflow=0
        )
        stack.push_async_callback(engine.dispose)
        if settings.sqlite_nolock:

            @event.listens_for(engine.sync_engine, "connect")
            def _pragmas(connection: Any, _record: Any) -> None:
                cursor = connection.cursor()
                cursor.execute("PRAGMA journal_mode=MEMORY")
                cursor.execute("PRAGMA synchronous=OFF")
                cursor.close()

        store = DatabaseTaskStore(engine)
        await store.initialize()
        return store, path

    try:
        store, path = await asyncio.wait_for(durable(), timeout=TASK_STORE_OPEN_TIMEOUT_S)
    except Exception as exc:  # noqa: BLE001 - an unwritable mount, a blocked fs, a timeout
        logger.warning(
            "A2A tasks stay in memory for this process: cannot open the task db in %s (%s: %s)",
            settings.data_dir,
            type(exc).__name__,
            exc,
        )
        return InMemoryTaskStore()
    logger.info("A2A tasks in %s", path)
    return store


async def _ping(_request: Any) -> JSONResponse:
    return JSONResponse({"status": "Healthy"})


def build_app(handler: Any, card: Any) -> Starlette:
    routes = [
        *create_agent_card_routes(card),
        *create_jsonrpc_routes(handler, rpc_url="/", context_builder=AgentCoreCallContextBuilder()),
        Route("/ping", _ping, methods=["GET"]),
    ]
    return Starlette(routes=routes)


@asynccontextmanager
async def open_app(
    settings: Settings, *, executor: Any = None, **overrides: Any
) -> AsyncIterator[Starlette]:
    """The app ``main`` serves, with its executor and task store open until exit.
    ``executor`` replaces the production one (tests); ``overrides`` go to
    ``open_executor`` otherwise."""
    card = build_agent_card(
        settings,
        url=os.environ.get("AGENTCORE_RUNTIME_URL", DEFAULT_RUNTIME_URL),
        binding="JSONRPC",
    )
    async with AsyncExitStack() as stack:
        if executor is None:
            executor = await stack.enter_async_context(open_executor(settings, **overrides))
        store = await open_task_store(stack, settings)
        handler = DefaultRequestHandlerV2(
            agent_executor=executor, task_store=store, agent_card=card
        )
        yield build_app(handler, card)


async def serve(settings: Settings | None = None) -> None:
    import uvicorn

    started = time.monotonic()

    def phase(what: str, *args: Any) -> None:
        logger.info("startup +%.1fs: " + what, time.monotonic() - started, *args)

    settings = settings or load_settings()
    phase("settings loaded (runtime %s, data dir %s)", settings.runtime, settings.data_dir)
    async with open_app(settings) as app:
        phase("executor and task store ready")
        config = uvicorn.Config(
            app, host="0.0.0.0", port=settings.a2a_port, log_config=None, access_log=False
        )
        server = uvicorn.Server(config)
        phase("server.serve on 0.0.0.0:%d", settings.a2a_port)
        await server.serve()


def main() -> None:
    """Serve until SIGTERM. Logs go to stdout (AgentCore ships stdout and stderr to
    CloudWatch); a startup error is logged with its traceback before exit 1."""
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stdout,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        force=True,
    )
    try:
        asyncio.run(serve())
    except Exception:
        logger.exception("docs-checker stopped on an error")
        sys.stdout.flush()
        raise SystemExit(1) from None
