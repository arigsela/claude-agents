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


def test_none_resets_the_accumulator():
    """The reset sentinel: a node returning None for an accumulator field
    clears it instead of appending, unlike operator.add (which would raise
    on None and, if it didn't, would still append forever). This is what
    `orient` uses at the start of every turn to stop `checked`/`drift` from
    leaking across turns on a persisted checkpointer thread (see graph.py)."""

    def node_a(state: AgentState) -> dict:
        return {"checked": ["first"]}

    def node_b(state: AgentState) -> dict:
        return {"checked": None}  # reset sentinel

    def node_c(state: AgentState) -> dict:
        return {"checked": ["second"]}

    g = StateGraph(AgentState)
    g.add_node("a", node_a)
    g.add_node("b", node_b)
    g.add_node("c", node_c)
    g.set_entry_point("a")
    g.add_edge("a", "b")
    g.add_edge("b", "c")
    g.add_edge("c", END)

    out = g.compile().invoke({"question": "q"})
    # Only "second" survives: node_b's None wiped node_a's "first" before
    # node_c appended, so entries from before the reset never leak through.
    assert out["checked"] == ["second"]
