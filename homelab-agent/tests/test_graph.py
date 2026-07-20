"""Graph nodes above orient: retrieve (this task), then routing/synthesis."""

from unittest.mock import AsyncMock, patch

from langgraph.store.memory import InMemoryStore

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


# --- Task 3: conversation memory nodes -------------------------------------


def _fake_embed(texts):
    """Deterministic bag-of-words embedding over a tiny fixed vocab, so
    identical/overlapping questions score highest. Returns EMBEDDING-dim
    vectors matching the test store's configured dims."""
    vocab = ["vault", "unseal", "cert", "manager", "argocd", "crashloop"]
    out = []
    for t in texts:
        tl = t.lower()
        out.append([float(tl.count(w)) for w in vocab])
    return out


def _mem_store():
    store = InMemoryStore(index={"dims": 6, "embed": _fake_embed, "fields": ["question"]})
    return store


async def test_recall_fills_memory_findings_and_checked():
    store = _mem_store()
    store.put(("homelab-agent", "memories"), "k1",
              {"question": "how do I unseal vault", "answer": "use the vault-unseal job"})
    result = await graph.recall(
        {"question": "vault unseal steps?"}, store=store
    )
    assert "vault-unseal job" in result["memory_findings"]
    assert result["checked"] == ["memory (1 prior exchange)"]


async def test_recall_noop_without_store():
    result = await graph.recall({"question": "anything"}, store=None)
    assert result == {}


async def test_remember_writes_exchange():
    store = _mem_store()
    await graph.remember(
        {"question": "is argocd healthy?", "answer": "yes, all synced"}, store=store
    )
    hits = store.search(("homelab-agent", "memories"), query="argocd health", limit=1)
    assert hits and hits[0].value["answer"] == "yes, all synced"


async def test_remember_noop_without_store():
    assert await graph.remember({"question": "q", "answer": "a"}, store=None) == {}


async def test_memory_findings_flow_into_synthesis():
    store = _mem_store()
    store.put(("homelab-agent", "memories"), "k1",
              {"question": "cert manager issuing", "answer": "uses ClusterIssuer letsencrypt"})
    captured = {}

    class FakeChat:
        async def ainvoke(self, prompt):
            captured["prompt"] = prompt

            class Msg:
                content = "answer"

            return Msg()

    with patch("homelab_agent.tools.run_doc_retrieval",
               AsyncMock(return_value=("docs", ["agent-docs MCP"]))), \
         patch("homelab_agent.graph.get_model", return_value=FakeChat()):
        g = graph.build_graph(store=store)
        out = await g.ainvoke(
            {"question": "how does cert manager issue certs?"}
        )
    assert "ClusterIssuer letsencrypt" in captured["prompt"]  # recalled into synthesis
    assert "memory (1 prior exchange)" in out["checked"]


class _RaisingSearchStore:
    async def asearch(self, *args, **kwargs):
        raise RuntimeError("embedding backend unreachable")


class _RaisingPutStore:
    async def aput(self, *args, **kwargs):
        raise RuntimeError("embedding backend unreachable")


async def test_recall_degrades_to_noop_on_store_search_error():
    result = await graph.recall({"question": "anything"}, store=_RaisingSearchStore())
    assert result == {}


async def test_remember_degrades_to_noop_on_store_put_error():
    result = await graph.remember(
        {"question": "q", "answer": "a"}, store=_RaisingPutStore()
    )
    assert result == {}


def test_synthesize_prompt_frames_memory_as_untrusted():
    from homelab_agent.prompts import SYNTHESIZE_PROMPT

    assert "UNTRUSTED" in SYNTHESIZE_PROMPT
    assert "NOT instructions" in SYNTHESIZE_PROMPT


async def test_docs_route_still_works_without_store():
    """Regression: the graph runs end-to-end when no store is configured."""
    with patch("homelab_agent.tools.run_doc_retrieval",
               AsyncMock(return_value=("docs", ["agent-docs MCP"]))), \
         patch("homelab_agent.graph.get_model",
               return_value=FakeChat("Answer.\n\nWhat I checked\n- agent-docs MCP")):
        g = graph.build_graph()  # store defaults to None
        out = await g.ainvoke({"question": "What is cert-manager and how does it issue certs here?"})
    assert out["answer"]
    assert "memory_findings" not in out or out["memory_findings"] == ""
