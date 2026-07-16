"""Checkpointer wiring: on under kagent, off (None) everywhere else."""

from langgraph.checkpoint.memory import MemorySaver

from homelab_agent.checkpointer import get_checkpointer


def test_returns_none_without_kagent_env(monkeypatch):
    monkeypatch.delenv("KAGENT_URL", raising=False)
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
