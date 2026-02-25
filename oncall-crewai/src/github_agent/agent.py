"""GitHub/GitOps CrewAI Agent and Crew definition.

Wraps the 5 GitHub tools in a CrewAI Agent with a Crew for execution.
"""

from crewai import Agent, Crew, Task
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
from shared.config import ANTHROPIC_MODEL
from shared.logging_config import setup_logging

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
        verbose=True,
    )


def invoke(query: str, context_id: str = "") -> str:
    """Invoke the GitHub agent with a query and return the result.

    Args:
        query: The GitOps request or question.
        context_id: Optional context/session identifier.

    Returns:
        The agent's response as a string.
    """
    logger.info(f"GitHub agent invoked: context_id={context_id}, query={query[:100]}...")

    agent = create_github_agent()

    task = Task(
        description=GITHUB_TASK_DESCRIPTION.format(query=query),
        expected_output=GITHUB_TASK_EXPECTED_OUTPUT,
        agent=agent,
    )

    crew = Crew(
        agents=[agent],
        tasks=[task],
        verbose=True,
    )

    result = crew.kickoff()
    logger.info(f"GitHub agent completed: context_id={context_id}")
    return str(result)
