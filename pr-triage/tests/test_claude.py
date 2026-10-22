"""The Claude calls must work on the default model (Claude Haiku 5.5) and stay swappable.

Run: uv run --project pr-triage --with pytest pytest pr-triage/tests -q
"""
from pathlib import Path
from types import SimpleNamespace

import pytest

from pr_triage import __main__ as cli
from pr_triage import claude


class FakeMessages:
    def __init__(self, resp):
        self.resp, self.kwargs = resp, None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return self.resp


def fake_client(content, stop_reason="end_turn"):
    return SimpleNamespace(messages=FakeMessages(SimpleNamespace(content=content, stop_reason=stop_reason)))


def thinking():
    # Claude Haiku 5.5 thinks by default; the block's text is empty unless display is "summarized".
    return SimpleNamespace(type="thinking", thinking="", signature="sig")


def text(s):
    return SimpleNamespace(type="text", text=s)


def test_the_default_model_is_haiku_5_5_everywhere():
    assert claude.DEFAULT_MODEL == "claude-haiku-5-5"
    root = Path(cli.__file__).parents[2]
    assert f"default: {claude.DEFAULT_MODEL}" in (root / "action.yml").read_text()
    assert "claude-haiku-4-5" not in Path(cli.__file__).read_text()  # the CLI uses DEFAULT_MODEL


def test_the_answer_is_read_after_a_thinking_block():
    client = fake_client([thinking(), text('{"decision": "skim", "reason": "one app"}')])
    assert claude.claude_decide(client, "claude-haiku-5-5", {"title": "t"}, None) == ("skim", "one app")


def test_the_request_leaves_room_for_thinking_and_sends_nothing_haiku_4_5_rejects():
    client = fake_client([text('{"bullets": ["a"]}')])
    claude.claude_note(client, "claude-haiku-5-5", {"title": "t"}, "read", ["rules"])
    sent = client.messages.kwargs
    assert sent["model"] == "claude-haiku-5-5"
    assert sent["max_tokens"] >= 8192
    assert sent["messages"][-1]["role"] == "user"
    # thinking budgets, sampling and effort 400 on one of the two models; leave them to the defaults.
    assert not {"thinking", "temperature", "top_p", "top_k"} & sent.keys()
    assert "effort" not in sent["output_config"]


@pytest.mark.parametrize("stop", ["max_tokens", "refusal"])
def test_a_cut_off_or_declined_answer_is_an_error(stop):
    client = fake_client([thinking()], stop_reason=stop)
    with pytest.raises(claude.ClaudeError, match=f"stop_reason={stop}"):
        claude.claude_decide(client, "claude-haiku-5-5", {"title": "t"}, None)
