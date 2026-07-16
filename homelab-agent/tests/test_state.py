"""Prove the reducer semantics the design doc promises:
list fields (checked, drift) ACCUMULATE across nodes via operator.add;
scalar fields are last-writer-wins."""

from langgraph.graph import END, StateGraph

from homelab_agent.state import AgentState


def test_list_fields_accumulate_and_scalars_overwrite():
    def node_a(state: AgentState) -> dict:
        return {"checked": ["agent-docs MCP"], "route": "docs"}

    def node_b(state: AgentState) -> dict:
        return {"checked": ["k8s-reader (A2A)"], "route": "live"}

    g = StateGraph(AgentState)
    g.add_node("a", node_a)
    g.add_node("b", node_b)
    g.set_entry_point("a")
    g.add_edge("a", "b")
    g.add_edge("b", END)

    out = g.compile().invoke({"question": "q"})

    # operator.add reducer: both appends survive, in execution order
    assert out["checked"] == ["agent-docs MCP", "k8s-reader (A2A)"]
    # no reducer: the later write wins
    assert out["route"] == "live"
    # untouched keys simply aren't present (total=False)
    assert "answer" not in out


def test_drift_accumulates():
    def node_a(state: AgentState) -> dict:
        return {"drift": ["docs say 3 replicas, cluster has 1"]}

    g = StateGraph(AgentState)
    g.add_node("a", node_a)
    g.set_entry_point("a")
    g.add_edge("a", END)

    out = g.compile().invoke({"question": "q", "drift": []})
    assert out["drift"] == ["docs say 3 replicas, cluster has 1"]
