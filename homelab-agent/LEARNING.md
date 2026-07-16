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

---

## 4. `create_react_agent` vs a hand-built graph (`tools.py`)

**What:** `create_react_agent` is LangGraph's prebuilt agent loop: model
with tools bound → if the reply contains tool calls, a `ToolNode` executes
them and loops back (`tools_condition` decides) → otherwise finish.

**Why both exist:** the prebuilt loop is perfect when the shape is "call
tools until done." A hand-built `StateGraph` is better when you need
deterministic, auditable routing between distinct stages.

**Here — we deliberately use BOTH:** the outer graph (`graph.py`) is
hand-built because explicit routing/drift stages are the reason this
migration chose LangGraph. Inside the single `retrieve` node,
`_build_doc_agent()` uses `create_react_agent` over the MCP doc tools,
because the atlas→index→app traversal is exactly the generic ReAct shape.
`ToolNode` and `tools_condition` are inside that prebuilt — we get them
without wiring them by hand.

**What you just learned:** prebuilts and hand-built graphs compose — a
whole prebuilt agent can live inside one node of your own graph.

---

## 5. Conditional edges (`graph.py`)

**What:** `add_conditional_edges(source, fn, mapping)` — after `source`
runs, LangGraph calls `fn(state)`; the returned label picks the next node
from `mapping`.

**Why it exists:** it makes branching a first-class, inspectable part of the
graph instead of an if-statement buried in a prompt or a node body.

**Here:** `needs_live()` after `retrieve` sends `route == "live"` through
`delegate_k8s → drift_check → synthesize`, everything else straight to
`synthesize`. Two properties worth noticing: (1) this is a decision, not a
fan-out — exactly one branch executes, so there's no join node that could
wait forever on the path that didn't run; (2) `drift_check` sits only on
the live branch, so `doc_findings` AND `live_findings` are guaranteed
present when it executes. `tests/test_graph.py` asserts the docs path never
awaits the delegate.

**What you just learned:** routing = a pure function of state + a label→node
map, and putting a node "behind" a branch is how you encode its
preconditions structurally.

---

## 6. Checkpointer & threads (`checkpointer.py`)

**What:** a checkpointer saves the graph state after every step, keyed by a
`thread_id` you pass at invoke time (`config={"configurable": {"thread_id": ...}}`).
`graph.get_state(config)` reads it back; a new invoke on the same thread
resumes from it.

**Why it exists:** without one, a compiled graph is stateless between
invocations — a pod restart or a follow-up question starts from nothing.
It is also the substrate for HITL interrupts (pause, persist, resume).

**Here:** `get_checkpointer()` returns kagent's `KAgentCheckpointer`
(controller-backed, survives restarts) only when `KAGENT_URL` is present —
i.e. when kagent injected its env into the BYO pod. Locally it returns
`None` and tests demonstrate the concept with `MemorySaver`
(`tests/test_checkpointer.py`). The A2A executor uses the caller's
`context_id` as the `thread_id`, so one A2A conversation = one thread.

**What you just learned:** persistence is a compile-time plug-in
(`compile(checkpointer=...)`) plus a per-call address (`thread_id`) — the
graph code itself never changes.

---

## 7. The A2A serving contract (`server.py`, `executor.py`)

**What:** kagent deploys a BYO image and talks to it over A2A on port 8080:
`GET /.well-known/agent.json` for discovery (the *agent card*: name,
skills, capabilities) and JSON-RPC `POST /` with `message/send` for work.

**Why it exists:** A2A is how kagent's control plane (UI, `/mcp` endpoint,
other agents) invokes ANY agent uniformly — Declarative or BYO.

**Here:** `server.py` mounts the a2a-sdk's `A2AStarletteApplication` inside
FastAPI (pattern borrowed from oncall-crewai) and carries over the three
skills from the old agent's `a2aConfig` verbatim. `executor.py` is the
actual bridge: extract the question from the A2A message → 
`graph.ainvoke({"question": ...}, config={"configurable": {"thread_id": context_id}})`
→ emit working/artifact/completed events. Note the join point of two earlier
concepts: the A2A `context_id` becomes the checkpointer `thread_id`.

**What you just learned:** the graph is the brain; A2A is the socket; the
executor is the adapter between them — and it's ~100 lines, not a framework.
