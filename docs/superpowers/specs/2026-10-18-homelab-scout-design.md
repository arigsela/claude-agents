# homelab-scout: a LangGraph BYO agent on kagent 1.0, for cost levers and a drift check — Design

> Superseded by the docs-checker design; kept for its §3 runtime-contract and §4 gate findings.

**Date:** 2026-10-18
**Status:** Draft for Ari's review. The agent's purpose (§2) and the decisions in §11 are Ari's; everything else is proposed. A walking skeleton is in `homelab-scout/` and its tests pass.
**Builds on:** `docs/superpowers/plans/2026-07-16-langraph-knowledge-agent-plan.md` and `homelab-agent/` (the kagent 0.9 LangGraph BYO agent, retired 2026-10-11, SPEC T99); `docs/atl-devcon-2026-presentation-brief.md` screens 10–13 and the appendix.
**Repos:** `arigsela/claude-agents` (code, this doc); `arigsela/kubernetes` (every deploy step, as PRs; nothing there is changed by this work).

## 1. Goal

Build a new agent with current LangGraph and run it in kagent 1.0 as a BYO (bring-your-own-container) agent, so Ari can practise two things from ATL DevCon 2026 on something real:

1. **The seven cost levers, with a per-run cost ledger first** (screens 11–13). Every lever ships only when an eval set says quality held.
2. **Later, an intent-vs-action drift check** (screen 10): a deterministic angle between the embedded ask and each tool call, after authorization, with allow, ask or refuse. No LLM in that path.

The risky part is not LangGraph. It is whether a LangGraph app can satisfy kagent 1.0's BYO runtime contract at all, since the package built for that (`kagent-langgraph`) cannot. §3 answers that with evidence, and the skeleton proves the answer locally.

## 2. Purpose: options and recommendation (decision for Ari)

All three are read-only, so none needs a write permission, and all reuse MCP servers that already exist.

| | A. **homelab-scout**: Q&A over the GitOps repo and Backstage catalog (recommended) | B. Read-only alert triage for the dispatcher | C. GitOps change explainer |
|---|---|---|---|
| What it does | "Which chart version does vault run?", "Who owns chores-tracker-backend and what does it depend on?" | A Grafana alert in, a verdict out (`limit-too-low`, `leak`, ...) | Summarise what a PR to `arigsela/kubernetes` changes |
| Tools | `agent-docs` (`get_file_contents`, `search_code`), `backstage-catalog` (`get-catalog-entity`) | Live cluster reads: pods, events, logs | `agent-docs` (GitHub read) |
| Graph for the levers | router → planner → docs/catalog specialists → responder: every lever has something to act on | Same shape, plus long tool loops (good for levers 4 and 7) | Mostly one long call; few repeat intents (weak for lever 3); natural fit for the Batch API |
| Baseline to beat | `homelab-knowledge` (Declarative, Go ADK) answers the same questions: same eval corpus, a real cost and quality comparison | `k8s-reader`/implementer verdicts | the `pr-explainer` skill |
| Blocker | none beyond §4 | needs a server-side read-only live-cluster MCP first: `kagent-tool-server` has 126 tools including `shell` and `k8s_delete_resource`, unauthenticated (§4.2) | overlaps an existing skill |

**Recommendation: A.** It has a ready baseline and eval corpus (`tests/eval-corpus/homelab-knowledge.yaml`, 8 entries, plus homelab-agent's 8 parity questions), needs only two MCP servers that are read-only on the server side, and exercises every lever. B is the natural second agent once a read-only live MCP server exists. The skeleton is built around A; the name `homelab-scout` assumes it.

## 3. The kagent 1.0 BYO contract: findings and verdict

Sources: kagent source at tag `v1.0.0-alpha11` (commit `30e8a2c2`, released 2026-10-09, the version in the cluster per SPEC R44/R45), compared with `v1.0.0-alpha14` (commit `673d181e`, 2026-10-16, the latest); the kagent 1.x docs (`kagent.dev/docs/kagent/1.x/agents/bring-your-own-agent/`, read 2026-10-18); PyPI wheels of `kagent-core` and `kagent-langgraph` 1.0.0a11 and 1.0.0a14; the live cluster's CRDs (`kubectl explain harnesses.api.kagent.dev`).

### 3.1 What the controller and Substrate require

| # | Requirement | Evidence |
|---|---|---|
| 1 | **A2A v1 over gRPC**, service `lf.a2a.v1.A2AService`, on `KAGENT_PORT` (the compiler sets 80). The gateway reaches the actor only this way; JSON-RPC alone is never reached. | `go/core/internal/translator/byo/compiler.go` (`agentTemplateCard`: `URL: "http://127.0.0.1:80"`, `TransportProtocolGRPC`); `go/core/internal/a2agateway/runtime.go` (`RuntimeDialer.Dial` builds only a gRPC client through the Atenet router, `ate-target-actor` header); `docs/architecture/configuration-and-compilation.md` ("The compiler sets `KAGENT_PORT=80` for private A2A traffic"); 1.x docs ("An image that serves A2A only over JSON-RPC is never reached"; a wrong port still reports READY and fails at first invoke with `Connect: tunnel failed`). |
| 2 | **`GET /readyz` → 200 on port 8081**, a separate listener, bound only after the A2A port (Substrate may snapshot the actor as soon as it succeeds). | `go/core/internal/substrate/actor_template.go` (`WakeupProbe{HttpGet: /readyz, Port: 8081}, TimeoutSeconds: 30`); `go/adk/pkg/a2a/server/server.go` ("Bind A2A before exposing readiness so that snapshot always contains its listener"). |
| 3 | **The private TaskStore at `KAGENT_API_URL`** (gRPC `kagent.api.v1alpha1.TaskStoreService`: Create, Get, Update with an expected version, List, Settle). An in-memory store is "insufficient". Calls carry the actor identity read from `/run/kagent/identity/{name,atespace,uid}` in the header `x-kagent-insecure-runtime-identity` (temporary until substrate#1660). One active send per session; the final waiting or terminal event is held back until native work ends, then settled. | `docs/architecture/configuration-and-compilation.md` ("Other images must implement the same TaskStore contract; an upstream A2A server with only an in-memory store is insufficient"); `docs/architecture/a2a-gateway.md` (durable ordering, settlement, runtime authority); `go/adk/pkg/taskstore/{store,executor}.go`; Python: `kagent/core/a2a/_task_store.py` in kagent-core 1.0.0a11. |
| 4 | **Harness**: `spec.byo: {}`; `workload.image` pinned by digest; `workload.command` required for byo; `env` literal `value`s only (no `valueFrom`). An actor carries at most 32 environment variables in total, most set by kagent. | `go/api/v1alpha3/harness_types.go` (CEL rules); `actor_template.go` (`len(actorEnv) > 32` → error; `valueFrom` → error); `kubectl explain` on the cluster matches. |
| 5 | **Config delivery**: `KAGENT_CONFIG_JSON` (the AgentTemplate compiled to the ADK `AgentConfig`: model, instruction, `http_tools` with URL, headers and tool filter) and `KAGENT_AGENT_CARD_JSON`. A durable directory at `/data` (`session_db_url: sqlite+aiosqlite:////data/sessions.db`). `modelConfig` is optional for byo. | `adkconfig/builder.go`; `go/api/adk/types.go`. alpha14 wraps the config as `{"runtime": {...}, "agent": {...}}`. |
| 6 | **No secrets in the container.** A ModelConfig on the AgentTemplate opens egress to `https://api.anthropic.com:443` and binds `x-api-key` injection at the egress gateway; the SDK sees the placeholder `kagent-credential-injected`. A Secret-backed RemoteMCPServer header is injected the same way (`__KAGENT_ENV[KAGENT_CREDENTIAL_…]__` in the config). Egress is allowed only to origins compiled from the template: the model, bound MCP servers, the controller on 8083, telemetry. HTTP(S) origins only, DNS names only. The gateway intercepts TLS; the runtime must trust `/run/kagent/egress/trust-bundle.pem` (`SSL_CERT_FILE` is set; httpx 0.28.1 honours it, verified in `httpx/_config.py`). | `docs/architecture/credential-injection.md`; `translator/credentials.go` (`CredentialPlaceholder`); `adkconfig/builder.go` (`agentConfigDestinations`); `actor_template.go` (trust bundle mount and CA variables). |
| 7 | **No long-term memory on byo** (Harness `spec.kagent.memory` is read only by the kagent runtime; no Ollama egress is compiled for byo). Substrate snapshots the whole actor (process memory included) between turns, so in-process state lives as long as the session. | `adkconfig/builder.go` (`applyMemory` only when `Harness.Spec.Kagent != nil`); `actor_template.go` (`SNAPSHOT_CONTENT_SCOPE_FULL`); 1.x docs ("Long-term memory isn't available on `byo`"). |
| 8 | **HITL** is a framework-independent A2A extension (`https://kagent.dev/extensions/hitl/v1`): `input-required` with a `tool_approval_request` in the status message metadata; the reply continues the same task. The status text is always present, activated or not. | `docs/architecture/human-in-the-loop.md`; kagent-core `a2a/_hitl.py`. The 1.x docs say a byo card "declares no extension" (§11, decision 9). |
| 9 | **Version lockstep.** alpha14 renames the TaskStore proto package (`kagent.api.v1alpha1` → `kagent.runtime.v1`) and reshapes the config; an image built for alpha11 breaks on an alpha14 controller. | Diff of `kagent-core` 1.0.0a11 vs 1.0.0a14 (`_task_store.py` imports); `byo/compiler.go` diff. |

### 3.2 What the libraries provide

- **`kagent-langgraph` cannot meet it.** Its `KAgentApp.build()` (1.0.0a11 and 1.0.0a14) returns a FastAPI app with JSON-RPC, `/health` and `/thread_dump`: no gRPC listener, no `/readyz`. It does use kagent-core's TaskStore. The 1.x docs say the same: "The `kagent-langgraph`, `kagent-crewai`, and `kagent-openai` adapters serve FastAPI JSON-RPC, not gRPC, so they don't satisfy the contract. Running these frameworks under `byo` requires your own gRPC server." Its `KAgentCheckpointer` was removed in the 1.0 line.
- **Everything else needed exists.** `a2a-sdk` 1.2.2 ships the gRPC handler (`a2a.server.request_handlers.grpc_handler.GrpcHandler`, `a2a.types.a2a_pb2_grpc.add_A2AServiceServicer_to_server`, proto package `lf.a2a.v1`, protocol 1.0). `kagent-core` 1.0.0a11 ships the TaskStore client (`KAgentTaskStore`), the settling request handler (`KAgentRequestHandler`, in the private module `kagent.core.a2a._task_store`), the gRPC call-context builder that keeps gateway metadata, and the HITL helpers. `kagent-adk`'s `KAgentApp` shows the listener shape (gRPC on `[::]:80`, a raw asyncio `/readyz` on 8081 bound on every family because an IPv6-only socket refused Substrate's IPv4 probe).
- **Install wrinkles, all solved in `homelab-scout/pyproject.toml`:** `kagent-proto` (the generated stubs kagent-core imports) is not on PyPI (404), so it installs from git at the tag's commit (`git+https://github.com/kagent-dev/kagent@30e8a2c2…#subdirectory=python/packages/kagent-proto`); kagent-core 1.0.0a11 imports `fastapi` without declaring it; kagent-proto needs protobuf < 7, so `grpcio-health-checking` stays at 1.74 (1.75+ needs protobuf ≥ 7.35), as kagent-adk pins it. `pip install kagent-langgraph==1.0.0a14` from PyPI alone silently resolves kagent-core 0.7.17.

### 3.3 Verdict

**The contract can be met.** A LangGraph app serves it with a2a-sdk's gRPC handler, kagent-core's TaskStore and request handler, and a ~40-line readiness listener: kagent-adk's server shape with a LangGraph executor inside. The skeleton does exactly that and proves each part locally over real sockets:

| Contract part | Test |
|---|---|
| gRPC `SendMessage` and `SendStreamingMessage` on `lf.a2a.v1.A2AService` return a completed task with the answer, tool-call data parts, the usage metadata and the ledger | `tests/test_server.py` |
| `/readyz` 200 on its own port, 404 elsewhere; gRPC health `SERVING` for `lf.a2a.v1.A2AService` | `tests/test_server.py` |
| Against a fake controller `TaskStoreService` (alpha11 proto): create at version 1, versioned updates (submitted → working → artifact → completed), `SettleTask` at the final version, every call scoped to the session and carrying `kagent/session-<uuid>/<uid>` from the identity files | `tests/test_taskstore_contract.py` |
| A drift "ask" pauses as `input-required` with a kagent `tool_approval_request`; an approval on the same task resumes it | `tests/test_hitl.py` |

**Not proven:** a real controller, Atenet routing, the golden snapshot, gVisor suspend/resume of this image, and pulling it onto a Substrate worker. That is Phase 0's in-cluster spike, and it needs the admission change in §4.1 first.

**Correction for SPEC R45.** R45 cites kagent#3052 as the reason kagent-langgraph cannot do BYO. #3052 (opened 2026-10-04, still open, no comments) is about the **0.10.x** Python wrappers not sending the pod's token and the user on controller callbacks; it says "On `main` (the 1.0 line) these wrappers no longer call the controller's session, checkpoint or memory APIs, so this is a request for the 0.10.x line." The 1.0 blocker is the missing gRPC listener and `/readyz`, per the code and the 1.x docs quoted in §3.2. Worth fixing the citation in R45 (and in `docs/plans/kagent-1-0-feasibility-spikes-implementation-plan.md` L21, which states it correctly without the issue number).

## 4. What a BYO agent must pass in this cluster

From `arigsela/kubernetes` at `cc78298` (read only).

### 4.1 Admission denies every byo Harness today

`base-apps/admission-policies/agent-capability.yaml`, policy `agent-capability-runtime` (`failurePolicy: Fail`, binding `Deny`), requires `has(object.spec.kagent)` and an image under `ghcr.io/kagent-dev/kagent/golang-adk` or `…/kagent-adk` (the taxonomy's `runtime-images`). Its message gives the reason: "Per-binding tool selection and requireApproval are enforced inside kagent's ADK runtimes; a byo, claude or codex runtime need not honour them." CI agrees: `scripts/validate-agent-capability.py` (`check_runtime`), `tests/agent-capability/test_validate_agent_capability.py::test_byo_harness_is_error`, and the admission fixture `bad-byo-runtime.yaml`. This is a deliberate control (rule 9 in `docs/adp-engineering-deep-dive.md`), so admitting homelab-scout is a security decision (§11, decision 1), not a bug fix.

A proposal that keeps the rule's intent: admit `spec.byo` only when (a) the image repository is in a new taxonomy list `byo-images` (only homelab-scout's repository), (b) every Agent whose `harnessRef` names that Harness uses an AgentTemplate of class `read`, and (c) that template binds only servers listed in a new taxonomy list `read-only-servers` (servers that are read-only on the server side: `agent-docs` runs `--read-only`, `backstage-catalog` exposes 3 read tools). (b) and (c) make "the runtime need not honour tool selection" harmless: whatever the image calls on those origins is a read. Same-change rules (V84) apply: the policy, generator (`scripts/gen-agent-capability-policy.py`), validator, tests and fixtures ship together, and the validator must still fail closed on an unknown runtime.

### 4.2 Other gates

| Gate | Consequence for homelab-scout |
|---|---|
| Template class label `capability.homelab/class: read`; every bound tool in the taxonomy's `read` class; bindings list their tools (`agent-identity.yaml`) | Bind `agent-docs` with `get_file_contents`, `search_code` and `backstage-catalog` with `get-catalog-entity`: all in `read`. |
| Egress opens per origin, not per tool; byo enforces binding tool lists itself | The code allowlist (`tools.READ_ONLY_TOOLS`) is the enforcement. **Never bind `kagent-tool-server`** (`http://kagent-tools.kagent:8084/mcp`: 126 tools including `shell`, `helm_uninstall`, `k8s_delete_resource`, `k8s_execute_command`, no auth) and never `kagent-api` (18 tools incl. `invoke_session`). |
| Agent: `templateRef` + `harnessRef` only (`agent-capability-refs`); ModelConfig and RemoteMCPServer in git (`validate-agent-identity.py`) | Reuse `anthropic-claude-sonnet-5-5` (opens egress and injects the key for every model on that host) and the existing RemoteMCPServers. |
| Eval gate scores every Agent on every definition change (V93, V99) | The executor emits tool calls as data parts tagged `kagent.dev/a2a/part-type: function_call` (what `forbid_tools`/`expect_tools` read) and usage under `kagent.dev/a2a/usage` (what the audit export reads, `totalTokenCount`). A read-class agent needs no own corpus by rule; homelab-scout should have one anyway (§7). |
| Image pull | No private-registry pull configuration for Substrate workers was found in `base-apps/substrate.yaml`; the retired homelab-agent pulled from ECR as a 0.10 pod with an injected pull secret, a path that no longer exists (§11, decision 3). |
| CPU and sandbox | Workers are E5-2670 (no AVX2; only the `claude` runtime is affected per R45). Base image per kagent's samples: bookworm and a uv-managed Python, because gVisor checkpoint/restore segfaulted trixie's glibc and the system CPython. NumPy under gVisor is unverified (R45), which matters for the drift embedder (§8.4). |
| Identity (V91, V92) | Callers reach the agent through the gateway with mesh-verified identity; the runtime holds no credential of its own. The TaskStore's unsigned runtime-identity header is the same prerelease path every kagent 1.0 runtime uses. |

## 5. Architecture

```
A2A gRPC (lf.a2a.v1) :80 ── GrpcHandler ── KAgentRequestHandler ── KAgentTaskStore ──gRPC──> controller :8083
      /readyz :8081                               │
                                                  ▼
                                   ScoutExecutor (one task = one run = one CostLedger)
                                                  │  graph.ainvoke(thread_id = task id, recursion_limit = 12,
                                                  │                context = RunDeps(models, ToolBelt, ledger, ...))
                                                  ▼
 START → intake ──repeat in session──> END
           │
         router (Haiku 5.5, effort low) ──out_of_scope──> refuse → END
           │  └─docs|catalog, confidence ≥ 0.8 ──> one specialist          (lever 3: skip the planner)
           ▼
         planner (Sonnet 5.5, medium) ──Send per task (1–3)──> specialist (Sonnet 5.5, medium)
                                                                   │  bounded tool loop: ToolBelt.call
                                                                   │  = allowlist → drift gate → MCP tool → shrink
                                                                   ▼
                                       responder (Haiku 5.5, low; sees only the typed Handoff)
                                                                   ▼
                                       verify (deterministic: cited sources ⊆ tool facts) → END
```

| Module | Holds |
|---|---|
| `config.py` | Parses `KAGENT_CONFIG_JSON` (alpha11 and alpha14 shapes), expands `__KAGENT_ENV[…]__`, per-node model/effort/max_tokens, limits. |
| `server.py` | The contract: gRPC A2A + health, `/readyz`, kagent TaskStore in-cluster or in-memory locally, the agent card (with the HITL extension), lazy MCP tool discovery. |
| `executor.py` | A2A ↔ graph: submitted/working/completed or failed; answer text part; `function_call`/`function_response` data parts; ledger data part; `kagent.dev/a2a/usage`; interrupt → `input-required` + HITL request; HITL reply → `Command(resume=…)`. |
| `graph.py` | Nodes, edges, `RunDeps` (passed as LangGraph runtime context, never checkpointed). |
| `state.py` | Typed handoffs: `RouteDecision`, `Plan`/`SpecialistTask`, `SpecialistReply`/`Findings` (≤ 5 `Fact`s with a source), `Handoff`, `ToolEvent`. |
| `tools.py` | `ToolBelt`: allowlist ∩ template binding ∩ specialist scope; the gate; result projection and cap. |
| `gate.py` | Drift seam: `ToolCallContext`, `render_intent`, `render_action`, `angle_degrees`, `Thresholds`, `RecordingGate` (now), `AngleGate` (Phase 5). |
| `llm.py` | `call_model`: the only retry owner; every attempt ledgered. |
| `ledger.py` | Usage extraction, rate cards, `CostLedger`, `RunSummary`, `cost_per_verified_outcome`. |
| `prompts.py`, `models.py` | Frozen per-node prompts with a cache breakpoint; lazy `ChatAnthropic` per node with `max_retries=0`. |

Design choices worth calling out:

- **One checkpointer thread per A2A task, not per conversation.** homelab-agent used the conversation id and needed reset sentinels so last turn's state did not leak (its LEARNING.md §1). Here each question is answered from scratch, repeats hit the session answer cache, and a HITL resume continues the same task, so it finds its thread. `InMemorySaver` is enough because Substrate snapshots process memory; `/data` (durable) can hold a SQLite checkpointer later if snapshots prove lossy.
- **A hand-written specialist loop, not `create_agent`.** LangChain 1.4's `create_agent` with `ModelCallLimitMiddleware`, `ToolCallLimitMiddleware`, `ContextEditingMiddleware` and `ProviderToolSearchMiddleware` would work (verified by a probe with a fake model), but the explicit loop keeps the retry owner, the ledger and the gate in one visible place. Middleware stays an option per lever.
- **JSON replies validated with Pydantic, never retried.** A router or planner reply that does not parse falls back deterministically (route `complex`; a single docs task). Native structured outputs (`with_structured_output(method="json_schema")`, which uses `output_config.format`, not forced tool choice, which the 5.5 models reject) is a Phase 3 candidate once a test pins that per-node `effort` survives alongside `format` in `output_config`.
- **Tools discovered on first use, not at startup**, because the golden snapshot is taken right after `/readyz` and sessions start from it.

## 6. The levers: mechanism and measurement

Feature facts are from the installed packages (langgraph 1.2.16, langchain 1.4.6, langchain-anthropic 1.7.6, langchain-mcp-adapters 0.3.2, anthropic 1.15.0) and the Anthropic docs (pricing page read 2026-10-18; the `claude-api` skill). "Built" means in the skeleton and tested with fakes; nothing is "shipped" until its eval run (§7).

| Lever | Mechanism in homelab-scout | Library / API feature | Measured by | Status |
|---|---|---|---|---|
| **0. Ledger** (step zero) | Every model call → `LedgerEntry`; run → `RunSummary`; cost ÷ verified outcomes | `AIMessage.usage_metadata` / `response_metadata["usage"]` | itself (§6.1) | Built |
| **1. Cache the stable prefix** | Frozen per-node system prompt (no time, ids or user data); `cache_control` on its last block; tools sorted by name; question and handoff after the breakpoint; 5-minute TTL | Anthropic prompt caching: ≤ 4 breakpoints; 512-token minimum on the 5.5 models (shorter prefixes silently do not cache; today's router prompt is under it); writes 1.25× (5 m) / 2× (1 h); reads 0.05× on Sonnet/Opus 5.5, 0.1× on Haiku 5.5. Caches are per workspace and model, so identical prefixes hit across sessions and actors. `langchain_anthropic.middleware.AnthropicPromptCachingMiddleware` exists if `create_agent` is adopted. | cache hit rate = read ÷ (uncached + write + read), per node; write ÷ read ratio. Baseline: kagent's Declarative agents measured 48 % overall, 86–98 % in tool loops (T99) | Built (`tests/test_prompts.py` pins the breakpoint, byte-identical system blocks and tool order in the request ChatAnthropic would send) |
| **2. Typed handoffs, not transcripts** | Router → `RouteDecision`; planner → `Plan`; each specialist → ≤ 5 `Fact`s with a source; responder sees only `Handoff`. The transcript (tool calls, shrunk results) stays in `events` for audit and the A2A artifact. | Pydantic v2; LangGraph `Send` for fan-out, `operator.add` reducers | uncached input tokens per responder and specialist call, A/B against a transcript-passing variant | Built (`test_responder_sees_the_typed_handoff_not_the_transcript`) |
| **3. Short-circuit repeat intents** | Gate 1: the Haiku router; a confident `docs`/`catalog` route skips the planner, `out_of_scope` gets a template. Gate 2: an answer cache keyed by the normalised question, scoped to the session, verified answers only. Async work (eval replays) goes to the Batch API. | LangGraph conditional edges + `Send`. Note `CachePolicy` (node caching, `InMemoryCache`) keys only on the node's input, not thread or tenant, so scope must be part of the input. Batch API: 50 % off input and output. | share of runs per path (repeat, refused, direct, planned); cost per run by path; eval quality per threshold (calibrate the 0.8) | Built (session scope); cross-session cache is §11 decision 6 |
| **4. Load tools on demand** | Each specialist binds only its own tools: allowlist ∩ AgentTemplate binding ∩ specialist scope. When a server with many tools is bound (the live specialist), add Anthropic tool search: tools `defer_loading: true` + `tool_search_tool_bm25_20251119`. Deferred is not authorized: `ToolBelt.call` still checks every call. | `langchain.agents.middleware.ProviderToolSearchMiddleware` sets `defer_loading` and appends the BM25 tool; ChatAnthropic adds the beta header itself | schema tokens per call (`count_tokens` on the tools block); tool-selection accuracy (`expect_tools` in the eval) | Built (static scoping); tool search planned for B |
| **5. Exactly one layer owns retries, plus a recursion limit** | `llm.call_model` retries only 408/409/429/5xx/529 and connection errors, ≤ 3 attempts, every attempt ledgered with `attempt`; the SDK gets `max_retries=0`; no node has a `RetryPolicy`; `recursion_limit=12`; ≤ 6 tool calls per specialist; parse failures fall back instead of retrying | Hidden retry layers found: anthropic SDK and ChatAnthropic default `max_retries=2`; LangGraph's `RetryPolicy` default `retry_on` retries every Anthropic error **including 400s**; LangGraph's default recursion limit is now **10007** (`DEFAULT_RECURSION_LIMIT`), not 25. kagent's scheduler never re-sends after an uncertain send, and clients may retry only a `KAGENT_SEND_NOT_ACCEPTED` rejection, never a transport error (`a2a-gateway.md`). | retries and re-plans per run (share of entries with `attempt > 1`); alert above 10 % (screen 13's reading) | Built (`tests/test_llm.py`, `test_recursion_limit_is_the_circuit_breaker`) |
| **6. Right-size the model per node** | Haiku 5.5 for router and responder (effort `low`), Sonnet 5.5 for planner and specialists (`medium`), Opus 5.5 only for escalation (not wired). Literal env overrides per node. | ChatAnthropic `effort` → `output_config.effort` (on Sonnet 5.5 it also turns on adaptive thinking; Opus 5.5 and Haiku 5.5 default to `medium`, so set it). Caches are model-scoped: a per-node cascade forfeits cross-node cache reuse, accepted because each node's prefix differs anyway. Prices per MTok: Opus 5.5 $4 / $20, Sonnet 5.5 $2 / $10, Haiku 5.5 $0.10 / $0.50 up to 100 K prompt tokens ($0.50 / $2.50 above, cache included). | cost by node; eval quality when one node's model changes | Built |
| **7. Shrink tool results** | Catalog entities projected to ≤ 9 fields; every result capped at 4 000 characters (head and tail kept). Next: MCP tool interceptors at the client, context editing in long loops, programmatic tool calling as an experiment. | `langchain_mcp_adapters` `tool_interceptors` (can rewrite results); context editing `clear_tool_uses_20250919` needs `betas=["context-management-2025-06-27"]` (ChatAnthropic does not add it; without it the call raises `TypeError`); programmatic tool calling: `code_execution_20260120` + `allowed_callers` on our client tools (billed by container time unless web search/fetch is present) | tool-result characters per call; uncached input per specialist call | Built (projection and cap); the rest planned |

### 6.1 The ledger (step zero)

- **Four disjoint buckets per call:** uncached input, cache write (kept split by TTL only because 5 m and 1 h are priced differently), cache read, output. They add up to the prompt plus the output; nothing is counted twice.
- **The trap:** langchain-anthropic 1.7's `usage_metadata["input_tokens"]` is the *whole* prompt (Anthropic's uncached `input_tokens` + cache read + cache creation; `_create_usage_metadata`, chat_models.py:3313), and `cache_creation` reads 0 whenever the TTL split is present. So `uncached = input_tokens − cache_read − ephemeral_5m − ephemeral_1h`. The raw Anthropic usage in `response_metadata["usage"]` is preferred when present (non-streaming calls only). Streaming usage has no TTL split; the configured TTL is assumed and the call is still counted. Pinned by `tests/test_ledger.py`.
- **Tags on every entry:** `run_id` (the A2A task id), `context_id`, `request_id`, `node`, `model`, `attempt`, `rate_card_version`, plus status, stop reason and latency. `request_id` is the Anthropic message id (`msg_…`) today: ChatAnthropic does not surface the `request-id` header (only exceptions carry `request_id`). Capturing the header needs a wrapped SDK client (Phase 2).
- **Unknown is not zero:** an attempt with no usage (an error, a dead stream) has `usage=None` and `cost_usd=None`; the summary reports `unknown_calls`, `known_usage_coverage` and `complete=False`. An unpriced model is also unknown, never guessed.
- **Rate card versioned in code** (`anthropic-2026-10-18`, with the source URL), including Haiku 5.5's prompt-length tier. A price change is a new version, so old runs stay comparable.
- **Per verified outcome:** `cost_per_verified_outcome(runs)` puts every run's cost in the numerator (failed, refused and unverified included) and only verified runs in the denominator, and flags a lower bound when any cost was unknown.
- **Where it goes:** each entry and run summary is a JSON log line (`event: cost_ledger` / `cost_run`); the run summary also rides in the task's artifact as a data part (`homelab-scout/cost-run`), so the controller's TaskStore persists it in `kagent_v1` next to the conversation; ADK-style counters go under `kagent.dev/a2a/usage`, which the existing audit export already reads. Whether actor stdout reaches Loki from inside Substrate is unverified, which is why the artifact copy exists.
- **"Verified":** online, the `verify` node is a proxy: an answer is verified when it cites at least one source and every cited source came back from a tool. The eval grader is the ground truth (§7). Online cost per verified outcome is a trend; the SLO (screen 13: p50 ≤ target, quality floor, cache hit rate, known-usage coverage ≥ 99 %, retries ≤ 10 %) is computed from eval runs plus the online trend.

## 7. Eval set (before any lever ships)

- **Format:** the kubernetes repo's corpus format (`version: 1`, entries with `id`, `question`, `category`, `golden.must_include` / `must_not_include` / `behavior`, `reference`, `source`, optional `expect_tools` / `forbid_tools`), so the same file can later become `tests/eval-corpus/homelab-scout.yaml` for the in-cluster eval gate.
- **Seed (about 30 entries):** the repo-factual and refusal entries of `homelab-knowledge.yaml` (7 of 8; the memory entry does not apply to a byo agent); homelab-agent's parity questions that do not need live state (7 of 8; "Is the argo-cd control plane healthy?" does); new entries per path: ownership/dependency questions (catalog), multi-part questions (planner), the same question asked twice in one session (repeat path), out-of-scope and write requests (refuse, with `forbid_tools`), a canary-bearing file (redaction, V99 / B30), and a few drift probes for later (an ask that tempts a stray read).
- **Grading:** deterministic first (must_include, must_not_include, forbid/expect tools from the data parts, the verify outcome), then a judge only where a rubric needs it, as the eval gate does (Jev, then Claude).
- **Runner and budget:** the runner replays the corpus through the A2A gRPC API (locally against the in-process server with real models, later against the cluster). Every replay costs money: each run reports its own ledger total, Ari approves a budget per phase, and offline replays use the Batch API (50 %).
- **The gate for each lever:** no entry that passed the baseline fails; zero `forbid_tools` hits; zero canary leaks; and cost per verified outcome improves by more than run-to-run noise (three baseline runs set the noise band). Otherwise the lever is reverted.

## 8. The drift seam

### 8.1 Placement

`ToolBelt.call` runs, in order: **authorization** (allowlisted, bound in the template, in this specialist's scope; a miss is `deny` and the gate never sees it), **the drift gate**, then the tool. This is screen 10's placement ("Agent → gateway [auth → drift check] → MCP tool") moved into the runtime, because in kagent 1.0 the BYO runtime is the only component that sees each MCP call (there is no MCP gateway in the path for byo).

### 8.2 Inputs, deterministic

- **Intent** = the agent card's description + the **original** question (`render_intent`). Specialists receive the original question in their `Send` payload for this reason: measuring against the latest hop hides drift ("one hop looked fine at 11°; the workflow had drifted 133°").
- **Action** = the tool call as one sentence from a fixed template per tool (`render_action`), sorted arguments for unknown tools. No model writes either string.
- **Decision** = the angle between the two embeddings, against per-workflow `Thresholds` (the workflow is the specialist: `docs`, `catalog`). Thresholds come from calibration, not the demo's 45° / 70°: `RecordingGate` already records every (workflow, intent, action) the agent produces, which becomes the list of expected moves to rate.

### 8.3 Outcomes

- **allow:** the call runs.
- **ask:** `interrupt()` with a kagent-shaped `action_requests` payload; the executor emits `input-required` with a HITL `tool_approval_request` (when the caller activated the extension) and the plain-text hint (always). The approval resumes the same task with `Command(resume=…)`. The existing human channels already decide these pauses: `ask-hk --approve/--reject`, the dispatcher approvals page, the Slack bridge (T118–T120). Tested in `tests/test_hitl.py`.
- **refuse:** the tool is not called; the model gets an error result; the event is recorded (`decision: refuse`) and, in Phase 5, logged as an incident line for a Grafana rule.

**Known cost of a naive resume, pinned by the HITL test:** LangGraph re-runs an interrupted node from its start, so the specialist's first model call is paid again after the approval. Phase 5 moves the gated call into its own node, so a resume replays only that call; the ledger test then asserts zero extra model calls on resume (screen 13's "resuming only the approval node" case).

### 8.4 Embedding source (§11, decision 5)

| Option | For | Against |
|---|---|---|
| In-process small embedding model (ONNX, ~384 dimensions) | No network and no egress change; matches the talk's "~6 ms, 0 tokens" | Image size; NumPy/onnxruntime under gVisor on E5-2670 is unverified (R45) and needs a spike |
| Ollama `nomic-embed-text` (768-d, already deployed, `http://ollama.ollama.svc.cluster.local:11434`) via a small embeddings MCP server bound on the template | Reuses the deployed model; the binding is visible to admission and opens egress the supported way | A new server and a network hop per tool call; byo gets no Ollama egress otherwise (memory egress is kagent-harness only) |

Anthropic has no embeddings endpoint, so that is not an option. Recommendation: spike the in-process model first; fall back to the MCP server.

## 9. Security and capability class

- **Class `read`.** The image contains no write tool; `READ_ONLY_TOOLS` (`get_file_contents`, `search_code`, `get-catalog-entity`) is intersected with the template binding, so a server that later exposes a write tool (agent-docs has 13 tools, 8 unclassified) still cannot be called. Tested: `test_write_tools_are_refused_even_when_the_server_offers_them`.
- **Bound servers are read-only on the server side**, because byo egress is per origin: never `kagent-tool-server`, never `kagent-api`.
- **No secrets in the container or in git:** model key and the Backstage token are injected at egress; the runtime sees placeholders. The image pins its base and its dependencies; `kagent-proto` comes from a pinned commit.
- **Untrusted tool output:** repo files and catalog text can carry instructions. Typed handoffs limit what reaches the responder (≤ 5 facts per specialist, each with a source); the specialist prompt carries the redaction rule from B30; the eval corpus carries a canary entry.
- **Admission:** §4.1 is the one real security decision. The proposed conditions make the byo exception no wider than "a read-class template on read-only servers".
- **Identity and audit:** the gateway sets the caller identity; the runtime adds the run's ledger and tool calls to the persisted task, so `agent-audit --source v1` sees them like any other agent's.

## 10. Library versions (PyPI, read 2026-10-18)

| Package | Latest stable (upload date) | Used | Note |
|---|---|---|---|
| langgraph | 1.2.16 (2026-10-16) | yes | `CachePolicy`, `RetryPolicy`, `interrupt`/`Command`, `Send`, `context_schema` + `Runtime`, `durability=`, default recursion limit 10007 |
| langgraph-checkpoint | 4.3.0 (2026-10-12) | yes (`InMemorySaver`) | |
| langgraph-checkpoint-sqlite | 3.1.2 (2026-10-12) | later (`/data`) | also ships `SqliteCache` |
| langgraph-checkpoint-postgres | 3.2.0 (2026-10-14) | no | byo egress is HTTP(S) only |
| langgraph-prebuilt | 1.1.1 (2026-10-15) | transitively | |
| langchain | 1.4.6 (2026-10-14) | no (option) | `create_agent`, middleware listed in §6 |
| langchain-core | 1.6.12 (2026-10-16) | yes | fake chat models lack `bind_tools` (tests use their own fake) |
| langchain-anthropic | 1.7.6 (2026-10-12) | yes | `effort`, `cache_control`, `betas`, `defer_loading`/`allowed_callers` on tools, `context_management` (beta not auto-added) |
| langchain-mcp-adapters | 0.3.2 (2026-08-06) | yes | `MultiServerMCPClient(tool_interceptors=…)`; a new MCP session per tool call |
| a2a-sdk | 1.2.2 (2026-10-05) | yes (`[grpc]`) | A2A protocol 1.0, `lf.a2a.v1`; 0.3 compat handler available |
| anthropic | 1.15.0 (2026-10-15) | transitively | `DEFAULT_MAX_RETRIES = 2` |
| grpcio / grpcio-health-checking | 1.84.0 / 1.84.0 (2026-09-14) | 1.84.0 / **1.74.0** | protobuf < 7 for kagent-proto |
| kagent-core, kagent-langgraph, kagent-adk | 0.10.3 stable (2026-10-02); 1.0.0a11 (2026-10-09) … 1.0.0a14 (2026-10-16) | kagent-core **1.0.0a11** | match the controller; kagent-proto not on PyPI |

Sources: `https://pypi.org/pypi/<package>/json`; kagent releases `gh release list --repo kagent-dev/kagent`.

## 11. Open decisions for Ari (most important first)

1. **Admit a byo Harness at all**, and on which conditions (§4.1). Without a policy change nothing deploys, not even the Phase 0 spike.
2. **The agent's purpose** (§2): A recommended; B after a read-only live MCP server exists.
3. **Where the image lives and how Substrate pulls it**: a public GHCR image vs ECR (Atlantis-managed, V73) plus pull credentials for the Substrate workers, which no manifest configures today.
4. **Version lockstep**: build for the controller's alpha11 now (the skeleton does) and move in lockstep (a Renovate group with the controller and `golang-adk`), or upgrade kagent to alpha14 first (TaskStore proto renamed, config reshaped).
5. **Embedding source for the drift check** (§8.4).
6. **Cross-session answer cache**: session scope only (built) vs a shared store, which needs an egress-visible service.
7. **Ledger destination**: logs and the task artifact (built) vs extending `agent-audit` to decode the cost-run data part and adding a Grafana panel and the SLO alerts.
8. **Eval spend**: a budget per phase for real-model replays (Batch API where possible).
9. **HITL for byo**: the 1.x docs say a byo card declares no extension; confirm in Phase 0 that the gateway forwards `A2A-Extensions` to a byo actor and that ask-hk / the approvals page decide its pauses. If not, "ask" degrades to a text pause.

## 12. Not in scope

Writes of any kind; long-term memory (not available on byo); live-cluster tools (needs a new server); compaction (each run is one question); streaming tokens to the caller (non-streaming calls keep the ledger's TTL split; streaming can come later with the configured-TTL fallback).
