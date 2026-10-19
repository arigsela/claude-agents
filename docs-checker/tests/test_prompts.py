"""Lever 1 at the wire: what ChatAnthropic would send, built offline (no request is made).

``_get_request_payload`` is private to langchain-anthropic 1.7; if it moves, this
test should move with it rather than be deleted, because it is the only check
that the breakpoint, the tool order and the per-node effort reach the request.
"""

from langchain_core.messages import HumanMessage

from docs_checker import prompts
from docs_checker.config import load_settings
from docs_checker.gate import RecordingGate
from docs_checker.models import AnthropicModels
from docs_checker.tools import ToolBelt
from tests.fakes import FAKE_BINDINGS, fake_tools_by_server


def payload(node: str, messages, tools=None):
    settings = load_settings({})
    model = AnthropicModels(
        settings.node_models, settings.levers, http_timeout_s=settings.http_timeout_s
    ).get(node)
    if tools:
        model = model.bind_tools(tools)
        return model.bound._get_request_payload(messages, **model.kwargs)
    return model._get_request_payload(messages)


def test_the_system_prompt_is_a_cached_frozen_prefix():
    system = prompts.AGENT_DESCRIPTION
    question = [HumanMessage("check base-apps/vault/docs.md")]
    first = payload("intake", [prompts.system_message(system, cache=True), *question])
    second = payload("intake", [prompts.system_message(system, cache=True), *question])

    assert first["system"] == second["system"]  # byte-identical across runs
    assert first["system"][-1]["cache_control"] == {"type": "ephemeral"}
    assert first["model"] == "claude-haiku-5-5"
    assert first["output_config"]["effort"] == "low"  # lever 6: effort per node


def test_node_tools_are_sent_sorted_and_scoped():
    belt = ToolBelt(fake_tools_by_server(), RecordingGate(), bindings=FAKE_BINDINGS)
    sent = payload(
        "judge_escalate",
        [prompts.system_message(prompts.AGENT_DESCRIPTION, cache=True), HumanMessage("q")],
        tools=belt.schemas_for("scope"),
    )
    assert [t["name"] for t in sent["tools"]] == ["get_commit", "get_file_contents", "list_commits"]
    assert sent["model"] == "claude-sonnet-5-5"
