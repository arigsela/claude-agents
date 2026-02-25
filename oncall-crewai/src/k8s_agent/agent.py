"""K8s Diagnostics CrewAI Agent and Crew definition.

Wraps the 7 K8s tools in a CrewAI Agent with a Crew for execution.
"""

from crewai import Agent, Crew, Task
from crewai.llm import LLM

from k8s_agent.prompts import (
    K8S_AGENT_BACKSTORY,
    K8S_AGENT_GOAL,
    K8S_AGENT_ROLE,
    K8S_TASK_DESCRIPTION,
    K8S_TASK_EXPECTED_OUTPUT,
)
from k8s_agent.tools import (
    analyze_service_health,
    get_deployment_status,
    get_pod_events,
    get_pod_logs,
    list_namespaces,
    list_pods,
    list_services,
)
from shared.config import ANTHROPIC_MODEL
from shared.logging_config import setup_logging

logger = setup_logging("k8s-agent")

K8S_TOOLS = [
    list_namespaces,
    list_pods,
    get_pod_logs,
    get_pod_events,
    get_deployment_status,
    list_services,
    analyze_service_health,
]


def create_k8s_agent() -> Agent:
    """Create the K8s diagnostics CrewAI agent."""
    return Agent(
        role=K8S_AGENT_ROLE,
        goal=K8S_AGENT_GOAL,
        backstory=K8S_AGENT_BACKSTORY,
        tools=K8S_TOOLS,
        llm=LLM(model=ANTHROPIC_MODEL),
        verbose=True,
    )


def invoke(query: str, context_id: str = "") -> str:
    """Invoke the K8s agent with a query and return the result.

    Args:
        query: The investigation query or question.
        context_id: Optional context/session identifier.

    Returns:
        The agent's response as a string.
    """
    logger.info(f"K8s agent invoked: context_id={context_id}, query={query[:100]}...")

    agent = create_k8s_agent()

    task = Task(
        description=K8S_TASK_DESCRIPTION.format(query=query),
        expected_output=K8S_TASK_EXPECTED_OUTPUT,
        agent=agent,
    )

    crew = Crew(
        agents=[agent],
        tasks=[task],
        verbose=True,
    )

    result = crew.kickoff()
    logger.info(f"K8s agent completed: context_id={context_id}")
    return str(result)
