"""Per-run cost ledger: step zero before any cost lever ships.

Every model call becomes one ``LedgerEntry`` tagged with run_id, request_id,
node, model, attempt and rate-card version, carrying four disjoint token
buckets: uncached input, cache write (split by TTL only because the two TTLs
are priced differently), cache read, and output. Nothing is counted twice:
the buckets add up to the prompt plus the output.

Two traps this module exists to avoid:

- ``AIMessage.usage_metadata["input_tokens"]`` from langchain-anthropic 1.7 is
  the *total* prompt (uncached + cache read + cache write; see
  ``_create_usage_metadata``), not Anthropic's ``input_tokens``. Adding the
  cache fields to it double-counts. The raw Anthropic usage, when present in
  ``response_metadata["usage"]``, is preferred.
- A call that returned no usage (an error, a stream that died) is *unknown*,
  not zero. Its cost is ``None`` and it lowers known-usage coverage instead of
  silently lowering the bill.

Each ledger also owns the run's ``Budget``, enforced by reservation before every
attempt (``llm.call_model`` reserves and settles). A run reports two costs:
*workload* (every call at list price, replayed ones included: what the work
costs) and *cash* (only calls that reached the API: what was paid). An entry is
replayed when its message's ``response_metadata`` carries
``REPLAYED_METADATA_KEY``; ``llm.call_model`` sets it from the eval replay
transport's response header.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from docs_checker.redact import redact, redact_obj

logger = logging.getLogger("docs_checker.ledger")

Outcome = Literal["verified", "unverified", "refused", "failed", "escalated"]

# response_metadata key that marks a message as served by the eval replay
# transport rather than the API: it counts in workload cost, not cash cost.
REPLAYED_METADATA_KEY = "docs_checker_replayed"

# Float sums drift (0.1 + 0.2 > 0.3): an exact fit must not be refused.
_EPSILON_USD = 1e-9


@dataclass(frozen=True)
class Rates:
    """USD per million tokens."""

    input: float
    cache_write_5m: float
    cache_write_1h: float
    cache_read: float
    output: float


@dataclass(frozen=True)
class RateCard:
    version: str
    source: str
    # model -> tiers of (max prompt tokens inclusive, or None for "any"), checked in order
    models: dict[str, tuple[tuple[int | None, Rates], ...]]

    def rates_for(self, model: str, prompt_tokens: int) -> Rates | None:
        for limit, rates in self.models.get(model, ()):
            if limit is None or prompt_tokens <= limit:
                return rates
        return None


# Source: https://platform.claude.com/docs/en/about-claude/pricing (read 2026-10-18).
# Cache reads on Opus 5.5 and Sonnet 5.5 are 0.05x input; Haiku 5.5 is priced by
# prompt length (all input tokens, cache reads and writes included).
RATE_CARDS: dict[str, RateCard] = {
    "anthropic-2026-10-18": RateCard(
        version="anthropic-2026-10-18",
        source="https://platform.claude.com/docs/en/about-claude/pricing",
        models={
            "claude-opus-5-5": ((None, Rates(4.00, 5.00, 8.00, 0.20, 20.00)),),
            "claude-sonnet-5-5": ((None, Rates(2.00, 2.50, 4.00, 0.10, 10.00)),),
            "claude-haiku-5-5": (
                (100_000, Rates(0.10, 0.125, 0.20, 0.01, 0.50)),
                (None, Rates(0.50, 0.625, 1.00, 0.05, 2.50)),
            ),
        },
    )
}


@dataclass(frozen=True)
class Usage:
    """Four disjoint buckets (cache write kept split by TTL for pricing)."""

    uncached_input: int
    cache_write_5m: int
    cache_write_1h: int
    cache_read: int
    output: int

    @property
    def cache_write(self) -> int:
        return self.cache_write_5m + self.cache_write_1h

    @property
    def prompt_tokens(self) -> int:
        return self.uncached_input + self.cache_write + self.cache_read


def _int(value: Any) -> int:
    return int(value) if isinstance(value, int | float) else 0


def _from_raw(raw: dict, default_ttl: str) -> Usage:
    """Anthropic's usage object: input_tokens already excludes cached tokens."""
    creation = _int(raw.get("cache_creation_input_tokens"))
    split = raw.get("cache_creation") or {}
    w5, w1 = _int(split.get("ephemeral_5m_input_tokens")), _int(
        split.get("ephemeral_1h_input_tokens")
    )
    if creation and not (w5 or w1):
        w5, w1 = (0, creation) if default_ttl == "1h" else (creation, 0)
    return Usage(
        uncached_input=_int(raw.get("input_tokens")),
        cache_write_5m=w5,
        cache_write_1h=w1,
        cache_read=_int(raw.get("cache_read_input_tokens")),
        output=_int(raw.get("output_tokens")),
    )


def _from_usage_metadata(meta: dict, default_ttl: str) -> Usage:
    """LangChain's usage_metadata: input_tokens is the TOTAL prompt; subtract the cache."""
    details = meta.get("input_token_details") or {}
    read = _int(details.get("cache_read"))
    w5, w1 = _int(details.get("ephemeral_5m_input_tokens")), _int(
        details.get("ephemeral_1h_input_tokens")
    )
    if not (w5 or w1):
        creation = _int(details.get("cache_creation"))
        w5, w1 = (0, creation) if default_ttl == "1h" else (creation, 0)
    total = _int(meta.get("input_tokens"))
    return Usage(
        uncached_input=max(total - read - w5 - w1, 0),
        cache_write_5m=w5,
        cache_write_1h=w1,
        cache_read=read,
        output=_int(meta.get("output_tokens")),
    )


def usage_from_message(message: Any, default_ttl: str = "5m") -> Usage | None:
    """Extract usage from an AIMessage, or None when the call reported none."""
    response_metadata = getattr(message, "response_metadata", None) or {}
    raw = response_metadata.get("usage")
    if isinstance(raw, dict) and "input_tokens" in raw:
        return _from_raw(raw, default_ttl)
    meta = getattr(message, "usage_metadata", None)
    if meta:
        return _from_usage_metadata(dict(meta), default_ttl)
    return None


def cost_usd(usage: Usage, rates: Rates) -> float:
    return (
        usage.uncached_input * rates.input
        + usage.cache_write_5m * rates.cache_write_5m
        + usage.cache_write_1h * rates.cache_write_1h
        + usage.cache_read * rates.cache_read
        + usage.output * rates.output
    ) / 1_000_000


def reservation_for(model: str, prompt_chars: int, max_tokens: int, rate_card: RateCard) -> float:
    """An upper bound on one attempt's cost (controller ruling B1).

    - Input: ``ceil(chars / 2.5)`` tokens, since dense text such as SHAs and YAML
      runs under 3 chars per token, at the dearest input-side rate (uncached, 5m
      or 1h cache write), since any of the prompt may be written to the cache.
    - Output: ``max_tokens`` at the output rate.
    - Both rates come from the model's highest-priced tier: the estimate can't
      tell which tier the real prompt lands in, and the tier sets both rates.

    Callers add what the messages don't show (bound tool schemas, the output
    format) to ``prompt_chars``. A model the rate card cannot price has no bound,
    so the run budget could not hold it: that is an error, not a free call.
    """
    tiers = [rates for _, rates in rate_card.models.get(model, ())]
    if not tiers:
        raise ValueError(f"rate card {rate_card.version} has no price for {model}")
    input_rate = max(max(r.input, r.cache_write_5m, r.cache_write_1h) for r in tiers)
    output_rate = max(r.output for r in tiers)
    prompt_tokens = -(-2 * prompt_chars // 5)  # ceil(chars / 2.5)
    return (prompt_tokens * input_rate + max_tokens * output_rate) / 1_000_000


class BudgetExceeded(Exception):
    """A reservation would take the run past its budget. Raised before the call."""


@dataclass(frozen=True, eq=False)  # compared by identity: each one settles once
class Reservation:
    amount_usd: float


class Budget:
    """The run budget, enforced by reservation before every attempt (C#1).

    ``reserve`` holds a conservative bound before an attempt; ``settle`` swaps it
    for the actual cost. Concurrent branches share one Budget, and the check and
    the hold happen under one lock, so branches starting together cannot reserve
    more than the limit between them. An attempt whose cost is unknown keeps its
    whole reservation as spent. A reservation never settled (its attempt was
    cancelled in flight) stays in ``reserved_usd``: whether it was billed is unknown.
    ``limit_usd=None`` never refuses but still counts.
    """

    def __init__(self, limit_usd: float | None = None):
        self.limit_usd = limit_usd
        self._lock = asyncio.Lock()
        self._open: set[Reservation] = set()
        self._spent = 0.0

    @property
    def spent_usd(self) -> float:
        return self._spent

    @property
    def reserved_usd(self) -> float:
        return sum(r.amount_usd for r in self._open)

    @property
    def remaining_usd(self) -> float | None:
        if self.limit_usd is None:
            return None
        return max(self.limit_usd - self._spent - self.reserved_usd, 0.0)

    async def reserve(self, amount_usd: float) -> Reservation:
        if amount_usd < 0:
            raise ValueError(f"cannot reserve a negative amount: {amount_usd}")
        async with self._lock:
            committed = self._spent + self.reserved_usd
            if (
                self.limit_usd is not None
                and committed + amount_usd > self.limit_usd + _EPSILON_USD
            ):
                raise BudgetExceeded(
                    f"reserving ${amount_usd:.6f} on top of ${committed:.6f} "
                    f"exceeds the ${self.limit_usd:.6f} run budget"
                )
            reservation = Reservation(amount_usd)
            self._open.add(reservation)
            return reservation

    def settle(self, reservation: Reservation, actual_usd: float | None) -> None:
        """Replace the reservation with the actual cost, or keep it all when the
        actual is unknown. Synchronous (no await), so it is atomic on the loop."""
        if reservation not in self._open:
            raise ValueError("reservation is not open (already settled, or another budget's)")
        self._open.remove(reservation)
        self._spent += reservation.amount_usd if actual_usd is None else actual_usd

    def restore(self, *, limit_usd: float | None, spent_usd: float, reserved_usd: float) -> None:
        """Take over a paused run's budget in a new process: its limit, its spend, and
        what it left unsettled (one open reservation that never settles)."""
        for value in (spent_usd, reserved_usd) + (() if limit_usd is None else (limit_usd,)):
            if isinstance(value, bool) or not isinstance(value, int | float) or value < 0:
                raise ValueError(f"not a budget amount: {value!r}")
        self.limit_usd = None if limit_usd is None else float(limit_usd)
        self._spent = float(spent_usd)
        self._open = {Reservation(float(reserved_usd))} if reserved_usd else set()


@dataclass(frozen=True)
class LedgerEntry:
    run_id: str
    context_id: str
    request_id: str | None
    node: str
    model: str
    attempt: int
    rate_card_version: str
    usage: Usage | None
    cost_usd: float | None
    status: Literal["ok", "error"]
    error: str | None = None
    stop_reason: str | None = None
    latency_ms: int = 0
    replayed: bool = False  # served by the eval replay transport, not the API
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["event"] = "cost_ledger"
        return data


@dataclass(frozen=True)
class RunSummary:
    run_id: str
    context_id: str
    outcome: Outcome
    calls: int
    unknown_calls: int
    uncached_input: int
    cache_write: int
    cache_read: int
    output: int
    cost_usd_known: float
    # Cost of the calls whose usage is known. With unknown calls or open
    # reservations the true run cost may be higher; ``complete`` says whether
    # this number is the whole bill.
    # The two costs below are lower bounds in the same way (C#28):
    workload_cost_usd: float  # every priced call, replayed ones included (= cost_usd_known)
    cash_cost_usd: float  # only the priced calls that went to the API
    # Reservations still open when the summary was taken: attempts cancelled in
    # flight, which may or may not have been billed.
    reserved_unsettled_usd: float
    complete: bool
    cache_hit_rate: float | None
    by_node: dict[str, float]
    rate_card_version: str

    @property
    def known_usage_coverage(self) -> float:
        return 1.0 if self.calls == 0 else (self.calls - self.unknown_calls) / self.calls

    def to_dict(self) -> dict:
        data = asdict(self)
        data["event"] = "cost_run"
        data["known_usage_coverage"] = self.known_usage_coverage
        return data


class CostLedger:
    """Collects the entries of one run (one A2A task)."""

    def __init__(
        self,
        run_id: str,
        context_id: str = "",
        rate_card: RateCard | None = None,
        default_ttl: str = "5m",
        emit: bool = True,
        budget: Budget | None = None,
    ):
        self.run_id = run_id
        self.context_id = context_id
        self.rate_card = rate_card or RATE_CARDS["anthropic-2026-10-18"]
        self.default_ttl = default_ttl
        self.emit = emit
        self.budget = budget if budget is not None else Budget(None)
        self.entries: list[LedgerEntry] = []
        # Why the cost is known to miss calls, beyond unknown usage: a resume that lost
        # the paused run's ledger counts from the restart only (C#25). The summary is
        # then not complete, and the report states each reason.
        self.lower_bound: list[str] = []

    def record_message(
        self, *, node: str, model: str, attempt: int, message: Any, latency_ms: int = 0
    ) -> LedgerEntry:
        usage = usage_from_message(message, self.default_ttl)
        metadata = getattr(message, "response_metadata", None) or {}
        cost = None
        if usage is not None:
            rates = self.rate_card.rates_for(model, usage.prompt_tokens)
            cost = cost_usd(usage, rates) if rates else None
        return self._append(
            LedgerEntry(
                run_id=self.run_id,
                context_id=self.context_id,
                request_id=metadata.get("request_id") or metadata.get("id"),
                node=node,
                model=model,
                attempt=attempt,
                rate_card_version=self.rate_card.version,
                usage=usage,
                cost_usd=cost,
                status="ok",
                stop_reason=metadata.get("stop_reason"),
                latency_ms=latency_ms,
                replayed=bool(metadata.get(REPLAYED_METADATA_KEY)),
            )
        )

    def record_error(
        self,
        *,
        node: str,
        model: str,
        attempt: int,
        error: BaseException,
        latency_ms: int = 0,
        request_id: str | None = None,
        replayed: bool = False,
    ) -> LedgerEntry:
        """``request_id`` and ``replayed`` come from the response the error followed,
        when the caller saw one; the error's own request id wins."""
        return self._append(
            LedgerEntry(
                run_id=self.run_id,
                context_id=self.context_id,
                request_id=getattr(error, "request_id", None) or request_id,
                node=node,
                model=model,
                attempt=attempt,
                rate_card_version=self.rate_card.version,
                usage=None,  # unknown, not zero
                cost_usd=None,
                status="error",
                # Upstream errors can echo request or response content: redact
                # before the text is stored or logged.
                error=redact(f"{type(error).__name__}: {error}")[:300],
                latency_ms=latency_ms,
                replayed=replayed,
            )
        )

    def dump_state(self) -> dict:
        """What a resume in another process needs, as plain data: the entries, the
        budget (limit, spend, unsettled reservations) and the lower-bound reasons."""
        budget = self.budget
        return {
            "entries": [asdict(entry) for entry in self.entries],
            "budget": {
                "limit_usd": budget.limit_usd,
                "spent_usd": budget.spent_usd,
                "reserved_usd": budget.reserved_usd,
            },
            "lower_bound": list(self.lower_bound),
        }

    def load_state(self, state: dict) -> None:
        """Continue the run ``dump_state`` described. Restored entries were logged by
        the process that made them, so they are not emitted again. Raises on anything
        malformed, leaving this ledger as it was."""
        entries = []
        for data in state["entries"]:
            usage = data["usage"]
            entries.append(
                LedgerEntry(**{**data, "usage": None if usage is None else Usage(**usage)})
            )
        reasons = state["lower_bound"]
        if not isinstance(reasons, list) or not all(isinstance(r, str) for r in reasons):
            raise TypeError("lower_bound must be a list of strings")
        restored = Budget(None)
        restored.restore(**state["budget"])
        self.budget.restore(
            limit_usd=restored.limit_usd,
            spent_usd=restored.spent_usd,
            reserved_usd=restored.reserved_usd,
        )
        self.entries = entries
        self.lower_bound = list(reasons)

    def _append(self, entry: LedgerEntry) -> LedgerEntry:
        self.entries.append(entry)
        if self.emit:
            line = json.dumps(redact_obj(entry.to_dict()), sort_keys=True, default=str)
            logger.info(line)
        return entry

    def summary(self, outcome: Outcome) -> RunSummary:
        known = [e for e in self.entries if e.usage is not None]
        unknown = len(self.entries) - len(known)
        uncached = sum(e.usage.uncached_input for e in known)
        write = sum(e.usage.cache_write for e in known)
        read = sum(e.usage.cache_read for e in known)
        prompt = uncached + write + read
        by_node: dict[str, float] = {}
        cash = 0.0
        priced_all = True
        for entry in self.entries:
            if entry.cost_usd is None:
                priced_all = False
                continue
            by_node[entry.node] = by_node.get(entry.node, 0.0) + entry.cost_usd
            if not entry.replayed:
                cash += entry.cost_usd
        workload = round(sum(by_node.values()), 8)
        return RunSummary(
            run_id=self.run_id,
            context_id=self.context_id,
            outcome=outcome,
            calls=len(self.entries),
            unknown_calls=unknown,
            uncached_input=uncached,
            cache_write=write,
            cache_read=read,
            output=sum(e.usage.output for e in known),
            cost_usd_known=workload,
            workload_cost_usd=workload,
            cash_cost_usd=round(cash, 8),
            reserved_unsettled_usd=round(self.budget.reserved_usd, 8),
            complete=priced_all and self.budget.reserved_usd == 0 and not self.lower_bound,
            cache_hit_rate=(read / prompt) if prompt else None,
            by_node={k: round(v, 8) for k, v in sorted(by_node.items())},
            rate_card_version=self.rate_card.version,
        )


def cost_per_verified_outcome(runs: Iterable[RunSummary]) -> dict:
    """Aggregate across runs: every run's cost in the numerator, only verified
    outcomes in the denominator. Failed, refused and escalated runs still cost."""
    runs = list(runs)
    total = sum(r.cost_usd_known for r in runs)
    verified = sum(1 for r in runs if r.outcome == "verified")
    return {
        "runs": len(runs),
        "verified": verified,
        "cost_usd": round(total, 8),
        "cost_per_verified_outcome": (total / verified) if verified else None,
        # A lower bound when any run had a call with unknown usage.
        "lower_bound": any(not r.complete for r in runs),
    }
