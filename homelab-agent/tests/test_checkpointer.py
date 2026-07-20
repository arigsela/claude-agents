"""Checkpointer wiring: on under kagent, off (None) everywhere else."""

import sys

from langgraph.checkpoint.memory import MemorySaver

from homelab_agent.checkpointer import get_checkpointer


def _reset_kagent_modules():
    """kagent.core._config reads KAGENT_URL/NAME/NAMESPACE into module-level
    globals at first import (not re-read per KAgentConfig() call), so tests
    that vary these vars across cases must force a fresh import to observe
    monkeypatched values — otherwise whichever kagent-env scenario runs
    first in the process permanently wins for the rest of the test session.
    """
    for name in list(sys.modules):
        if name == "kagent" or name.startswith("kagent."):
            del sys.modules[name]


def test_returns_none_without_kagent_env(monkeypatch):
    monkeypatch.delenv("KAGENT_URL", raising=False)
    assert get_checkpointer() is None


def test_returns_kagent_checkpointer_under_kagent_env(monkeypatch):
    """KAgentConfig() requires KAGENT_URL, KAGENT_NAME, KAGENT_NAMESPACE
    (see kagent.core._config.KAgentConfig.__init__) — all three must be set
    for get_checkpointer() to reach the real KAgentCheckpointer branch.
    """
    _reset_kagent_modules()
    monkeypatch.setenv("KAGENT_URL", "http://kagent-controller.kagent:8083")
    monkeypatch.setenv("KAGENT_NAME", "homelab-knowledge")
    monkeypatch.setenv("KAGENT_NAMESPACE", "kagent")

    from kagent.langgraph import KAgentCheckpointer

    checkpointer = get_checkpointer()

    assert checkpointer is not None
    assert isinstance(checkpointer, KAgentCheckpointer)


def test_returns_none_on_partial_kagent_env(monkeypatch):
    """KAGENT_URL alone is not enough: KAgentConfig() also requires
    KAGENT_NAME and KAGENT_NAMESPACE, and raises ValueError without them.
    get_checkpointer()'s contract is checkpointer-or-None — it must degrade
    to None here, not propagate that exception."""
    _reset_kagent_modules()
    monkeypatch.setenv("KAGENT_URL", "http://kagent-controller.kagent:8083")
    monkeypatch.delenv("KAGENT_NAME", raising=False)
    monkeypatch.delenv("KAGENT_NAMESPACE", raising=False)

    assert get_checkpointer() is None


async def test_threads_persist_state_across_invocations():
    """The concept the checkpointer buys us, demonstrated with MemorySaver:
    same thread_id → the graph resumes with remembered state."""
    from unittest.mock import AsyncMock, patch

    from homelab_agent.graph import build_graph

    with patch("homelab_agent.tools.run_doc_retrieval",
               AsyncMock(return_value=("findings", ["agent-docs MCP"]))), \
         patch("homelab_agent.graph.get_model") as mock_model:
        reply = AsyncMock()
        reply.return_value.content = "answer"
        mock_model.return_value.ainvoke = reply

        g = build_graph(checkpointer=MemorySaver())
        config = {"configurable": {"thread_id": "session-1"}}
        # Async nodes in the graph → ainvoke; get_state is sync.
        await g.ainvoke({"question": "What is cert-manager?"}, config=config)

        snapshot = g.get_state(config)
    assert snapshot.values["question"] == "What is cert-manager?"
    assert snapshot.values["answer"] == "answer"


async def test_checked_does_not_accumulate_across_turns_on_same_thread():
    """Regression for the persisted-thread bug: with a checkpointer active,
    a second invoke on the SAME thread_id resumes stored channel values.
    Without a reset, `checked` (an accumulator field) would keep growing
    turn over turn and pollute every follow-up answer's "What I checked"
    section with entries from earlier questions. orient's reset sentinel
    (see graph.py / state.py's `accumulate`) must clear it each turn."""
    from unittest.mock import AsyncMock, patch

    from homelab_agent.graph import build_graph

    with patch(
        "homelab_agent.tools.run_doc_retrieval",
        AsyncMock(
            side_effect=[
                ("cert-manager findings", ["agent-docs MCP turn1"]),
                ("vault findings", ["agent-docs MCP turn2"]),
            ]
        ),
    ), patch("homelab_agent.graph.get_model") as mock_model:
        reply = AsyncMock()
        reply.return_value.content = "answer"
        mock_model.return_value.ainvoke = reply

        g = build_graph(checkpointer=MemorySaver())
        config = {"configurable": {"thread_id": "session-multi-turn"}}

        # Both questions keyword-route to "docs" (no delegate_k8s/drift_check).
        await g.ainvoke({"question": "What is cert-manager?"}, config=config)
        result2 = await g.ainvoke({"question": "What is vault?"}, config=config)

    # Only turn 2's entry — turn 1's must not have leaked through.
    assert result2["checked"] == ["agent-docs MCP turn2"]


async def test_live_findings_does_not_leak_into_later_docs_turn_on_same_thread():
    """Companion regression to the checked/drift leak: live_findings is a
    plain scalar written only by delegate_k8s on the live path. Without a
    turn-start reset it survives in the persisted thread's state after a
    live turn and leaks into a later docs turn's synthesize prompt — an
    internally inconsistent answer where "What I checked" (already reset)
    omits k8s-reader but the "Live cluster findings" section still shows
    stale data from the earlier live turn."""
    from unittest.mock import AsyncMock, patch

    from homelab_agent.graph import build_graph

    class FakeChat:
        def __init__(self, *replies):
            self._replies = list(replies)

        async def ainvoke(self, _input):
            class Msg:
                pass

            msg = Msg()
            msg.content = self._replies.pop(0)
            return msg

    # 3 model calls total: turn 1's drift_check + synthesize, turn 2's synthesize.
    fake_chat = FakeChat(
        "NONE",
        "Vault is healthy.\n\nWhat I checked\n- k8s-reader",
        "cert-manager is deployed via Argo CD.\n\nWhat I checked\n- agent-docs MCP",
    )

    with patch(
        "homelab_agent.tools.run_doc_retrieval",
        AsyncMock(
            side_effect=[
                ("vault runbook says 3 replicas", ["agent-docs MCP"]),
                ("cert-manager docs", ["agent-docs MCP"]),
            ]
        ),
    ), patch(
        "homelab_agent.tools.ask_k8s_reader", AsyncMock(return_value="vault-0 running")
    ), patch("homelab_agent.graph.get_model", return_value=fake_chat):
        g = build_graph(checkpointer=MemorySaver())
        config = {"configurable": {"thread_id": "session-live-then-docs"}}

        # Turn 1: live-route question -> delegate_k8s writes live_findings.
        await g.ainvoke({"question": "Is the argo-cd control plane healthy?"}, config=config)
        # Turn 2: docs-route question on the SAME thread -> delegate_k8s must NOT run,
        # so live_findings must not still hold turn 1's value.
        result2 = await g.ainvoke({"question": "What is cert-manager?"}, config=config)

    assert result2.get("live_findings", "") == ""
