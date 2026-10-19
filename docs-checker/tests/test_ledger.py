import json
import logging

import pytest
from langchain_core.messages import AIMessage

from docs_checker.ledger import (
    RATE_CARDS,
    REPLAYED_METADATA_KEY,
    Budget,
    CostLedger,
    Usage,
    cost_per_verified_outcome,
    usage_from_message,
)

CARD = RATE_CARDS["anthropic-2026-10-18"]


def test_langchain_usage_metadata_is_split_into_disjoint_buckets():
    # langchain-anthropic 1.7 reports input_tokens as the WHOLE prompt.
    message = AIMessage(
        content="x",
        usage_metadata={
            "input_tokens": 1210,
            "output_tokens": 7,
            "total_tokens": 1217,
            "input_token_details": {
                "cache_read": 1000,
                "cache_creation": 0,
                "ephemeral_5m_input_tokens": 150,
                "ephemeral_1h_input_tokens": 50,
            },
        },
    )
    usage = usage_from_message(message)
    assert usage == Usage(
        uncached_input=10, cache_write_5m=150, cache_write_1h=50, cache_read=1000, output=7
    )
    assert usage.prompt_tokens == 1210  # nothing counted twice


def test_raw_anthropic_usage_is_preferred_when_present():
    message = AIMessage(
        content="x",
        usage_metadata={"input_tokens": 999, "output_tokens": 1, "total_tokens": 1000},
        response_metadata={
            "usage": {
                "input_tokens": 10,  # Anthropic's input_tokens already excludes cache
                "cache_read_input_tokens": 1000,
                "cache_creation_input_tokens": 200,
                "output_tokens": 7,
            }
        },
    )
    usage = usage_from_message(message)
    assert (usage.uncached_input, usage.cache_write_5m, usage.cache_read, usage.output) == (
        10,
        200,
        1000,
        7,
    )


def test_streaming_usage_without_a_ttl_split_uses_the_configured_ttl():
    message = AIMessage(
        content="x",
        usage_metadata={
            "input_tokens": 1210,
            "output_tokens": 7,
            "total_tokens": 1217,
            "input_token_details": {"cache_read": 1000, "cache_creation": 200},
        },
    )
    assert usage_from_message(message, default_ttl="1h").cache_write_1h == 200


def test_missing_usage_is_unknown_not_zero():
    assert usage_from_message(AIMessage(content="x")) is None
    ledger = CostLedger("r", emit=False)
    ledger.record_message(
        node="router", model="claude-haiku-5-5", attempt=1, message=AIMessage(content="x")
    )
    ledger.record_error(node="router", model="claude-haiku-5-5", attempt=2, error=TimeoutError("t"))
    summary = ledger.summary("failed")
    assert summary.unknown_calls == 2
    assert summary.known_usage_coverage == 0.0
    assert summary.complete is False
    assert all(e.cost_usd is None for e in ledger.entries)


def test_cost_uses_the_versioned_rate_card():
    usage = Usage(
        uncached_input=1_000_000,
        cache_write_5m=0,
        cache_write_1h=0,
        cache_read=1_000_000,
        output=1_000_000,
    )
    rates = CARD.rates_for("claude-sonnet-5-5", usage.prompt_tokens)
    from docs_checker.ledger import cost_usd

    assert cost_usd(usage, rates) == pytest.approx(2.00 + 0.10 + 10.00)


def test_haiku_is_priced_by_prompt_length_including_cache():
    small = CARD.rates_for("claude-haiku-5-5", 100_000)
    large = CARD.rates_for("claude-haiku-5-5", 100_001)
    assert (small.input, large.input) == (0.10, 0.50)


def test_unknown_model_has_no_price_rather_than_a_guess():
    ledger = CostLedger("r", emit=False)
    message = AIMessage(
        content="x", usage_metadata={"input_tokens": 5, "output_tokens": 5, "total_tokens": 10}
    )
    entry = ledger.record_message(
        node="planner", model="claude-mystery-9", attempt=1, message=message
    )
    assert entry.usage is not None and entry.cost_usd is None
    assert ledger.summary("verified").complete is False


def test_every_entry_carries_the_tags(caplog):
    ledger = CostLedger("run-7", "ctx-7")
    message = AIMessage(
        content="x",
        usage_metadata={"input_tokens": 5, "output_tokens": 5, "total_tokens": 10},
        response_metadata={"id": "msg_123", "stop_reason": "end_turn"},
    )
    with caplog.at_level(logging.INFO, logger="docs_checker.ledger"):
        ledger.record_message(node="router", model="claude-haiku-5-5", attempt=2, message=message)
    line = json.loads(caplog.records[-1].getMessage())
    assert {
        k: line[k]
        for k in ("event", "run_id", "request_id", "node", "model", "attempt", "rate_card_version")
    } == {
        "event": "cost_ledger",
        "run_id": "run-7",
        "request_id": "msg_123",
        "node": "router",
        "model": "claude-haiku-5-5",
        "attempt": 2,
        "rate_card_version": "anthropic-2026-10-18",
    }


def test_cost_per_verified_outcome_keeps_failed_runs_in_the_numerator():
    def run(outcome, cost_tokens):
        ledger = CostLedger(outcome, emit=False)
        message = AIMessage(
            content="x",
            usage_metadata={
                "input_tokens": cost_tokens,
                "output_tokens": 0,
                "total_tokens": cost_tokens,
            },
        )
        ledger.record_message(node="planner", model="claude-sonnet-5-5", attempt=1, message=message)
        return ledger.summary(outcome)

    result = cost_per_verified_outcome([run("verified", 1_000_000), run("failed", 1_000_000)])
    assert result["verified"] == 1
    assert result["cost_per_verified_outcome"] == pytest.approx(4.00)  # $2 + $2, one verified
    assert result["lower_bound"] is False


def test_summary_cache_hit_rate():
    ledger = CostLedger("r", emit=False)
    message = AIMessage(
        content="x",
        usage_metadata={
            "input_tokens": 1000,
            "output_tokens": 10,
            "total_tokens": 1010,
            "input_token_details": {"cache_read": 900, "cache_creation": 0},
        },
    )
    ledger.record_message(node="specialist", model="claude-sonnet-5-5", attempt=1, message=message)
    assert ledger.summary("verified").cache_hit_rate == pytest.approx(0.9)


def test_error_text_is_redacted_before_it_is_stored_or_logged(caplog):
    import logging

    from docs_checker.ledger import CostLedger

    class Upstream(Exception):
        pass

    ledger = CostLedger("run-1", "ctx-1", emit=True)
    with caplog.at_level(logging.INFO):
        entry = ledger.record_error(
            node="router",
            model="claude-haiku-5-5",
            attempt=1,
            error=Upstream("400 echo: Authorization: Bearer sk-ant-api03-SECRETSECRETSECRET"),
        )
    assert "SECRETSECRET" not in entry.error and "[REDACTED]" in entry.error
    assert "SECRETSECRET" not in caplog.text


def _priced(replayed: bool = False) -> AIMessage:
    """One million uncached Sonnet input tokens: $2.00."""
    return AIMessage(
        content="x",
        usage_metadata={"input_tokens": 1_000_000, "output_tokens": 0, "total_tokens": 1_000_000},
        response_metadata={REPLAYED_METADATA_KEY: True} if replayed else {},
    )


def test_replayed_calls_count_in_workload_not_cash(caplog):
    ledger = CostLedger("r", emit=True)
    with caplog.at_level(logging.INFO, logger="docs_checker.ledger"):
        live = ledger.record_message(
            node="judge", model="claude-sonnet-5-5", attempt=1, message=_priced()
        )
        replayed = ledger.record_message(
            node="judge", model="claude-sonnet-5-5", attempt=1, message=_priced(replayed=True)
        )
    assert (live.replayed, replayed.replayed) == (False, True)
    assert json.loads(caplog.records[-1].getMessage())["replayed"] is True
    summary = ledger.summary("verified")
    assert summary.workload_cost_usd == pytest.approx(4.00)  # what the work costs at list price
    assert summary.cash_cost_usd == pytest.approx(2.00)  # what actually went to the API
    assert summary.cost_usd_known == summary.workload_cost_usd
    assert summary.to_dict()["cash_cost_usd"] == pytest.approx(2.00)


def test_cash_cost_is_a_lower_bound_like_the_rest_when_usage_is_unknown():
    ledger = CostLedger("r", emit=False)
    ledger.record_message(node="judge", model="claude-sonnet-5-5", attempt=1, message=_priced())
    ledger.record_error(node="judge", model="claude-sonnet-5-5", attempt=2, error=TimeoutError())
    summary = ledger.summary("failed")
    assert (summary.workload_cost_usd, summary.cash_cost_usd) == (
        pytest.approx(2.00),
        pytest.approx(2.00),
    )
    assert summary.complete is False


def test_an_error_entry_keeps_the_request_id_and_replay_flag_it_is_given():
    ledger = CostLedger("r", emit=False)
    entry = ledger.record_error(
        node="judge",
        model="claude-haiku-5-5",
        attempt=1,
        error=TimeoutError("t"),
        request_id="req_9",
        replayed=True,
    )
    assert (entry.request_id, entry.replayed) == ("req_9", True)


def test_a_ledger_has_an_unlimited_budget_unless_given_one():
    assert CostLedger("r", emit=False).budget.limit_usd is None
    assert CostLedger("r", emit=False, budget=Budget(0.10)).budget.limit_usd == 0.10


async def test_the_summary_reports_reservations_still_open():
    ledger = CostLedger("r", emit=False, budget=Budget(1.00))
    settled = await ledger.budget.reserve(0.20)
    await ledger.budget.reserve(0.05)  # an attempt still in flight when the run ended
    ledger.budget.settle(settled, 0.01)
    summary = ledger.summary("failed")
    assert summary.reserved_unsettled_usd == pytest.approx(0.05)
    assert summary.to_dict()["reserved_unsettled_usd"] == pytest.approx(0.05)
