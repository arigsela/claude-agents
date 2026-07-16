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

---

## 2. StateGraph & nodes (`graph.py`)

**What:** a `StateGraph` is a builder: you `add_node(name, fn)`, connect
names with `add_edge`, pick an entry point, and `compile()` it into a
runnable you can `invoke` / `ainvoke`.

**Why it exists:** the graph makes control flow *explicit and auditable* —
you can read `build_graph()` and know every path a request can take, unlike
a monolithic prompt loop. That auditability is the reason this migration
chose LangGraph.

**Here:** `orient` in `src/homelab_agent/graph.py` is the first node: a
plain function taking `AgentState` and returning `{"route": ..., "plan": ...}`.
Note the hybrid inside it — a deterministic keyword pass first, a cheap LLM
(`get_router_model()`) only for ambiguity, and a safe default (`docs`) on
LLM failure. Nodes may contain arbitrary logic; LangGraph only cares about
the `state -> partial update` contract.

**What you just learned:** a node is just a function; the graph is just
declared wiring; `compile()` turns the declaration into a runnable.

---

## 3. MCP tools as LangGraph tools & the A2A client (`tools.py`)

**What:** `MultiServerMCPClient` (from `langchain-mcp-adapters`) connects to
one or more MCP servers and returns their tools as LangChain `BaseTool`s.
A2A is a separate protocol — agent-to-agent JSON-RPC over HTTP — and calling
another agent is just an HTTP POST (`message/send`).

**Why they exist:** MCP standardizes "here are tools you can call" between
processes; the adapter means LangGraph code never speaks MCP directly. A2A
standardizes "ask another agent a question and get its answer."

**Here:** kagent does NOT auto-inject MCP tools into BYO containers, so
`get_doc_tools()` in `src/homelab_agent/tools.py` wires the same two
in-cluster MCP servers the old agent used (`agent_docs`, `backstage_catalog`),
with URLs/auth from env. Delegation to k8s-reader — a `type: Agent` CRD tool
in the old Declarative spec — becomes `ask_k8s_reader()`: an explicit A2A
client call a graph node makes. Same capability, now visible in code.

**What you just learned:** in a BYO agent, *you* own the integration edges;
MCP and A2A are the two standard sockets this stack plugs into.
