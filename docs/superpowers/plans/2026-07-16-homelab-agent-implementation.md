# homelab-agent (LangGraph BYO) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `homelab-agent/` LangGraph container — a re-implementation of the `homelab-knowledge` kagent agent as an explicit StateGraph served over A2A on :8080 — with tests, a golden-question parity harness, pedagogical LEARNING.md, Dockerfile, and ECR deploy script.

**Architecture:** A hand-built sequential `StateGraph` (`orient → retrieve → [delegate_k8s → drift_check]? → synthesize`) where `retrieve` internally runs a prebuilt ReAct agent over MCP doc tools, `delegate_k8s` is an A2A client call to k8s-reader, and the whole graph is served by an oncall-crewai-style A2A server (FastAPI + `A2AStarletteApplication` + custom `AgentExecutor`). All endpoints/tokens are env-driven via `config.py`.

**Tech Stack:** Python 3.11, LangGraph, langchain-anthropic (`ChatAnthropic`), langchain-mcp-adapters (`MultiServerMCPClient`), a2a-sdk (server + JSON-RPC client via httpx), FastAPI/uvicorn, pytest + pytest-asyncio. Design doc: `docs/superpowers/plans/2026-07-16-langraph-knowledge-agent-plan.md`.

## Global Constraints

Every task's requirements implicitly include all of these:

- **Scope:** create/modify files only under `homelab-agent/` (plus checking boxes in this plan). No changes to other projects or to the `arigsela/kubernetes` repo.
- **Python ≥3.11.** All commands run from `/Users/arisela/git/claude-agents/homelab-agent/` with `.venv` activated: `source .venv/bin/activate`.
- **Config-driven everything:** every endpoint, token, and model name is read from env in `config.py` (cluster-internal URLs may appear only as *defaults* in `config.py` and in README docs — nowhere else in code).
- **Read-only guarantee:** no tool, prompt, or code path may mutate the cluster or repo. Prompts must instruct: recommend GitOps PRs instead of `kubectl apply`/mutations; never quote secret values (only Vault path/property); never invent file paths or resource names.
- **Response format (verbatim requirement):** 1. Brief answer first (1–3 sentences). 2. Then a "What I checked" section listing delegates/sources used. 3. Then specifics: file paths in arigsela/kubernetes, exact resource names, kubectl commands the user could run to verify.
- **Sequential graph:** v1 has NO parallel fan-out/fan-in. `checked` and `drift` are the only fields with `operator.add` reducers; every other field is written by exactly one node.
- **Learning deliverable:** every task that introduces a LangGraph concept (a) appends its given section to `LEARNING.md` and (b) carries teaching comments in the code explaining the LangGraph construct (not restating Python). This is spec, not garnish.
- **Agent card skills:** the three skill ids `repo-knowledge`, `cluster-troubleshooting`, `deployment-guidance` must be carried over exactly.
- **Model names via env:** `MODEL_NAME` default `claude-sonnet-4-6`; `ROUTER_MODEL_NAME` default `claude-haiku-4-5-20251001`.
- **TDD:** write the failing test first, watch it fail, implement, watch it pass, commit. Conventional-commit messages scoped to `homelab-agent`.

---

## File Structure (end state)

```
homelab-agent/
  pyproject.toml
  .gitignore
  .dockerignore
  Dockerfile
  deploy-to-ecr.sh
  README.md            # env-var contract table + run instructions
  LEARNING.md          # LangGraph concept glossary mapped to this code
  src/homelab_agent/
    __init__.py
    config.py          # Settings from env (endpoints, tokens, models)
    state.py           # AgentState TypedDict + reducers
    prompts.py         # system/router/retrieve/drift/synthesize prompts
    model.py           # ChatAnthropic factories
    tools.py           # MCP client, doc-retrieval ReAct runner, A2A client
    graph.py           # nodes + StateGraph wiring
    checkpointer.py    # optional KAgentCheckpointer wiring
    executor.py        # A2A AgentExecutor bridging to the graph
    server.py          # FastAPI + A2AStarletteApplication on :8080
    parity.py          # parity-check helpers (format/read-only checks, report)
  scripts/
    parity_check.py    # golden-question runner (old vs new agent over A2A)
  tests/
    __init__.py
    parity/golden_questions.yaml
    test_config.py
    test_state.py
    test_orient.py
    test_tools.py
    test_graph.py
    test_checkpointer.py
    test_server_a2a.py
    test_parity_checks.py
```

---

### Task 1: Scaffold, config.py, and the env contract

**Files:**
- Create: `homelab-agent/pyproject.toml`, `homelab-agent/.gitignore`, `homelab-agent/src/homelab_agent/__init__.py`, `homelab-agent/src/homelab_agent/config.py`, `homelab-agent/tests/__init__.py`, `homelab-agent/tests/test_config.py`, `homelab-agent/README.md`, `homelab-agent/LEARNING.md`

**Interfaces:**
- Produces: `homelab_agent.config.settings` — module-level `Settings` instance; fields (all `str` unless noted): `anthropic_api_key`, `model_name`, `router_model_name`, `agent_docs_mcp_url`, `agent_docs_mcp_auth_header`, `backstage_mcp_url`, `backstage_mcp_token`, `k8s_reader_a2a_url`, `log_level`. Also `Settings.from_env() -> Settings` classmethod. Later tasks import `from homelab_agent.config import settings`.

- [ ] **Step 1: Create the package scaffold and venv**

```bash
mkdir -p homelab-agent/src/homelab_agent homelab-agent/tests
cd homelab-agent
python3 -m venv .venv && source .venv/bin/activate
touch src/homelab_agent/__init__.py tests/__init__.py
```

Create `homelab-agent/.gitignore`:

```gitignore
.venv/
__pycache__/
*.egg-info/
.pytest_cache/
parity-report*.md
.env
```

Create `homelab-agent/pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=68.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "homelab-agent"
version = "0.1.0"
description = "LangGraph BYO kagent agent answering homelab GitOps + live-cluster questions"
readme = "README.md"
requires-python = ">=3.11"

dependencies = [
    "langgraph>=1.0",
    "langchain-core>=1.0",
    "langchain-anthropic>=1.0",
    "langchain-mcp-adapters>=0.1.9",
    "a2a-sdk[http-server]>=0.3.10",
    "fastapi>=0.128.0",
    "uvicorn[standard]>=0.30.0",
    "httpx>=0.28.0",
    "pydantic>=2.12.0",
    "python-dotenv>=1.0.0",
    "pyyaml>=6.0.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=1.0",
    "pytest-mock>=3.14",
    "black>=25.0",
    "ruff>=0.8",
]

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.black]
line-length = 100

[tool.ruff]
line-length = 100
```

Install: `pip install -e ".[dev]"`
Expected: resolves and installs cleanly. **Contingency (do not skip):** if pip cannot satisfy a floor (e.g. `langgraph>=1.0` has no matching release), run `pip index versions <package>`, relax that floor to the latest available major, and note the actual installed version in README's "Pinned environment" section. Do NOT silently drop a dependency.

- [ ] **Step 2: Write the failing config test**

Create `homelab-agent/tests/test_config.py`:

```python
"""Config is the env contract: everything external is injectable via env."""

from homelab_agent.config import Settings


def test_defaults_point_at_cluster_services(monkeypatch):
    # Clear any ambient env so we test the defaults themselves.
    for var in (
        "MODEL_NAME", "ROUTER_MODEL_NAME", "AGENT_DOCS_MCP_URL",
        "AGENT_DOCS_MCP_AUTH_HEADER", "BACKSTAGE_MCP_URL",
        "BACKSTAGE_MCP_TOKEN", "K8S_READER_A2A_URL", "LOG_LEVEL",
    ):
        monkeypatch.delenv(var, raising=False)
    s = Settings.from_env()
    assert s.model_name == "claude-sonnet-4-6"
    assert s.router_model_name == "claude-haiku-4-5-20251001"
    assert s.agent_docs_mcp_url == "http://agent-docs-mcp.kagent:3000/mcp"
    assert s.backstage_mcp_url == (
        "http://backstage.backstage.svc.cluster.local/api/mcp-actions/v1/catalog"
    )
    assert s.k8s_reader_a2a_url == "http://k8s-reader.kagent.svc.cluster.local:8080"
    assert s.agent_docs_mcp_auth_header == ""
    assert s.backstage_mcp_token == ""
    assert s.log_level == "INFO"


def test_env_overrides_defaults(monkeypatch):
    monkeypatch.setenv("MODEL_NAME", "claude-sonnet-5")
    monkeypatch.setenv("K8S_READER_A2A_URL", "http://localhost:9999")
    monkeypatch.setenv("BACKSTAGE_MCP_TOKEN", "sekrit")
    s = Settings.from_env()
    assert s.model_name == "claude-sonnet-5"
    assert s.k8s_reader_a2a_url == "http://localhost:9999"
    assert s.backstage_mcp_token == "sekrit"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'homelab_agent.config'`

- [ ] **Step 4: Implement config.py**

Create `homelab-agent/src/homelab_agent/config.py`:

```python
"""Environment-driven configuration.

This module is the ENTIRE env contract between this container and the
kagent BYO Agent CR that will deploy it (see README table). Cluster URLs
appear here only as defaults so local runs and tests can override them.
"""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    anthropic_api_key: str
    model_name: str
    router_model_name: str
    agent_docs_mcp_url: str
    agent_docs_mcp_auth_header: str
    backstage_mcp_url: str
    backstage_mcp_token: str
    k8s_reader_a2a_url: str
    log_level: str

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
            model_name=os.getenv("MODEL_NAME", "claude-sonnet-4-6"),
            router_model_name=os.getenv(
                "ROUTER_MODEL_NAME", "claude-haiku-4-5-20251001"
            ),
            agent_docs_mcp_url=os.getenv(
                "AGENT_DOCS_MCP_URL", "http://agent-docs-mcp.kagent:3000/mcp"
            ),
            agent_docs_mcp_auth_header=os.getenv("AGENT_DOCS_MCP_AUTH_HEADER", ""),
            backstage_mcp_url=os.getenv(
                "BACKSTAGE_MCP_URL",
                "http://backstage.backstage.svc.cluster.local/api/mcp-actions/v1/catalog",
            ),
            backstage_mcp_token=os.getenv("BACKSTAGE_MCP_TOKEN", ""),
            k8s_reader_a2a_url=os.getenv(
                "K8S_READER_A2A_URL", "http://k8s-reader.kagent.svc.cluster.local:8080"
            ),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
        )


settings = Settings.from_env()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_config.py -v`
Expected: 2 passed

- [ ] **Step 6: Write README.md (env contract) and LEARNING.md skeleton**

Create `homelab-agent/README.md`:

```markdown
# homelab-agent

LangGraph BYO re-implementation of the `homelab-knowledge` kagent agent.
Serves the A2A protocol on :8080. See `LEARNING.md` for the LangGraph
concept glossary and `docs/superpowers/plans/2026-07-16-langraph-knowledge-agent-plan.md`
for the design.

## Env contract (what the kagent BYO `Agent` CR must provide)

| Env var | Required | Default | Purpose |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | yes (runtime) | — | ChatAnthropic auth (own Vault key, not shared `kagent-anthropic`) |
| `MODEL_NAME` | no | `claude-sonnet-4-6` | Main graph model (parity with current agent) |
| `ROUTER_MODEL_NAME` | no | `claude-haiku-4-5-20251001` | Cheap model for the orient fallback classifier |
| `AGENT_DOCS_MCP_URL` | no | `http://agent-docs-mcp.kagent:3000/mcp` | Read-only GitHub MCP (streamable HTTP) |
| `AGENT_DOCS_MCP_AUTH_HEADER` | no | `` | Optional `Authorization` header value for agent-docs MCP |
| `BACKSTAGE_MCP_URL` | no | `http://backstage.backstage.svc.cluster.local/api/mcp-actions/v1/catalog` | Backstage catalog MCP (streamable HTTP) |
| `BACKSTAGE_MCP_TOKEN` | yes (runtime) | `` | Bearer token for the Backstage MCP |
| `K8S_READER_A2A_URL` | no | `http://k8s-reader.kagent.svc.cluster.local:8080` | A2A endpoint of the read-only k8s-reader agent |
| `LOG_LEVEL` | no | `INFO` | Python log level |
| `AGENT_URL` | no | `http://0.0.0.0:8080` | Self-URL advertised in the A2A agent card |

`KAGENT_URL` / kagent runtime envs are injected by the kagent controller into
BYO pods and enable the checkpointer (see `checkpointer.py`); absent locally,
the graph runs without persistence.

## Local dev

    python3 -m venv .venv && source .venv/bin/activate
    pip install -e ".[dev]"
    pytest tests/ -v

## Run the server locally

    ANTHROPIC_API_KEY=... uvicorn homelab_agent.server:app --host 0.0.0.0 --port 8080

## Parity harness

    OLD_AGENT_URL=http://localhost:18080 NEW_AGENT_URL=http://localhost:8080 \
      python scripts/parity_check.py
```

Create `homelab-agent/LEARNING.md`:

```markdown
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
```

- [ ] **Step 7: Commit**

```bash
cd /Users/arisela/git/claude-agents
git add homelab-agent/
git commit -m "feat(homelab-agent): scaffold package with env-contract config"
```

---

### Task 2: State schema and reducers (`state.py`)

**Files:**
- Create: `homelab-agent/src/homelab_agent/state.py`
- Test: `homelab-agent/tests/test_state.py`
- Modify: `homelab-agent/LEARNING.md` (append section 1)

**Interfaces:**
- Produces: `homelab_agent.state.AgentState` (TypedDict, `total=False`) with keys `question: str`, `route: Route`, `plan: str`, `doc_findings: str`, `live_findings: str`, `drift: Annotated[list[str], operator.add]`, `answer: str`, `checked: Annotated[list[str], operator.add]`; and `homelab_agent.state.Route = Literal["docs", "live", "ownership"]`. All later graph nodes read/return partial dicts of this shape.

- [ ] **Step 1: Write the failing test**

Create `homelab-agent/tests/test_state.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_state.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'homelab_agent.state'`

- [ ] **Step 3: Implement state.py**

Create `homelab-agent/src/homelab_agent/state.py`:

```python
"""The State: one typed dict threaded through every node of the graph.

LangGraph concept — State & reducers:
Each node receives the CURRENT state and returns a PARTIAL update (a dict
with only the keys it changes). LangGraph merges that update into the state.
HOW it merges is per-field:

- Plain fields (question, route, ...) are replaced — last writer wins.
  Safe here because exactly one node writes each of them and the v1 graph
  is strictly sequential (see graph.py).
- Fields annotated with a reducer, like `Annotated[list[str], operator.add]`,
  are MERGED with the reducer instead: operator.add concatenates lists, so
  `checked` and `drift` accumulate entries from multiple nodes without any
  node needing to read-modify-write the whole list.
"""

import operator
from typing import Annotated, Literal

from typing_extensions import TypedDict

# Where orient decided this question should go.
Route = Literal["docs", "live", "ownership"]


class AgentState(TypedDict, total=False):
    question: str          # the user's question (set once, at invoke)
    route: Route           # written by orient
    plan: str              # short rationale from orient's classifier
    doc_findings: str      # written by retrieve
    live_findings: str     # written by delegate_k8s
    drift: Annotated[list[str], operator.add]    # appended by drift_check
    answer: str            # written by synthesize
    checked: Annotated[list[str], operator.add]  # appended by retrieve/delegate_k8s
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_state.py -v`
Expected: 2 passed

- [ ] **Step 5: Append LEARNING.md section 1**

Append to `homelab-agent/LEARNING.md`:

```markdown
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
```

- [ ] **Step 6: Commit**

```bash
cd /Users/arisela/git/claude-agents
git add homelab-agent/
git commit -m "feat(homelab-agent): AgentState schema with operator.add reducers"
```

---

### Task 3: Prompts, model factories, and the orient node

**Files:**
- Create: `homelab-agent/src/homelab_agent/prompts.py`, `homelab-agent/src/homelab_agent/model.py`, `homelab-agent/src/homelab_agent/graph.py`
- Test: `homelab-agent/tests/test_orient.py`
- Modify: `homelab-agent/LEARNING.md` (append section 2)

**Interfaces:**
- Consumes: `AgentState`, `Route` from Task 2; `settings` from Task 1.
- Produces: `prompts.SYSTEM_PROMPT`, `prompts.ROUTER_PROMPT`, `prompts.RETRIEVE_PROMPT`, `prompts.DRIFT_PROMPT`, `prompts.SYNTHESIZE_PROMPT` (all `str`); `model.get_model()` and `model.get_router_model()` returning `ChatAnthropic`; `graph.orient(state: AgentState) -> dict` (returns `{"route": Route, "plan": str}`); `graph.build_graph(checkpointer=None)` returning a compiled graph (this task: `orient → END`; later tasks extend it).

- [ ] **Step 1: Write the failing tests**

Create `homelab-agent/tests/test_orient.py`:

```python
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

def test_build_graph_runs_orient():
    from homelab_agent.graph import build_graph

    g = build_graph()
    out = g.invoke({"question": "Is the argo-cd control plane healthy?"})
    assert out["route"] == "live"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_orient.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'homelab_agent.graph'`

- [ ] **Step 3: Implement prompts.py**

Create `homelab-agent/src/homelab_agent/prompts.py`:

```python
"""All prompts in one place. SYSTEM_PROMPT is ported from the Declarative
agent's systemMessage (base-apps/kagent/agents/homelab-knowledge.yaml in
arigsela/kubernetes); the {{include}} template blocks are replaced by their
inlined constraint text since a BYO container has no kagent prompt templates.
"""

SYSTEM_PROMPT = """\
You are HomelabAssist, an expert assistant for this homelab Kubernetes
cluster and its GitOps repo at github.com/arigsela/kubernetes. You answer
"what/why/how" and triage questions by RETRIEVING the repo's agent-docs
(never from memorized facts, which go stale), and by delegating to the
k8s-reader specialist agent for live cluster state.

## Constraints (read-only, GitOps-first)

- You are strictly READ-ONLY. Never perform or recommend direct mutations:
  no `kubectl apply`, `delete`, `edit`, `patch`, `exec`, or `scale`. This
  cluster is GitOps-driven — recommend a PR to arigsela/kubernetes instead.
- Never invent file paths or resource names. If a doc doesn't cover it,
  say so and read the source, or delegate for a real lookup.
- If asked about secrets, never quote values — only the Vault path/property.
"""

ROUTER_PROMPT = """\
Classify this question about a Kubernetes homelab into exactly one category.
Reply with ONLY one word: docs, live, or ownership.

- docs: answerable from the GitOps repo's documentation (architecture,
  config, how something works, onboarding guidance).
- live: requires CURRENT cluster state (pod status, events, logs, health,
  sync state, "is X running/crashing/stuck").
- ownership: about who owns a component, its dependencies/dependents, or
  what system it belongs to.

Question: {question}
"""

RETRIEVE_PROMPT = SYSTEM_PROMPT + """\

## How to retrieve (atlas → index → app)

Read files with the `get_file_contents` tool (the read-only GitHub MCP),
always passing owner=`arigsela`, repo=`kubernetes`, ref=`main`, and the
file's `path`. Use `search_code` (same MCP) when you need to locate a file:
1. Read `INFRASTRUCTURE_ATLAS.md` to orient (system context, topology,
   source registry, the "For agents" traversal rule).
2. Read `base-apps/_INDEX.md` to find the app's row.
3. Read that app's `base-apps/<app>/docs.md` (architecture/config),
   `runbook.md` (symptom → check → fix), and `catalog-info.yaml`
   (owner, system, dependsOn) as needed.
4. Treat the files listed under a doc's `sources:` as authoritative —
   read them rather than guessing.

For OWNERSHIP, DEPENDENCY, or SYSTEM-membership questions ("who owns X?",
"what depends on X?", "what system is X part of?"), use the
`get-catalog-entity` tool instead of raw files: it returns an entity plus
its RESOLVED relations — including reverse relations like `dependencyOf`
that no single catalog-info.yaml contains. Fall back to `catalog-info.yaml`
via the GitHub MCP only if the catalog tool is unavailable.

Report your findings as compact notes (file paths read, key facts, exact
resource names). Another step formats the final user-facing answer.
"""

DRIFT_PROMPT = """\
Compare documented state vs live cluster state for a homelab GitOps repo.
List each concrete disagreement (docs say X, cluster shows Y) as one bullet
starting with "- ". If there are no disagreements, reply exactly: NONE

## Documentation findings
{docs}

## Live cluster findings
{live}
"""

SYNTHESIZE_PROMPT = SYSTEM_PROMPT + """\

Compose the final answer from the findings below. REQUIRED format:
1. Brief answer first (1-3 sentences).
2. A "What I checked" section listing the delegates/sources used (given below).
3. Specifics: file paths in arigsela/kubernetes, exact resource names, and
   read-only kubectl commands the user could run to verify.
If drift findings are present, call them out explicitly as DRIFT — the docs
are meant to track reality, so a mismatch is valuable signal.

## Question
{question}

## Documentation findings
{doc_findings}

## Live cluster findings (from k8s-reader; empty if not consulted)
{live_findings}

## Drift findings
{drift}

## Sources/delegates used (for "What I checked")
{checked}
"""
```

- [ ] **Step 4: Implement model.py**

Create `homelab-agent/src/homelab_agent/model.py`:

```python
"""ChatAnthropic factories.

LangGraph concept — the model is just another dependency: nodes call a
LangChain chat model object; nothing about LangGraph dictates which. A BYO
container owns its own model wiring (kagent ModelConfig does not apply).
"""

from langchain_anthropic import ChatAnthropic

from homelab_agent.config import settings


def get_model() -> ChatAnthropic:
    """Main model (Sonnet): retrieval agent, drift check, synthesis."""
    return ChatAnthropic(model=settings.model_name, temperature=0, max_tokens=4096)


def get_router_model() -> ChatAnthropic:
    """Cheap model for orient's fallback classifier only."""
    return ChatAnthropic(
        model=settings.router_model_name, temperature=0, max_tokens=16
    )
```

- [ ] **Step 5: Implement graph.py (orient + minimal graph)**

Create `homelab-agent/src/homelab_agent/graph.py`:

```python
"""The StateGraph: nodes + edges.

LangGraph concept — a NODE is a plain function `state -> partial update`.
This module grows across tasks following the learning arc:
  Task 3: orient (this file's first node) wired orient → END
  Task 5: retrieve
  Task 6: delegate_k8s, drift_check, synthesize + conditional routing
"""

import logging

from langgraph.graph import END, StateGraph

from homelab_agent.model import get_router_model
from homelab_agent.prompts import ROUTER_PROMPT
from homelab_agent.state import AgentState, Route

logger = logging.getLogger(__name__)

# Deterministic first pass, à la oncall-crewai's router: cheap, predictable,
# and it keeps the LLM out of the loop for the common phrasings.
_OWNERSHIP_KEYWORDS = (
    "who owns", "owner", "depends on", "dependency", "dependencies",
    "what system", "part of",
)
_LIVE_KEYWORDS = (
    "crashloop", "crashing", "pending", "stuck", "failing", "down",
    "healthy", "health", "status", "logs", "events", "restart",
    "running", "sync",
)
_DOCS_KEYWORDS = (
    "what is", "how does", "how do", "how is", "where does", "where is",
    "explain", "pattern", "onboard", "deploy a new",
)


def _keyword_route(question: str) -> Route | None:
    q = question.lower()
    if any(k in q for k in _OWNERSHIP_KEYWORDS):
        return "ownership"
    if any(k in q for k in _LIVE_KEYWORDS):
        return "live"
    if any(k in q for k in _DOCS_KEYWORDS):
        return "docs"
    return None  # ambiguous → LLM fallback


def orient(state: AgentState) -> dict:
    """Node 1: classify the question. Writes `route` (+ a one-line `plan`)."""
    question = state["question"]
    route = _keyword_route(question)
    if route is not None:
        return {"route": route, "plan": f"keyword-routed to '{route}'"}

    # Ambiguity: ask the cheap router model for a single-word verdict.
    try:
        reply = get_router_model().invoke(ROUTER_PROMPT.format(question=question))
        candidate = reply.content.strip().lower()
    except Exception as exc:  # LLM down ≠ agent down: degrade to docs-only
        logger.warning("router model failed (%s); defaulting to docs", exc)
        candidate = ""
    route = candidate if candidate in ("docs", "live", "ownership") else "docs"
    return {"route": route, "plan": f"llm-routed to '{route}'"}


def build_graph(checkpointer=None):
    """Assemble and compile the StateGraph.

    LangGraph concept — you declare nodes and edges on a StateGraph builder,
    then compile() it into a runnable. `set_entry_point` marks where START
    routes to; END is a sentinel, not a node you define.
    """
    g = StateGraph(AgentState)
    g.add_node("orient", orient)
    g.set_entry_point("orient")
    g.add_edge("orient", END)  # extended in later tasks
    return g.compile(checkpointer=checkpointer)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_orient.py tests/test_state.py -v`
Expected: all passed (orient tests + state tests still green)

- [ ] **Step 7: Append LEARNING.md section 2**

Append to `homelab-agent/LEARNING.md`:

```markdown
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
```

- [ ] **Step 8: Commit**

```bash
cd /Users/arisela/git/claude-agents
git add homelab-agent/
git commit -m "feat(homelab-agent): prompts, model factories, and orient node with keyword+LLM routing"
```

---

### Task 4: Tools — MCP client and the k8s-reader A2A client (`tools.py`)

**Files:**
- Create: `homelab-agent/src/homelab_agent/tools.py`
- Test: `homelab-agent/tests/test_tools.py`
- Modify: `homelab-agent/LEARNING.md` (append section 3)

**Interfaces:**
- Consumes: `settings` (Task 1), `get_model` (Task 3), `RETRIEVE_PROMPT` (Task 3).
- Produces: `tools._mcp_server_config() -> dict`; `tools.get_doc_tools() -> list` (async); `tools.a2a_send(url: str, text: str, timeout: float = 120.0) -> str` (async; JSON-RPC `message/send`, returns extracted text); `tools.ask_k8s_reader(question: str) -> str` (async); `tools._extract_a2a_text(result: dict) -> str`. (Task 5 adds `run_doc_retrieval`.)

- [ ] **Step 1: Write the failing tests**

Create `homelab-agent/tests/test_tools.py`:

```python
"""Tools layer: MCP server config from env, and the A2A JSON-RPC client."""

import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from homelab_agent import tools


# --- MCP server config ------------------------------------------------------

def test_mcp_config_has_agent_docs_and_backstage(monkeypatch):
    monkeypatch.setenv("BACKSTAGE_MCP_TOKEN", "tok123")
    monkeypatch.setenv("AGENT_DOCS_MCP_AUTH_HEADER", "")
    # settings is module-level; rebuild from patched env for the test
    from homelab_agent.config import Settings
    with patch.object(tools, "settings", Settings.from_env()):
        cfg = tools._mcp_server_config()
    assert cfg["agent_docs"]["transport"] == "streamable_http"
    assert cfg["agent_docs"]["url"].endswith("/mcp")
    assert "headers" not in cfg["agent_docs"]  # no auth header configured
    assert cfg["backstage_catalog"]["headers"]["Authorization"] == "Bearer tok123"


def test_mcp_config_agent_docs_auth_header(monkeypatch):
    monkeypatch.setenv("AGENT_DOCS_MCP_AUTH_HEADER", "Basic abc=")
    from homelab_agent.config import Settings
    with patch.object(tools, "settings", Settings.from_env()):
        cfg = tools._mcp_server_config()
    assert cfg["agent_docs"]["headers"]["Authorization"] == "Basic abc="


# --- A2A text extraction ----------------------------------------------------

def test_extract_text_from_task_artifacts():
    result = {
        "artifacts": [
            {"parts": [{"kind": "text", "text": "vault is healthy"}]},
        ],
        "status": {"state": "completed"},
    }
    assert tools._extract_a2a_text(result) == "vault is healthy"


def test_extract_text_falls_back_to_status_message():
    result = {
        "artifacts": [],
        "status": {
            "state": "completed",
            "message": {"parts": [{"kind": "text", "text": "from status"}]},
        },
    }
    assert tools._extract_a2a_text(result) == "from status"


def test_extract_text_from_direct_message_result():
    result = {"kind": "message", "parts": [{"kind": "text", "text": "hi"}]}
    assert tools._extract_a2a_text(result) == "hi"


# --- a2a_send ---------------------------------------------------------------

async def test_a2a_send_posts_jsonrpc_and_returns_text():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": captured["body"]["id"],
                "result": {
                    "artifacts": [{"parts": [{"kind": "text", "text": "3 pods Running"}]}],
                    "status": {"state": "completed"},
                },
            },
        )

    transport = httpx.MockTransport(handler)
    with patch.object(tools, "_transport", transport):
        reply = await tools.a2a_send("http://fake-agent:8080", "pods in vault ns?")

    assert reply == "3 pods Running"
    body = captured["body"]
    assert body["method"] == "message/send"
    assert body["params"]["message"]["role"] == "user"
    assert body["params"]["message"]["parts"][0]["text"] == "pods in vault ns?"


async def test_a2a_send_raises_on_jsonrpc_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": "1",
                  "error": {"code": -32600, "message": "bad request"}},
        )

    with patch.object(tools, "_transport", httpx.MockTransport(handler)):
        with pytest.raises(RuntimeError, match="bad request"):
            await tools.a2a_send("http://fake-agent:8080", "q")


async def test_ask_k8s_reader_targets_configured_url():
    with patch.object(tools, "a2a_send", new=AsyncMock(return_value="ok")) as mock_send:
        out = await tools.ask_k8s_reader("is vault healthy?")
    assert out == "ok"
    mock_send.assert_awaited_once_with(
        tools.settings.k8s_reader_a2a_url, "is vault healthy?"
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_tools.py -v`
Expected: FAIL with `ModuleNotFoundError` / `AttributeError` (module doesn't exist yet)

- [ ] **Step 3: Implement tools.py**

Create `homelab-agent/src/homelab_agent/tools.py`:

```python
"""External capabilities: MCP doc tools and the k8s-reader A2A delegate.

LangGraph concept — MCP tools as LangGraph tools:
`langchain-mcp-adapters`' MultiServerMCPClient speaks the MCP protocol to
remote servers and converts each discovered MCP tool into a LangChain `BaseTool`.
Anything that accepts LangChain tools (bind_tools, ToolNode, prebuilt agents)
can then call them — the graph never knows MCP is underneath.

Note: kagent does NOT inject MCP tools into BYO containers (Phase 0 finding
#3) — this module is the replacement wiring, pointed at the same in-cluster
MCP servers the Declarative agent used.
"""

import logging
import uuid

import httpx
from langchain_mcp_adapters.client import MultiServerMCPClient

from homelab_agent.config import settings

logger = logging.getLogger(__name__)

# Test seam: tests inject an httpx.MockTransport here.
_transport: httpx.AsyncBaseTransport | None = None


def _mcp_server_config() -> dict:
    """Build MultiServerMCPClient config from env (see README env table)."""
    agent_docs: dict = {
        "transport": "streamable_http",
        "url": settings.agent_docs_mcp_url,
    }
    if settings.agent_docs_mcp_auth_header:
        agent_docs["headers"] = {"Authorization": settings.agent_docs_mcp_auth_header}

    backstage: dict = {
        "transport": "streamable_http",
        "url": settings.backstage_mcp_url,
    }
    if settings.backstage_mcp_token:
        backstage["headers"] = {"Authorization": f"Bearer {settings.backstage_mcp_token}"}

    return {"agent_docs": agent_docs, "backstage_catalog": backstage}


async def get_doc_tools() -> list:
    """Discover the doc tools (get_file_contents, search_code,
    get-catalog-entity) from the in-cluster MCP servers as LangChain tools."""
    client = MultiServerMCPClient(_mcp_server_config())
    return await client.get_tools()


# --- A2A client (delegation is an HTTP call, not a CRD tool) -----------------

def _extract_a2a_text(result: dict) -> str:
    """Pull the text out of an A2A `message/send` result.

    The result may be a Task (text lives in artifacts, or in the final
    status message) or a direct Message. Mirrors the tolerant extraction
    oncall-crewai uses on the server side.
    """
    texts: list[str] = []

    def _collect(parts) -> None:
        for part in parts or []:
            text = part.get("text")
            if text:
                texts.append(text)

    for artifact in result.get("artifacts") or []:
        _collect(artifact.get("parts"))
    if not texts:
        message = (result.get("status") or {}).get("message") or {}
        _collect(message.get("parts"))
    if not texts and result.get("kind") == "message":
        _collect(result.get("parts"))
    return "\n".join(texts)


async def a2a_send(url: str, text: str, timeout: float = 120.0) -> str:
    """Send one A2A JSON-RPC `message/send` and return the reply text."""
    payload = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": "message/send",
        "params": {
            "message": {
                "kind": "message",
                "role": "user",
                "messageId": str(uuid.uuid4()),
                "parts": [{"kind": "text", "text": text}],
            }
        },
    }
    async with httpx.AsyncClient(timeout=timeout, transport=_transport) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()
    if "error" in data:
        raise RuntimeError(f"A2A error from {url}: {data['error'].get('message')}")
    return _extract_a2a_text(data.get("result") or {})


async def ask_k8s_reader(question: str) -> str:
    """Delegate a live-state question to the read-only k8s-reader agent.

    This replaces the Declarative agent's `type: Agent` CRD tool: in a BYO
    container, delegation is an explicit A2A client call from a graph node.
    Capability-transitivity is preserved — k8s-reader binds only read tools.
    """
    return await a2a_send(settings.k8s_reader_a2a_url, question)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_tools.py -v`
Expected: 8 passed

- [ ] **Step 5: Append LEARNING.md section 3**

Append to `homelab-agent/LEARNING.md`:

```markdown
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
```

- [ ] **Step 6: Commit**

```bash
cd /Users/arisela/git/claude-agents
git add homelab-agent/
git commit -m "feat(homelab-agent): MCP tool discovery and k8s-reader A2A client"
```

---

### Task 5: The retrieve node (ReAct sub-agent over doc tools)

**Files:**
- Modify: `homelab-agent/src/homelab_agent/tools.py` (add `run_doc_retrieval`), `homelab-agent/src/homelab_agent/graph.py` (add `retrieve` node; rewire `orient → retrieve → END`)
- Test: `homelab-agent/tests/test_graph.py` (new file, retrieve section)
- Modify: `homelab-agent/LEARNING.md` (append section 4)

**Interfaces:**
- Consumes: `get_doc_tools`, `get_model`, `RETRIEVE_PROMPT`.
- Produces: `tools.run_doc_retrieval(question: str, route: str) -> tuple[str, list[str]]` (async; returns `(findings, checked)`); `graph.retrieve(state: AgentState) -> dict` (async; returns `{"doc_findings": str, "checked": list[str]}`). Task 6 relies on `retrieve` being an async node already wired after `orient`.

- [ ] **Step 1: Write the failing tests**

Create `homelab-agent/tests/test_graph.py`:

```python
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
```

Also add to `homelab-agent/tests/test_tools.py`:

```python
# --- run_doc_retrieval -------------------------------------------------------

async def test_run_doc_retrieval_invokes_react_agent_and_reports_checked():
    class FakeAgent:
        async def ainvoke(self, payload):
            class Msg:
                content = "found: base-apps/cert-manager/docs.md"
            return {"messages": [Msg()]}

    with patch.object(tools, "get_doc_tools", new=AsyncMock(return_value=[])), \
         patch.object(tools, "_build_doc_agent", return_value=FakeAgent()):
        findings, checked = await tools.run_doc_retrieval("what is cert-manager?", "docs")

    assert "cert-manager" in findings
    assert checked == ["agent-docs MCP (get_file_contents / search_code)"]


async def test_run_doc_retrieval_ownership_route_reports_backstage():
    class FakeAgent:
        async def ainvoke(self, payload):
            class Msg:
                content = "owner: platform-engineering"
            return {"messages": [Msg()]}

    with patch.object(tools, "get_doc_tools", new=AsyncMock(return_value=[])), \
         patch.object(tools, "_build_doc_agent", return_value=FakeAgent()):
        findings, checked = await tools.run_doc_retrieval("who owns vault?", "ownership")

    assert checked == [
        "agent-docs MCP (get_file_contents / search_code)",
        "backstage-catalog MCP (get-catalog-entity)",
    ]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_graph.py tests/test_tools.py -v`
Expected: new tests FAIL (`AttributeError: ... has no attribute 'retrieve'` / `'run_doc_retrieval'`); previous tests still pass.

- [ ] **Step 3: Add run_doc_retrieval to tools.py**

Append to `homelab-agent/src/homelab_agent/tools.py`:

```python
# --- doc retrieval: a prebuilt ReAct agent INSIDE one node -------------------

def _build_doc_agent(model, doc_tools, system_prompt: str):
    """Build the tool-calling loop for retrieval.

    LangGraph concept — create_react_agent vs a hand-built graph:
    `create_react_agent` compiles the standard agent loop for you — a model
    node with tools bound, a ToolNode that executes whichever tool the model
    called, and a `tools_condition` edge looping until the model stops
    calling tools. We hand-build the OUTER graph (auditable routing is the
    point of this migration) but use the prebuilt loop INSIDE retrieve,
    where "call read tools until you've gathered enough" is exactly the
    generic ReAct shape and hand-rolling it would add nothing.
    """
    try:
        from langgraph.prebuilt import create_react_agent

        return create_react_agent(model, doc_tools, prompt=system_prompt)
    except ImportError:
        # Newer stacks moved the prebuilt into langchain
        from langchain.agents import create_agent

        return create_agent(model, tools=doc_tools, system_prompt=system_prompt)


async def run_doc_retrieval(question: str, route: str) -> tuple[str, list[str]]:
    """Run the atlas→index→app traversal; return (findings, checked)."""
    from homelab_agent.model import get_model
    from homelab_agent.prompts import RETRIEVE_PROMPT

    doc_tools = await get_doc_tools()
    agent = _build_doc_agent(get_model(), doc_tools, RETRIEVE_PROMPT)
    result = await agent.ainvoke(
        {"messages": [("user", f"Route: {route}\nQuestion: {question}")]}
    )
    findings = result["messages"][-1].content

    checked = ["agent-docs MCP (get_file_contents / search_code)"]
    if route == "ownership":
        checked.append("backstage-catalog MCP (get-catalog-entity)")
    return findings, checked
```

- [ ] **Step 4: Add the retrieve node and rewire graph.py**

In `homelab-agent/src/homelab_agent/graph.py`, add after `orient` (and add `from homelab_agent import tools` to the imports):

```python
async def retrieve(state: AgentState) -> dict:
    """Node 2: always runs. Doc retrieval via the ReAct sub-agent.

    Thin by design: the node owns the STATE contract (which fields it
    writes); tools.py owns the HOW. That keeps nodes trivially testable —
    tests patch tools.run_doc_retrieval and never touch MCP or the model.
    """
    findings, checked = await tools.run_doc_retrieval(
        state["question"], state["route"]
    )
    return {"doc_findings": findings, "checked": checked}
```

And update `build_graph` wiring:

```python
    g = StateGraph(AgentState)
    g.add_node("orient", orient)
    g.add_node("retrieve", retrieve)
    g.set_entry_point("orient")
    g.add_edge("orient", "retrieve")
    g.add_edge("retrieve", END)  # conditional routing lands in Task 6
    return g.compile(checkpointer=checkpointer)
```

Note: `test_build_graph_runs_orient` in test_orient.py used sync `invoke` on an orient-only graph; with `retrieve` wired in it would hit the patched-nothing path. Update that test to patch retrieval:

```python
async def test_build_graph_runs_orient():
    from unittest.mock import AsyncMock, patch

    from homelab_agent.graph import build_graph

    # The graph now contains async nodes → must use ainvoke, not invoke.
    with patch("homelab_agent.tools.run_doc_retrieval",
               AsyncMock(return_value=("", []))):
        g = build_graph()
        out = await g.ainvoke({"question": "Is the argo-cd control plane healthy?"})
    assert out["route"] == "live"
```

- [ ] **Step 5: Run the full suite**

Run: `pytest tests/ -v`
Expected: all passed

- [ ] **Step 6: Append LEARNING.md section 4**

Append to `homelab-agent/LEARNING.md`:

```markdown
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
```

- [ ] **Step 7: Commit**

```bash
cd /Users/arisela/git/claude-agents
git add homelab-agent/
git commit -m "feat(homelab-agent): retrieve node running ReAct doc traversal over MCP tools"
```

---

### Task 6: delegate_k8s, drift_check, synthesize + conditional routing (full graph)

**Files:**
- Modify: `homelab-agent/src/homelab_agent/graph.py` (three nodes, `needs_live`, final wiring)
- Test: `homelab-agent/tests/test_graph.py` (extend)
- Modify: `homelab-agent/LEARNING.md` (append section 5)

**Interfaces:**
- Consumes: `tools.ask_k8s_reader`, `get_model`, `DRIFT_PROMPT`, `SYNTHESIZE_PROMPT`.
- Produces: `graph.delegate_k8s`, `graph.drift_check`, `graph.synthesize` (async nodes); `graph.needs_live(state) -> str` returning `"live"` or `"docs"`; final `build_graph()` shape: `orient → retrieve → (conditional) → [delegate_k8s → drift_check]? → synthesize → END`. `synthesize` writes `answer` — the server (Task 8) reads `result["answer"]`.

- [ ] **Step 1: Write the failing tests**

Append to `homelab-agent/tests/test_graph.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_graph.py -v`
Expected: new tests FAIL with `AttributeError` (nodes don't exist); Task 5 tests still pass.

- [ ] **Step 3: Implement the three nodes and final wiring**

In `homelab-agent/src/homelab_agent/graph.py`, add `get_model` to the model import and `DRIFT_PROMPT, SYNTHESIZE_PROMPT` to the prompts import, then add:

```python
async def delegate_k8s(state: AgentState) -> dict:
    """Node 3 (conditional): live-state lookup via the k8s-reader delegate."""
    reply = await tools.ask_k8s_reader(state["question"])
    return {"live_findings": reply, "checked": ["k8s-reader (A2A delegate)"]}


async def drift_check(state: AgentState) -> dict:
    """Node 4: docs vs live diff. Only reachable on the live path, so both
    inputs always exist when this runs (see routing below)."""
    reply = await get_model().ainvoke(
        DRIFT_PROMPT.format(
            docs=state.get("doc_findings", ""),
            live=state.get("live_findings", ""),
        )
    )
    text = reply.content.strip()
    if text.upper().startswith("NONE"):
        return {"drift": []}
    drift = [
        line.lstrip("- ").strip()
        for line in text.splitlines()
        if line.strip().startswith("-")
    ]
    return {"drift": drift}


async def synthesize(state: AgentState) -> dict:
    """Node 5: compose the final answer in the required response format."""
    reply = await get_model().ainvoke(
        SYNTHESIZE_PROMPT.format(
            question=state.get("question", ""),
            doc_findings=state.get("doc_findings", ""),
            live_findings=state.get("live_findings", ""),
            drift="\n".join(state.get("drift", [])) or "(none)",
            checked="\n".join(f"- {c}" for c in state.get("checked", [])),
        )
    )
    return {"answer": reply.content}


def needs_live(state: AgentState) -> str:
    """Conditional edge after retrieve.

    LangGraph concept — a conditional edge is a FUNCTION of state returning
    a label; add_conditional_edges maps labels to destination nodes. This is
    the deterministic branch point: only `route == "live"` visits the
    delegate; ownership/docs go straight to synthesize. Because branching is
    a routing DECISION (one path taken), not a fan-out (both paths taken),
    there is no join to stall and every node runs at most once — the
    correctness property the design doc calls out.
    """
    return "live" if state.get("route") == "live" else "docs"
```

And the final `build_graph` wiring:

```python
    g = StateGraph(AgentState)
    g.add_node("orient", orient)
    g.add_node("retrieve", retrieve)
    g.add_node("delegate_k8s", delegate_k8s)
    g.add_node("drift_check", drift_check)
    g.add_node("synthesize", synthesize)

    g.set_entry_point("orient")
    g.add_edge("orient", "retrieve")
    g.add_conditional_edges(
        "retrieve", needs_live, {"live": "delegate_k8s", "docs": "synthesize"}
    )
    g.add_edge("delegate_k8s", "drift_check")
    g.add_edge("drift_check", "synthesize")
    g.add_edge("synthesize", END)
    return g.compile(checkpointer=checkpointer)
```

- [ ] **Step 4: Run the full suite**

Run: `pytest tests/ -v`
Expected: all passed

- [ ] **Step 5: Append LEARNING.md section 5**

Append to `homelab-agent/LEARNING.md`:

```markdown
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
```

- [ ] **Step 6: Commit**

```bash
cd /Users/arisela/git/claude-agents
git add homelab-agent/
git commit -m "feat(homelab-agent): full StateGraph with conditional live-state routing, drift check, synthesis"
```

---

### Task 7: Checkpointer (`checkpointer.py`)

**Files:**
- Create: `homelab-agent/src/homelab_agent/checkpointer.py`
- Test: `homelab-agent/tests/test_checkpointer.py`
- Modify: `homelab-agent/pyproject.toml` (add kagent dependency), `homelab-agent/LEARNING.md` (append section 6)

**Interfaces:**
- Consumes: nothing internal (reads env directly).
- Produces: `checkpointer.get_checkpointer() -> BaseCheckpointSaver | None` — returns a `KAgentCheckpointer` when running under kagent (`KAGENT_URL` env present and the package importable), else `None`. Task 8's server calls `build_graph(checkpointer=get_checkpointer())`.

- [ ] **Step 1: Discover the kagent package (pin it honestly)**

```bash
pip install kagent-langgraph
python -c "from kagent.langgraph import KAgentCheckpointer; from kagent.core import KAgentConfig; import inspect; print(inspect.signature(KAgentCheckpointer.__init__)); print([a for a in dir(KAgentConfig) if not a.startswith('_')])"
pip show kagent-langgraph | head -3
```

Expected: prints the constructor signature and KAgentConfig attributes.
**Contingency:** if `kagent-langgraph` is not on PyPI under that name, try `pip install kagent-adk` then the same import probe; if neither provides `KAgentCheckpointer`, implement `get_checkpointer()` to return `None` with a logged warning, add a `# TODO(deploy-follow-up)` comment naming the missing package, and record this in your completion report as a concern — do NOT fake a checkpointer.

Add the discovered package to `pyproject.toml` dependencies with the installed version as floor (e.g. `"kagent-langgraph>=X.Y.Z"`), and note the version in README's "Pinned environment" section.

- [ ] **Step 2: Write the failing tests**

Create `homelab-agent/tests/test_checkpointer.py`:

```python
"""Checkpointer wiring: on under kagent, off (None) everywhere else."""

from langgraph.checkpoint.memory import MemorySaver

from homelab_agent.checkpointer import get_checkpointer


def test_returns_none_without_kagent_env(monkeypatch):
    monkeypatch.delenv("KAGENT_URL", raising=False)
    assert get_checkpointer() is None


async def test_threads_persist_state_across_invocations():
    """The concept the checkpointer buys us, demonstrated with MemorySaver:
    same thread_id → the graph resumes with remembered state."""
    from unittest.mock import AsyncMock, patch

    from homelab_agent.graph import build_graph

    with patch("homelab_agent.tools.run_doc_retrieval",
               AsyncMock(return_value=("findings", ["agent-docs MCP"]))), \
         patch("homelab_agent.graph.get_model") as mock_model:
        reply = AsyncMock()
        reply.return_value.content = "answer"
        mock_model.return_value.ainvoke = reply

        g = build_graph(checkpointer=MemorySaver())
        config = {"configurable": {"thread_id": "session-1"}}
        # Async nodes in the graph → ainvoke; get_state is sync.
        await g.ainvoke({"question": "What is cert-manager?"}, config=config)

        snapshot = g.get_state(config)
    assert snapshot.values["question"] == "What is cert-manager?"
    assert snapshot.values["answer"] == "answer"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_checkpointer.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'homelab_agent.checkpointer'`

- [ ] **Step 4: Implement checkpointer.py**

Create `homelab-agent/src/homelab_agent/checkpointer.py` (adapt the ONE constructor call to the signature printed in Step 1 — the module contract below must not change):

```python
"""Optional KAgentCheckpointer wiring.

LangGraph concept — checkpointer & threads:
a checkpointer persists the graph's state after every superstep, keyed by
`thread_id` (passed via config.configurable). Same thread_id → the graph
resumes from the saved state; different thread_id → a fresh conversation.
"Thread state persistence" = conversations survive pod restarts.

kagent's controller offers a checkpoint store over HTTP; KAgentCheckpointer
is the LangGraph adapter for it. kagent injects its config (KAGENT_URL etc.)
into BYO pods — locally those envs are absent and we run without
persistence, which keeps tests hermetic.
"""

import logging
import os

logger = logging.getLogger(__name__)


def get_checkpointer():
    """Return a KAgentCheckpointer when running under kagent, else None."""
    if not os.getenv("KAGENT_URL"):
        return None
    try:
        from kagent.core import KAgentConfig
        from kagent.langgraph import KAgentCheckpointer
    except ImportError as exc:
        logger.warning("kagent packages unavailable (%s); running without persistence", exc)
        return None

    config = KAgentConfig()
    # NOTE: adapt this constructor call to the signature discovered in the
    # pinned release (Task 7 Step 1). The contract of THIS function is fixed.
    return KAgentCheckpointer(base_url=config.url, app_name=config.app_name)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_checkpointer.py -v`
Expected: 2 passed

- [ ] **Step 6: Append LEARNING.md section 6**

Append to `homelab-agent/LEARNING.md`:

```markdown
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
```

- [ ] **Step 7: Commit**

```bash
cd /Users/arisela/git/claude-agents
git add homelab-agent/
git commit -m "feat(homelab-agent): optional KAgentCheckpointer wiring with thread persistence demo"
```

---

### Task 8: A2A server and executor (`server.py`, `executor.py`)

**Files:**
- Create: `homelab-agent/src/homelab_agent/executor.py`, `homelab-agent/src/homelab_agent/server.py`
- Test: `homelab-agent/tests/test_server_a2a.py`
- Modify: `homelab-agent/LEARNING.md` (append section 7)

**Interfaces:**
- Consumes: `build_graph`, `get_checkpointer`, `settings`.
- Produces: `executor.HomelabAgentExecutor` (a2a-sdk `AgentExecutor`); `server.create_app() -> FastAPI` and module-level `app` — uvicorn entrypoint `homelab_agent.server:app`, port 8080. Agent card name `homelab-agent`, version `0.1.0`, three skills with ids `repo-knowledge`, `cluster-troubleshooting`, `deployment-guidance`.

- [ ] **Step 1: Write the failing tests**

Create `homelab-agent/tests/test_server_a2a.py`:

```python
"""A2A protocol surface: health, agent card, executor event flow.
Mirrors oncall-crewai/tests/test_k8s_agent_a2a.py."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.delenv("KAGENT_URL", raising=False)
    from homelab_agent.server import create_app

    return create_app()


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestHealth:
    async def test_health_returns_200(self, client):
        response = await client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "healthy", "agent": "homelab-agent"}


class TestAgentCard:
    async def test_card_identity(self, client):
        response = await client.get("/.well-known/agent.json")
        assert response.status_code == 200
        card = response.json()
        assert card["name"] == "homelab-agent"
        assert card["version"] == "0.1.0"

    async def test_card_carries_the_three_skills(self, client):
        card = (await client.get("/.well-known/agent.json")).json()
        ids = [s["id"] for s in card["skills"]]
        assert ids == ["repo-knowledge", "cluster-troubleshooting", "deployment-guidance"]

    async def test_card_skills_have_examples(self, client):
        card = (await client.get("/.well-known/agent.json")).json()
        repo = next(s for s in card["skills"] if s["id"] == "repo-knowledge")
        assert "What is cert-manager and how does it issue certs here?" in repo["examples"]


class TestExecutor:
    async def test_execute_success_emits_working_artifact_completed(self):
        from a2a.server.events.event_queue import EventQueue
        from a2a.types import TaskState, TextPart

        from homelab_agent.executor import HomelabAgentExecutor

        executor = HomelabAgentExecutor()
        context = MagicMock()
        context.task_id = str(uuid.uuid4())
        context.context_id = str(uuid.uuid4())
        context.message.parts = [TextPart(text="What is cert-manager?")]

        event_queue = EventQueue()
        fake_graph = MagicMock()
        fake_graph.ainvoke = AsyncMock(
            return_value={"answer": "cert-manager issues certs via Argo CD."}
        )
        with patch.object(executor, "_graph", fake_graph):
            await executor.execute(context, event_queue)

        # thread_id must be the A2A context_id (one conversation = one thread)
        _, kwargs = fake_graph.ainvoke.call_args
        assert kwargs["config"]["configurable"]["thread_id"] == context.context_id

        event1 = await event_queue.dequeue_event(no_wait=True)
        assert event1.status.state == TaskState.working
        event2 = await event_queue.dequeue_event(no_wait=True)
        assert event2.artifact is not None
        event3 = await event_queue.dequeue_event(no_wait=True)
        assert event3.status.state == TaskState.completed
        assert "cert-manager" in event3.status.message.parts[0].root.text

    async def test_execute_error_emits_failed(self):
        from a2a.server.events.event_queue import EventQueue
        from a2a.types import TaskState, TextPart

        from homelab_agent.executor import HomelabAgentExecutor

        executor = HomelabAgentExecutor()
        context = MagicMock()
        context.task_id = str(uuid.uuid4())
        context.context_id = str(uuid.uuid4())
        context.message.parts = [TextPart(text="boom")]

        event_queue = EventQueue()
        fake_graph = MagicMock()
        fake_graph.ainvoke = AsyncMock(side_effect=RuntimeError("LLM timeout"))
        with patch.object(executor, "_graph", fake_graph):
            await executor.execute(context, event_queue)

        event1 = await event_queue.dequeue_event(no_wait=True)
        assert event1.status.state == TaskState.working
        event2 = await event_queue.dequeue_event(no_wait=True)
        assert event2.status.state == TaskState.failed
        assert "LLM timeout" in event2.status.message.parts[0].root.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_server_a2a.py -v`
Expected: FAIL with `ModuleNotFoundError` (server/executor don't exist)

- [ ] **Step 3: Implement executor.py**

Create `homelab-agent/src/homelab_agent/executor.py`:

```python
"""A2A AgentExecutor: the bridge from the A2A protocol to the LangGraph graph.

The a2a-sdk server calls execute() per message/send request; we extract the
question, run the graph (thread_id = A2A context_id, so one A2A conversation
maps to one checkpointer thread), and stream working → artifact → completed
events back. Mirrors oncall-crewai's executor shape.
"""

import logging
import uuid

from a2a.server.agent_execution import AgentExecutor
from a2a.server.agent_execution.context import RequestContext
from a2a.server.events.event_queue import EventQueue
from a2a.types import (
    Artifact,
    Message,
    Part,
    Role,
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
    TextPart,
)

from homelab_agent.checkpointer import get_checkpointer
from homelab_agent.graph import build_graph

logger = logging.getLogger(__name__)


def _status_event(task_id, context_id, state, text, final):
    return TaskStatusUpdateEvent(
        task_id=task_id,
        context_id=context_id,
        final=final,
        status=TaskStatus(
            state=state,
            message=Message(
                role=Role.agent,
                message_id=str(uuid.uuid4()),
                parts=[TextPart(text=text)],
            ),
        ),
    )


def _extract_user_input(message) -> str:
    if message and message.parts:
        texts = []
        for part in message.parts:
            if isinstance(part, TextPart):
                texts.append(part.text)
            elif hasattr(part, "root") and isinstance(part.root, TextPart):
                texts.append(part.root.text)
        if texts:
            return " ".join(texts)
    return "Give me an overview of this homelab cluster."


class HomelabAgentExecutor(AgentExecutor):
    def __init__(self):
        # Compile once; the checkpointer (if any) makes threads persistent.
        self._graph = build_graph(checkpointer=get_checkpointer())

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        task_id, context_id = context.task_id, context.context_id
        try:
            question = _extract_user_input(context.message)
            logger.info("homelab-agent question: %s", question[:120])

            await event_queue.enqueue_event(_status_event(
                task_id, context_id, TaskState.working,
                "Consulting agent-docs (and live state if needed)...", False,
            ))

            result = await self._graph.ainvoke(
                {"question": question},
                config={"configurable": {"thread_id": context_id or str(uuid.uuid4())}},
            )
            answer = result.get("answer") or "No answer produced."

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

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError("homelab-agent does not support cancellation")
```

- [ ] **Step 4: Implement server.py**

Create `homelab-agent/src/homelab_agent/server.py`:

```python
"""A2A server on :8080 — the kagent BYO serving contract.

kagent deploys the BYO image and expects the A2A protocol on port 8080:
GET /.well-known/agent.json (discovery) and JSON-RPC POST / (message/send).
Pattern mirrored from oncall-crewai's k8s_agent/server.py.
"""

import logging
import os

from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentSkill
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from homelab_agent.config import settings
from homelab_agent.executor import HomelabAgentExecutor

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger(__name__)


def _build_agent_card() -> AgentCard:
    url = os.getenv("AGENT_URL", "http://0.0.0.0:8080")
    # The three skills carried over verbatim from the Declarative agent's
    # a2aConfig — their example prompts are also the parity-harness inputs.
    return AgentCard(
        name="homelab-agent",
        description=(
            "Answers questions about the homelab GitOps repo, base-apps "
            "deployments, and live cluster state (via the k8s-reader delegate)."
        ),
        url=url,
        version="0.1.0",
        default_input_modes=["text"],
        default_output_modes=["text"],
        capabilities=AgentCapabilities(streaming=False),
        skills=[
            AgentSkill(
                id="repo-knowledge",
                name="Repo & Architecture Knowledge",
                description=(
                    "Explain what's deployed, where it lives in the GitOps "
                    "repo, and how components are wired together."
                ),
                examples=[
                    "What is cert-manager and how does it issue certs here?",
                    "Who owns chores-tracker-backend and what does it depend on?",
                    "Where does vault store its config and how is it unsealed?",
                ],
                tags=["gitops", "documentation", "architecture"],
            ),
            AgentSkill(
                id="cluster-troubleshooting",
                name="Cluster State Troubleshooting",
                description=(
                    "Diagnose issues by checking live pod/deployment/event "
                    "state and correlating with the GitOps manifests."
                ),
                examples=[
                    "cert-manager Certificates are stuck pending — walk me through the runbook.",
                    "chores-tracker-backend is CrashLooping — what does its runbook say to check?",
                    "Is the argo-cd control plane healthy?",
                ],
                tags=["troubleshooting", "kubernetes", "argocd"],
            ),
            AgentSkill(
                id="deployment-guidance",
                name="Deployment & Onboarding Guidance",
                description=(
                    "Recommend how to onboard a new app following the "
                    "established base-apps patterns (Crossplane composition, "
                    "SecretStore, ingress, ECR auth)."
                ),
                examples=[
                    "I want to deploy a new service called billing-api. What's the right pattern?",
                    "How do I add Vault secrets for a new namespace?",
                ],
                tags=["onboarding", "crossplane", "idp"],
            ),
        ],
    )


def create_app() -> FastAPI:
    fastapi_app = FastAPI(title="homelab-agent A2A", version="0.1.0")

    @fastapi_app.get("/health")
    async def health():
        return JSONResponse({"status": "healthy", "agent": "homelab-agent"})

    handler = DefaultRequestHandler(
        agent_executor=HomelabAgentExecutor(),
        task_store=InMemoryTaskStore(),
    )
    a2a_app = A2AStarletteApplication(
        agent_card=_build_agent_card(),
        http_handler=handler,
    )
    fastapi_app.mount("/", a2a_app.build())
    logger.info("homelab-agent A2A server ready")
    return fastapi_app


app = create_app()
```

- [ ] **Step 5: Run the full suite**

Run: `pytest tests/ -v`
Expected: all passed

- [ ] **Step 6: Append LEARNING.md section 7**

Append to `homelab-agent/LEARNING.md`:

```markdown
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
```

- [ ] **Step 7: Commit**

```bash
cd /Users/arisela/git/claude-agents
git add homelab-agent/
git commit -m "feat(homelab-agent): A2A server on :8080 with agent card and graph executor"
```

---

### Task 9: Golden-question parity harness

**Files:**
- Create: `homelab-agent/tests/parity/golden_questions.yaml`, `homelab-agent/src/homelab_agent/parity.py`, `homelab-agent/scripts/parity_check.py`
- Test: `homelab-agent/tests/test_parity_checks.py`

**Interfaces:**
- Consumes: `tools.a2a_send` (Task 4).
- Produces: `parity.format_check(answer: str) -> list[str]` (violation strings, empty = pass); `parity.read_only_check(answer: str) -> list[str]`; `parity.build_report(results: list[dict]) -> str` (markdown). `scripts/parity_check.py` runs the golden questions against `OLD_AGENT_URL` and `NEW_AGENT_URL` env endpoints and writes `parity-report.md`. This harness gates cutover — but *running* it against live agents happens in the arigsela/kubernetes follow-up.

- [ ] **Step 1: Create the golden-question set**

Create `homelab-agent/tests/parity/golden_questions.yaml` (these are the 8 example prompts from the Declarative agent's `a2aConfig.skills`, verbatim):

```yaml
# Golden questions = the example prompts from homelab-knowledge's
# a2aConfig.skills. Parity means the new agent answers these at least as
# well as the old one, in the required format, read-only.
- skill: repo-knowledge
  question: "What is cert-manager and how does it issue certs here?"
- skill: repo-knowledge
  question: "Who owns chores-tracker-backend and what does it depend on?"
- skill: repo-knowledge
  question: "Where does vault store its config and how is it unsealed?"
- skill: cluster-troubleshooting
  question: "cert-manager Certificates are stuck pending — walk me through the runbook."
- skill: cluster-troubleshooting
  question: "chores-tracker-backend is CrashLooping — what does its runbook say to check?"
- skill: cluster-troubleshooting
  question: "Is the argo-cd control plane healthy?"
- skill: deployment-guidance
  question: "I want to deploy a new service called billing-api. What's the right pattern?"
- skill: deployment-guidance
  question: "How do I add Vault secrets for a new namespace?"
```

- [ ] **Step 2: Write the failing tests**

Create `homelab-agent/tests/test_parity_checks.py`:

```python
"""Automated parity checks: response format + read-only behavior."""

from homelab_agent.parity import build_report, format_check, read_only_check

GOOD_ANSWER = """cert-manager issues certificates via Let's Encrypt.

## What I checked
- agent-docs MCP (get_file_contents / search_code)

## Specifics
- base-apps/cert-manager/docs.md
- Verify: kubectl get certificates -A
"""


def test_format_check_passes_good_answer():
    assert format_check(GOOD_ANSWER) == []


def test_format_check_flags_missing_what_i_checked():
    violations = format_check("Just an answer with no sections.")
    assert any("What I checked" in v for v in violations)


def test_read_only_check_passes_read_commands():
    assert read_only_check(GOOD_ANSWER) == []
    assert read_only_check("Run kubectl get pods and kubectl describe deploy x") == []


def test_read_only_check_flags_mutations():
    for bad in (
        "Run kubectl apply -f fix.yaml",
        "kubectl delete pod vault-0",
        "kubectl edit deployment x",
        "kubectl patch svc y",
        "kubectl exec -it vault-0 -- sh",
        "kubectl scale deploy x --replicas=3",
    ):
        assert read_only_check(bad), f"should flag: {bad}"


def test_build_report_contains_both_answers_and_checks():
    results = [{
        "skill": "repo-knowledge",
        "question": "What is cert-manager?",
        "old_answer": "old says hi",
        "new_answer": GOOD_ANSWER,
        "new_violations": [],
    }]
    report = build_report(results)
    assert "What is cert-manager?" in report
    assert "old says hi" in report
    assert "PASS" in report
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_parity_checks.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'homelab_agent.parity'`

- [ ] **Step 4: Implement parity.py**

Create `homelab-agent/src/homelab_agent/parity.py`:

```python
"""Parity-harness checks: the automatable slice of "answers at parity".

Correctness comparison stays human (read the report); these checks catch
the objective regressions: broken response format and mutation advice.
"""

import re

_MUTATION_RE = re.compile(
    r"kubectl\s+(apply|delete|edit|patch|exec|scale|create|replace|drain|cordon)\b",
    re.IGNORECASE,
)


def format_check(answer: str) -> list[str]:
    """The required format's load-bearing marker: a 'What I checked' section."""
    violations = []
    if "what i checked" not in answer.lower():
        violations.append("missing 'What I checked' section")
    return violations


def read_only_check(answer: str) -> list[str]:
    """Flag any recommended mutating kubectl command (GitOps-PR-only rule)."""
    return [f"mutation advice: '{m.group(0)}'" for m in _MUTATION_RE.finditer(answer)]


def build_report(results: list[dict]) -> str:
    lines = ["# Parity report: homelab-knowledge (old) vs homelab-agent (new)", ""]
    for r in results:
        status = "PASS" if not r["new_violations"] else "FAIL"
        lines += [
            f"## [{status}] ({r['skill']}) {r['question']}",
            "",
            "### Old agent",
            "", r["old_answer"] or "(no reply)", "",
            "### New agent",
            "", r["new_answer"] or "(no reply)", "",
        ]
        if r["new_violations"]:
            lines += ["### Violations", ""]
            lines += [f"- {v}" for v in r["new_violations"]]
            lines += [""]
    return "\n".join(lines)
```

- [ ] **Step 5: Implement the runner script**

Create `homelab-agent/scripts/parity_check.py`:

```python
#!/usr/bin/env python
"""Run the golden questions against both agents over A2A; write parity-report.md.

Usage (both agents must be reachable, e.g. via kubectl port-forward):
    OLD_AGENT_URL=http://localhost:18080 NEW_AGENT_URL=http://localhost:8080 \
        python scripts/parity_check.py
"""

import asyncio
import os
import pathlib
import sys

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "src"))

from homelab_agent.parity import build_report, format_check, read_only_check  # noqa: E402
from homelab_agent.tools import a2a_send  # noqa: E402

GOLDEN = pathlib.Path(__file__).parent.parent / "tests" / "parity" / "golden_questions.yaml"


async def ask(url: str, question: str) -> str:
    try:
        return await a2a_send(url, question, timeout=300.0)
    except Exception as exc:  # a dead agent shouldn't kill the whole run
        return f"(error: {exc})"


async def main() -> int:
    old_url = os.environ["OLD_AGENT_URL"]
    new_url = os.environ["NEW_AGENT_URL"]
    questions = yaml.safe_load(GOLDEN.read_text())

    results = []
    for item in questions:
        question = item["question"]
        print(f"asking both agents: {question}")
        old_answer = await ask(old_url, question)
        new_answer = await ask(new_url, question)
        results.append({
            "skill": item["skill"],
            "question": question,
            "old_answer": old_answer,
            "new_answer": new_answer,
            "new_violations": format_check(new_answer) + read_only_check(new_answer),
        })

    report = build_report(results)
    out = pathlib.Path("parity-report.md")
    out.write_text(report)
    failures = sum(1 for r in results if r["new_violations"])
    print(f"wrote {out} — {len(results)} questions, {failures} with violations")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
```

- [ ] **Step 6: Run the full suite**

Run: `pytest tests/ -v`
Expected: all passed

- [ ] **Step 7: Commit**

```bash
cd /Users/arisela/git/claude-agents
git add homelab-agent/
git commit -m "feat(homelab-agent): golden-question parity harness with format and read-only checks"
```

---

### Task 10: Dockerfile, deploy script, docs finalization

**Files:**
- Create: `homelab-agent/Dockerfile`, `homelab-agent/.dockerignore`, `homelab-agent/deploy-to-ecr.sh`
- Modify: `homelab-agent/README.md` (Docker section), `homelab-agent/LEARNING.md` (closing section)

**Interfaces:**
- Consumes: `homelab_agent.server:app` (Task 8).
- Produces: image `852893458518.dkr.ecr.us-east-2.amazonaws.com/homelab-agent:<version>` — the value the follow-up kagent BYO CR will reference in `spec.byo.deployment.image`.

- [ ] **Step 1: Create Dockerfile and .dockerignore**

Create `homelab-agent/.dockerignore`:

```
.venv
__pycache__
*.egg-info
.pytest_cache
tests
scripts
parity-report*.md
.env
```

Create `homelab-agent/Dockerfile` (pattern: oncall-crewai's Dockerfile.k8s-agent):

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# curl for the container healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir .

ENV PYTHONUNBUFFERED=1

# kagent BYO contract: the container serves the A2A protocol on :8080
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

CMD ["uvicorn", "homelab_agent.server:app", "--host", "0.0.0.0", "--port", "8080"]
```

- [ ] **Step 2: Verify the image builds and serves**

```bash
cd homelab-agent
docker build -t homelab-agent:dev .
docker run -d --rm -p 18081:8080 -e ANTHROPIC_API_KEY=dummy --name ha-test homelab-agent:dev
sleep 3
curl -sf http://localhost:18081/health
curl -sf http://localhost:18081/.well-known/agent.json | head -c 200
docker stop ha-test
```

Expected: health returns `{"status":"healthy","agent":"homelab-agent"}`; agent card JSON starts printing. (If docker is unavailable in the environment, report this as a concern instead of skipping silently.)

- [ ] **Step 3: Create deploy-to-ecr.sh**

Create `homelab-agent/deploy-to-ecr.sh` (single-service adaptation of oncall-crewai's script; `chmod +x` it):

```bash
#!/bin/bash
# Build the homelab-agent image (AMD64, from Apple Silicon) and push to ECR.
#
# Usage:
#   ./deploy-to-ecr.sh            # tag v0.1.0
#   ./deploy-to-ecr.sh v0.2.0     # explicit tag
set -e

ECR_REGISTRY="852893458518.dkr.ecr.us-east-2.amazonaws.com"
REPO="homelab-agent"
VERSION="${1:-v0.1.0}"
REGION="us-east-2"

echo "==> Logging into ECR ($REGION)"
aws ecr get-login-password --region "$REGION" | \
  docker login --username AWS --password-stdin "$ECR_REGISTRY"

echo "==> Ensuring ECR repository exists: $REPO"
aws ecr describe-repositories --repository-names "$REPO" --region "$REGION" >/dev/null 2>&1 || \
  aws ecr create-repository --repository-name "$REPO" --region "$REGION" \
    --image-scanning-configuration scanOnPush=true >/dev/null

echo "==> Building and pushing $ECR_REGISTRY/$REPO:$VERSION (linux/amd64)"
docker buildx build --platform linux/amd64 \
  -t "$ECR_REGISTRY/$REPO:$VERSION" \
  -t "$ECR_REGISTRY/$REPO:latest" \
  --push .

echo "==> Done: $ECR_REGISTRY/$REPO:$VERSION"
echo "    Reference this tag in arigsela/kubernetes base-apps/kagent/agents/homelab-agent.yaml (spec.byo.deployment.image)"
```

Run: `bash -n deploy-to-ecr.sh` — Expected: no output (syntax OK). Do NOT run the actual push in this task.

- [ ] **Step 4: Finalize README and LEARNING.md**

Append to `homelab-agent/README.md`:

```markdown
## Container

    docker build -t homelab-agent:dev .
    docker run --rm -p 8080:8080 -e ANTHROPIC_API_KEY=... homelab-agent:dev

## Deploy image to ECR

    ./deploy-to-ecr.sh v0.1.0

Cluster-side deployment (kagent BYO `Agent` CR, ESO secrets, Vault role) is
the follow-up plan in `arigsela/kubernetes` — this repo only produces the
image and documents the env contract above.
```

Append to `homelab-agent/LEARNING.md`:

```markdown
---

## Closing: the whole picture

One request's life: A2A `message/send` hits `server.py` (:8080) →
`executor.py` extracts the question and calls the compiled graph with
`thread_id = context_id` → `orient` classifies (keywords, then cheap LLM) →
`retrieve` runs a prebuilt ReAct agent over MCP doc tools → the conditional
edge sends live-state questions through `delegate_k8s` (A2A call to
k8s-reader) and `drift_check` (docs vs live diff) → `synthesize` composes
the formatted answer → the checkpointer persists the thread → the executor
streams the answer back as A2A events.

Deliberately deferred (v2 candidates): running `retrieve` and `delegate_k8s`
in parallel — that needs a list-form join edge
(`add_edge(["retrieve", "delegate_k8s"], "drift_check")`) plus branch-aware
join handling so docs-only routes don't wait on a node that never runs; and
HITL interrupts, which the checkpointer already makes possible
(`interrupt_before=["delegate_k8s"]` at compile time would pause there).
```

- [ ] **Step 5: Run the full suite one last time**

Run: `pytest tests/ -v && black --check src/ && ruff check src/`
Expected: all tests pass; formatters clean (run `black src/` to fix if needed).

- [ ] **Step 6: Commit**

```bash
cd /Users/arisela/git/claude-agents
git add homelab-agent/
git commit -m "feat(homelab-agent): Dockerfile, ECR deploy script, and docs finalization"
```

---

## Verification (whole plan)

From `/Users/arisela/git/claude-agents/homelab-agent/` with `.venv` active:

1. `pytest tests/ -v` — full suite green.
2. `docker build -t homelab-agent:dev . && docker run -d --rm -p 18081:8080 -e ANTHROPIC_API_KEY=dummy --name ha-verify homelab-agent:dev && sleep 3 && curl -sf http://localhost:18081/health && curl -sf http://localhost:18081/.well-known/agent.json >/dev/null && docker stop ha-verify` — container serves the A2A contract.
3. `LEARNING.md` has all 7 concept sections + closing; every section names real files.
4. README env docs are complete: every `os.getenv` key used anywhere in `src/` appears in the README (table or prose). Check: `grep -rhoE 'os\.getenv\("[A-Z_]+"' src/ | sort -u`.
5. Grep gate: `grep -rn "kagent.svc\|kagent:3000\|backstage.svc" src/ | grep -v config.py` returns nothing (endpoints only in config defaults).
