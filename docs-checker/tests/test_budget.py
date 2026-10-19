import asyncio

import pytest

from docs_checker.ledger import (
    RATE_CARDS,
    Budget,
    BudgetExceeded,
    Reservation,
    Usage,
    cost_usd,
    reservation_for,
)

CARD = RATE_CARDS["anthropic-2026-10-18"]


async def test_four_concurrent_reservations_cannot_exceed_the_limit():
    # Review Focus 3: four docs starting together with $0.02 left.
    budget = Budget(0.02)
    results = await asyncio.gather(
        *(budget.reserve(0.01) for _ in range(4)), return_exceptions=True
    )
    assert sum(isinstance(r, Reservation) for r in results) == 2
    assert sum(isinstance(r, BudgetExceeded) for r in results) == 2
    assert budget.reserved_usd == pytest.approx(0.02)
    assert budget.remaining_usd == pytest.approx(0.0)


async def test_unknown_usage_keeps_the_reservation_as_spent():
    budget = Budget(1.00)
    reservation = await budget.reserve(0.05)
    budget.settle(reservation, None)
    assert budget.spent_usd == pytest.approx(0.05)
    assert budget.reserved_usd == 0.0
    assert budget.remaining_usd == pytest.approx(0.95)


async def test_settle_replaces_the_reservation_with_the_actual_cost():
    budget = Budget(0.10)
    first = await budget.reserve(0.06)
    with pytest.raises(BudgetExceeded):
        await budget.reserve(0.06)  # 0.06 reserved + 0.06 > 0.10
    budget.settle(first, 0.01)
    assert (budget.spent_usd, budget.reserved_usd) == (pytest.approx(0.01), 0.0)
    await budget.reserve(0.06)  # fits once the reservation shrank to the actual


async def test_a_reservation_settles_once():
    budget = Budget(None)
    reservation = await budget.reserve(0.01)
    budget.settle(reservation, 0.01)
    with pytest.raises(ValueError):
        budget.settle(reservation, 0.01)
    assert budget.spent_usd == pytest.approx(0.01)


async def test_an_unlimited_budget_never_refuses_but_still_counts():
    budget = Budget(None)
    reservation = await budget.reserve(1_000.0)
    assert budget.remaining_usd is None
    assert budget.reserved_usd == pytest.approx(1_000.0)
    budget.settle(reservation, 2.5)
    assert budget.spent_usd == pytest.approx(2.5)


async def test_an_exact_fit_is_not_refused_by_float_rounding():
    budget = Budget(0.3)
    await budget.reserve(0.1)
    await budget.reserve(0.2)  # 0.1 + 0.2 == 0.30000000000000004 in floats
    assert budget.remaining_usd == pytest.approx(0.0)


def test_reservation_prices_the_prompt_at_the_dearest_input_rate_plus_max_tokens_at_output():
    # 2500 chars -> 1000 tokens at Sonnet's 1h cache-write rate ($4/M, the dearest
    # input-side rate), plus 1000 output tokens at $10/M.
    assert reservation_for("claude-sonnet-5-5", 2500, 1000, CARD) == pytest.approx(0.014)


def test_reservation_rounds_the_token_estimate_up():
    assert reservation_for("claude-sonnet-5-5", 1, 0, CARD) == pytest.approx(4.00 / 1_000_000)


def test_a_tiered_model_reserves_at_its_highest_tier():
    # A short Haiku prompt is still reserved at the >100k tier: the estimate can't
    # know the real token count, and the tier sets both the input and output rate.
    assert reservation_for("claude-haiku-5-5", 250, 100, CARD) == pytest.approx(
        (100 * 1.00 + 100 * 2.50) / 1_000_000
    )


def test_the_reservation_covers_a_cache_write_heavy_call_on_dense_text():
    # 300k chars of SHAs and YAML at 2.5 chars/token is 120k real tokens, over
    # Haiku's 100k tier, all written to the 1h cache, with the full output used.
    chars, max_tokens = 300_000, 4096
    usage = Usage(
        uncached_input=0, cache_write_5m=0, cache_write_1h=120_000, cache_read=0, output=max_tokens
    )
    actual = cost_usd(usage, CARD.rates_for("claude-haiku-5-5", usage.prompt_tokens))
    assert reservation_for("claude-haiku-5-5", chars, max_tokens, CARD) >= actual


def test_a_model_without_a_price_cannot_be_reserved_for():
    with pytest.raises(ValueError, match="claude-mystery-9"):
        reservation_for("claude-mystery-9", 10, 10, CARD)
