# ==============================================================================
# Sub-Agent — CrewAI Agent Creation & Invocation
# ==============================================================================
#
# WHAT THIS FILE DOES:
# Creates the CrewAI agent with its tools, knowledge sources, and configuration,
# then provides an invoke() function that runs the agent on a query.
#
# HOW CREWAI AGENTS WORK:
# 1. You define an Agent with role, goal, backstory, tools, and optional knowledge
# 2. You define a Task (what the agent should do) and assign it to the agent
# 3. You create a Crew (a group of agents + tasks) and call crew.kickoff()
# 4. CrewAI orchestrates the execution: the agent reasons, calls tools, and produces output
#
# AGENT CONFIGURATION EXPLAINED:
# - cache=False: Don't cache tool results (we want fresh data every time)
# - reasoning=True: Enable chain-of-thought reasoning (better quality, more tokens)
# - max_execution_time=300: Kill the agent after 5 minutes (prevents runaway loops)
# - max_rpm=30: Rate limit to 30 LLM requests per minute (prevents cost explosions)
# - max_iter=25: Max tool-call iterations before forced completion
# - verbose=True: Log detailed execution info (disable in production for cleaner logs)
# ==============================================================================

from crewai import Agent, Crew, Task, Process, LLM

from shared.config import ANTHROPIC_MODEL
from shared.models import AgentOutput, validate_agent_output
from shared.observability import (
    agent_step_callback,
    task_completion_callback,
    timed_invoke,
    log_token_usage,
)
from shared.logging_config import setup_logging


# Import the agent's tools — each @tool-decorated function becomes available
from dnd_character_agent.tools import search_knowledge, get_system_info, check_health
from dnd_character_agent.prompts import (
    AGENT_ROLE,
    AGENT_GOAL,
    AGENT_BACKSTORY,
    TASK_DESCRIPTION_TEMPLATE,
)

logger = setup_logging("dnd_character_agent.agent")


def create_agent() -> Agent:
    """
    Create and configure the CrewAI agent with tools and knowledge.

    Returns:
        A fully configured CrewAI Agent ready to process queries.
    """
    # List of tools the agent can use during execution.
    # The agent decides which tools to call based on the query and tool descriptions.
    tools = [search_knowledge, get_system_info, check_health]



    agent = Agent(
        role=AGENT_ROLE,
        goal=AGENT_GOAL,
        backstory=AGENT_BACKSTORY,
        tools=tools,
        llm=LLM(model=ANTHROPIC_MODEL),

        # --- BEHAVIORAL SETTINGS ---
        cache=False,                # Always fetch fresh data (no stale results)
        verbose=True,               # Detailed logging (set False in production)
        # NOTE: reasoning=True requires an OpenAI API key even when using
        # Anthropic as the main LLM. Enable only if OPENAI_API_KEY is set.
        # reasoning=True,

        # --- SAFETY LIMITS ---
        max_execution_time=300,     # 5-minute timeout per invocation
        max_rpm=30,                 # Max 30 LLM calls per minute (cost control)
        max_iter=25,                # Max 25 tool-call iterations


        # --- STRUCTURED OUTPUT ---
        # Uncomment these to enable structured Pydantic output with guardrails.
        # This forces the agent to return a JSON object matching AgentOutput schema.
        # The guardrail function validates quality and retries if needed.
        # output_pydantic=AgentOutput,
        # guardrail=validate_agent_output,
    )

    return agent


@timed_invoke
def invoke(query: str) -> str:
    """
    Run the agent on a query and return the result.

    This is the main entry point called by the A2A executor when the
    orchestrator delegates a query to this sub-agent.

    Args:
        query: The user's question or command.

    Returns:
        The agent's response as a string.
    """
    logger.info(f"Invoking agent with query: {query[:100]}")

    # Create a fresh agent for each invocation
    agent = create_agent()

    # Create the task — what the agent should do
    task = Task(
        description=TASK_DESCRIPTION_TEMPLATE.format(query=query),
        expected_output="A thorough, accurate response with specific details and recommendations.",
        agent=agent,
    )

    # Create a Crew (even for a single agent, CrewAI requires a Crew wrapper)
    crew = Crew(
        agents=[agent],
        tasks=[task],
        process=Process.sequential,   # Tasks run in order (only one here)
        verbose=True,
        # NOTE: planning=True requires an OpenAI API key even when using
        # Anthropic as the main LLM. Enable only if OPENAI_API_KEY is set.
        # planning=True,
        # Observability callbacks
        step_callback=agent_step_callback,
        task_callback=task_completion_callback,
    )

    # Execute the crew and get the result
    result = crew.kickoff()

    # Log token usage for cost tracking
    log_token_usage(result)

    return str(result)

