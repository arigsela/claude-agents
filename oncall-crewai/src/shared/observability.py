"""CrewAI observability hooks for oncall-crewai.

Provides step_callback, task_callback, timing decorators, and
token usage extraction. Uses stable CrewAI callback APIs.
"""

from __future__ import annotations

import time
from functools import wraps
from typing import Any

from shared.logging_config import setup_logging

logger = setup_logging("crewai-observability")


def agent_step_callback(step_output: Any) -> None:
    """Callback invoked after each agent reasoning step.

    Pass this as ``step_callback=`` to Agent().
    """
    text = str(step_output)[:200]
    logger.info(f"[AGENT STEP] {text}")


def task_completion_callback(task_output: Any) -> None:
    """Callback invoked after each task completes.

    Pass this as ``task_callback=`` to Crew().
    """
    description = getattr(task_output, "description", "")[:80]
    raw_len = len(getattr(task_output, "raw", "") or "")
    logger.info(f"[TASK COMPLETE] description={description}... output_len={raw_len}")


def log_token_usage(result: Any, agent_name: str = "") -> None:
    """Extract and log token usage from a CrewOutput object."""
    token_usage = getattr(result, "token_usage", None)
    if token_usage:
        total = getattr(token_usage, "total_tokens", "N/A")
        prompt = getattr(token_usage, "prompt_tokens", "N/A")
        completion = getattr(token_usage, "completion_tokens", "N/A")
        logger.info(
            f"[TOKENS] agent={agent_name} "
            f"total={total} prompt={prompt} completion={completion}"
        )
    else:
        logger.debug(f"[TOKENS] agent={agent_name} token_usage not available")


def timed_invoke(func):
    """Decorator that logs execution time of invoke() calls."""

    @wraps(func)
    def wrapper(*args, **kwargs):
        start = time.monotonic()
        try:
            result = func(*args, **kwargs)
            elapsed = time.monotonic() - start
            logger.info(
                f"[TIMING] {func.__module__}.{func.__name__} "
                f"elapsed={elapsed:.2f}s"
            )
            return result
        except Exception:
            elapsed = time.monotonic() - start
            logger.error(
                f"[TIMING] {func.__module__}.{func.__name__} "
                f"FAILED elapsed={elapsed:.2f}s"
            )
            raise

    return wrapper
