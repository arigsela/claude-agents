"""A2A server on :8080 — the kagent BYO serving contract.

kagent deploys the BYO image and expects the A2A protocol on port 8080:
GET /.well-known/agent.json (discovery) and JSON-RPC POST / (message/send).
Pattern mirrored from oncall-crewai's k8s_agent/server.py.
"""

import logging
import os

import httpx
from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentSkill
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from homelab_agent.config import settings
from homelab_agent.executor import HomelabAgentExecutor

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger(__name__)


def _build_request_handler() -> DefaultRequestHandler:
    """Build the A2A request handler.

    Under kagent (KAGENT_URL present), back it with kagent's DB-persisting
    task store so conversation tasks are recorded in the controller's Postgres
    and the kagent UI can replay past conversations. Without a KAgentTaskStore
    the a2a-sdk only keeps tasks in-process, so the UI shows the session but no
    messages (list-tasks-db count:0). Locally (no KAGENT_URL) — and on any
    wiring failure — fall back to the in-memory store so dev/tests stay
    hermetic. Same configured-or-degrade contract as the checkpointer/store.
    """
    executor = HomelabAgentExecutor()
    if os.getenv("KAGENT_URL"):
        try:
            from kagent.core import KAgentConfig
            from kagent.core.a2a import KAgentRequestContextBuilder, KAgentTaskStore

            config = KAgentConfig()
            client = httpx.AsyncClient(base_url=config.url)
            task_store = KAgentTaskStore(client)
            return DefaultRequestHandler(
                agent_executor=executor,
                task_store=task_store,
                request_context_builder=KAgentRequestContextBuilder(task_store=task_store),
            )
        except Exception as exc:  # partial env, unreachable controller, etc.
            logger.warning(
                "kagent task store unavailable (%s); tasks will not persist to the "
                "kagent UI (using in-memory store)",
                exc,
            )
    return DefaultRequestHandler(
        agent_executor=executor,
        task_store=InMemoryTaskStore(),
    )


def _build_agent_card() -> AgentCard:
    url = os.getenv("AGENT_URL", "http://0.0.0.0:8080")
    # The three skills carried over verbatim from the Declarative agent's
    # a2aConfig — their example prompts are also the parity-harness inputs.
    return AgentCard(
        name="homelab-agent",
        description=(
            "Answers questions about the homelab GitOps repo, base-apps "
            "deployments, and live cluster state (via the k8s-reader delegate)."
        ),
        url=url,
        version="0.1.0",
        default_input_modes=["text"],
        default_output_modes=["text"],
        capabilities=AgentCapabilities(streaming=True),
        skills=[
            AgentSkill(
                id="repo-knowledge",
                name="Repo & Architecture Knowledge",
                description=(
                    "Explain what's deployed, where it lives in the GitOps "
                    "repo, and how components are wired together."
                ),
                examples=[
                    "What is cert-manager and how does it issue certs here?",
                    "Who owns chores-tracker-backend and what does it depend on?",
                    "Where does vault store its config and how is it unsealed?",
                ],
                tags=["gitops", "documentation", "architecture"],
            ),
            AgentSkill(
                id="cluster-troubleshooting",
                name="Cluster State Troubleshooting",
                description=(
                    "Diagnose issues by checking live pod/deployment/event "
                    "state and correlating with the GitOps manifests."
                ),
                examples=[
                    "cert-manager Certificates are stuck pending — walk me through the runbook.",
                    "chores-tracker-backend is CrashLooping — what does its runbook say to check?",
                    "Is the argo-cd control plane healthy?",
                ],
                tags=["troubleshooting", "kubernetes", "argocd"],
            ),
            AgentSkill(
                id="deployment-guidance",
                name="Deployment & Onboarding Guidance",
                description=(
                    "Recommend how to onboard a new app following the "
                    "established base-apps patterns (Crossplane composition, "
                    "SecretStore, ingress, ECR auth)."
                ),
                examples=[
                    "I want to deploy a new service called billing-api. What's the right pattern?",
                    "How do I add Vault secrets for a new namespace?",
                ],
                tags=["onboarding", "crossplane", "idp"],
            ),
        ],
    )


def create_app() -> FastAPI:
    fastapi_app = FastAPI(title="homelab-agent A2A", version="0.1.0")

    @fastapi_app.get("/health")
    async def health():
        return JSONResponse({"status": "healthy", "agent": "homelab-agent"})

    handler = _build_request_handler()
    a2a_app = A2AStarletteApplication(
        agent_card=_build_agent_card(),
        http_handler=handler,
    )
    fastapi_app.mount("/", a2a_app.build())
    logger.info("homelab-agent A2A server ready")
    return fastapi_app


app = create_app()
