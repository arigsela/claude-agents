# ==============================================================================
# A2A Delegate Agent Factory
# ==============================================================================
#
# WHAT IS A "DELEGATE AGENT"?
# The orchestrator doesn't do work itself — it delegates to sub-agents.
# A delegate agent is a thin CrewAI Agent configured with an A2AConfig that
# tells it to forward all work to a remote sub-agent via the A2A protocol.
#
# HOW A2A (AGENT-TO-AGENT) WORKS:
# 1. The orchestrator creates a CrewAI Agent with an A2AConfig pointing to the sub-agent's URL
# 2. When the agent is asked to do work, CrewAI sends a JSON-RPC 2.0 "message/send"
#    request to the sub-agent's A2A endpoint
# 3. The sub-agent processes the request, runs its CrewAI agent locally, and returns the result
# 4. The orchestrator receives the response and includes it in the flow's final output
#
# WHY A2A INSTEAD OF DIRECT FUNCTION CALLS?
# - Each agent is independently deployable (separate container, separate scaling)
# - Agents can be written in different languages (A2A is protocol-level, not code-level)
# - Agents are discoverable via /.well-known/agent.json (standard endpoint)
# - Failure isolation — if a sub-agent crashes, the orchestrator stays up
# ==============================================================================

from crewai import Agent, LLM
from crewai.agent import A2AConfig, APIKeyAuth

from shared.config import ANTHROPIC_MODEL, SUB_AGENT_URL, API_KEYS
from shared.logging_config import setup_logging

logger = setup_logging("orchestrator.agents")


def create_sub_agent_delegate() -> Agent:
    """
    Create a delegate agent that forwards queries to the sub-agent via A2A.

    This agent has NO local tools — all work is done by the remote sub-agent.
    The A2AConfig tells CrewAI where to send the request and how to authenticate.

    Returns:
        A CrewAI Agent configured as an A2A delegate.
    """
    # Build the A2A agent card URL from the sub-agent's base URL.
    # The /.well-known/agent-card.json endpoint is the A2A discovery standard.
    agent_card_url = f"{SUB_AGENT_URL}/.well-known/agent-card.json"

    # Get the first API key for authentication (empty list = no auth in dev)
    api_key = API_KEYS[0] if API_KEYS else ""

    logger.info(f"Creating A2A delegate for sub-agent at {agent_card_url}")

    return Agent(
        role="Chores Tracker Backend Specialist Coordinator",
        goal="Delegate queries to the Chores Tracker Backend Specialist sub-agent and return results.",
        backstory=(
            "You are a coordinator that routes queries to a specialized sub-agent. "
            "Forward the user's query exactly as received — do not modify or interpret it. "
            "Return the sub-agent's response exactly as received."
        ),
        # A2AConfig tells CrewAI to use the A2A protocol instead of local execution
        a2a=A2AConfig(
            endpoint=agent_card_url,
            auth=APIKeyAuth(
                api_key=api_key,
                location="header",     # Send API key in HTTP header
                name="X-API-Key",      # Header name
            ),
            timeout=120,               # Seconds to wait for sub-agent response
            max_turns=10,              # Max back-and-forth exchanges
            trust_remote_completion_status=True,  # Accept sub-agent's "done" signal
        ),
        llm=LLM(model=ANTHROPIC_MODEL),
        verbose=True,
    )

