import pytest

from docs_checker.ledger import CostLedger
from docs_checker.llm import RetryBudget, call_model, is_retryable
from tests.fakes import BadRequestError, ScriptedModel, TransientError, reply


async def no_sleep(_):
    return None


async def test_a_transient_failure_is_retried_and_both_attempts_are_ledgered():
    model = ScriptedModel([TransientError("overloaded"), reply("ok")])
    ledger = CostLedger("r", emit=False)
    result = await call_model(
        model, [], node="router", model_name="claude-haiku-5-5", ledger=ledger, sleep=no_sleep
    )
    assert result.text == "ok"
    assert [(e.attempt, e.status) for e in ledger.entries] == [(1, "error"), (2, "ok")]
    assert ledger.entries[0].usage is None  # unknown, not zero


async def test_a_bad_request_is_not_retried():
    model = ScriptedModel([BadRequestError("invalid"), reply("never")])
    ledger = CostLedger("r", emit=False)
    with pytest.raises(BadRequestError):
        await call_model(
            model, [], node="planner", model_name="claude-sonnet-5-5", ledger=ledger, sleep=no_sleep
        )
    assert len(ledger.entries) == 1 and len(model.calls) == 1


async def test_attempts_are_bounded():
    model = ScriptedModel(
        [TransientError("a"), TransientError("b"), TransientError("c"), reply("late")]
    )
    ledger = CostLedger("r", emit=False)
    with pytest.raises(TransientError):
        await call_model(
            model,
            [],
            node="specialist",
            model_name="claude-sonnet-5-5",
            ledger=ledger,
            budget=RetryBudget(max_attempts=3),
            sleep=no_sleep,
        )
    assert [e.attempt for e in ledger.entries] == [1, 2, 3]


def test_retryable_classification():
    assert is_retryable(TransientError())
    assert not is_retryable(BadRequestError())
    assert not is_retryable(ValueError())

    class APIConnectionError(Exception):
        pass

    assert is_retryable(APIConnectionError())


def test_the_sdk_does_not_retry_underneath():
    from docs_checker.config import load_settings
    from docs_checker.models import AnthropicModels

    model = AnthropicModels(load_settings({}).node_models).get("router")
    assert model.max_retries == 0
