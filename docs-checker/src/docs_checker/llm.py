"""The one layer that owns model-call retries (lever 5), and the ledger hook.

Retries can hide in three places in this stack: the Anthropic SDK
(``max_retries=2`` by default, also ChatAnthropic's default), LangGraph's
``RetryPolicy`` (whose default ``retry_on`` retries every Anthropic error,
including a 400), and this module. Stacked, 3 x 3 = 9 full-price calls. Here
the SDK is built with ``max_retries=0``, no node sets a ``RetryPolicy``, and
``call_model`` retries only transient failures, recording every attempt in the
ledger so retries show up in cost instead of disappearing inside a client.
"""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any

from docs_checker.ledger import CostLedger

# HTTP statuses worth a second attempt: timeout, conflict, rate limit, 5xx, overloaded.
RETRYABLE_STATUS = frozenset({408, 409, 429, 500, 502, 503, 504, 529})


def is_retryable(error: BaseException) -> bool:
    status = getattr(error, "status_code", None)
    if isinstance(status, int):
        return status in RETRYABLE_STATUS
    # anthropic.APIConnectionError / APITimeoutError carry no status code.
    return type(error).__name__ in {"APIConnectionError", "APITimeoutError"}


@dataclass(frozen=True)
class RetryBudget:
    max_attempts: int = 3
    base_delay: float = 0.5
    max_delay: float = 8.0


DEFAULT_BUDGET = RetryBudget()

Sleep = Callable[[float], Awaitable[None]]


async def call_model(
    model: Any,
    messages: Sequence[Any],
    *,
    node: str,
    model_name: str,
    ledger: CostLedger,
    budget: RetryBudget = DEFAULT_BUDGET,
    sleep: Sleep = asyncio.sleep,
) -> Any:
    """Invoke ``model`` once per attempt; every attempt lands in the ledger."""
    for attempt in range(1, budget.max_attempts + 1):
        started = time.monotonic()
        try:
            message = await model.ainvoke(list(messages))
        except Exception as error:
            elapsed = int((time.monotonic() - started) * 1000)
            ledger.record_error(
                node=node, model=model_name, attempt=attempt, error=error, latency_ms=elapsed
            )
            if attempt == budget.max_attempts or not is_retryable(error):
                raise
            delay = min(budget.max_delay, budget.base_delay * 2 ** (attempt - 1))
            await sleep(delay * (0.5 + random.random() / 2))
            continue
        elapsed = int((time.monotonic() - started) * 1000)
        ledger.record_message(
            node=node, model=model_name, attempt=attempt, message=message, latency_ms=elapsed
        )
        return message
    raise AssertionError("unreachable")
