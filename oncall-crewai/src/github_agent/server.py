"""GitHub A2A Agent Server.

Standalone A2A-compliant server for the GitHub/GitOps agent.
Serves /.well-known/agent.json for agent discovery and handles
JSON-RPC message/send requests via the a2a-sdk.

Entry point: uvicorn github_agent.server:app --host 0.0.0.0 --port 8080
"""

import os

from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentSkill
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from github_agent.executor import GitHubAgentExecutor
from shared.config import API_KEYS
from shared.logging_config import setup_logging

logger = setup_logging("github-server")


def _build_agent_card() -> AgentCard:
    """Build the A2A AgentCard for discovery."""
    host = os.getenv("GITHUB_AGENT_HOST", "0.0.0.0")
    port = int(os.getenv("GITHUB_AGENT_PORT", "8080"))
    url = os.getenv("GITHUB_AGENT_URL", f"http://{host}:{port}")

    return AgentCard(
        name="GitOps Remediation Agent",
        description=(
            "GitOps specialist that inspects Kubernetes manifests in the "
            "arigsela/kubernetes repo, checks recent deployments, and "
            "creates remediation PRs via the GitOps workflow."
        ),
        url=url,
        version="0.1.0",
        default_input_modes=["text"],
        default_output_modes=["text"],
        capabilities=AgentCapabilities(streaming=False),
        skills=[
            AgentSkill(
                id="inspect-manifests",
                name="Inspect K8s Manifests",
                description=(
                    "Read and list Kubernetes manifest files from the "
                    "GitOps repository under base-apps/."
                ),
                tags=["github", "gitops", "manifests"],
            ),
            AgentSkill(
                id="create-remediation-pr",
                name="Create Remediation PR",
                description=(
                    "Create a pull request with patch-based changes to "
                    "Kubernetes manifests for incident remediation."
                ),
                tags=["github", "gitops", "pr", "remediation"],
            ),
            AgentSkill(
                id="check-deployments",
                name="Check Recent Deployments",
                description=(
                    "Search for recent GitHub Actions workflow runs to "
                    "correlate with Kubernetes incidents."
                ),
                tags=["github", "deployments", "actions"],
            ),
        ],
    )


def create_app() -> FastAPI:
    """Create the FastAPI application with A2A server mounted."""
    fastapi_app = FastAPI(
        title="GitHub GitOps A2A Agent",
        version="0.1.0",
    )

    # Auth middleware — enforce API key on all routes except health/discovery
    @fastapi_app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        if request.url.path == "/health" or request.url.path.startswith("/.well-known/"):
            return await call_next(request)
        if API_KEYS:
            auth_header = request.headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                token = auth_header[7:]
            else:
                token = request.headers.get("X-API-Key", "")
            if token not in API_KEYS:
                return JSONResponse(
                    {"detail": "Invalid API key"}, status_code=401
                )
        return await call_next(request)

    @fastapi_app.get("/health")
    async def health():
        return JSONResponse({"status": "healthy", "agent": "github-gitops"})

    agent_card = _build_agent_card()
    executor = GitHubAgentExecutor()
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

    logger.info(f"GitHub A2A agent server ready: {agent_card.url}")
    return fastapi_app


app = create_app()
