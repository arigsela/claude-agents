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
    with patch("homelab_agent.tools.run_doc_retrieval", fake):
        g = graph.build_graph()
        out = await g.ainvoke({"question": "What is cert-manager and how does it issue certs here?"})
    assert out["route"] == "docs"
    assert out["doc_findings"] == "findings"
    assert out["checked"] == ["agent-docs MCP"]
