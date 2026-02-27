"""K8s Diagnostics CrewAI Agent and Crew definition.

Wraps the 7 K8s tools in a CrewAI Agent with a Crew for execution.
Includes structured output, guardrails, observability, and planning.
"""

import time

from crewai import Agent, Crew, Process, Task
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
from shared.config import ANTHROPIC_MODEL, CREWAI_VERBOSE
from shared.logging_config import setup_logging
from shared.models import K8sDiagnosisOutput, validate_k8s_diagnosis
from shared.observability import (
    agent_step_callback,
    log_token_usage,
    task_completion_callback,
    timed_invoke,
)

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
        verbose=CREWAI_VERBOSE,
        cache=False,  # Always fetch fresh cluster data
        max_execution_time=300,  # 5 min hard stop
        max_rpm=30,
        max_iter=25,
        reasoning=True,
        max_reasoning_attempts=2,
        respect_context_window=True,
        step_callback=agent_step_callback,
        fingerprint="k8s-diagnostics-agent-v1",
    )


@timed_invoke
def invoke(query: str, context_id: str = "") -> str:
    """Invoke the K8s agent with a query and return the result.

    Args:
        query: The investigation query or question.
        context_id: Optional context/session identifier.

    Returns:
        The agent's response as a string.
    """
    logger.info(f"K8s agent invoked: context_id={context_id}, query={query[:100]}...")

    # Before kickoff: validate input
    if not query or not query.strip():
        raise ValueError("Query cannot be empty")
    query = query.strip()

    agent = create_k8s_agent()

    task = Task(
        description=K8S_TASK_DESCRIPTION.format(query=query),
        expected_output=K8S_TASK_EXPECTED_OUTPUT,
        agent=agent,
        output_pydantic=K8sDiagnosisOutput,
        guardrail=validate_k8s_diagnosis,
        guardrail_max_retries=2,
    )

    crew = Crew(
        agents=[agent],
        tasks=[task],
        process=Process.sequential,
        verbose=CREWAI_VERBOSE,
        cache=False,
        output_log_file="/tmp/crewai-logs.txt",
        task_callback=task_completion_callback,
    )

    result = crew.kickoff()

    # After kickoff: log metrics
    log_token_usage(result, agent_name="k8s-diagnostics")
    logger.info(f"K8s agent completed: context_id={context_id}")

    # Return structured output if available, otherwise raw
    if hasattr(result, "pydantic") and result.pydantic:
        return result.pydantic.model_dump_json()
    return result.raw if hasattr(result, "raw") else str(result)
