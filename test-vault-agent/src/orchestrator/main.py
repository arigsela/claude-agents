# ==============================================================================
# Orchestrator — FastAPI Application
# ==============================================================================
#
# WHAT THIS FILE DOES:
# This is the main entry point for the orchestrator service. It creates a
# FastAPI web server with three key endpoints:
#
# 1. GET  /health   — Health check (used by K8s liveness/readiness probes)
# 2. POST /invoke   — Send a query to be routed to the appropriate sub-agent
# 3. GET  /info     — Returns metadata about the orchestrator and its agents
#
# HOW REQUESTS FLOW:
#   Client → POST /invoke {"query": "..."} → OrchestratorFlow.kickoff()
#   → keyword classification → A2A call to sub-agent → response back to client
#
# RUNNING THIS SERVICE:
#   uvicorn orchestrator.main:app --host 0.0.0.0 --port 8000
# ==============================================================================

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os

from shared.config import PROJECT_NAME, ORCHESTRATOR_PORT, API_KEYS
from shared.logging_config import setup_logging

logger = setup_logging("orchestrator")


# --- REQUEST/RESPONSE MODELS ---
# Pydantic models define the shape of API requests and responses.
# FastAPI auto-generates OpenAPI docs from these (visit /docs in the browser).

class InvokeRequest(BaseModel):
    """Request body for the /invoke endpoint."""
    query: str  # The user's question or command


class InvokeResponse(BaseModel):
    """Response body from the /invoke endpoint."""
    result: str  # The agent's response text
    route: str   # Which sub-agent handled the query (for debugging)


# --- APPLICATION FACTORY ---
# Using a function to create the app allows for easier testing
# (you can create a fresh app instance for each test).

def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    application = FastAPI(
        title=f"{PROJECT_NAME} Orchestrator",
        description="Routes queries to CrewAI sub-agents via A2A protocol.",
        version="1.0.0",
    )

    # CORS (Cross-Origin Resource Sharing) middleware.
    # This is required if a browser-based frontend calls this API.
    # In production, restrict origins to your actual frontend domain.
    cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
    application.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    return application


app = create_app()


# --- ENDPOINTS ---

@app.get("/health")
async def health_check():
    """
    Health check endpoint.

    Kubernetes uses this for:
    - livenessProbe: "Is the process alive?" (restarts pod if this fails)
    - readinessProbe: "Is the service ready for traffic?" (removes from Service endpoints if this fails)

    Returns a simple JSON object with service status.
    """
    return {"status": "healthy", "service": PROJECT_NAME}


@app.get("/info")
async def service_info():
    """
    Returns metadata about the orchestrator and its configured agents.
    Useful for debugging and service discovery.
    """
    from orchestrator.prompts import ROUTING_KEYWORDS
    from shared.config import SUB_AGENT_URL

    return {
        "service": PROJECT_NAME,
        "role": "orchestrator",
        "sub_agents": [
            {
                "name": "test-agent",
                "url": SUB_AGENT_URL,
                "keywords": ROUTING_KEYWORDS,
            }
        ],
    }


@app.post("/invoke", response_model=InvokeResponse)
async def invoke(request: InvokeRequest):
    """
    Main query endpoint.

    Receives a user query, runs it through the OrchestratorFlow (which
    classifies the query and routes it to the appropriate sub-agent via A2A),
    and returns the result.

    The flow is synchronous but wrapped in async for FastAPI compatibility.
    """
    logger.info(f"Received query: {request.query[:100]}")

    try:
        # Import here to avoid circular imports and allow lazy loading
        from orchestrator.flow import OrchestratorFlow

        # Create a new flow instance and execute it.
        # CrewAI Flows maintain state across steps (classify → route → handle).
        flow = OrchestratorFlow()
        result = flow.kickoff(inputs={"query": request.query})

        # The flow's final state contains the result and which route was taken
        return InvokeResponse(
            result=str(result),
            route=flow.state.route,
        )
    except Exception as e:
        logger.error(f"Error processing query: {e}")
        raise HTTPException(status_code=500, detail=str(e))

