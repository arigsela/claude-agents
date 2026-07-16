"""Graph nodes above orient: retrieve (this task), then routing/synthesis."""

from unittest.mock import AsyncMock, patch

from homelab_agent import graph


async def test_retrieve_node_fills_findings_and_checked():
    fake = AsyncMock(return_value=("cert-manager is deployed via Argo CD",
                                   ["agent-docs MCP (get_file_contents / search_code)"]))
    with patch("homelab_agent.tools.run_doc_retrieval", fake):
        result = await graph.retrieve(
            {"question": "What is cert-manager?", "route": "docs"}
        )
    fake.assert_awaited_once_with("What is cert-manager?", "docs")
    assert result["doc_findings"] == "cert-manager is deployed via Argo CD"
    assert result["checked"] == ["agent-docs MCP (get_file_contents / search_code)"]


async def test_graph_runs_orient_then_retrieve():
    fake = AsyncMock(return_value=("findings", ["agent-docs MCP"]))
    # Task 6 wires retrieve -> synthesize (docs path), so this end-to-end
    # invoke now also reaches the model; patch get_model here too.
    with patch("homelab_agent.tools.run_doc_retrieval", fake), \
         patch("homelab_agent.graph.get_model", return_value=FakeChat("answer")):
        g = graph.build_graph()
        out = await g.ainvoke({"question": "What is cert-manager and how does it issue certs here?"})
    assert out["route"] == "docs"
    assert out["doc_findings"] == "findings"
    assert out["checked"] == ["agent-docs MCP"]


# --- Task 6: full pipeline ---------------------------------------------------

class FakeChat:
    """Stands in for ChatAnthropic: returns queued replies in order."""

    def __init__(self, *replies):
        self._replies = list(replies)

    async def ainvoke(self, _input):
        class Msg:
            pass

        msg = Msg()
        msg.content = self._replies.pop(0)
        return msg


async def test_delegate_k8s_node():
    with patch("homelab_agent.tools.ask_k8s_reader",
               AsyncMock(return_value="vault-0 Running, 0 restarts")):
        result = await graph.delegate_k8s({"question": "is vault healthy?"})
    assert result["live_findings"] == "vault-0 Running, 0 restarts"
    assert result["checked"] == ["k8s-reader (A2A delegate)"]


async def test_drift_check_parses_bullets():
    fake = FakeChat("- docs say 3 replicas, cluster shows 1")
    with patch("homelab_agent.graph.get_model", return_value=fake):
        result = await graph.drift_check(
            {"doc_findings": "3 replicas", "live_findings": "1 replica"}
        )
    assert result["drift"] == ["docs say 3 replicas, cluster shows 1"]


async def test_drift_check_preserves_leading_negative_numbers():
    # lstrip("- ") is a char-set strip: it would also eat the leading "-"
    # off "-1 replica...", mangling "-1" into "1". Must preserve it.
    fake = FakeChat("- -1 replica vs 3 documented")
    with patch("homelab_agent.graph.get_model", return_value=fake):
        result = await graph.drift_check(
            {"doc_findings": "3 replicas", "live_findings": "-1 replica"}
        )
    assert result["drift"] == ["-1 replica vs 3 documented"]


async def test_drift_check_none_means_empty():
    fake = FakeChat("NONE")
    with patch("homelab_agent.graph.get_model", return_value=fake):
        result = await graph.drift_check(
            {"doc_findings": "x", "live_findings": "x"}
        )
    assert result["drift"] == []


async def test_synthesize_formats_answer():
    fake = FakeChat("Vault is healthy.\n\nWhat I checked\n- agent-docs MCP")
    with patch("homelab_agent.graph.get_model", return_value=fake):
        result = await graph.synthesize({
            "question": "q", "doc_findings": "d", "live_findings": "l",
            "drift": [], "checked": ["agent-docs MCP"],
        })
    assert "What I checked" in result["answer"]


def test_needs_live_routing():
    assert graph.needs_live({"route": "live"}) == "live"
    assert graph.needs_live({"route": "docs"}) == "docs"
    assert graph.needs_live({"route": "ownership"}) == "docs"


async def test_docs_route_end_to_end_skips_delegate():
    """docs question: delegate_k8s and drift_check must NOT run."""
    delegate = AsyncMock(return_value="SHOULD NOT BE CALLED")
    with patch("homelab_agent.tools.run_doc_retrieval",
               AsyncMock(return_value=("cert-manager docs", ["agent-docs MCP"]))), \
         patch("homelab_agent.tools.ask_k8s_reader", delegate), \
         patch("homelab_agent.graph.get_model",
               return_value=FakeChat("Answer.\n\nWhat I checked\n- agent-docs MCP")):
        g = graph.build_graph()
        out = await g.ainvoke(
            {"question": "What is cert-manager and how does it issue certs here?"}
        )
    delegate.assert_not_awaited()
    assert out["route"] == "docs"
    assert out["checked"] == ["agent-docs MCP"]
    assert "drift" not in out or out["drift"] == []
    assert "What I checked" in out["answer"]


async def test_live_route_end_to_end_runs_delegate_and_drift():
    """live question: full path, checked accumulates BOTH sources."""
    with patch("homelab_agent.tools.run_doc_retrieval",
               AsyncMock(return_value=("runbook says 3 replicas", ["agent-docs MCP"]))), \
         patch("homelab_agent.tools.ask_k8s_reader",
               AsyncMock(return_value="1 replica running")), \
         patch("homelab_agent.graph.get_model",
               return_value=FakeChat(
                   "- docs say 3 replicas, cluster shows 1",   # drift_check call
                   "Drift found.\n\nWhat I checked\n- both",    # synthesize call
               )):
        g = graph.build_graph()
        out = await g.ainvoke({"question": "Is the argo-cd control plane healthy?"})
    assert out["route"] == "live"
    assert out["checked"] == ["agent-docs MCP", "k8s-reader (A2A delegate)"]
    assert out["drift"] == ["docs say 3 replicas, cluster shows 1"]
    assert "What I checked" in out["answer"]
