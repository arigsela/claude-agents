import anthropic
import httpx2
import pytest
from langchain_core.messages import HumanMessage

from docs_checker.config import NODES, load_settings
from docs_checker.ledger import CostLedger
from docs_checker.levers import Levers
from docs_checker.llm import RetryBudget, call_model, request_id_hook
from docs_checker.models import AnthropicModels, no_tools_choice
from tests.test_llm import message_body

SONNET = "claude-sonnet-5-5"
HAIKU = "claude-haiku-5-5"


def models_for(levers: Levers, **kwargs) -> AnthropicModels:
    settings = load_settings({"DOCS_CHECKER_LEVERS": ",".join(_names(levers)) or "none"})
    return AnthropicModels(settings.node_models, levers, http_timeout_s=60.0, **kwargs)


def _names(levers: Levers) -> list[str]:
    return [n for n in Levers.names() if getattr(levers, n)]


def test_default_node_models():
    models = load_settings({}).node_models
    assert tuple(models) == NODES
    assert {n: m.model for n, m in models.items()} == {
        "intake": HAIKU,
        "extract": HAIKU,
        "judge": HAIKU,
        "judge_escalate": SONNET,
        "fix": HAIKU,
        "report": HAIKU,
    }


def test_right_size_off_puts_sonnet_on_every_node():
    settings = load_settings({"DOCS_CHECKER_LEVERS": "-right_size"})
    assert {m.model for m in settings.node_models.values()} == {SONNET}
    on = load_settings({"DOCS_CHECKER_LEVERS": "right_size"})
    assert on.node_models["judge"].model == HAIKU


def test_retry_limits_on_leaves_retries_to_call_model():
    sdk = models_for(Levers.all_on()).get("judge")._async_client
    assert sdk.max_retries == 0
    assert sdk.timeout == 60.0


async def test_retry_limits_off_is_the_stacked_default():
    levers = Levers.without("retry_limits")
    chat = models_for(levers).get("judge")
    assert chat.max_retries == 2 and chat._async_client.max_retries == 2  # SDK retries
    assert chat._async_client.timeout is None
    # call_model's own budget is still 3 attempts: up to 3 x 3 requests on the wire.
    assert RetryBudget().max_attempts == 3
    hits: list[int] = []

    # Retryable 529s are retried by the SDK 2 times per call_model attempt.
    def overloaded(request: httpx2.Request) -> httpx2.Response:
        hits.append(1)
        return httpx2.Response(
            529, json={"type": "error", "error": {"type": "overloaded_error", "message": "o"}}
        )

    stacked = models_for(levers, transport=httpx2.MockTransport(overloaded)).get("judge")

    async def no_sleep(_):
        return None

    with pytest.raises(anthropic.APIStatusError):
        await call_model(
            stacked,
            [HumanMessage("q")],
            node="judge",
            model_name=HAIKU,
            ledger=CostLedger("r", emit=False),
            budget=RetryBudget(max_attempts=3),
            max_tokens=256,
            sleep=no_sleep,
        )
    assert len(hits) == 9


def test_tools_off_payload_has_type_none():
    from langchain_core.tools import tool

    @tool
    def get_file_contents(path: str) -> str:
        """Read a file."""
        return path

    bound = (
        models_for(Levers.all_on())
        .get("judge")
        .bind_tools([get_file_contents], tool_choice=no_tools_choice())
    )
    payload = bound.bound._get_request_payload([HumanMessage("q")], **bound.kwargs)
    assert payload["tool_choice"] == {"type": "none"}
    assert payload["tools"][0]["name"] == "get_file_contents"


async def test_request_id_reaches_the_ledger_through_anthropic_models():
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, headers={"request-id": "req_models"}, json=message_body("ok"))

    models = models_for(
        Levers.all_on(), transport=httpx2.MockTransport(handler), on_response=request_id_hook
    )
    ledger = CostLedger("r", emit=False)
    await call_model(
        models.get("judge"),
        [HumanMessage("q")],
        node="judge",
        model_name=models.name("judge"),
        ledger=ledger,
        budget=RetryBudget(max_attempts=3),
        max_tokens=256,
    )
    assert ledger.entries[0].request_id == "req_models"
