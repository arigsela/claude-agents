# ==============================================================================
# Orchestrator — FastAPI Application
# ==============================================================================
#
# Entry point for the orchestrator service. Creates a FastAPI web server with:
# - GET  /health   — Health check (K8s probes)
# - POST /invoke   — Route query to sub-agent
# - GET  /info     — Orchestrator metadata
# - Auth, session, and CopilotKit endpoints (conditional)
# - A2A server for agent-to-agent discovery
#
# RUNNING THIS SERVICE:
#   uvicorn orchestrator.main:app --host 0.0.0.0 --port 8000
# ==============================================================================

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

from shared.a2a_utils import extract_user_input
from shared.config import PROJECT_NAME, ORCHESTRATOR_PORT, API_KEYS
from shared.logging_config import setup_logging


try:
    from orchestrator.copilotkit_endpoint import copilotkit_handler
    _HAS_AG_UI = True
except ImportError:
    _HAS_AG_UI = False


from orchestrator.session_manager import SessionManager



logger = setup_logging("orchestrator")


# --- REQUEST/RESPONSE MODELS ---

class InvokeRequest(BaseModel):
    """Request body for the /invoke endpoint."""
    query: str


    context_id: str = ""




class InvokeResponse(BaseModel):
    """Response body from the /invoke endpoint."""
    result: str
    route: str


    context_id: str = ""




# --- A2A Executor ---

class OrchestratorExecutor(AgentExecutor):
    """A2A executor that runs the OrchestratorFlow."""

    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        task_id = context.task_id
        context_id = context.context_id

        try:
            user_input = extract_user_input(context.message)
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
                            parts=[TextPart(text="Processing query...")],
                        ),
                    ),
                )
            )

            from orchestrator.flow import OrchestratorFlow
            flow = OrchestratorFlow()
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


# --- App factory ---

def _build_agent_card() -> AgentCard:
    host = os.getenv("ORCHESTRATOR_HOST", "0.0.0.0")
    port = int(os.getenv("ORCHESTRATOR_PORT", str(ORCHESTRATOR_PORT)))
    url = os.getenv("ORCHESTRATOR_URL", f"http://{host}:{port}")

    return AgentCard(
        name="dungeons-dragons-agent Orchestrator",
        description="Routes queries to specialized sub-agents via A2A protocol.",
        url=url,
        version="1.0.0",
        default_input_modes=["text"],
        default_output_modes=["text"],
        capabilities=AgentCapabilities(streaming=False),
        skills=[
            AgentSkill(
                id="route-query",
                name="Route Query",
                description="Classify and route a query to the appropriate sub-agent.",
                tags=["routing", "orchestration"],
            ),
        ],
    )


def create_app() -> FastAPI:
    """Create the orchestrator FastAPI application."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):


        app.state.session_manager = SessionManager()
        app.state.session_manager.start_cleanup_task()


        logger.info("Orchestrator started")
        yield


        app.state.session_manager.stop_cleanup_task()


        logger.info("Orchestrator stopped")

    fastapi_app = FastAPI(
        title="dungeons-dragons-agent Orchestrator",
        version="1.0.0",
        description="Routes queries to CrewAI sub-agents via A2A protocol.",
        lifespan=lifespan,
    )

    cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
    fastapi_app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in cors_origins if o.strip()],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @fastapi_app.get("/health")
    async def health():
        return JSONResponse({"status": "healthy", "service": "dungeons-dragons-agent"})

    @fastapi_app.get("/info")
    async def service_info():
        from orchestrator.prompts import ROUTING_KEYWORDS
        from shared.config import SUB_AGENT_URL
        return {
            "service": PROJECT_NAME,
            "role": "orchestrator",
            "copilotkit": True,
            "sub_agents": [
                {
                    "name": "character-creation-agent",
                    "url": SUB_AGENT_URL,
                    "keywords": ROUTING_KEYWORDS,
                }
            ],
        }



    # --- Query endpoint ---

    @fastapi_app.post("/invoke", response_model=InvokeResponse)
    def invoke(request: InvokeRequest):
        logger.info(f"Received query: {request.query[:100]}")
        try:
            from orchestrator.flow import OrchestratorFlow


            context_id = request.context_id or str(uuid.uuid4())
            query_text = request.query
            if request.context_id:
                try:
                    mgr: SessionManager = fastapi_app.state.session_manager
                    context = mgr.build_conversation_context(context_id)
                    if context:
                        query_text = context + request.query
                except Exception as e:
                    logger.warning(f"Failed to load session context: {e}")



            flow = OrchestratorFlow()
            flow.state.query = query_text
            result = flow.kickoff()
            result_text = str(result)



            if request.context_id:
                try:
                    mgr: SessionManager = fastapi_app.state.session_manager
                    mgr.append_messages(
                        session_id=context_id,
                        user_msg=request.query,
                        assistant_msg=result_text,
                    )
                except Exception as e:
                    logger.warning(f"Failed to persist session {context_id}: {e}")

            return InvokeResponse(result=result_text, route=flow.state.route, context_id=context_id)


        except Exception as e:
            logger.error(f"Error processing query: {e}")
            raise HTTPException(status_code=500, detail=str(e))



    # --- CopilotKit AG-UI endpoint ---
    if _HAS_AG_UI:
        @fastapi_app.post("/copilotkit")
        async def copilotkit(request: Request):
            return await copilotkit_handler(request)



    # --- Session endpoints ---

    @fastapi_app.post("/sessions/{session_id}", status_code=201)
    async def init_session(session_id: str):
        mgr: SessionManager = fastapi_app.state.session_manager
        session = mgr.get_or_create_session(session_id)
        return JSONResponse(session.to_summary(), status_code=201)

    @fastapi_app.get("/sessions")
    async def list_sessions():
        mgr: SessionManager = fastapi_app.state.session_manager
        return JSONResponse(mgr.list_sessions())

    @fastapi_app.get("/sessions/{session_id}")
    async def get_session(session_id: str):
        mgr: SessionManager = fastapi_app.state.session_manager
        session = mgr.get_session(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        return JSONResponse(session.to_dict())

    @fastapi_app.delete("/sessions/{session_id}", status_code=204)
    async def delete_session(session_id: str):
        mgr: SessionManager = fastapi_app.state.session_manager
        if not mgr.delete_session(session_id):
            raise HTTPException(status_code=404, detail="Session not found")



    # --- A2A server ---
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

