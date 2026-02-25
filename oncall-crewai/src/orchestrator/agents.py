"""Orchestrator delegate agents using CrewAI A2A.

These are thin proxy agents that delegate to remote specialist agents
via the A2A protocol. They carry no local tools — all work is done
by the remote agent.
"""

from crewai import Agent
from crewai.a2a import A2AClientConfig
from crewai.a2a.auth import APIKeyAuth
from crewai.llm import LLM

from shared.config import API_KEYS, ANTHROPIC_MODEL, GITHUB_AGENT_URL, K8S_AGENT_URL
from shared.logging_config import setup_logging

logger = setup_logging("orchestrator-agents")

# CrewAI's A2AClientConfig fetches the agent card from the endpoint URL path.
# When given just "http://host:port", it GETs "/" which returns 405.
# Appending the well-known path tells CrewAI where to find the card.
A2A_CARD_PATH = "/.well-known/agent-card.json"


def _build_a2a_auth() -> APIKeyAuth | None:
    """Build A2A auth from the orchestrator's API_KEYS (shared secret)."""
    if API_KEYS:
        return APIKeyAuth(
            api_key=API_KEYS[0],
            location="header",
            name="X-API-Key",
        )
    return None


def create_k8s_delegate() -> Agent:
    """Create a delegate agent that routes to the K8s A2A agent."""
    endpoint = f"{K8S_AGENT_URL}{A2A_CARD_PATH}"
    logger.info(f"Creating K8s delegate -> {endpoint}")
    return Agent(
        role="K8s Investigation Coordinator",
        goal="Delegate Kubernetes diagnostic tasks to the K8s specialist agent",
        backstory=(
            "You coordinate K8s diagnostic investigations by delegating "
            "to the remote K8s Diagnostics Agent via A2A protocol."
        ),
        a2a=A2AClientConfig(
            endpoint=endpoint,
            auth=_build_a2a_auth(),
            timeout=120,
            max_turns=10,
            trust_remote_completion_status=True,
        ),
        llm=LLM(model=ANTHROPIC_MODEL),
    )


def create_github_delegate() -> Agent:
    """Create a delegate agent that routes to the GitHub A2A agent."""
    endpoint = f"{GITHUB_AGENT_URL}{A2A_CARD_PATH}"
    logger.info(f"Creating GitHub delegate -> {endpoint}")
    return Agent(
        role="GitOps Coordination Specialist",
        goal="Delegate GitOps tasks to the GitHub specialist agent",
        backstory=(
            "You coordinate GitOps operations by delegating to the "
            "remote GitOps Remediation Agent via A2A protocol."
        ),
        a2a=A2AClientConfig(
            endpoint=endpoint,
            auth=_build_a2a_auth(),
            timeout=120,
            max_turns=10,
            trust_remote_completion_status=True,
        ),
        llm=LLM(model=ANTHROPIC_MODEL),
    )
