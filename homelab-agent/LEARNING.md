# LEARNING.md — LangGraph, explained through this agent

A concept glossary for a LangGraph newcomer, in the order the code was
built. Each section: what the concept is, why it exists, and exactly where
`homelab-agent` uses it.

Concepts covered as the build progresses:

1. State & reducers — `state.py`
2. StateGraph & nodes — `graph.py` (orient)
3. MCP tools as LangGraph tools & the A2A client — `tools.py`
4. `create_react_agent` vs a hand-built graph — `tools.py` (retrieve)
5. Conditional edges — `graph.py` (routing after retrieve)
6. Checkpointer & threads — `checkpointer.py`
7. The A2A serving contract — `server.py` / `executor.py`

(Sections are appended by the task that introduces each concept.)

---

## 1. State & reducers (`state.py`)

**What:** LangGraph threads ONE typed dict — the State — through every node.
A node is a function `state -> partial update`; LangGraph merges the update.

**Why it exists:** nodes stay pure and composable; the merge policy (not the
node) decides what happens when several nodes touch the same field.

**Here:** `AgentState` in `src/homelab_agent/state.py`. `checked` and `drift`
are `Annotated[list[str], operator.add]` — a *reducer* — so `retrieve` and
`delegate_k8s` can each append to `checked` without clobbering each other.
Every other field is written by exactly one node, so plain last-writer-wins
is safe. `tests/test_state.py` proves both behaviors with a toy 2-node graph.

**What you just learned:** state updates are *merged, not assigned*, and the
per-field reducer is where that policy lives.
