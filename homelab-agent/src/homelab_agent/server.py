"""A2A server on :8080 — the kagent BYO serving contract.

kagent deploys the BYO image and expects the A2A protocol on port 8080:
GET /.well-known/agent.json (discovery) and JSON-RPC POST / (message/send).
Pattern mirrored from oncall-crewai's k8s_agent/server.py.
"""

import logging
import os

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
        capabilities=AgentCapabilities(streaming=False),
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

    handler = DefaultRequestHandler(
        agent_executor=HomelabAgentExecutor(),
        task_store=InMemoryTaskStore(),
    )
    a2a_app = A2AStarletteApplication(
        agent_card=_build_agent_card(),
        http_handler=handler,
    )
    fastapi_app.mount("/", a2a_app.build())
    logger.info("homelab-agent A2A server ready")
    return fastapi_app


app = create_app()
