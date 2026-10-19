import asyncio
import json
import logging

import anthropic
import httpx2
import pytest
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel

from docs_checker.ledger import RATE_CARDS, Budget, BudgetExceeded, CostLedger, reservation_for
from docs_checker.llm import (
    REPLAYED_HEADER,
    RetryBudget,
    call_model,
    is_retryable,
    prompt_chars,
    request_id_hook,
)
from tests.fakes import BadRequestError, ScriptedModel, TransientError, reply

CARD = RATE_CARDS["anthropic-2026-10-18"]
HAIKU = "claude-haiku-5-5"


async def no_sleep(_):
    return None


async def test_a_transient_failure_is_retried_and_both_attempts_are_ledgered():
    model = ScriptedModel([TransientError("overloaded"), reply("ok")])
    ledger = CostLedger("r", emit=False)
    result = await call_model(
        model,
        [],
        node="router",
        model_name="claude-haiku-5-5",
        ledger=ledger,
        max_tokens=100,
        sleep=no_sleep,
    )
    assert result.text == "ok"
    assert [(e.attempt, e.status) for e in ledger.entries] == [(1, "error"), (2, "ok")]
    assert ledger.entries[0].usage is None  # unknown, not zero


async def test_a_bad_request_is_not_retried():
    model = ScriptedModel([BadRequestError("invalid"), reply("never")])
    ledger = CostLedger("r", emit=False)
    with pytest.raises(BadRequestError):
        await call_model(
            model,
            [],
            node="planner",
            model_name="claude-sonnet-5-5",
            ledger=ledger,
            max_tokens=100,
            sleep=no_sleep,
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
            max_tokens=100,
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

    settings = load_settings({})
    model = AnthropicModels(
        settings.node_models, settings.levers, http_timeout_s=settings.http_timeout_s
    ).get("intake")
    assert model.max_retries == 0


# --- Real ChatAnthropic over an httpx2 MockTransport (no network, no key) ---


class Verdict(BaseModel):
    supported: bool


def message_body(text: str, *, input_tokens: int = 1000, output_tokens: int = 50) -> dict:
    return {
        "id": "msg_abc",
        "type": "message",
        "role": "assistant",
        "model": HAIKU,
        "content": [{"type": "text", "text": text}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        },
    }


OVERLOADED = {"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}}
# Haiku 5.5 under 100k prompt tokens: 1000 in at $0.10/M plus 50 out at $0.50/M.
HAIKU_COST = (1000 * 0.10 + 50 * 0.50) / 1_000_000


def chat_over(responses: list[httpx2.Response]) -> tuple[ChatAnthropic, list[httpx2.Request]]:
    """A real ChatAnthropic whose HTTP client serves ``responses`` in order and
    carries the request-id hook, the way Task 4's clients will."""
    requests: list[httpx2.Request] = []
    queue = list(responses)

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return queue.pop(0)

    chat = ChatAnthropic(model=HAIKU, max_tokens=256, max_retries=0)
    chat.__dict__["_async_client"] = anthropic.AsyncClient(
        api_key="sk-test",
        max_retries=0,
        timeout=60,
        http_client=httpx2.AsyncClient(
            transport=httpx2.MockTransport(handler),
            event_hooks={"response": [request_id_hook]},
        ),
    )
    return chat, requests


def structured(chat: ChatAnthropic):
    return chat.with_structured_output(Verdict, method="json_schema", include_raw=True)


async def call(model, ledger, **kwargs):
    return await call_model(
        model,
        [HumanMessage("Is chart vault at 0.30.1?")],
        node="judge",
        model_name=HAIKU,
        ledger=ledger,
        max_tokens=256,
        sleep=no_sleep,
        **kwargs,
    )


async def test_structured_output_dict_is_accounted_from_raw():
    chat, _ = chat_over([httpx2.Response(200, json=message_body('{"supported": true}'))])
    ledger = CostLedger("r", emit=False)
    result = await call(structured(chat), ledger)
    assert set(result) == {"raw", "parsed", "parsing_error"}  # returned as the model gave it
    assert result["parsed"] == Verdict(supported=True) and result["parsing_error"] is None
    (entry,) = ledger.entries
    assert entry.cost_usd is not None
    assert entry.cost_usd == pytest.approx(HAIKU_COST)
    assert ledger.budget.spent_usd == pytest.approx(HAIKU_COST)  # settled to the actual
    assert ledger.budget.reserved_usd == 0.0


async def test_request_id_reaches_the_ledger_through_structured_output():
    # include_raw runs the model inside a RunnableMap, so the HTTP response (and
    # the hook) happen in a child task: the shared recorder carries the id back.
    response = httpx2.Response(
        200, headers={"request-id": "req_123"}, json=message_body('{"supported": false}')
    )
    chat, _ = chat_over([response])
    ledger = CostLedger("r", emit=False)
    result = await call(structured(chat), ledger)
    assert ledger.entries[0].request_id == "req_123"  # not the message id
    assert result["raw"].response_metadata["request_id"] == "req_123"


async def test_a_parse_failure_is_accounted_and_not_retried():
    chat, requests = chat_over([httpx2.Response(200, json=message_body("not json"))])
    ledger = CostLedger("r", emit=False)
    result = await call(structured(chat), ledger)
    assert result["parsed"] is None and result["parsing_error"] is not None
    assert len(requests) == 1
    assert ledger.entries[0].cost_usd == pytest.approx(HAIKU_COST)


async def test_the_replay_header_marks_the_call_replayed():
    response = httpx2.Response(
        200,
        headers={"request-id": "req_cassette", REPLAYED_HEADER: "1"},
        json=message_body("ok"),
    )
    chat, _ = chat_over([response])
    ledger = CostLedger("r", emit=False)
    await call(chat, ledger)
    assert (ledger.entries[0].replayed, ledger.entries[0].request_id) == (True, "req_cassette")
    summary = ledger.summary("verified")
    assert summary.workload_cost_usd == pytest.approx(HAIKU_COST)
    assert summary.cash_cost_usd == 0.0
    # The run budget is charged at workload price, so a replayed run stops where a live one would.
    assert ledger.budget.spent_usd == pytest.approx(HAIKU_COST)


async def test_a_retried_error_keeps_its_request_id_and_settles_to_nothing():
    chat, requests = chat_over(
        [
            httpx2.Response(529, headers={"request-id": "req_529"}, json=OVERLOADED),
            httpx2.Response(200, headers={"request-id": "req_200"}, json=message_body("ok")),
        ]
    )
    ledger = CostLedger("r", emit=False)
    await call(chat, ledger)
    assert len(requests) == 2
    assert [(e.status, e.request_id) for e in ledger.entries] == [
        ("error", "req_529"),
        ("ok", "req_200"),
    ]
    # A 529 is a response: nothing was billed, so the failed attempt settles to $0 (M4)
    # and the ledger entry's usage stays unknown.
    assert ledger.entries[0].cost_usd is None
    assert ledger.budget.spent_usd == pytest.approx(HAIKU_COST)
    assert ledger.budget.reserved_usd == 0.0


async def test_the_recorder_does_not_leak_between_calls():
    chat, _ = chat_over(
        [
            httpx2.Response(200, headers={"request-id": "req_1"}, json=message_body("a")),
            httpx2.Response(200, json=message_body("b")),  # no request-id header
        ]
    )
    ledger = CostLedger("r", emit=False)
    await call(chat, ledger)
    await call(chat, ledger)
    assert [e.request_id for e in ledger.entries] == ["req_1", "msg_abc"]


async def test_the_hook_outside_call_model_is_a_no_op():
    await request_id_hook(httpx2.Response(200, headers={"request-id": "req_x"}))


# --- The run budget, reserved before every attempt ---


class GatedModel(ScriptedModel):
    """Holds every call until ``gate`` opens, so attempts overlap."""

    def __init__(self, reply_message=None):
        super().__init__([])
        self.gate = asyncio.Event()
        self.reply_message = reply_message

    async def ainvoke(self, messages, *_, **__):
        self.calls.append(list(messages))
        await self.gate.wait()
        return self.reply_message or reply("ok")


async def started(model: ScriptedModel, count: int) -> None:
    while len(model.calls) < count:
        await asyncio.sleep(0)


async def test_concurrent_calls_cannot_overspend_the_run_budget():
    # Review Focus 3 through call_model: four branches start together with room for two.
    messages = [HumanMessage("x" * 3000)]
    each = reservation_for(HAIKU, prompt_chars(messages), 1000, CARD)
    ledger = CostLedger("r", emit=False, budget=Budget(2 * each))
    model = GatedModel()
    branches = [
        asyncio.create_task(
            call_model(
                model, messages, node="judge", model_name=HAIKU, ledger=ledger, max_tokens=1000
            )
        )
        for _ in range(4)
    ]
    await started(model, 2)
    assert ledger.budget.reserved_usd == pytest.approx(2 * each)
    model.gate.set()
    results = await asyncio.gather(*branches, return_exceptions=True)
    assert sum(isinstance(r, BudgetExceeded) for r in results) == 2
    assert len(model.calls) == 2  # the refused branches never reached the model
    assert len(ledger.entries) == 2
    assert ledger.budget.reserved_usd == 0.0
    assert ledger.budget.spent_usd == pytest.approx(sum(e.cost_usd for e in ledger.entries))


async def test_budget_exceeded_stops_before_the_call():
    model = ScriptedModel([reply("never")])
    ledger = CostLedger("r", emit=False, budget=Budget(0.0))
    with pytest.raises(BudgetExceeded):
        await call(model, ledger)
    assert model.calls == [] and ledger.entries == []


class APIConnectionError(Exception):
    """Named like the SDK's: no status code, no response, billing unknown."""


async def test_a_retry_needs_its_own_reservation():
    messages = [HumanMessage("Is chart vault at 0.30.1?")]
    each = reservation_for(HAIKU, prompt_chars(messages), 256, CARD)
    model = ScriptedModel([APIConnectionError("reset"), reply("ok")])
    ledger = CostLedger("r", emit=False, budget=Budget(1.5 * each))
    with pytest.raises(BudgetExceeded):
        await call(model, ledger)
    assert len(model.calls) == 1  # a connection error: billing unknown, reservation kept
    assert ledger.budget.spent_usd == pytest.approx(each)


async def test_an_error_with_an_http_status_settles_to_nothing_but_a_connection_error_not():
    # M4: a 529/429 is a response the API did not bill, so its reservation is released;
    # an error with no status may have reached the API, so the reservation stays spent.
    messages = [HumanMessage("Is chart vault at 0.30.1?")]
    each = reservation_for(HAIKU, prompt_chars(messages), 256, CARD)
    ok_cost = (100 * 0.10 + 50 * 0.50) / 1_000_000  # the fake reply: 100 in, 50 out, Haiku
    ledger = CostLedger("r", emit=False)
    await call(ScriptedModel([TransientError("overloaded"), reply("ok")]), ledger)
    assert ledger.budget.spent_usd == pytest.approx(ok_cost)
    ledger = CostLedger("r", emit=False)
    await call(ScriptedModel([APIConnectionError("reset"), reply("ok")]), ledger)
    assert ledger.budget.spent_usd == pytest.approx(each + ok_cost)
    assert ledger.budget.reserved_usd == 0.0


async def test_a_call_without_usage_keeps_its_reservation_as_spent():
    messages = [HumanMessage("Is chart vault at 0.30.1?")]
    each = reservation_for(HAIKU, prompt_chars(messages), 256, CARD)
    ledger = CostLedger("r", emit=False)
    await call(ScriptedModel([AIMessage(content="no usage reported")]), ledger)
    assert ledger.entries[0].cost_usd is None
    assert ledger.budget.spent_usd == pytest.approx(each)


async def test_a_cancelled_attempt_leaves_its_reservation_unsettled():
    messages = [HumanMessage("Is chart vault at 0.30.1?")]
    each = reservation_for(HAIKU, prompt_chars(messages), 256, CARD)
    ledger = CostLedger("r", emit=False)
    model = GatedModel()
    branch = asyncio.create_task(call(model, ledger))
    await started(model, 1)
    branch.cancel()
    with pytest.raises(asyncio.CancelledError):
        await branch
    # Whether the request was billed is unknown: it is ledgered with unknown usage,
    # it stays reserved, and the summary says the bill is incomplete.
    (entry,) = ledger.entries
    assert (entry.status, entry.usage, entry.cost_usd) == ("error", None, None)
    assert ledger.budget.reserved_usd == pytest.approx(each)
    summary = ledger.summary("failed")
    assert summary.reserved_unsettled_usd == pytest.approx(each)
    assert summary.unknown_calls == 1
    assert summary.complete is False


async def test_a_cancelled_http_call_keeps_its_request_id():
    # The response arrived (and the hook recorded its id) but the attempt was
    # cancelled before the message came back.
    reached, hold = asyncio.Event(), asyncio.Event()

    async def stall(response):  # runs after request_id_hook
        reached.set()
        await hold.wait()

    chat, _ = chat_over(
        [httpx2.Response(200, headers={"request-id": "req_cut"}, json=message_body("x"))]
    )
    chat._async_client._client.event_hooks["response"].append(stall)
    ledger = CostLedger("r", emit=False)
    branch = asyncio.create_task(call(chat, ledger))
    await reached.wait()
    branch.cancel()
    with pytest.raises(asyncio.CancelledError):
        await branch
    assert ledger.entries[0].request_id == "req_cut"


async def test_overhead_chars_raise_the_reservation():
    # Bound tool schemas and the output format are part of the prompt too.
    messages = [HumanMessage("Is chart vault at 0.30.1?")]
    plain = reservation_for(HAIKU, prompt_chars(messages), 256, CARD)
    with_overhead = reservation_for(HAIKU, prompt_chars(messages) + 5000, 256, CARD)
    assert with_overhead > plain
    ledger = CostLedger("r", emit=False)
    no_usage = ScriptedModel([AIMessage(content="no usage reported")])
    await call(no_usage, ledger, overhead_chars=5000)
    assert ledger.budget.spent_usd == pytest.approx(with_overhead)  # unknown: reservation kept


async def test_an_actual_cost_over_the_reservation_logs_a_warning(caplog):
    huge = reply("ok", uncached=1_000_000)  # far more than a one-line prompt can reserve
    ledger = CostLedger("r", emit=False)
    with caplog.at_level(logging.WARNING, logger="docs_checker.llm"):
        await call(ScriptedModel([huge]), ledger)
    (record,) = [r for r in caplog.records if r.name == "docs_checker.llm"]
    assert record.levelno == logging.WARNING
    text = record.getMessage()
    assert "judge" in text and HAIKU in text
    assert f"{ledger.entries[0].cost_usd:.8f}" in text


def test_prompt_chars_counts_text_blocks_and_tool_calls():
    tool_call = {"name": "search_code", "args": {"query": "vault"}, "id": "t1", "type": "tool_call"}
    blocks = [{"type": "text", "text": "abc"}]
    assert prompt_chars([HumanMessage("abcd")]) == 4
    assert prompt_chars([HumanMessage(blocks)]) == len(json.dumps(blocks))
    with_call = AIMessage(content="", tool_calls=[tool_call])
    assert prompt_chars([with_call]) >= len(json.dumps(with_call.tool_calls))


async def test_request_id_hook_reads_bedrock_header():
    from docs_checker.llm import _recording

    with _recording() as recorder:
        await request_id_hook(httpx2.Response(200, headers={"x-amzn-requestid": "abc"}))
    assert recorder["request_id"] == "abc"
