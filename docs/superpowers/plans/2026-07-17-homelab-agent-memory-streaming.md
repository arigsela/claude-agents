# homelab-agent Memory + Streaming Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add embedding-based conversation memory (Ollama `nomic-embed-text` + a Postgres/pgvector LangGraph store, with `recall`/`remember` graph nodes) and response streaming (per-node progress + token-streamed final answer) to the existing `homelab-agent/` container, bringing it to full capability parity with the Declarative `homelab-knowledge` agent.

**Architecture:** A new `memory.py` provides `get_store()` (Postgres/pgvector store with an Ollama embedding index, or `None` when unconfigured — same graceful-degradation contract as `checkpointer.get_checkpointer()`). Two thin new graph nodes — `recall` (after `orient`) and `remember` (after `synthesize`) — read/write the store, keeping the graph strictly sequential. The A2A executor is rewritten to drive the graph with `graph.astream(stream_mode=["updates","messages"])`, mapping node-completion updates to coarse progress events and `synthesize` token deltas to streamed answer events.

**Tech Stack:** Python 3.11+, LangGraph (`InMemoryStore`/`PostgresStore`, `astream`), `langchain-ollama` (`OllamaEmbeddings`), `langgraph-checkpoint-postgres` + `psycopg`, a2a-sdk 0.3.x, pytest. Design spec: `docs/superpowers/specs/2026-07-17-homelab-agent-memory-streaming-design.md`.

## Global Constraints

Every task's requirements implicitly include all of these:

- **Scope:** create/modify files only under `homelab-agent/` (plus checking boxes in this plan). No `arigsela/kubernetes` changes; no touching other projects. **Never `git add` the untracked `AGENTS.md` at the repo root** — commit only `homelab-agent/` paths (use explicit pathspecs, e.g. `git add homelab-agent/...`).
- **Working dir:** all commands run from `/Users/arisela/git/claude-agents/homelab-agent/` with the venv active: `source .venv/bin/activate`.
- **Config-driven:** every new endpoint/DSN/model/tunable is read from env in `config.py`; cluster URLs appear only as `config.py` defaults and in README docs.
- **Graceful degradation (mirror the checkpointer):** memory is **off when unconfigured** — no `MEMORY_DB_URL` (or an unreachable/broken store/embeddings) → `get_store()` returns `None`, and `recall`/`remember` are no-ops. `get_store()` must **never raise** out of the function.
- **Sequential-graph correctness:** `recall`/`remember` are single-in/single-out nodes on the linear path; no fan-out/fan-in; every node still runs at most once per turn. Only reducer fields (`checked`, `drift`) accumulate; `memory_findings` is plain last-writer-wins written only by `recall`, and is reset each turn by `orient`.
- **Read-only guarantee preserved:** memory persists only `(question, answer)` text the agent already produced, to the agent's own DB namespace; no new cluster/repo mutation path.
- **Streaming is additive:** the `working → artifact → completed` A2A event contract and `thread_id = context_id` join are preserved; non-streaming callers see the unchanged terminal `completed` answer.
- **Test hygiene:** all tests hermetic — no live Ollama/Postgres. Suite stays green; `black --check src/` and `ruff check src/` stay clean (run `black src/` if needed before committing). The 2 pre-existing otel-openai deprecation warnings are known; add no new warnings.
- **TDD:** failing test first, watch it fail, implement, watch it pass, commit. Conventional-commit messages scoped to `homelab-agent`.
- **Memory is untrusted input:** recalled exchanges include user-controlled text and recall is agent-wide (the namespace is a key prefix, not an authorization boundary). The synthesis prompt must frame recalled content as untrusted, reference-only data (never instructions), and `recall`/`remember` must degrade to no-ops on any runtime store/embedding error so a memory-backend problem never fails the request.

---

## Corrections applied after review (Codex judge, round 1) — these GOVERN where they contradict an embedded snippet below

1. **Terminal answer (Task 4):** the final artifact/completed answer is taken from the authoritative `synthesize` state delta (the `"updates"` stream), falling back to concatenated `"messages"` token deltas, then `"No answer produced."` — NOT solely from concatenated tokens. Implemented in commit `bcc7359`. Any `answer = "".join(answer_parts) or …` snippet below is superseded by this.
2. **Store failures surface at call time (Tasks 2 & 3):** `get_store()` only exercises the **Postgres** connection at `setup()`; an unreachable **Ollama** endpoint is not caught there — it surfaces when `recall`/`remember` embed. Therefore `recall` and `remember` wrap their store calls in `try/except`, log, and return `{}` (no-op) on any runtime error. Do not claim "unreachable Ollama → get_store() None."
3. **Store lifetime (Task 2):** the manually-entered `store_cm` context manager MUST be retained (module-level reference) so it is not garbage-collected and closed under the long-lived process. Do not discard it.
4. **Memory trust boundary (Task 3):** the `SYNTHESIZE_PROMPT` memory block frames recalled exchanges as UNTRUSTED reference-only data (see the strengthened block in the spec), not the softer "may be stale" wording in the embedded snippet.

---

## File Structure (end state additions)

```
homelab-agent/
  pyproject.toml              # + langchain-ollama, langgraph-checkpoint-postgres, psycopg[binary]
  README.md                   # + memory env rows; Pinned environment additions
  LEARNING.md                 # + section 8 (memory: Store + embeddings), section 9 (streaming)
  src/homelab_agent/
    config.py                 # + 6 memory Settings fields
    memory.py                 # NEW — get_store() factory + embedding index
    state.py                  # + memory_findings field
    prompts.py                # SYNTHESIZE_PROMPT gains the memory block
    graph.py                  # + recall, remember nodes; build_graph(store=...); orient reset
    executor.py               # store wiring + astream streaming rewrite
    server.py                 # AgentCapabilities(streaming=True)
  tests/
    test_config.py            # + memory field assertions
    test_memory.py            # NEW — get_store() contract
    test_graph.py             # + recall/remember/memory-in-synthesis tests
    test_server_a2a.py        # + streaming event-stream tests
```

---

### Task 1: Config, dependencies, and the memory env contract

**Files:**
- Modify: `homelab-agent/pyproject.toml`, `homelab-agent/src/homelab_agent/config.py`, `homelab-agent/README.md`
- Test: `homelab-agent/tests/test_config.py`

**Interfaces:**
- Consumes: existing `Settings` (9 fields) from `config.py`.
- Produces: `Settings` gains 6 fields (later tasks read `settings.*`): `memory_db_url: str`, `ollama_base_url: str`, `embedding_model: str`, `memory_top_k: int`, `memory_namespace: str`, `memory_similarity_floor: float`. `Settings.from_env()` populates them from env with the documented defaults.

- [ ] **Step 1: Add dependencies and verify they install**

Edit `homelab-agent/pyproject.toml` — add to the `dependencies` array (after the existing `a2a-sdk` line):

```toml
    "langchain-ollama>=0.2",
    "langgraph-checkpoint-postgres>=2.0",
    "psycopg[binary]>=3.1",
```

Install and capture the resolved versions:

```bash
pip install -e ".[dev]"
python -c "from langchain_ollama import OllamaEmbeddings; from langgraph.store.postgres import PostgresStore; import psycopg; print('imports OK')"
pip show langchain-ollama langgraph-checkpoint-postgres psycopg | grep -E '^(Name|Version)'
```

Expected: `imports OK` and three name/version pairs.
**Contingency (do not skip):** if a floor can't resolve, run `pip index versions <pkg>`, relax to the latest available major, and record the actual installed version in README's "Pinned environment" section. If `langgraph.store.postgres` is not importable under any released `langgraph-checkpoint-postgres`, STOP and report BLOCKED with the pip error — do not fake the store.

- [ ] **Step 2: Write the failing config test**

Append to `homelab-agent/tests/test_config.py`:

```python
def test_memory_defaults(monkeypatch):
    for var in (
        "MEMORY_DB_URL", "OLLAMA_BASE_URL", "EMBEDDING_MODEL",
        "MEMORY_TOP_K", "MEMORY_NAMESPACE", "MEMORY_SIMILARITY_FLOOR",
    ):
        monkeypatch.delenv(var, raising=False)
    s = Settings.from_env()
    assert s.memory_db_url == ""
    assert s.ollama_base_url == "http://ollama.ollama.svc.cluster.local:11434"
    assert s.embedding_model == "nomic-embed-text"
    assert s.memory_top_k == 3
    assert s.memory_namespace == "homelab-agent"
    assert s.memory_similarity_floor == 0.3


def test_memory_env_overrides(monkeypatch):
    monkeypatch.setenv("MEMORY_DB_URL", "postgresql://u:p@db:5432/kagent")
    monkeypatch.setenv("MEMORY_TOP_K", "5")
    monkeypatch.setenv("MEMORY_SIMILARITY_FLOOR", "0.55")
    s = Settings.from_env()
    assert s.memory_db_url == "postgresql://u:p@db:5432/kagent"
    assert s.memory_top_k == 5
    assert s.memory_similarity_floor == 0.55
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_config.py -v -k memory`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'memory_db_url'`

- [ ] **Step 4: Add the fields to config.py**

In `homelab-agent/src/homelab_agent/config.py`, add these fields to the `Settings` dataclass (after `k8s_reader_a2a_url`, before `log_level`):

```python
    memory_db_url: str
    ollama_base_url: str
    embedding_model: str
    memory_top_k: int
    memory_namespace: str
    memory_similarity_floor: float
```

And in `from_env()`, add these to the constructor call (before `log_level=`):

```python
            memory_db_url=os.getenv("MEMORY_DB_URL", ""),
            ollama_base_url=os.getenv(
                "OLLAMA_BASE_URL", "http://ollama.ollama.svc.cluster.local:11434"
            ),
            embedding_model=os.getenv("EMBEDDING_MODEL", "nomic-embed-text"),
            memory_top_k=int(os.getenv("MEMORY_TOP_K", "3")),
            memory_namespace=os.getenv("MEMORY_NAMESPACE", "homelab-agent"),
            memory_similarity_floor=float(os.getenv("MEMORY_SIMILARITY_FLOOR", "0.3")),
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_config.py -v`
Expected: all pass (new memory tests + pre-existing config tests)

- [ ] **Step 6: Update README env contract**

In `homelab-agent/README.md`, add these rows to the env-contract table:

```markdown
| `MEMORY_DB_URL` | no | `` (empty → memory off) | Postgres+pgvector DSN for conversation memory (from a scoped secret) |
| `OLLAMA_BASE_URL` | no | `http://ollama.ollama.svc.cluster.local:11434` | Ollama endpoint for embeddings |
| `EMBEDDING_MODEL` | no | `nomic-embed-text` | Embedding model (768-dim) |
| `MEMORY_TOP_K` | no | `3` | Recalled prior exchanges per turn |
| `MEMORY_NAMESPACE` | no | `homelab-agent` | Store namespace prefix |
| `MEMORY_SIMILARITY_FLOOR` | no | `0.3` | Minimum similarity to include a recalled exchange |
```

Add to README's "Pinned environment" section the three new resolved package versions from Step 1.

- [ ] **Step 7: Commit**

```bash
cd /Users/arisela/git/claude-agents
git add homelab-agent/pyproject.toml homelab-agent/src/homelab_agent/config.py homelab-agent/README.md homelab-agent/tests/test_config.py
git commit -m "feat(homelab-agent): memory config fields, deps, and env contract"
```

---

### Task 2: `memory.py` — the store factory

**Files:**
- Create: `homelab-agent/src/homelab_agent/memory.py`
- Test: `homelab-agent/tests/test_memory.py`
- Modify: `homelab-agent/LEARNING.md` (append section 8)

**Interfaces:**
- Consumes: `settings` from `config.py`.
- Produces: `memory.EMBEDDING_DIMS` (int constant, `768`); `memory.get_store() -> BaseStore | None` — returns a configured `PostgresStore` (with an Ollama embedding index) when `settings.memory_db_url` is set and construction succeeds, else `None`; **never raises**. Task 3's `build_graph` and Task 4's executor call `get_store()`.

- [ ] **Step 1: Discover the PostgresStore construction API**

`PostgresStore` was just installed (Task 1). Probe the exact long-lived construction + setup API before writing the factory:

```bash
python -c "
from langgraph.store.postgres import PostgresStore
import inspect
print('from_conn_string:', inspect.signature(PostgresStore.from_conn_string))
print('has setup:', hasattr(PostgresStore, 'setup'))
print('init:', inspect.signature(PostgresStore.__init__))
"
```

Record the output in your report. The factory below uses `PostgresStore.from_conn_string(...)` entered manually (kept for the process lifetime) + `.setup()`. If the installed signature differs (e.g. requires a connection pool object, or `index=` is named differently), adapt **only the construction lines** to the real signature — the module contract (`get_store() -> BaseStore | None`, never raises) is fixed. Document any adaptation in your report.

- [ ] **Step 2: Write the failing tests**

Create `homelab-agent/tests/test_memory.py`:

```python
"""memory.get_store(): configured store or None, and it never raises."""

from homelab_agent.memory import EMBEDDING_DIMS, get_store


def test_returns_none_without_db_url(monkeypatch):
    monkeypatch.delenv("MEMORY_DB_URL", raising=False)
    # settings is module-level; rebuild from patched env
    from homelab_agent.config import Settings
    from homelab_agent import memory

    monkeypatch.setattr(memory, "settings", Settings.from_env())
    assert get_store() is None


def test_never_raises_on_broken_config(monkeypatch):
    # A DB URL that cannot possibly connect must degrade to None, not raise.
    monkeypatch.setenv("MEMORY_DB_URL", "postgresql://nope:nope@127.0.0.1:1/nodb")
    from homelab_agent.config import Settings
    from homelab_agent import memory

    monkeypatch.setattr(memory, "settings", Settings.from_env())
    # Must return None (connection/setup fails) without propagating an exception.
    assert get_store() is None


def test_embedding_dims_matches_nomic():
    assert EMBEDDING_DIMS == 768
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_memory.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'homelab_agent.memory'`

- [ ] **Step 4: Implement memory.py**

Create `homelab-agent/src/homelab_agent/memory.py` (adapt the two construction lines in Step 4 to the signature found in Step 1 if needed):

```python
"""Conversation-memory store factory.

LangGraph concept — the Store (long-term memory):
A checkpointer persists ONE thread's state (short-term, keyed by thread_id).
A Store is separate: a cross-thread key-value space that, when given an
`index`, also does semantic search — `store.search(namespace, query=...)`
embeds the query and returns the nearest stored values. That is exactly
"recall a similar past exchange," which a checkpointer cannot do.

Here the index embeds with Ollama `nomic-embed-text` (the same model the
Declarative agent used) and persists to kagent's pgvector Postgres. Like
`checkpointer.get_checkpointer()`, this degrades to None when unconfigured
or unreachable — memory is on in-cluster, off locally — and never raises.
"""

import logging

from langchain_ollama import OllamaEmbeddings
from langgraph.store.base import BaseStore

from homelab_agent.config import settings

logger = logging.getLogger(__name__)

# nomic-embed-text produces 768-dim vectors. If EMBEDDING_MODEL changes to a
# model with different dimensionality, update this constant to match.
EMBEDDING_DIMS = 768


def _index_config() -> dict:
    """Embedding index: embed the stored `question` field with Ollama."""
    embeddings = OllamaEmbeddings(
        model=settings.embedding_model, base_url=settings.ollama_base_url
    )
    return {"dims": EMBEDDING_DIMS, "embed": embeddings, "fields": ["question"]}


def get_store() -> BaseStore | None:
    """Return a pgvector-backed semantic store, or None when memory is off."""
    if not settings.memory_db_url:
        return None
    try:
        from langgraph.store.postgres import PostgresStore

        # from_conn_string returns a context manager; enter it manually and
        # keep the store for the process lifetime (the executor holds it).
        store_cm = PostgresStore.from_conn_string(
            settings.memory_db_url, index=_index_config()
        )
        store = store_cm.__enter__()
        store.setup()  # idempotent: creates the store + vector tables if absent
        return store
    except Exception as exc:  # unreachable DB, bad DSN, missing pgvector, etc.
        logger.warning(
            "memory store unavailable (%s); running without conversation memory",
            exc,
        )
        return None
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_memory.py -v`
Expected: 3 passed. (`test_never_raises_on_broken_config` proves the `except` path returns `None`.)

- [ ] **Step 6: Append LEARNING.md section 8**

Append to `homelab-agent/LEARNING.md`:

```markdown
---

## 8. The Store — long-term semantic memory (`memory.py`)

**What:** a `Store` is LangGraph's cross-thread key-value space. Give it an
`index` (dims + an `embed` function + which fields to embed) and it gains
semantic search: `store.search(namespace, query=...)` embeds the query and
returns the nearest stored values with a similarity `score`.

**Why it's different from the checkpointer:** the checkpointer persists ONE
conversation's state (short-term, keyed by `thread_id`). The Store is
long-term and cross-thread — it's how the agent recalls a *similar past
exchange* it had in some other conversation, which a checkpointer can't do.

**Here:** `get_store()` in `memory.py` builds a `PostgresStore` over kagent's
pgvector database, indexed by Ollama `nomic-embed-text` (the same embedding
model the Declarative agent used). It degrades to `None` when `MEMORY_DB_URL`
is unset or the DB/Ollama is unreachable — identical to the checkpointer's
"configured or None, never raises" contract. The `recall`/`remember` graph
nodes (graph.py) read and write it.

**What you just learned:** checkpointer = this conversation's memory; Store =
the agent's memory across all conversations, made searchable by embeddings.
```

- [ ] **Step 7: Commit**

```bash
cd /Users/arisela/git/claude-agents
git add homelab-agent/src/homelab_agent/memory.py homelab-agent/tests/test_memory.py homelab-agent/LEARNING.md
git commit -m "feat(homelab-agent): pgvector store factory with Ollama embedding index"
```

---

### Task 3: `recall`/`remember` nodes, state, prompt, and graph wiring

**Files:**
- Modify: `homelab-agent/src/homelab_agent/state.py`, `homelab-agent/src/homelab_agent/prompts.py`, `homelab-agent/src/homelab_agent/graph.py`
- Test: `homelab-agent/tests/test_graph.py`
- Modify: `homelab-agent/LEARNING.md` (append section 9 — memory in the graph)

**Interfaces:**
- Consumes: `AgentState` (state.py), `settings`, `SYNTHESIZE_PROMPT`, `BaseStore` (injected by LangGraph).
- Produces: `graph.recall(state, *, store=None) -> dict` (async; fills `memory_findings` + appends to `checked`); `graph.remember(state, *, store=None) -> dict` (async; writes the `(question, answer)` exchange); `AgentState["memory_findings"]: str`; `build_graph(checkpointer=None, store=None)` compiles with the store and the new wiring `orient → recall → retrieve → (conditional) → … → synthesize → remember → END`. Task 4's executor calls `build_graph(checkpointer=..., store=...)`.

- [ ] **Step 1: Write the failing tests**

Append to `homelab-agent/tests/test_graph.py`:

```python
# --- Task 3: conversation memory nodes -------------------------------------

from langgraph.store.memory import InMemoryStore


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
```

Note: `test_docs_route_still_works_without_store` reuses the module's existing `FakeChat` (defined earlier in this file for Task 6). Keep that class; the memory test above defines a local `FakeChat` only inside `test_memory_findings_flow_into_synthesis`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_graph.py -v -k "recall or remember or memory"`
Expected: FAIL — `AttributeError: module 'homelab_agent.graph' has no attribute 'recall'`

- [ ] **Step 3: Add the state field**

In `homelab-agent/src/homelab_agent/state.py`, add to `AgentState` (after `live_findings`):

```python
    memory_findings: str   # written by recall; recalled prior (Q,A) exchanges
```

- [ ] **Step 4: Add the memory block to SYNTHESIZE_PROMPT**

In `homelab-agent/src/homelab_agent/prompts.py`, in `SYNTHESIZE_PROMPT`, add this block immediately before the `## Question` section:

```
## Related prior exchanges (from memory — may be stale, verify against docs)
{memory_findings}
```

(The `synthesize` node will pass `memory_findings=...` when formatting — Step 6.)

- [ ] **Step 5: Add recall and remember nodes**

In `homelab-agent/src/homelab_agent/graph.py`, add these imports at the top (alongside existing imports):

```python
import uuid

from homelab_agent.config import settings
```

Then add the two nodes (place `recall` after `orient`, `remember` after `synthesize`):

```python
async def recall(state: AgentState, *, store=None) -> dict:
    """Node: semantic recall of similar past exchanges (no-op without a store).

    LangGraph injects `store` (the one passed to build_graph/compile) by
    parameter name; it is None when memory is unconfigured, so this node
    degrades to a no-op exactly like the store factory does.
    """
    if store is None:
        return {}
    namespace = (settings.memory_namespace, "memories")
    hits = store.search(namespace, query=state["question"], limit=settings.memory_top_k)
    kept = [h for h in hits if (h.score or 0.0) >= settings.memory_similarity_floor]
    if not kept:
        return {}
    findings = "\n".join(
        f"- Q: {h.value.get('question', '')}\n  A: {h.value.get('answer', '')}"
        for h in kept
    )
    label = f"memory ({len(kept)} prior exchange{'s' if len(kept) != 1 else ''})"
    return {"memory_findings": findings, "checked": [label]}


async def remember(state: AgentState, *, store=None) -> dict:
    """Node: persist this turn's (question, answer) exchange (no-op without a store)."""
    if store is None:
        return {}
    namespace = (settings.memory_namespace, "memories")
    store.put(
        namespace,
        str(uuid.uuid4()),
        {"question": state.get("question", ""), "answer": state.get("answer", "")},
    )
    return {}
```

- [ ] **Step 6: Pass memory_findings through synthesize and reset it in orient**

In `graph.py`, in the `synthesize` node's prompt `.format(...)` call, add the argument:

```python
        memory_findings=state.get("memory_findings", "") or "(none)",
```

In `orient`, extend the turn-start `reset` dict to also clear `memory_findings`:

```python
    reset = {"checked": None, "drift": None, "live_findings": "", "memory_findings": ""}
```

- [ ] **Step 7: Rewire build_graph**

In `homelab-agent/src/homelab_agent/graph.py`, update `build_graph`:

```python
def build_graph(checkpointer=None, store=None):
    g = StateGraph(AgentState)
    g.add_node("orient", orient)
    g.add_node("recall", recall)
    g.add_node("retrieve", retrieve)
    g.add_node("delegate_k8s", delegate_k8s)
    g.add_node("drift_check", drift_check)
    g.add_node("synthesize", synthesize)
    g.add_node("remember", remember)

    g.set_entry_point("orient")
    g.add_edge("orient", "recall")
    g.add_edge("recall", "retrieve")
    g.add_conditional_edges(
        "retrieve", needs_live, {"live": "delegate_k8s", "docs": "synthesize"}
    )
    g.add_edge("delegate_k8s", "drift_check")
    g.add_edge("drift_check", "synthesize")
    g.add_edge("synthesize", "remember")
    g.add_edge("remember", END)
    return g.compile(checkpointer=checkpointer, store=store)
```

- [ ] **Step 8: Run the full suite**

Run: `pytest tests/ -v`
Expected: all pass (new memory tests + all prior tests; the graph now has `recall`/`remember` but they no-op without a store, so existing end-to-end tests are unaffected).

- [ ] **Step 9: Append LEARNING.md section 9**

Append to `homelab-agent/LEARNING.md`:

```markdown
---

## 9. Memory in the graph — `recall` & `remember` (`graph.py`)

**What:** two thin nodes wrap the Store. `recall` (right after `orient`)
embeds the question, `store.search`es for the top-k similar past exchanges
above a similarity floor, and writes them to `memory_findings`. `remember`
(right after `synthesize`) `store.put`s this turn's `(question, answer)`.

**Why here, why thin:** placing `recall` early lets the recalled context flow
into `synthesize`'s prompt (labeled "may be stale, verify against docs" so it
never overrides fresh reads). `remember` runs last so it has the final answer.
Both are single-in/single-out on the linear path — the graph stays sequential.
LangGraph injects the `store` by parameter name; it's `None` when memory is
off, so both nodes no-op and the agent behaves exactly as before.

**The reset detail:** `orient` clears `memory_findings` (alongside
`checked`/`drift`/`live_findings`) at turn start, so on a persisted
checkpointer thread last turn's recall never leaks into this turn.

**What you just learned:** long-term memory is just two nodes around a Store —
read early to inform the answer, write late to capture it.
```

- [ ] **Step 10: Commit**

```bash
cd /Users/arisela/git/claude-agents
git add homelab-agent/src/homelab_agent/state.py homelab-agent/src/homelab_agent/prompts.py homelab-agent/src/homelab_agent/graph.py homelab-agent/tests/test_graph.py homelab-agent/LEARNING.md
git commit -m "feat(homelab-agent): recall/remember nodes wiring conversation memory into the graph"
```

---

### Task 4: Executor store wiring + streaming, and server capability

**Files:**
- Modify: `homelab-agent/src/homelab_agent/executor.py`, `homelab-agent/src/homelab_agent/server.py`
- Test: `homelab-agent/tests/test_server_a2a.py`
- Modify: `homelab-agent/LEARNING.md` (append section 10 — streaming)

**Interfaces:**
- Consumes: `build_graph` (now `(checkpointer=, store=)`), `get_checkpointer`, `get_store`, a2a-sdk event types.
- Produces: `HomelabAgentExecutor._graph` compiled with `store=get_store()`; `execute()` drives `astream` emitting progress + streamed `synthesize` deltas + terminal artifact/completed; `server` agent card advertises `streaming=True`.

- [ ] **Step 1: Write the failing tests**

Append to `homelab-agent/tests/test_server_a2a.py`:

```python
# --- Task 4: streaming ------------------------------------------------------

class TestStreaming:
    async def test_card_advertises_streaming(self, client):
        card = (await client.get("/.well-known/agent.json")).json()
        assert card["capabilities"]["streaming"] is True

    async def test_execute_streams_progress_then_answer(self):
        from a2a.server.events.event_queue import EventQueue
        from a2a.types import TaskState, TextPart

        from homelab_agent.executor import HomelabAgentExecutor

        executor = HomelabAgentExecutor()
        context = MagicMock()
        context.task_id = str(uuid.uuid4())
        context.context_id = str(uuid.uuid4())
        context.message.parts = [TextPart(text="What is cert-manager?")]

        # Fake astream: yield two node-update events, then two synthesize token
        # deltas, matching stream_mode=["updates","messages"] tuple shape.
        async def fake_astream(inputs, config=None, stream_mode=None):
            yield ("updates", {"orient": {"route": "docs"}})
            yield ("updates", {"retrieve": {"doc_findings": "x"}})
            msg1 = MagicMock(); msg1.content = "cert-"; msg1.text = "cert-"
            msg2 = MagicMock(); msg2.content = "manager."; msg2.text = "manager."
            yield ("messages", (msg1, {"langgraph_node": "synthesize"}))
            yield ("messages", (msg2, {"langgraph_node": "synthesize"}))

        executor._graph = MagicMock()
        executor._graph.astream = fake_astream

        event_queue = EventQueue()
        await executor.execute(context, event_queue)

        events = []
        while True:
            try:
                events.append(await event_queue.dequeue_event(no_wait=True))
            except Exception:
                break

        texts = []
        final_completed = None
        for e in events:
            if hasattr(e, "status") and e.status.message:
                texts.append(e.status.message.parts[0].root.text)
            if hasattr(e, "status") and e.status.state == TaskState.completed:
                final_completed = e
        # progress markers present
        assert any("Retrieving docs" in t for t in texts)
        # streamed synthesize deltas concatenate to the full answer
        assert final_completed is not None
        assert final_completed.status.message.parts[0].root.text == "cert-manager."

    async def test_execute_error_still_fails(self):
        from a2a.server.events.event_queue import EventQueue
        from a2a.types import TaskState, TextPart

        from homelab_agent.executor import HomelabAgentExecutor

        executor = HomelabAgentExecutor()
        context = MagicMock()
        context.task_id = str(uuid.uuid4())
        context.context_id = str(uuid.uuid4())
        context.message.parts = [TextPart(text="boom")]

        async def boom_astream(inputs, config=None, stream_mode=None):
            raise RuntimeError("stream exploded")
            yield  # pragma: no cover  (makes this an async generator)

        executor._graph = MagicMock()
        executor._graph.astream = boom_astream

        event_queue = EventQueue()
        await executor.execute(context, event_queue)

        events = []
        while True:
            try:
                events.append(await event_queue.dequeue_event(no_wait=True))
            except Exception:
                break
        assert any(
            hasattr(e, "status") and e.status.state == TaskState.failed for e in events
        )
        assert any("stream exploded" in e.status.message.parts[0].root.text
                   for e in events if hasattr(e, "status") and e.status.message)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_server_a2a.py -v -k "Streaming or streaming"`
Expected: FAIL — `test_card_advertises_streaming` asserts `True` but card says `False`; the executor streaming tests fail because `execute()` still uses `ainvoke`.

- [ ] **Step 3: Set streaming=True in server.py**

In `homelab-agent/src/homelab_agent/server.py`, change:

```python
        capabilities=AgentCapabilities(streaming=False),
```
to:
```python
        capabilities=AgentCapabilities(streaming=True),
```

- [ ] **Step 4: Wire the store into the executor's graph**

In `homelab-agent/src/homelab_agent/executor.py`, add the import and update `__init__`:

```python
from homelab_agent.memory import get_store
```

```python
    def __init__(self):
        # Compile once. Checkpointer = short-term thread state; store = long-term
        # semantic memory. Both are None when unconfigured (local dev).
        self._graph = build_graph(checkpointer=get_checkpointer(), store=get_store())
```

- [ ] **Step 5: Rewrite execute() to stream**

In `homelab-agent/src/homelab_agent/executor.py`, add a module-level progress map and a token helper, then replace the body of `execute()`'s success path (the `ainvoke` call and the artifact/completed emission) with the streaming loop. Full replacement of `execute`:

```python
_PROGRESS = {
    "orient": "Orienting…",
    "recall": "Recalling related context…",
    "retrieve": "Retrieving docs…",
    "delegate_k8s": "Delegating to k8s-reader…",
    "drift_check": "Checking for drift…",
    "synthesize": "Synthesizing answer…",
    # remember: silent housekeeping, no progress event
}


def _chunk_text(message_chunk) -> str:
    """Extract text from a LangGraph 'messages'-mode chunk (str or block list)."""
    text = getattr(message_chunk, "text", None)
    if isinstance(text, str) and text:
        return text
    content = getattr(message_chunk, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            b.get("text", "") for b in content if isinstance(b, dict)
        )
    return ""
```

```python
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        task_id = context.task_id
        context_id = context.context_id or str(uuid.uuid4())
        try:
            question = _extract_user_input(context.message)
            logger.info("homelab-agent question: %s", question[:120])

            await event_queue.enqueue_event(_status_event(
                task_id, context_id, TaskState.working,
                "Working on it…", False,
            ))

            answer_parts: list[str] = []
            async for mode, chunk in self._graph.astream(
                {"question": question},
                config={"configurable": {"thread_id": context_id}},
                stream_mode=["updates", "messages"],
            ):
                if mode == "updates":
                    for node_name in chunk:
                        message = _PROGRESS.get(node_name)
                        if message:
                            await event_queue.enqueue_event(_status_event(
                                task_id, context_id, TaskState.working, message, False,
                            ))
                elif mode == "messages":
                    message_chunk, metadata = chunk
                    if metadata.get("langgraph_node") == "synthesize":
                        token = _chunk_text(message_chunk)
                        if token:
                            answer_parts.append(token)
                            await event_queue.enqueue_event(_status_event(
                                task_id, context_id, TaskState.working, token, False,
                            ))

            answer = "".join(answer_parts) or "No answer produced."

            await event_queue.enqueue_event(TaskArtifactUpdateEvent(
                task_id=task_id,
                context_id=context_id,
                artifact=Artifact(
                    artifact_id=str(uuid.uuid4()),
                    parts=[Part(root=TextPart(text=answer))],
                ),
            ))
            await event_queue.enqueue_event(_status_event(
                task_id, context_id, TaskState.completed, answer, True,
            ))
        except Exception as exc:
            logger.error("executor error: %s", exc, exc_info=True)
            await event_queue.enqueue_event(_status_event(
                task_id, context_id, TaskState.failed,
                f"homelab-agent error: {exc}", True,
            ))
```

Note: `answer` is assembled from streamed `synthesize` deltas. This equals the graph's final `answer` because `synthesize` is the only node whose model output is the answer and it writes that same text to state. Keep `_status_event`, `_extract_user_input`, `cancel`, and the imports (`Artifact`, `Part`, `TextPart`, `TaskArtifactUpdateEvent`, `TaskState`, `uuid`) as they are.

- [ ] **Step 6: Run the full suite**

Run: `pytest tests/ -v`
Expected: all pass. Update any pre-existing executor test that asserted the old single-`ainvoke` behavior only if it now fails; if the Task 8 success test (`test_execute_success_emits_working_artifact_completed`) mocked `_graph.ainvoke`, it must be updated to mock `_graph.astream` as an async generator (mirror `fake_astream` above) — keep its existing assertions on the working/artifact/completed sequence. Record any such adaptation in your report.

- [ ] **Step 7: Append LEARNING.md section 10**

Append to `homelab-agent/LEARNING.md`:

```markdown
---

## 10. Streaming — `astream` → A2A events (`executor.py`)

**What:** `graph.astream(..., stream_mode=["updates","messages"])` yields
`(mode, chunk)` tuples as the graph runs. `updates` fires once per node with
its state delta; `messages` fires per LLM token with `(chunk, metadata)`,
where `metadata["langgraph_node"]` says which node produced it.

**Why two modes:** `updates` drives coarse progress ("Retrieving docs…",
"Delegating to k8s-reader…"); `messages`, filtered to the `synthesize` node,
streams the final answer token-by-token. Tokens from the router/drift model
calls are ignored — only the answer streams.

**Here:** `execute()` maps `updates` → progress `TaskStatusUpdateEvent`s and
`synthesize` `messages` → streamed answer events, then emits the assembled
answer as the terminal `artifact` + `completed` events. Non-streaming callers
can ignore the intermediate events and just read `completed` — the old
contract is intact; streaming is purely additive.

**What you just learned:** a LangGraph graph is a live event source, and the
A2A executor is a translator from graph events to protocol events.
```

- [ ] **Step 8: Verify formatting and commit**

```bash
cd /Users/arisela/git/claude-agents/homelab-agent && source .venv/bin/activate
black src/ && ruff check src/ && pytest tests/ -q
cd /Users/arisela/git/claude-agents
git add homelab-agent/src/homelab_agent/executor.py homelab-agent/src/homelab_agent/server.py homelab-agent/tests/test_server_a2a.py homelab-agent/LEARNING.md
git commit -m "feat(homelab-agent): stream progress + answer tokens over A2A; wire memory store into executor"
```

---

## Verification (whole plan)

From `/Users/arisela/git/claude-agents/homelab-agent/` with `.venv` active:

1. `pytest tests/ -v` — full suite green (memory + streaming + all prior tests).
2. `black --check src/ && ruff check src/` — clean.
3. Memory off by default: `python -c "from homelab_agent.memory import get_store; print(get_store())"` prints `None` (no `MEMORY_DB_URL`).
4. Graph shape: `python -c "from homelab_agent.graph import build_graph; g=build_graph(); print([n for n in g.get_graph().nodes])"` includes `recall` and `remember`.
5. README env table documents all 6 new env vars; `grep -rhoE 'os\.getenv\("[A-Z_]+"' src/ | sort -u` keys all appear in the README.
6. LEARNING.md has sections 8, 9, 10.
7. Container still builds + serves (optional, Docker): rebuild per Task 10 of the base plan and confirm `/health` — memory stays off in the container without `MEMORY_DB_URL`, so no behavior change locally.

## Follow-up (out of scope — `arigsela/kubernetes`)

The BYO CR work gains: a least-privilege ESO/Vault secret providing `MEMORY_DB_URL` (a Postgres role scoped to the agent's own namespace/table in the kagent pgvector DB), NetworkPolicy reach to Ollama + Postgres, and setting `MEMORY_DB_URL` on `spec.byo.deployment.env`. The README env contract enumerates exactly what to provide.
