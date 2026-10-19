"""The one layer that owns model-call retries (lever 5), and the ledger hook.

Retries can hide in three places in this stack: the Anthropic SDK
(``max_retries=2`` by default, also ChatAnthropic's default), LangGraph's
``RetryPolicy`` (whose default ``retry_on`` retries every Anthropic error,
including a 400), and this module. Stacked, 3 x 3 = 9 full-price calls. Here
the SDK is built with ``max_retries=0``, no node sets a ``RetryPolicy``, and
``call_model`` retries only transient failures, recording every attempt in the
ledger so retries show up in cost instead of disappearing inside a client.

Every attempt also goes through the run budget and the request-id recorder:

- **Budget (C#1).** Before each attempt ``call_model`` reserves
  ``reservation_for(...)`` on ``ledger.budget``; ``BudgetExceeded`` propagates
  before any call is made. After the attempt it settles to the priced cost, or
  keeps the whole reservation when the cost is unknown (an error, no usage). An
  attempt cancelled in flight stays reserved: whether it was billed is unknown.
- **Structured output (C#2).** ``with_structured_output(..., include_raw=True)``
  returns ``{"raw", "parsed", "parsing_error"}``. Usage is read from ``raw`` and
  the dict is returned unchanged; a parse failure is a result, not a retry.
- **Request ids (C#38).** langchain drops the ``request-id`` response header. Each
  attempt puts a fresh recorder dict in ``RESPONSE_RECORDER``, and
  ``request_id_hook`` (an httpx2 response event hook on the Anthropic client)
  writes into it. The HTTP call may run in a child task (a ``RunnableMap`` does):
  the child copies the context, so it holds the same dict and its write reaches
  this frame. The id is stamped into the message's
  ``response_metadata["request_id"]``, which the ledger reads.
- **Replay.** The eval replay transport marks its responses with the header
  ``x-docs-checker-replayed: 1`` (``REPLAYED_HEADER``). The hook records it and the
  message gets ``response_metadata[REPLAYED_METADATA_KEY] = True``, so the ledger
  counts it as workload cost, not cash.
"""

from __future__ import annotations

import asyncio
import json
import random
import time
from collections.abc import Awaitable, Callable, Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from docs_checker.ledger import REPLAYED_METADATA_KEY, CostLedger, reservation_for

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

# The current attempt's recorder: {"request_id": str | None, "replayed": bool}.
RESPONSE_RECORDER: ContextVar[dict[str, Any] | None] = ContextVar(
    "docs_checker_response_recorder", default=None
)
REPLAYED_HEADER = "x-docs-checker-replayed"
STRUCTURED_KEYS = frozenset({"raw", "parsed", "parsing_error"})


async def request_id_hook(response: Any) -> None:
    """httpx2 response event hook: copy the response's ``request-id`` and replay
    marker into the current attempt's recorder. A no-op outside ``call_model``."""
    recorder = RESPONSE_RECORDER.get()
    if recorder is None:
        return
    recorder["request_id"] = response.headers.get("request-id")
    recorder["replayed"] = response.headers.get(REPLAYED_HEADER) == "1"


def prompt_chars(messages: Sequence[Any]) -> int:
    """Characters in the prompt: text as is, content blocks and tool calls as JSON."""
    total = 0
    for message in messages:
        content = getattr(message, "content", message)
        total += len(content) if isinstance(content, str) else len(json.dumps(content, default=str))
        tool_calls = getattr(message, "tool_calls", None)
        if tool_calls:
            total += len(json.dumps(tool_calls, default=str))
    return total


@contextmanager
def _recording() -> Iterator[dict[str, Any]]:
    """A fresh recorder for one attempt, visible to ``request_id_hook`` until exit."""
    recorder: dict[str, Any] = {}
    token = RESPONSE_RECORDER.set(recorder)
    try:
        yield recorder
    finally:
        RESPONSE_RECORDER.reset(token)


def _raw_message(result: Any) -> Any:
    """The AIMessage to account: ``raw`` of a structured-output dict, else the result."""
    if isinstance(result, dict) and STRUCTURED_KEYS <= result.keys():
        return result["raw"]
    return result


def _stamp(message: Any, recorder: dict[str, Any]) -> None:
    metadata = getattr(message, "response_metadata", None)
    if not isinstance(metadata, dict):
        return
    if recorder.get("request_id"):
        metadata["request_id"] = recorder["request_id"]
    if recorder.get("replayed"):
        metadata[REPLAYED_METADATA_KEY] = True


async def call_model(
    model: Any,
    messages: Sequence[Any],
    *,
    node: str,
    model_name: str,
    ledger: CostLedger,
    budget: RetryBudget = DEFAULT_BUDGET,
    max_tokens: int,
    sleep: Sleep = asyncio.sleep,
) -> Any:
    """Invoke ``model`` once per attempt; every attempt is reserved, ledgered and settled.

    ``max_tokens`` is the output cap the model was built with: it bounds the
    output side of each reservation. Returns what the model returned (a
    structured-output dict unchanged).
    """
    amount = reservation_for(model_name, prompt_chars(messages), max_tokens, ledger.rate_card)
    for attempt in range(1, budget.max_attempts + 1):
        if attempt > 1:  # back off before a retry, holding no reservation
            delay = min(budget.max_delay, budget.base_delay * 2 ** (attempt - 2))
            await sleep(delay * (0.5 + random.random() / 2))
        reservation = await ledger.budget.reserve(amount)  # BudgetExceeded: no call made
        with _recording() as recorder:
            started = time.monotonic()
            try:
                result = await model.ainvoke(list(messages))
            except Exception as error:
                ledger.record_error(
                    node=node,
                    model=model_name,
                    attempt=attempt,
                    error=error,
                    latency_ms=int((time.monotonic() - started) * 1000),
                    request_id=recorder.get("request_id"),
                    replayed=bool(recorder.get("replayed")),
                )
                ledger.budget.settle(reservation, None)  # usage unknown: stays spent
                if attempt == budget.max_attempts or not is_retryable(error):
                    raise
                continue
        raw = _raw_message(result)
        _stamp(raw, recorder)
        entry = ledger.record_message(
            node=node,
            model=model_name,
            attempt=attempt,
            message=raw,
            latency_ms=int((time.monotonic() - started) * 1000),
        )
        ledger.budget.settle(reservation, entry.cost_usd)
        return result
    raise AssertionError("unreachable")
