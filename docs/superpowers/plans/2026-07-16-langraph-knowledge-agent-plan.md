# Design: Migrate `homelab-knowledge` to a LangGraph BYO agent (`homelab-agent`)

**Date:** 2026-07-16
**Status:** design — pending user review
**Topic:** Re-implement the `homelab-knowledge` kagent Declarative agent as a Bring-Your-Own (BYO) LangGraph agent, deployed as a kagent `Agent` CR, coexisting with the current agent until cutover.

## Goal

Replace the Declarative `homelab-knowledge` agent with a containerized **LangGraph** agent (`homelab-agent`) that runs as a **kagent BYO `Agent` CR** — keeping it inside kagent's control plane (A2A exposure, `/mcp`, Backstage/IDP, GitOps) while gaining an explicit, auditable graph with deterministic control flow and clear HITL insertion points. Roll out alongside the existing agent; cut over once parity is proven.

## Decisions (settled during brainstorming)

| Decision | Choice | Rationale |
|---|---|---|
| Framework | **LangGraph** | Deliberate user choice (explicit graph/control-flow model), despite the in-repo template being CrewAI. |
| Integration | **kagent BYO `Agent` CR** (`spec.type: BYO`) | Stay in kagent's control plane: A2A, `/mcp`, Backstage/IDP, controller-backed checkpointing, k8s-reader delegation. |
| Graph shape | **Explicit multi-node `StateGraph`** | The reason to pick LangGraph; auditable nodes, deterministic routing, HITL points. |
| Rollout | **Coexist → cut over** | New CR runs beside the Declarative one; retire the old only after parity. Read-only + IDP-managed → near-zero blast radius. |
| Source location | **`arigsela/claude-agents` repo** (new `homelab-agent/` dir) | Mirrors `oncall-crewai`; built to ECR. The `docs/reference/claude-agents/` here is only a reference clone. |
| Agent name | **`homelab-agent`** | User-chosen name for the coexistence period. |
| Parity harness | **In scope** | Golden-question parity test gates the cutover. |
| Learning goal | **In scope** — pedagogical docs | User is new to LangGraph; the implementation must be documented so each concept/term is explained and mapped to how `homelab-agent` uses it. This is a deliverable, not an afterthought. |

## Learning goal & pedagogical documentation

The user is new to LangGraph and wants to **understand what is being built as it is built**, not just receive working code. Treat teaching as a first-class deliverable:

- **`homelab-agent/LEARNING.md`** — a concept glossary written for a LangGraph newcomer. For each term below: a plain-language definition, why it exists, and **exactly where/how `homelab-agent` uses it** (with a pointer to the file/line). Terms to cover: `State` (the typed dict threaded through the graph) and **reducers** (how state updates merge), `StateGraph`, **nodes** (functions that read/return state), **edges** and **conditional edges** (routing, e.g. the post-`retrieve` `delegate_k8s?` decision), `ToolNode` / `tools_condition`, **checkpointer** (`KAgentCheckpointer` — what "thread state persistence" means), `create_react_agent` vs. a hand-built graph (and why we choose which), `MultiServerMCPClient` / `langchain-mcp-adapters` (how MCP tools become LangGraph tools), `ChatAnthropic` binding, and the **A2A** serving contract (:8080).
- **Annotated code** — `graph.py`, `state.py`, and `tools.py` carry teaching comments explaining the LangGraph-specific constructs (not restating Python), so reading the code reinforces `LEARNING.md`.
- **Plan structure follows the learning arc** — the implementation plan should sequence tasks so each introduces one concept at a time (state → a single node → edges → conditional routing → tools → checkpointer → A2A serving), with a short "what you just learned" note per phase, rather than landing the whole graph at once.

This does not change the architecture; it changes how we *build and document* it.

## Phase 0 findings (verified — gate the plan)

1. **BYO is supported on the current kagent 0.9.11 — no chart bump required.** Verified against `go/api/config/crd/bases/kagent.dev_agents.yaml` at tag `v0.9.11`: `spec.type` enum = `{Declarative, BYO}`; `spec.byo.deployment` is a full Deployment-like spec (`image`, `env`, `ports`, `resources`, `replicas`, `imagePullSecrets`, `serviceAccountName`, `cmd`, `args`, `volumes`, `volumeMounts`, `annotations`, `affinity`). kagent "deploys the image and expects it to serve the agent over the A2A protocol on **port 8080**." This is the opposite of the Agent Substrate situation (which needs the 0.10 beta line).
2. **State:** `from kagent.langgraph import KAgentCheckpointer`, `from kagent.core import KAgentConfig`; instantiate against `KAgentConfig().url` / `.app_name` and pass to `create_react_agent(..., checkpointer=...)` (or `graph.compile(checkpointer=...)`). kagent injects the config via env into the BYO pod.
3. **MCP tools are NOT auto-injected into BYO containers.** The container wires its own tools. To use the existing `agent-docs` and `backstage-catalog` MCP servers, `homelab-agent` connects via `langchain-mcp-adapters` `MultiServerMCPClient` (`await client.get_tools()` → `model.bind_tools(...)` / `ToolNode`), pointed at their in-cluster endpoints, with tokens from Vault/ESO.
4. **Model is owned by the container:** `ChatAnthropic(model="claude-sonnet-4-6…")`, API key from env (Vault/ESO). kagent `providers`/`ModelConfig` do not apply to BYO.
5. **k8s-reader delegation** becomes an **A2A client call** from a graph node (target `k8s-reader` in the `kagent` namespace over A2A), not a `type: Agent` CRD tool.

## Scope

**This plan covers only work in `arigsela/claude-agents`** — the `homelab-agent/` container source, tests, parity harness code, `LEARNING.md`, Dockerfile, and `deploy-to-ecr.sh`. The cluster-side deliverables (kagent BYO `Agent` CR, ESO `SecretStore`/`ExternalSecret`, Vault role, and any kagent docs corrections) live in `arigsela/kubernetes` and are an explicit **follow-up plan**, not part of this one. This repo's obligation to that follow-up is a clean interface: a documented env-var contract and fully config-driven endpoints.

## Architecture

Two repos, mirroring the `oncall-crewai` split:

- **`arigsela/claude-agents` → `homelab-agent/`** *(this plan)* — the LangGraph container source, built to ECR (`852893458518.dkr.ecr.us-east-2.amazonaws.com`) via a `deploy-to-ecr.sh` copied from `oncall-crewai`.
- **`arigsela/kubernetes` → `base-apps/kagent/agents/homelab-agent.yaml`** *(follow-up plan, out of scope here)* — the kagent BYO `Agent` CR (`spec.type: BYO`, `spec.byo.deployment.image` = the ECR tag), plus a credential-scoped `SecretStore`/`ExternalSecret` for the agent's env secrets. Argo CD syncs it like every other agent.

### Container layout (in `arigsela/claude-agents/homelab-agent/`)

```
homelab-agent/
  src/
    graph.py        # LangGraph StateGraph (nodes + edges)
    state.py        # typed State schema
    tools.py        # MultiServerMCPClient -> agent-docs + backstage tools; k8s-reader A2A client
    model.py        # ChatAnthropic (Sonnet), key from env
    checkpointer.py # KAgentCheckpointer wiring
    server.py       # A2A server on :8080 (kagent-adk helper or oncall-crewai-style A2A mount)
    prompts.py      # system instruction (ported from current systemMessage)
    config.py       # env: endpoints, tokens, model, log level
  tests/            # node unit tests, A2A protocol tests, golden-question parity
  LEARNING.md     # LangGraph concept glossary mapped to this agent's code (pedagogical)
  Dockerfile
  deploy-to-ecr.sh
  pyproject.toml
```

## The StateGraph

**State** (`state.py`): `question`, `route` (docs | live | ownership), `plan`, `doc_findings`, `live_findings`, `drift[]`, `answer`, `checked[]` (which sources/delegates were used).

**Reducers (explicit, to avoid concurrent-update ambiguity):** the accumulating list fields `checked` and `drift` are declared `Annotated[list, operator.add]` so any node can append without clobbering. All other fields (`route`, `plan`, `doc_findings`, `live_findings`, `answer`) use default last-writer-wins semantics — safe because exactly one node writes each field and v1 execution is strictly sequential (below).

**Nodes / edges (v1 is a sequential pipeline with conditional skips — no parallel fan-out/fan-in):**

- **orient** — classify the query into docs-only / live-state / ownership-dependency. Deterministic keyword pass first (cheap, à la oncall-crewai's router), cheap-LLM fallback for ambiguity. Sets `route`.
- **retrieve** — always runs after `orient`. Atlas→index→app traversal over the **agent-docs MCP** (`get_file_contents`, `search_code`); ownership/dependency questions call **backstage-catalog** (`get-catalog-entity`). Fills `doc_findings`, appends to `checked`.
- **delegate_k8s** — A2A call to **k8s-reader**; fills `live_findings`, appends to `checked`. Reached only via the conditional edge below.
- **drift_check** — diffs `doc_findings` against `live_findings`; appends to `drift` (preserving the current agent's drift-detection behavior). Only reachable on the live path, so both inputs are always present when it runs.
- **synthesize** — enforce the response format: brief answer → "What I checked" (delegates/sources used) → specifics (file paths in `arigsela/kubernetes`, resource names, `kubectl` commands to verify).

**Routing:** `orient → retrieve` (unconditional). A **conditional edge after `retrieve`** inspects `route`: if live state is needed → `delegate_k8s → drift_check → synthesize`; otherwise → `synthesize` directly. `synthesize → END`. Every node therefore executes at most once per run, there is no fan-in join to stall on docs-only routes, and no two nodes ever write the same superstep.

**Deliberately deferred:** running `retrieve` and `delegate_k8s` in parallel would require a list-form join edge (`add_edge(["retrieve", "delegate_k8s"], "drift_check")`) plus branch-aware handling so docs-only routes don't wait forever on a node that never runs. That is out of scope for v1 (the latency win is small; correctness risk is not) — but it's documented in `LEARNING.md` as the teaching example for why reducers and join semantics exist.

## Secrets & config (env contract — this repo's side only)

Secret *provisioning* (ESO `ServiceAccount` + `SecretStore` + Vault role + per-consumer key, per `templates/agent-identity/README.md`) happens in the `arigsela/kubernetes` follow-up. **This plan's deliverable is the contract:** `config.py` reads everything from env, and a definitive env-var table (in `homelab-agent/README.md`) documents exactly what the container expects, so the CR/ESO work later is transcription:

- `ANTHROPIC_API_KEY` — Sonnet model (own Vault key, not the shared `kagent-anthropic`).
- GitHub MCP token — to reach the `agent-docs` MCP (read-only, `repos` toolset).
- Backstage MCP token — to reach `backstage-catalog`.
- Endpoint envs — agent-docs MCP URL, backstage MCP URL, `k8s-reader` A2A URL, `KAgentConfig` (injected by kagent).

Endpoint URLs, MCP transport, and auth-header scheme are all config-driven — no in-cluster addresses are hardcoded, so reachability assumptions can be corrected without code changes.

## Preserved guarantees (parity with today's agent)

- **Read-only, capability-transitive:** the graph only ever calls read tools + `k8s-reader` (itself read-only). Carry the `capability.homelab/class: read` label. No mutation advice; GitOps-PR-only recommendations; never quote secret values (only Vault path/property).
- **Model:** Sonnet (context headroom for ingesting delegate replies).
- **Backstage/IDP:** carry over `terasky.backstage.io/*`, `backstage.io/*`, `arigsela.com/idp-managed: "true"` annotations on the new CR; keep the three `a2aConfig` skills (repo-knowledge, cluster-troubleshooting, deployment-guidance).
- **Compaction bug is moot:** the current agent disables kagent's experimental sliding-window compaction (it sends malformed requests to Anthropic). A BYO container owns its own context management, so we can do proper in-graph summarization instead — a net improvement.

## Rollout: coexist → cut over *(executed in the follow-up plan)*

1. Deploy `homelab-agent` (BYO) alongside `homelab-knowledge` (Declarative). Both reconciled by Argo CD.
2. Validate with the **golden-question parity harness**: the example prompts in the current agent's `a2aConfig.skills` become the test set; run both agents over A2A/`/mcp` and compare answers (correctness, format, drift-detection, read-only behavior).
3. Once parity holds, retire the Declarative `homelab-knowledge` CR and repoint anything that delegated to it (nothing currently delegates *to* it; verify). Fully reversible at each step.

This plan's contribution to the rollout: the harness itself (golden questions codified, runnable against configurable A2A endpoints) and the container image. Deployment, live parity runs, and cutover are gated in `arigsela/kubernetes`.

## Testing & observability

- **Unit:** per-node tests with mocked MCP tools and a mocked k8s-reader A2A client (mirrors `oncall-crewai/tests/test_*_tools.py`).
- **A2A protocol:** server-mount / agent-card / message-send tests (mirrors `test_*_agent_a2a.py`).
- **Parity:** golden-question suite (gates cutover).
- **Observability:** OTel spans to Coroot via the kagent adapter's span attributes, matching current wiring.

## Risks & open items (for the plan to resolve)

1. **A2A serving helper** — confirm whether to use the `kagent-adk` base image's A2A server scaffolding or an `oncall-crewai`-style custom A2A mount. Minor; resolved in an early implementation task.
2. **MCP reachability** — the `agent-docs` MCP is currently a container `MCPServer` surfaced via a `RemoteMCPServer` registration; confirm the BYO container can reach the underlying MCP endpoint directly with `MultiServerMCPClient` (transport + auth header). Cannot be fully verified from this repo — mitigate by keeping transport/auth config-driven and smoke-testing early via port-forward.
3. **`kagent-langgraph` / `kagent.core` package versions** — pin versions compatible with the 0.9.11 controller; confirm `KAgentCheckpointer` API shape against the pinned release (sample is from `main`). Restart-persistence behavior is only verifiable once deployed (follow-up plan).

## Success criteria (this repo)

- `homelab-agent/` builds a container that serves A2A on :8080, with the full StateGraph (orient → retrieve → conditional delegate_k8s → drift_check → synthesize) wired per the routing/reducer semantics above.
- Unit tests (per-node, mocked MCP/A2A) and A2A protocol tests pass; the golden-question parity harness exists and runs against configurable endpoints.
- The env-var contract is documented; endpoints/transport/auth are fully config-driven; read-only behavior, drift detection, and the response format are preserved in prompts and graph logic.
- Image pushes to ECR via `deploy-to-ecr.sh`.
- **Learning deliverable met:** `homelab-agent/LEARNING.md` explains each LangGraph concept used and maps it to where/why the code uses it; `graph.py`/`state.py`/`tools.py` carry teaching comments; the implementation plan introduces concepts one phase at a time. The user can read the finished agent and explain what `State`, a node, a conditional edge, `ToolNode`, and the checkpointer each do here.

**Deferred to the `arigsela/kubernetes` follow-up:** CR deployment on 0.9.11, live parity runs and Declarative-agent retirement, restart persistence (KAgentCheckpointer against the controller), traces to Coroot.
