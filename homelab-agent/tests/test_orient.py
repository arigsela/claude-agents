"""orient = the first node: classify the question into docs/live/ownership.
Deterministic keyword pass first; cheap-LLM fallback only for ambiguity."""

from unittest.mock import MagicMock, patch

import pytest

from homelab_agent.graph import _keyword_route, orient


# --- deterministic keyword pass -------------------------------------------

@pytest.mark.parametrize(
    "question,expected",
    [
        ("chores-tracker-backend is CrashLooping — what does its runbook say?", "live"),
        ("cert-manager Certificates are stuck pending — walk me through the runbook.", "live"),
        ("Is the argo-cd control plane healthy?", "live"),
        ("Who owns chores-tracker-backend and what does it depend on?", "ownership"),
        ("What system is vault part of?", "ownership"),
        ("What is cert-manager and how does it issue certs here?", "docs"),
        ("Where does vault store its config and how is it unsealed?", "docs"),
    ],
)
def test_keyword_route(question, expected):
    assert _keyword_route(question) == expected


def test_keyword_route_returns_none_when_ambiguous():
    # No live/ownership keyword and no clear docs phrasing → defer to LLM
    assert _keyword_route("billing-api rollout question") is None


# --- the node --------------------------------------------------------------

def test_orient_uses_keywords_without_llm():
    with patch("homelab_agent.graph.get_router_model") as mock_model:
        result = orient({"question": "Who owns chores-tracker-backend?"})
    mock_model.assert_not_called()
    assert result["route"] == "ownership"


def test_orient_falls_back_to_llm_for_ambiguous():
    fake = MagicMock()
    fake.invoke.return_value = MagicMock(content="live")
    with patch("homelab_agent.graph.get_router_model", return_value=fake):
        result = orient({"question": "billing-api rollout question"})
    assert result["route"] == "live"


def test_orient_defaults_to_docs_on_llm_garbage_or_error():
    fake = MagicMock()
    fake.invoke.return_value = MagicMock(content="banana")
    with patch("homelab_agent.graph.get_router_model", return_value=fake):
        assert orient({"question": "billing-api rollout question"})["route"] == "docs"

    fake.invoke.side_effect = RuntimeError("api down")
    with patch("homelab_agent.graph.get_router_model", return_value=fake):
        assert orient({"question": "billing-api rollout question"})["route"] == "docs"


# --- minimal graph: orient wired into a real StateGraph ---------------------

async def test_build_graph_runs_orient():
    from unittest.mock import AsyncMock, patch

    from homelab_agent.graph import build_graph

    # The graph now contains async nodes → must use ainvoke, not invoke.
    with patch("homelab_agent.tools.run_doc_retrieval",
               AsyncMock(return_value=("", []))):
        g = build_graph()
        out = await g.ainvoke({"question": "Is the argo-cd control plane healthy?"})
    assert out["route"] == "live"
