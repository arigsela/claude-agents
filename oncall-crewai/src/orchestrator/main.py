"""Orchestrator main application.

FastAPI app with:
- POST /query — run the OncallFlow to route queries to specialist agents
- POST /copilotkit — AG-UI SSE endpoint for CopilotKit frontend
- GET /sessions — list conversation sessions
- GET /sessions/{session_id} — get session with messages
- DELETE /sessions/{session_id} — delete session
- GET /health — health check
- GET / — API info
- A2A server mounted for agent-to-agent discovery

Entry point: uvicorn orchestrator.main:app --host 0.0.0.0 --port 8000
"""

import asyncio
import os
import uuid
from contextlib import asynccontextmanager

from a2a.server.agent_execution import AgentExecutor
from a2a.server.agent_execution.context import RequestContext
from a2a.server.apps import A2AStarletteApplication
from a2a.server.events.event_queue import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentSkill,
    Message,
    Role,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
    TextPart,
)
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from orchestrator.copilotkit_endpoint import copilotkit_handler
from orchestrator.flow import OncallFlow
from orchestrator.session_manager import SessionManager
from shared.config import API_HOST, API_KEYS, API_PORT, CORS_ORIGINS
from shared.logging_config import setup_logging

logger = setup_logging("orchestrator")


# ============================================================
# Auth
# ============================================================


def verify_api_key(request: Request):
    """Verify API key from Authorization header."""
    if not API_KEYS:
        return  # No auth in dev mode

    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
    else:
        token = request.headers.get("X-API-Key", "")

    if token not in API_KEYS:
        raise HTTPException(status_code=401, detail="Invalid API key")


# ============================================================
# Request/Response models
# ============================================================


class QueryRequest(BaseModel):
    prompt: str
    context_id: str = ""


class QueryResponse(BaseModel):
    response: str
    route: str
    context_id: str


# ============================================================
# Orchestrator A2A Executor
# ============================================================


class OrchestratorExecutor(AgentExecutor):
    """A2A executor that runs the OncallFlow."""

    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        task_id = context.task_id
        context_id = context.context_id

        try:
            user_input = self._extract_user_input(context)
            logger.info(f"A2A execute: task_id={task_id}, query={user_input[:80]}...")

            await event_queue.enqueue_event(
                TaskStatusUpdateEvent(
                    task_id=task_id,
                    context_id=context_id,
                    final=False,
                    status=TaskStatus(
                        state=TaskState.working,
                        message=Message(
                            role=Role.agent,
                            message_id=str(uuid.uuid4()),
                            parts=[TextPart(text="Triaging query...")],
                        ),
                    ),
                )
            )

            flow = OncallFlow()
            flow.state.query = user_input
            result = await asyncio.to_thread(flow.kickoff)

            await event_queue.enqueue_event(
                TaskStatusUpdateEvent(
                    task_id=task_id,
                    context_id=context_id,
                    final=True,
                    status=TaskStatus(
                        state=TaskState.completed,
                        message=Message(
                            role=Role.agent,
                            message_id=str(uuid.uuid4()),
                            parts=[TextPart(text=str(result))],
                        ),
                    ),
                )
            )

        except Exception as e:
            logger.error(f"Orchestrator executor error: {e}", exc_info=True)
            await event_queue.enqueue_event(
                TaskStatusUpdateEvent(
                    task_id=task_id,
                    context_id=context_id,
                    final=True,
                    status=TaskStatus(
                        state=TaskState.failed,
                        message=Message(
                            role=Role.agent,
                            message_id=str(uuid.uuid4()),
                            parts=[TextPart(text=f"Orchestrator error: {e}")],
                        ),
                    ),
                )
            )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError("Orchestrator does not support cancellation")

    def _extract_user_input(self, context: RequestContext) -> str:
        message = context.message
        if message and message.parts:
            text_parts = []
            for part in message.parts:
                if isinstance(part, TextPart):
                    text_parts.append(part.text)
                elif hasattr(part, "root") and isinstance(part.root, TextPart):
                    text_parts.append(part.root.text)
            if text_parts:
                return " ".join(text_parts)
        return "Perform a general cluster health check"


# ============================================================
# App factory
# ============================================================


def _build_agent_card() -> AgentCard:
    """Build the orchestrator's A2A AgentCard."""
    host = os.getenv("ORCHESTRATOR_HOST", API_HOST)
    port = int(os.getenv("ORCHESTRATOR_PORT", str(API_PORT)))
    url = os.getenv("ORCHESTRATOR_URL", f"http://{host}:{port}")

    return AgentCard(
        name="OnCall Orchestrator",
        description=(
            "Triage coordinator that routes oncall queries to specialist "
            "agents — K8s Diagnostics and GitOps Remediation — and "
            "synthesizes their results."
        ),
        url=url,
        version="0.1.0",
        default_input_modes=["text"],
        default_output_modes=["text"],
        capabilities=AgentCapabilities(streaming=False),
        skills=[
            AgentSkill(
                id="triage-incident",
                name="Triage Incident",
                description=(
                    "Classify an oncall query and route it to the appropriate "
                    "specialist agent for investigation."
                ),
                tags=["oncall", "triage", "routing"],
            ),
            AgentSkill(
                id="coordinate-investigation",
                name="Coordinate Investigation",
                description=(
                    "Coordinate a multi-agent investigation across K8s diagnostics "
                    "and GitOps remediation when both are needed."
                ),
                tags=["oncall", "coordination", "multi-agent"],
            ),
        ],
    )


def create_app() -> FastAPI:
    """Create the orchestrator FastAPI application."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Startup: initialize session manager
        app.state.session_manager = SessionManager()
        app.state.session_manager.start_cleanup_task()
        logger.info("SessionManager started with cleanup task")
        yield
        # Shutdown: stop cleanup
        app.state.session_manager.stop_cleanup_task()
        logger.info("SessionManager cleanup task stopped")

    fastapi_app = FastAPI(
        title="OnCall Orchestrator",
        version="0.1.0",
        description="Multi-agent oncall orchestrator using CrewAI + A2A protocol",
        lifespan=lifespan,
    )

    # CORS
    origins = [o.strip() for o in CORS_ORIGINS.split(",") if o.strip()]
    fastapi_app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @fastapi_app.get("/health")
    async def health():
        return JSONResponse({"status": "healthy", "agent": "orchestrator"})

    @fastapi_app.get("/")
    async def root():
        return JSONResponse({
            "service": "oncall-crewai-orchestrator",
            "version": "0.1.0",
            "agents": ["k8s-diagnostics", "github-gitops"],
            "endpoints": {
                "query": "POST /query",
                "copilotkit": "POST /copilotkit",
                "health": "GET /health",
                "agent_card": "GET /.well-known/agent.json",
            },
        })

    @fastapi_app.post("/query", response_model=QueryResponse)
    def query(req: QueryRequest, _=Depends(verify_api_key)):
        logger.info(f"Query received: {req.prompt[:80]}...")

        flow = OncallFlow()
        flow.state.query = req.prompt
        result = flow.kickoff()

        return QueryResponse(
            response=str(result),
            route=flow.state.route,
            context_id=req.context_id or str(uuid.uuid4()),
        )

    # CopilotKit AG-UI endpoint (must be registered BEFORE A2A mount at "/")
    @fastapi_app.post("/copilotkit")
    async def copilotkit(request: Request, _=Depends(verify_api_key)):
        return await copilotkit_handler(request)

    # Session management endpoints
    @fastapi_app.get("/sessions")
    async def list_sessions(_=Depends(verify_api_key)):
        mgr: SessionManager = fastapi_app.state.session_manager
        return JSONResponse(mgr.list_sessions())

    @fastapi_app.get("/sessions/{session_id}")
    async def get_session(session_id: str, _=Depends(verify_api_key)):
        mgr: SessionManager = fastapi_app.state.session_manager
        session = mgr.get_session(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        return JSONResponse(session.to_dict())

    @fastapi_app.delete("/sessions/{session_id}", status_code=204)
    async def delete_session(session_id: str, _=Depends(verify_api_key)):
        mgr: SessionManager = fastapi_app.state.session_manager
        if not mgr.delete_session(session_id):
            raise HTTPException(status_code=404, detail="Session not found")

    # A2A server
    agent_card = _build_agent_card()
    executor = OrchestratorExecutor()
    task_store = InMemoryTaskStore()
    handler = DefaultRequestHandler(
        agent_executor=executor,
        task_store=task_store,
    )
    a2a_app = A2AStarletteApplication(
        agent_card=agent_card,
        http_handler=handler,
    )

    fastapi_app.mount("/", a2a_app.build())

    logger.info(f"Orchestrator ready: {agent_card.url}")
    return fastapi_app


app = create_app()
