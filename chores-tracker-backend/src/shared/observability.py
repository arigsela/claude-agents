# ==============================================================================
# Observability — Agent Execution Monitoring
# ==============================================================================
#
# WHY OBSERVABILITY?
# AI agents are non-deterministic — the same input can produce different outputs.
# Without observability, debugging production issues is nearly impossible.
# These callbacks hook into CrewAI's execution lifecycle to log:
# - Each reasoning step the agent takes
# - Task completion with output length
# - Execution timing (how long each invocation takes)
# - Token usage (cost tracking)
#
# HOW CREWAI CALLBACKS WORK:
# CrewAI's Crew class accepts `step_callback` and `task_callback` functions.
# - step_callback: Called after EACH agent reasoning step (tool call, thought, etc.)
# - task_callback: Called when a task completes with its final output
#
# These are set on the Crew, not individual agents:
#   Crew(agents=[...], tasks=[...], step_callback=agent_step_callback, task_callback=task_completion_callback)
# ==============================================================================

import time
import functools
from shared.logging_config import setup_logging

logger = setup_logging("observability")


def agent_step_callback(step_output) -> None:
    """
    Called after each agent reasoning step.

    Logs the first 200 characters of each step to track the agent's
    thought process without flooding the logs with full outputs.

    Args:
        step_output: CrewAI's step output object (varies by step type).
    """
    output_text = str(step_output)[:200]
    logger.info(f"Agent step: {output_text}")


def task_completion_callback(task_output) -> None:
    """
    Called when a CrewAI task completes.

    Logs the task description and output length. Useful for identifying
    tasks that produce unexpectedly short or long outputs.

    Args:
        task_output: CrewAI's TaskOutput object with .description and .raw.
    """
    description = getattr(task_output, "description", "unknown")[:100]
    raw_output = getattr(task_output, "raw", "")
    logger.info(
        f"Task completed: {description} | Output length: {len(raw_output)} chars"
    )


def timed_invoke(func):
    """
    Decorator that logs execution time for agent invocations.

    Wrap your agent's invoke() function with this to automatically track
    how long each query takes. Useful for identifying slow queries and
    setting appropriate timeouts.

    Usage:
        @timed_invoke
        def invoke(query: str) -> str:
            ...
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        start = time.time()
        try:
            result = func(*args, **kwargs)
            elapsed = time.time() - start
            logger.info(f"{func.__name__} completed in {elapsed:.2f}s")
            return result
        except Exception as e:
            elapsed = time.time() - start
            logger.error(f"{func.__name__} FAILED after {elapsed:.2f}s: {e}")
            raise
    return wrapper


def log_token_usage(crew_output) -> None:
    """
    Extract and log token usage from a CrewAI execution result.

    Token usage helps track costs (each LLM call costs money) and identify
    agents that use excessive tokens (indicating prompt issues or loops).

    Args:
        crew_output: The CrewOutput returned by crew.kickoff().
    """
    usage = getattr(crew_output, "token_usage", None)
    if usage:
        logger.info(
            f"Token usage — total: {usage.get('total_tokens', 'N/A')}, "
            f"prompt: {usage.get('prompt_tokens', 'N/A')}, "
            f"completion: {usage.get('completion_tokens', 'N/A')}"
        )

