"""K8s A2A Agent Server.

Standalone A2A-compliant server for the K8s Diagnostics agent.
Serves /.well-known/agent.json for agent discovery and handles
JSON-RPC message/send requests via the a2a-sdk.

Entry point: uvicorn k8s_agent.server:app --host 0.0.0.0 --port 8080
"""

import os

from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCard, AgentCapabilities, AgentSkill
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from k8s_agent.executor import K8sAgentExecutor
from shared.logging_config import setup_logging

logger = setup_logging("k8s-server")


def _build_agent_card() -> AgentCard:
    """Build the A2A AgentCard for discovery."""
    host = os.getenv("K8S_AGENT_HOST", "0.0.0.0")
    port = int(os.getenv("K8S_AGENT_PORT", "8080"))
    url = os.getenv("K8S_AGENT_URL", f"http://{host}:{port}")

    return AgentCard(
        name="K8s Diagnostics Agent",
        description=(
            "Kubernetes SRE specialist that diagnoses pod, deployment, "
            "and service health issues in a K3s homelab cluster."
        ),
        url=url,
        version="0.1.0",
        default_input_modes=["text"],
        default_output_modes=["text"],
        capabilities=AgentCapabilities(streaming=False),
        skills=[
            AgentSkill(
                id="diagnose-pods",
                name="Diagnose Pod Issues",
                description=(
                    "Investigate pod failures, crash loops, image pull errors, "
                    "and high restart counts."
                ),
                tags=["kubernetes", "pods", "diagnostics"],
            ),
            AgentSkill(
                id="check-deployments",
                name="Check Deployment Status",
                description=(
                    "Verify deployment replica counts, rollout status, "
                    "and availability conditions."
                ),
                tags=["kubernetes", "deployments"],
            ),
            AgentSkill(
                id="analyze-service-health",
                name="Analyze Service Health",
                description=(
                    "Comprehensive health analysis aggregating pod status, "
                    "deployment state, and cluster events."
                ),
                tags=["kubernetes", "health", "analysis"],
            ),
        ],
    )


def create_app() -> FastAPI:
    """Create the FastAPI application with A2A server mounted."""
    fastapi_app = FastAPI(
        title="K8s Diagnostics A2A Agent",
        version="0.1.0",
    )

    @fastapi_app.get("/health")
    async def health():
        return JSONResponse({"status": "healthy", "agent": "k8s-diagnostics"})

    # Build A2A components
    agent_card = _build_agent_card()
    executor = K8sAgentExecutor()
    task_store = InMemoryTaskStore()
    handler = DefaultRequestHandler(
        agent_executor=executor,
        task_store=task_store,
    )

    # Build A2A Starlette app
    a2a_app = A2AStarletteApplication(
        agent_card=agent_card,
        http_handler=handler,
    )

    # Mount A2A app — serves /.well-known/agent.json and POST / (JSON-RPC)
    fastapi_app.mount("/", a2a_app.build())

    logger.info(f"K8s A2A agent server ready: {agent_card.url}")
    return fastapi_app


app = create_app()
