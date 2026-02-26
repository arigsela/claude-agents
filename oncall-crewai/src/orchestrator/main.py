"""Orchestrator main application.

FastAPI app with:
- POST /auth/login — authenticate user, return JWT
- POST /auth/register — create user account, return JWT
- GET /auth/me — get current user info (requires JWT)
- POST /query — run the OncallFlow to route queries to specialist agents
- POST /copilotkit — AG-UI SSE endpoint for CopilotKit frontend
- GET /sessions — list conversation sessions (scoped by user)
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

from orchestrator.auth import AuthInfo, create_jwt, verify_auth
from orchestrator.flow import OncallFlow

# Lazy import: ag_ui is an optional dependency not available in all environments
try:
    from orchestrator.copilotkit_endpoint import copilotkit_handler

    _HAS_AG_UI = True
except ImportError:
    _HAS_AG_UI = False
from orchestrator.session_manager import SessionManager
from orchestrator.user_manager import UserManager
from shared.a2a_utils import extract_user_input
from shared.config import API_HOST, API_KEYS, API_PORT, CORS_ORIGINS
from shared.logging_config import setup_logging

import shared.observability  # noqa: F401 — register event listeners

logger = setup_logging("orchestrator")


# ============================================================
# Request/Response models
# ============================================================


class AuthRequest(BaseModel):
    username: str
    password: str


class AuthResponse(BaseModel):
    token: str
    user_id: str
    username: str


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
        return extract_user_input(
            context.message,
            default="Perform a general cluster health check",
        )


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
        # Startup: initialize user manager and session manager
        app.state.user_manager = UserManager()
        app.state.session_manager = SessionManager()
        app.state.session_manager.start_cleanup_task()
        logger.info("UserManager and SessionManager started")
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

    # ============================================================
    # Auth endpoints (no auth required for login/register)
    # ============================================================

    @fastapi_app.post("/auth/register", response_model=AuthResponse)
    async def register(req: AuthRequest, request: Request):
        um: UserManager = request.app.state.user_manager
        try:
            user = um.create_user(req.username, req.password)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        token = create_jwt(user.user_id, user.username)
        return AuthResponse(token=token, user_id=user.user_id, username=user.username)

    @fastapi_app.post("/auth/login", response_model=AuthResponse)
    async def login(req: AuthRequest, request: Request):
        um: UserManager = request.app.state.user_manager
        user = um.authenticate(req.username, req.password)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid username or password")
        token = create_jwt(user.user_id, user.username)
        return AuthResponse(token=token, user_id=user.user_id, username=user.username)

    @fastapi_app.get("/auth/me")
    async def auth_me(auth: AuthInfo = Depends(verify_auth)):
        if not auth.user_id:
            raise HTTPException(status_code=401, detail="JWT authentication required")
        return JSONResponse({"user_id": auth.user_id, "username": auth.username})

    # ============================================================
    # Query / CopilotKit endpoints
    # ============================================================

    @fastapi_app.post("/query", response_model=QueryResponse)
    async def query(req: QueryRequest, auth: AuthInfo = Depends(verify_auth)):
        logger.info(f"Query received: {req.prompt[:80]}...")

        flow = OncallFlow()
        flow.state.query = req.prompt
        result = await asyncio.to_thread(flow.kickoff)

        return QueryResponse(
            response=str(result),
            route=flow.state.route,
            context_id=req.context_id or str(uuid.uuid4()),
        )

    # CopilotKit AG-UI endpoint (must be registered BEFORE A2A mount at "/")
    if _HAS_AG_UI:

        @fastapi_app.post("/copilotkit")
        async def copilotkit(request: Request, auth: AuthInfo = Depends(verify_auth)):
            return await copilotkit_handler(request, auth)

    # ============================================================
    # Session management endpoints (scoped by user)
    # ============================================================

    @fastapi_app.post("/sessions/{session_id}", status_code=201)
    async def init_session(session_id: str, auth: AuthInfo = Depends(verify_auth)):
        """Pre-create a session with the authenticated user's ID."""
        mgr: SessionManager = fastapi_app.state.session_manager
        session = mgr.get_or_create_session(session_id, user_id=auth.user_id or "")
        return JSONResponse(session.to_summary(), status_code=201)

    @fastapi_app.get("/sessions")
    async def list_sessions(auth: AuthInfo = Depends(verify_auth)):
        mgr: SessionManager = fastapi_app.state.session_manager
        return JSONResponse(mgr.list_sessions(user_id=auth.user_id))

    @fastapi_app.get("/sessions/{session_id}")
    async def get_session(session_id: str, auth: AuthInfo = Depends(verify_auth)):
        mgr: SessionManager = fastapi_app.state.session_manager
        session = mgr.get_session(session_id, user_id=auth.user_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        return JSONResponse(session.to_dict())

    @fastapi_app.delete("/sessions/{session_id}", status_code=204)
    async def delete_session(session_id: str, auth: AuthInfo = Depends(verify_auth)):
        mgr: SessionManager = fastapi_app.state.session_manager
        if not mgr.delete_session(session_id, user_id=auth.user_id):
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
