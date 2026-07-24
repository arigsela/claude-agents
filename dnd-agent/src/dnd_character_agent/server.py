# ==============================================================================
# Sub-Agent — FastAPI Server with A2A Protocol Support
# ==============================================================================
#
# WHAT THIS FILE DOES:
# Creates a FastAPI server that:
# 1. Serves the A2A agent card at /.well-known/agent.json (discovery)
# 2. Handles A2A JSON-RPC requests at /a2a (the main protocol endpoint)
# 3. Provides a /health endpoint for K8s probes
# 4. Enforces API key authentication on all endpoints except health and discovery
#
# A2A AGENT CARD:
# The /.well-known/agent.json endpoint is the A2A discovery standard.
# Other agents (like the orchestrator) fetch this URL to learn:
# - What the agent can do (name, description, skills)
# - Where to send requests (URL)
# - What authentication is required
#
# RUNNING THIS SERVICE:
#   uvicorn dnd_character_agent.server:app --host 0.0.0.0 --port 8080
# ==============================================================================

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import os

from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCard, AgentSkill, AgentCapabilities

from shared.config import PROJECT_NAME, SUB_AGENT_PORT, API_KEYS
from shared.logging_config import setup_logging

logger = setup_logging("dnd_character_agent.server")


# --- A2A AGENT CARD ---
# This describes the agent to other agents and discovery systems.
# The orchestrator fetches this to know how to communicate with us.
AGENT_CARD = AgentCard(
    name="Dungeons and Dragons Character creation/knowledge specialist",
    description="Answer questions about Dungeons And Dragons related to character creation/changes/story",
    url=os.getenv("AGENT_URL", f"http://localhost:{SUB_AGENT_PORT}"),
    version="1.0.0",
    default_input_modes=["text"],
    default_output_modes=["text"],
    capabilities=AgentCapabilities(streaming=False),
    skills=[
        AgentSkill(
            id="query",
            name="Query Processing",
            description="Process domain-specific queries using tools and knowledge.",
            tags=["query", "knowledge"],
        ),
    ],
)


def create_app() -> FastAPI:
    """Create the FastAPI application with A2A endpoints mounted."""

    application = FastAPI(
        title=f"{PROJECT_NAME} - Dungeons and Dragons Character creation/knowledge specialist",
        version="1.0.0",
    )

    # --- API KEY AUTHENTICATION MIDDLEWARE ---
    # This runs BEFORE every request. It checks for a valid API key
    # in the X-API-Key header. Health and discovery endpoints are exempt.
    @application.middleware("http")
    async def auth_middleware(request: Request, call_next):
        # Allow health checks and A2A discovery without auth
        # (K8s probes and agent discovery need unauthenticated access)
        public_paths = ["/health", "/.well-known/"]
        if any(request.url.path.startswith(p) for p in public_paths):
            return await call_next(request)

        # If no API keys configured, allow all (dev mode)
        if not API_KEYS:
            return await call_next(request)

        # Check both Authorization: Bearer and X-API-Key headers
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
        else:
            token = request.headers.get("X-API-Key", "")

        if token not in API_KEYS:
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or missing API key"},
            )

        return await call_next(request)

    # --- HEALTH ENDPOINT ---
    @application.get("/health")
    async def health():
        return {"status": "healthy", "service": "dnd_character_agent"}

    # --- MOUNT A2A APPLICATION ---
    # The A2A SDK provides a Starlette sub-application that handles:
    # - /.well-known/agent.json (agent card / discovery)
    # - POST / (JSON-RPC 2.0 message handling)
    from dnd_character_agent.executor import SubAgentExecutor

    task_store = InMemoryTaskStore()
    handler = DefaultRequestHandler(
        agent_executor=SubAgentExecutor(),
        task_store=task_store,
    )

    a2a_app = A2AStarletteApplication(
        agent_card=AGENT_CARD,
        http_handler=handler,
    )

    # Mount the A2A app — this adds the protocol endpoints
    application.mount("/", a2a_app.build())

    logger.info(f"Sub-agent server ready: {AGENT_CARD.url}")
    return application


app = create_app()

