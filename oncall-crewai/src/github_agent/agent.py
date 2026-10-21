"""GitHub/GitOps CrewAI Agent and Crew definition.

Wraps the 5 GitHub tools in a CrewAI Agent with a Crew for execution.
Includes guardrails, observability, and structured logging.
"""

import time

from crewai import Agent, Crew, Process, Task
from crewai.llm import LLM

from github_agent.prompts import (
    GITHUB_AGENT_BACKSTORY,
    GITHUB_AGENT_GOAL,
    GITHUB_AGENT_ROLE,
    GITHUB_TASK_DESCRIPTION,
    GITHUB_TASK_EXPECTED_OUTPUT,
)
from github_agent.tools import (
    create_document_pr,
    create_remediation_pr,
    get_gitops_file,
    list_gitops_directory,
    search_recent_deployments,
)
from shared.config import ANTHROPIC_MODEL, CREWAI_VERBOSE
from shared.logging_config import setup_logging
from shared.models import validate_gitops_output
from shared.observability import (
    agent_step_callback,
    log_token_usage,
    task_completion_callback,
    timed_invoke,
)

logger = setup_logging("github-agent")

GITHUB_TOOLS = [
    search_recent_deployments,
    get_gitops_file,
    list_gitops_directory,
    create_remediation_pr,
    create_document_pr,
]


def create_github_agent() -> Agent:
    """Create the GitHub/GitOps CrewAI agent."""
    return Agent(
        role=GITHUB_AGENT_ROLE,
        goal=GITHUB_AGENT_GOAL,
        backstory=GITHUB_AGENT_BACKSTORY,
        tools=GITHUB_TOOLS,
        llm=LLM(model=ANTHROPIC_MODEL),
        verbose=CREWAI_VERBOSE,
        cache=True,  # GitHub data changes less frequently
        max_execution_time=300,  # 5 min hard stop
        max_rpm=30,
        max_iter=20,
        respect_context_window=True,
        step_callback=agent_step_callback,
        fingerprint="gitops-remediation-agent-v1",
    )


@timed_invoke
def invoke(query: str, context_id: str = "") -> str:
    """Invoke the GitHub agent with a query and return the result.

    Args:
        query: The GitOps request or question.
        context_id: Optional context/session identifier.

    Returns:
        The agent's response as a string.
    """
    logger.info(f"GitHub agent invoked: context_id={context_id}, query={query[:100]}...")

    # Before kickoff: validate input
    if not query or not query.strip():
        raise ValueError("Query cannot be empty")
    query = query.strip()

    agent = create_github_agent()

    task = Task(
        description=GITHUB_TASK_DESCRIPTION.format(query=query),
        expected_output=GITHUB_TASK_EXPECTED_OUTPUT,
        agent=agent,
        guardrail=validate_gitops_output,
        guardrail_max_retries=2,
    )

    crew = Crew(
        agents=[agent],
        tasks=[task],
        process=Process.sequential,
        verbose=CREWAI_VERBOSE,
        output_log_file=True,
        task_callback=task_completion_callback,
    )

    result = crew.kickoff()

    # After kickoff: log metrics
    log_token_usage(result, agent_name="gitops-remediation")
    logger.info(f"GitHub agent completed: context_id={context_id}")

    return result.raw if hasattr(result, "raw") else str(result)
