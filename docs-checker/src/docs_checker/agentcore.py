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

        store = _LoggedTaskStore(engine, path)
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


def _logged_task_store_class() -> type:
    from a2a.server.tasks import DatabaseTaskStore

    class LoggedTaskStore(DatabaseTaskStore):
        """a2a turns a store error into a JSON-RPC error without logging it; log it here
        with the db's size and the pragmas in effect, so a storage failure is visible."""

        def __init__(self, engine: Any, path: Any):
            super().__init__(engine)
            self._path = path

        async def _report(self, what: str, error: Exception) -> None:
            pragmas = {}
            try:
                async with self.engine.connect() as connection:
                    for name in ("journal_mode", "synchronous", "page_size", "temp_store"):
                        result = await connection.exec_driver_sql(f"PRAGMA {name}")
                        pragmas[name] = result.scalar()
            except Exception as probe:  # noqa: BLE001 - diagnostics only
                pragmas["probe"] = f"{type(probe).__name__}: {probe}"
            size = self._path.stat().st_size if self._path.exists() else None
            logger.exception(
                "task store %s failed (%s); %s bytes, pragmas %s, %s",
                what,
                type(error).__name__,
                size,
                pragmas,
                storage_state(str(self._path.parent)),
            )

        async def save(self, *args: Any, **kwargs: Any) -> Any:
            try:
                return await super().save(*args, **kwargs)
            except Exception as error:
                await self._report("save", error)
                raise

        async def get(self, *args: Any, **kwargs: Any) -> Any:
            try:
                return await super().get(*args, **kwargs)
            except Exception as error:
                await self._report("get", error)
                raise

    return LoggedTaskStore


def _LoggedTaskStore(engine: Any, path: Any) -> Any:
    return _logged_task_store_class()(engine, path)


async def _ping(_request: Any) -> JSONResponse:
    return JSONResponse({"status": "Healthy"})


def storage_state(path: str) -> str:
    """The mount under ``path`` and its free space, for the logs: AgentCore attaches
    session storage per session, so what a process sees at startup can differ from what
    it sees once a session is routed to it."""
    mount = "?"
    try:
        with open("/proc/self/mountinfo", encoding="utf-8") as handle:
            best = ""
            for line in handle:
                fields = line.split()
                point = fields[4]
                if path.startswith(point) and len(point) >= len(best):
                    best = point
                    fstype = fields[fields.index("-") + 1] if "-" in fields else "?"
                    mount = f"{point} ({fstype})"
    except OSError:
        pass
    try:
        stat = os.statvfs(path)
        free = f"{stat.f_bavail * stat.f_frsize} bytes free of {stat.f_blocks * stat.f_frsize}"
    except OSError as error:
        free = f"statvfs failed: {error}"
    return f"{path} on {mount}, {free}"


STORAGE_WAIT_S = 30.0
STORAGE_RETRY_S = 0.5


def probe_storage(path: str) -> None:
    """Commit one SQLite transaction under ``path`` with the dbs' own flags; raises
    when session storage refuses the write."""
    import sqlite3
    from pathlib import Path

    Path(path).mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(f"file:{path}/storage-probe.sqlite?nolock=1", uri=True)
    try:
        connection.execute("PRAGMA journal_mode=MEMORY")
        connection.execute("PRAGMA synchronous=OFF")
        connection.execute("CREATE TABLE IF NOT EXISTS probe (at REAL)")
        connection.execute("DELETE FROM probe")
        connection.execute("INSERT INTO probe VALUES (?)", (time.time(),))
        connection.commit()
    finally:
        connection.close()


class _StorageGate:
    """ASGI middleware: before the first request that is not /ping, wait until session
    storage takes a write. Live, a new session's storage refused writes for a few
    seconds (SQLITE_FULL on the first commit of either db; the same session was fine
    5 s later), so the probe retries for up to ``STORAGE_WAIT_S`` and then lets the
    request through either way, with the outcome logged."""

    def __init__(self, app: Any, path: str):
        self.app, self.path = app, path
        self.ready = False
        self.lock = asyncio.Lock()

    async def _wait(self) -> None:
        started, attempts = time.monotonic(), 0
        while True:
            attempts += 1
            try:
                await asyncio.to_thread(probe_storage, self.path)
            except Exception as error:  # noqa: BLE001 - any refusal is retried, then logged
                if time.monotonic() - started >= STORAGE_WAIT_S:
                    logger.warning(
                        "session storage still refuses writes after %.1f s (%d attempts, "
                        "%s: %s); %s",
                        time.monotonic() - started,
                        attempts,
                        type(error).__name__,
                        error,
                        storage_state(self.path),
                    )
                    return
                await asyncio.sleep(STORAGE_RETRY_S)
                continue
            logger.info(
                "session storage took a write after %.1f s (%d attempts); %s",
                time.monotonic() - started,
                attempts,
                storage_state(self.path),
            )
            return

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if not self.ready and scope.get("type") == "http" and scope.get("path") != "/ping":
            async with self.lock:
                if not self.ready:
                    await self._wait()
                    self.ready = True
        await self.app(scope, receive, send)


def build_app(handler: Any, card: Any, data_dir: str | None = None) -> Any:
    routes = [
        *create_agent_card_routes(card),
        *create_jsonrpc_routes(handler, rpc_url="/", context_builder=AgentCoreCallContextBuilder()),
        Route("/ping", _ping, methods=["GET"]),
    ]
    app = Starlette(routes=routes)
    return _StorageGate(app, data_dir) if data_dir else app


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
        yield build_app(handler, card, settings.data_dir)


async def serve(settings: Settings | None = None) -> None:
    import uvicorn

    started = time.monotonic()

    def phase(what: str, *args: Any) -> None:
        logger.info("startup +%.1fs: " + what, time.monotonic() - started, *args)

    settings = settings or load_settings()
    phase("settings loaded (runtime %s, data dir %s)", settings.runtime, settings.data_dir)
    phase("storage: %s", storage_state(settings.data_dir))
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
