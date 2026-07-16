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
