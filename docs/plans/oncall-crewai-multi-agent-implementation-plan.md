# OnCall Multi-Agent Decomposition Implementation Plan

## Overview

Decompose the monolithic `oncall-agent-api` into a multi-agent architecture using **CrewAI + A2A protocol**. Three standalone services — an orchestrator, a K8s diagnostics agent, and a GitHub/GitOps agent — each independently reachable via A2A protocol, deployed as separate K8s pods with isolated RBAC.

New project: `oncall-crewai/` (sibling to `oncall-agent-api/`, which continues running unchanged).

**Last Updated:** 2026-02-24
**Current Status:** ALL PHASES COMPLETE
**Overall Progress:** 39/39 tasks (100%)

## Success Criteria

- [ ] 3 services running independently (orchestrator, k8s-agent, github-agent)
- [ ] Each A2A agent serves `/.well-known/agent.json` with its capabilities
- [ ] Orchestrator routes K8s queries to K8s agent via A2A protocol
- [ ] Orchestrator routes GitHub/GitOps queries to GitHub agent via A2A protocol
- [ ] K8s agent can diagnose pod issues using its 7 extracted tools
- [ ] GitHub agent can list/read manifests and create PRs using its 5 extracted tools
- [ ] Agents are directly callable via A2A (bypassing orchestrator)
- [ ] Existing oncall-agent-api continues to work unchanged
- [ ] All services work in docker-compose for local development
- [ ] K8s manifests ready for cluster deployment

## Research Findings

### Relevant Source Files (oncall-agent-api)
- `src/tools/custom_tools.py` — K8s tools (lines 24-371), GitHub tools (lines 374-869)
- `src/api/agent_client.py` — System prompts (lines 88-202), tool schemas (lines 224-789)
- `src/api/api_server.py` — FastAPI app structure, endpoints, middleware
- `config/service_mapping.yaml` — Service catalog (60+ services)
- `k8s/` — Existing K8s manifests (deployment, rbac, configmap, secret)

### Key Technical Findings
1. **CrewAI A2AServerConfig is metadata only** — does NOT start a server. Must use `a2a-sdk` (`A2AStarletteApplication` + `AgentExecutor`) to serve A2A endpoints
2. **CrewAI A2AClientConfig IS fully integrated** — handles agent card fetching, delegation, multi-turn automatically
3. **CrewAI tools must be synchronous and return strings** — existing async tools returning dicts need adaptation
4. **A2AStarletteApplication is Starlette-based** — can be mounted inside FastAPI via `app.mount()`
5. **CrewAI uses LiteLLM for Claude** — model string: `"anthropic/claude-sonnet-4-5-20250929"`

### Architecture Decisions

#### Decision 1: A2A Server Implementation
**Options considered:**
1. CrewAI A2AServerConfig only — simpler, but metadata-only, no actual server
2. a2a-sdk A2AStarletteApplication — full server with JSON-RPC, task store, agent card discovery

**Chosen:** Option 2 — because A2AServerConfig is metadata-only and doesn't start a server. The a2a-sdk provides the actual HTTP server with JSON-RPC routing, task store, and agent card discovery endpoint.

#### Decision 2: Orchestrator Routing
**Options considered:**
1. CrewAI hierarchical process (LLM decides) — simpler but has known issues with sequential execution
2. CrewAI Flow with @router (code decides) — deterministic routing with conditional logic

**Chosen:** Option 2 — because hierarchical process has known issues with sequential execution. Flows give deterministic routing with @router while still using LLM reasoning within each route.

#### Decision 3: Tool Isolation (Tier 2 - A2A Combined)
**Options considered:**
1. Separate MCP server pods per tool group — maximum isolation, 5 pods total
2. Tools in-process within A2A agent — simpler, 3 pods total

**Chosen:** Option 2 (Tier 2) — keeps pod count at 3, simpler for exploration. MCP servers can be extracted later as a follow-up exercise.

#### Decision 4: Agent-to-Tool Communication
**Options considered:**
1. MCP protocol to separate tool server — additional network hop, more isolation
2. Direct Python function calls in-process — simpler, lower latency

**Chosen:** Option 2 — tools run as CrewAI @tool decorated functions inside the agent pod. No MCP overhead.

### Target Architecture

```
                        External Traffic
                             │
                             ▼
┌──────────────────────────────────────────────────────────────┐
│  namespace: oncall-crewai                                    │
│                                                              │
│  ┌──────────────────────────────────────────┐               │
│  │  Pod: orchestrator                       │               │
│  │  SA: crewai-orchestrator (no cluster)    │               │
│  │  Secrets: ANTHROPIC_API_KEY, API_KEYS    │               │
│  │  Port: 8000                              │               │
│  │                                          │               │
│  │  FastAPI + CrewAI Flow                   │               │
│  │  ├── @router: classify query             │               │
│  │  ├── K8s delegate (A2AClientConfig) ───────────┐        │
│  │  └── GitHub delegate (A2AClientConfig) ──────┐ │        │
│  │                                          │   │ │        │
│  │  A2A: /.well-known/agent.json            │   │ │        │
│  └──────────────────────────────────────────┘   │ │        │
│                                                  │ │        │
│  ┌──────────────────────────────────────────┐   │ │        │
│  │  Pod: k8s-agent-a2a                    ◄─────┘ │        │
│  │  SA: k8s-diagnostics-agent (read-only)   │     │        │
│  │  Secrets: ANTHROPIC_API_KEY              │     │        │
│  │  Port: 8080                              │     │        │
│  │                                          │     │        │
│  │  A2A Server + CrewAI Agent               │     │        │
│  │  Tools (in-process):                     │     │        │
│  │  • list_namespaces, list_pods            │     │        │
│  │  • get_pod_logs, get_pod_events          │     │        │
│  │  • get_deployment_status, list_services  │     │        │
│  │  • analyze_service_health                │     │        │
│  │                                          │     │        │
│  │  A2A: /.well-known/agent.json            │     │        │
│  └──────────────────────────────────────────┘     │        │
│                                                    │        │
│  ┌──────────────────────────────────────────┐     │        │
│  │  Pod: github-agent-a2a                 ◄───────┘        │
│  │  SA: github-gitops-agent (no cluster)    │              │
│  │  Secrets: ANTHROPIC_API_KEY, GITHUB_TOKEN│              │
│  │  Port: 8080                              │              │
│  │                                          │              │
│  │  A2A Server + CrewAI Agent               │              │
│  │  Tools (in-process):                     │              │
│  │  • search_recent_deployments             │              │
│  │  • get_gitops_file, list_gitops_directory│              │
│  │  • create_remediation_pr                 │              │
│  │  • create_document_pr                    │              │
│  │                                          │              │
│  │  A2A: /.well-known/agent.json            │              │
│  └──────────────────────────────────────────┘              │
│                                                              │
│  ┌──────────────────────────────────────────┐              │
│  │  Pod: oncall-agent-api (EXISTING)        │  ← unchanged │
│  └──────────────────────────────────────────┘              │
└──────────────────────────────────────────────────────────────┘
```

### Directory Structure

```
oncall-crewai/
├── pyproject.toml
├── requirements.txt
├── .env.example
├── .gitignore
├── docker-compose.yml
├── README.md
│
├── src/
│   ├── shared/
│   │   ├── __init__.py
│   │   ├── config.py
│   │   └── logging_config.py
│   │
│   ├── k8s_agent/
│   │   ├── __init__.py
│   │   ├── tools.py
│   │   ├── agent.py
│   │   ├── executor.py
│   │   ├── server.py
│   │   └── prompts.py
│   │
│   ├── github_agent/
│   │   ├── __init__.py
│   │   ├── tools.py
│   │   ├── agent.py
│   │   ├── executor.py
│   │   ├── server.py
│   │   └── prompts.py
│   │
│   └── orchestrator/
│       ├── __init__.py
│       ├── main.py
│       ├── flow.py
│       ├── agents.py
│       └── prompts.py
│
├── config/
│   └── service_mapping.yaml
│
├── docker/
│   ├── Dockerfile.orchestrator
│   ├── Dockerfile.k8s-agent
│   └── Dockerfile.github-agent
│
├── k8s/
│   ├── namespace.yaml
│   ├── orchestrator/
│   │   ├── deployment.yaml
│   │   ├── configmap.yaml
│   │   └── secret.yaml
│   ├── k8s-agent/
│   │   ├── deployment.yaml
│   │   ├── rbac.yaml
│   │   ├── configmap.yaml
│   │   └── secret.yaml
│   └── github-agent/
│       ├── deployment.yaml
│       ├── configmap.yaml
│       └── secret.yaml
│
└── tests/
    ├── conftest.py
    ├── test_k8s_tools.py
    ├── test_github_tools.py
    ├── test_k8s_agent_a2a.py
    ├── test_github_agent_a2a.py
    ├── test_orchestrator_routing.py
    └── test_e2e.py
```

---

## Implementation

### Phase 1: Project Scaffolding & Dependencies (4/4 tasks) ✅

Set up the oncall-crewai project with directory structure, dependencies, and shared utilities.

#### Task 1.1: Create project directory structure ✅
**Files:** `oncall-crewai/` (new directory)
**Steps:**
1. Create `oncall-crewai/` at `/Users/arisela/git/claude-agents/oncall-crewai/`
2. Create directory tree:
   ```
   oncall-crewai/
   ├── src/
   │   ├── shared/
   │   ├── k8s_agent/
   │   ├── github_agent/
   │   └── orchestrator/
   ├── config/
   ├── docker/
   ├── k8s/
   │   ├── orchestrator/
   │   ├── k8s-agent/
   │   └── github-agent/
   └── tests/
   ```
3. Add `__init__.py` files in all Python packages

**Testing:**
- [ ] Directory structure exists with all `__init__.py` files
- [ ] `python -c "import src.shared"` works from project root

#### Task 1.2: Create pyproject.toml with dependencies ✅
**Files:** `oncall-crewai/pyproject.toml`
**Steps:**
1. Define project metadata (name: oncall-crewai, python: >=3.11)
2. Core dependencies: `crewai[a2a]`, `a2a-sdk[http-server]`, `fastapi`, `uvicorn[standard]`, `kubernetes>=31.0.0`, `PyGithub>=2.5.0`, `pydantic>=2.12.0`, `python-dotenv`
3. Dev dependencies: `pytest`, `pytest-asyncio`, `pytest-mock`, `black`, `ruff`
4. Generate `requirements.txt` from locked deps

**Testing:**
- [ ] `pip install -e ".[dev]"` succeeds in a venv
- [ ] `python -c "import crewai; import a2a"` succeeds

#### Task 1.3: Create shared configuration module ✅
**Files:** `oncall-crewai/src/shared/config.py`, `oncall-crewai/src/shared/logging_config.py`
**Steps:**
1. `config.py`: Load env vars with defaults (ANTHROPIC_API_KEY, AGENT_LOG_LEVEL, service URLs for agent discovery)
2. `config.py`: Service catalog loader (reads service_mapping.yaml or embedded dict for K8s agent)
3. `logging_config.py`: Structured logging setup with configurable level
4. Copy `config/service_mapping.yaml` from oncall-agent-api (K8s-relevant entries only, drop Zeus/Datadog)

**Testing:**
- [ ] Config loads with defaults when no env vars set
- [ ] Service catalog loads and returns expected structure

#### Task 1.4: Create .env.example and .gitignore ✅
**Files:** `oncall-crewai/.env.example`, `oncall-crewai/.gitignore`
**Steps:**
1. `.env.example` with all required/optional env vars documented
2. `.gitignore` for Python project (venv, __pycache__, .env, etc.)

**Testing:**
- [ ] Files exist with correct content

---

### Phase 2: K8s Tools Extraction (5/5 tasks) ✅

Extract the 7 Kubernetes tools from `custom_tools.py` and adapt them to CrewAI's `@tool` format.

#### Task 2.1: Port K8s client helper ✅
**Files:** `oncall-crewai/src/k8s_agent/tools.py`
**Steps:**
1. Port `_get_k8s_client()` from `custom_tools.py:28-40`
2. Adapt for sync usage (CrewAI tools are sync): use the kubernetes client's synchronous API directly
3. Support both in-cluster config and local kubeconfig

**Testing:**
- [ ] `_get_k8s_client()` returns CoreV1Api and AppsV1Api instances
- [ ] Works with mocked kubernetes.config

#### Task 2.2: Port list_namespaces tool ✅
**Files:** `oncall-crewai/src/k8s_agent/tools.py`
**Steps:**
1. Adapt `list_namespaces` (custom_tools.py:43-81) to CrewAI @tool format
2. Change signature from `async def list_namespaces(args: dict)` to `@tool def list_namespaces(pattern: str = "") -> str`
3. Return JSON string instead of dict
4. Keep the pattern filtering logic

**Testing:**
- [ ] Tool returns JSON with namespace list
- [ ] Pattern filtering works (e.g., pattern="default")
- [ ] Empty pattern returns all namespaces

#### Task 2.3: Port remaining K8s tools ✅
**Files:** `oncall-crewai/src/k8s_agent/tools.py`
**Steps:**
1. Adapt each tool following same pattern as Task 2.2:
   - `list_pods(namespace: str, label_selector: str = "")` — from lines 84-143
   - `get_pod_logs(namespace: str, pod_name: str, container: str = "", tail_lines: int = 100)` — from lines 146-173
   - `get_pod_events(namespace: str, pod_name: str = "")` — from lines 176-212
   - `get_deployment_status(namespace: str, deployment_name: str = "")` — from lines 215-263
   - `list_services(namespace: str = "", service_name: str = "", check_label: str = "")` — from lines 266-370
2. All return JSON strings
3. All use synchronous K8s client calls

**Testing:**
- [ ] Each tool returns valid JSON
- [ ] Parameters are properly typed
- [ ] Error handling returns error messages as strings (not exceptions)

#### Task 2.4: Port analyze_service_health composite tool ✅
**Files:** `oncall-crewai/src/k8s_agent/tools.py`
**Steps:**
1. Adapt `analyze_service_health` (custom_tools.py:876-947)
2. This tool calls list_pods, get_deployment_status, and get_pod_events internally
3. Call the adapted tool functions directly (they're in the same module)
4. Parse JSON strings from sub-tools, aggregate, return combined JSON

**Testing:**
- [ ] Composite tool aggregates results from sub-tools
- [ ] Returns structured health analysis as JSON string

#### Task 2.5: Write unit tests for K8s tools ✅
**Files:** `oncall-crewai/tests/test_k8s_tools.py`
**Steps:**
1. Create test fixtures that mock kubernetes client (CoreV1Api, AppsV1Api)
2. Test each tool function with mocked responses
3. Test error handling (namespace not found, pod not found, etc.)
4. Follow existing test patterns from `oncall-agent-api/tests/`

**Testing:**
- [ ] `pytest tests/test_k8s_tools.py -v` passes
- [ ] All 7 tools have at least 1 positive and 1 error test case

---

### Phase 3: K8s A2A Agent Service (5/5 tasks) ✅

Build the K8s Diagnostics agent as a standalone A2A-compliant service.

#### Task 3.1: Create K8s agent system prompt ✅
**Files:** `oncall-crewai/src/k8s_agent/prompts.py`
**Steps:**
1. Extract K8s-relevant sections from oncall system prompt (agent_client.py:88-202)
2. Include: critical services list, known issues (vault unsealing, chores-tracker startup), dependency tree, troubleshooting workflow
3. Include: service catalog data (embedded from service_mapping.yaml)
4. Remove: GitOps PR workflow, GitHub-specific instructions, Zeus/Datadog references
5. Add: "You are a Kubernetes diagnostics specialist. You investigate pod, deployment, and service health issues."

**Testing:**
- [ ] Prompt is coherent and K8s-focused
- [ ] No references to GitHub/GitOps/Zeus/Datadog

#### Task 3.2: Create CrewAI Agent + Crew definition ✅
**Files:** `oncall-crewai/src/k8s_agent/agent.py`
**Steps:**
1. Define CrewAI Agent with:
   - `role="Kubernetes SRE Specialist"`
   - `goal="Diagnose Kubernetes pod, deployment, and service issues"`
   - `backstory` from system prompt
   - `tools=[list_namespaces, list_pods, get_pod_logs, get_pod_events, get_deployment_status, list_services, analyze_service_health]`
   - `llm=LLM(model="anthropic/claude-sonnet-4-5-20250929")`
2. Define Task template for handling investigation requests
3. Define Crew wrapping the agent
4. Create `invoke(query: str, context_id: str) -> str` method

**Testing:**
- [ ] Agent initializes without errors
- [ ] Crew can be kicked off with test input (mocked LLM)

#### Task 3.3: Create AgentExecutor bridge ✅
**Files:** `oncall-crewai/src/k8s_agent/executor.py`
**Steps:**
1. Implement `K8sAgentExecutor(AgentExecutor)` following the a2a-sdk pattern
2. `execute()`: extract user input from context → invoke CrewAI agent → return result via event_queue
3. `cancel()`: raise UnsupportedOperationError
4. Handle errors gracefully (catch exceptions, return error messages)

**Testing:**
- [ ] Executor processes a request context and returns a text response
- [ ] Errors are caught and returned as error messages

#### Task 3.4: Create A2A server with FastAPI ✅
**Files:** `oncall-crewai/src/k8s_agent/server.py`
**Steps:**
1. Define AgentCard:
   - name: "K8s Diagnostics Agent"
   - skills: diagnose-pods, check-deployments, analyze-service-health
   - capabilities: streaming=False (start simple)
   - url: configurable via `K8S_AGENT_URL` env var
2. Create `DefaultRequestHandler` with `K8sAgentExecutor` and `InMemoryTaskStore`
3. Build `A2AStarletteApplication`
4. Create FastAPI app with `/health` endpoint
5. Mount A2A app at root
6. Entry point: `uvicorn k8s_agent.server:app --host 0.0.0.0 --port 8080`

**Testing:**
- [ ] `GET /health` returns 200
- [ ] `GET /.well-known/agent.json` returns valid AgentCard JSON
- [ ] AgentCard contains expected skills
- [ ] `POST /` with JSON-RPC message/send returns a response

#### Task 3.5: Write A2A integration tests for K8s agent ✅
**Files:** `oncall-crewai/tests/test_k8s_agent_a2a.py`
**Steps:**
1. Test AgentCard endpoint (well-known)
2. Test health endpoint
3. Test message/send with mocked CrewAI agent (no real LLM calls)
4. Test error handling for malformed requests

**Testing:**
- [ ] `pytest tests/test_k8s_agent_a2a.py -v` passes

---

### Phase 4: GitHub Tools Extraction (3/3 tasks) ✅

Extract the 5 GitHub/GitOps tools and adapt them to CrewAI format.

#### Task 4.1: Port GitHub client helpers ✅
**Files:** `oncall-crewai/src/github_agent/tools.py`
**Steps:**
1. Port `_get_github_client()` from custom_tools.py:378-383
2. Port `_get_gitops_config()` from custom_tools.py:433-438
3. Port `_validate_gitops_path()` from custom_tools.py:441-451
4. Port `_apply_patches()` from custom_tools.py:542-610
5. Port `_build_pr_body()` helper

**Testing:**
- [ ] Helpers initialize correctly with mocked env vars

#### Task 4.2: Port GitHub tools to CrewAI format ✅
**Files:** `oncall-crewai/src/github_agent/tools.py`
**Steps:**
1. `search_recent_deployments(repo_name: str, hours_back: int = 24, workflow_name: str = "")` — from lines 386-425
2. `get_gitops_file(file_path: str)` — from lines 454-490
3. `list_gitops_directory(dir_path: str = "")` — from lines 493-539
4. `create_remediation_pr(service: str, action_summary: str, changes_json: str, incident_context: str, reason: str)` — from lines 613-770. Note: `changes` param is JSON string since CrewAI tools take primitives
5. `create_document_pr(filename: str, content: str, description: str)` — from lines 778-868
6. All adapted to sync, returning JSON strings

**Testing:**
- [ ] Each tool returns valid JSON
- [ ] Path validation prevents traversal attacks
- [ ] PR creation includes proper branch naming

#### Task 4.3: Write unit tests for GitHub tools ✅
**Files:** `oncall-crewai/tests/test_github_tools.py`
**Steps:**
1. Mock PyGithub client
2. Test each tool function
3. Test path validation security
4. Test patch application logic
5. Follow patterns from `oncall-agent-api/tests/api/test_gitops_tools.py`

**Testing:**
- [ ] `pytest tests/test_github_tools.py -v` passes

---

### Phase 5: GitHub A2A Agent Service (4/4 tasks) ✅

Build the GitHub/GitOps agent as a standalone A2A service (same pattern as Phase 3).

#### Task 5.1: Create GitHub agent system prompt ✅
**Files:** `oncall-crewai/src/github_agent/prompts.py`
**Steps:**
1. Extract GitOps-relevant sections from oncall system prompt
2. Include: GitOps workflow, PR creation safeguards (user confirmation required), branch naming, path restrictions
3. Include: repo config (arigsela/kubernetes, base-apps/)
4. Add: "You are a GitOps remediation specialist. You inspect Kubernetes manifests and create PRs for changes."

**Testing:**
- [ ] Prompt covers GitOps workflow and safety requirements

#### Task 5.2: Create CrewAI Agent + Crew + AgentExecutor ✅
**Files:** `oncall-crewai/src/github_agent/agent.py`, `oncall-crewai/src/github_agent/executor.py`
**Steps:**
1. Same pattern as Phase 3 Tasks 3.2 and 3.3
2. Agent role: "GitOps Remediation Engineer"
3. Tools: the 5 GitHub tools from Phase 4
4. GitHubAgentExecutor bridging to a2a-sdk

**Testing:**
- [ ] Agent initializes, Crew can be kicked off

#### Task 5.3: Create A2A server ✅
**Files:** `oncall-crewai/src/github_agent/server.py`
**Steps:**
1. AgentCard: name "GitOps Remediation Agent", skills: inspect-manifests, create-remediation-pr, check-deployments
2. Same server pattern as Phase 3 Task 3.4
3. Port 8080 (different pod, same port is fine in K8s)

**Testing:**
- [ ] `GET /.well-known/agent.json` returns valid AgentCard
- [ ] `GET /health` returns 200
- [ ] Skills listed in agent card match tool capabilities

#### Task 5.4: Write A2A integration tests ✅
**Files:** `oncall-crewai/tests/test_github_agent_a2a.py`
**Steps:**
1. Same pattern as Phase 3 Task 3.5
2. Test AgentCard, health, message/send

**Testing:**
- [ ] `pytest tests/test_github_agent_a2a.py -v` passes

---

### Phase 6: Orchestrator Service (5/5 tasks) ✅

Build the orchestrator that routes queries to specialist agents via A2A protocol.

#### Task 6.1: Create orchestrator agents with A2AClientConfig ✅
**Files:** `oncall-crewai/src/orchestrator/agents.py`
**Steps:**
1. Define K8s delegate agent:
   ```python
   k8s_delegate = Agent(
       role="K8s Investigation Coordinator",
       goal="Delegate Kubernetes diagnostic tasks to the K8s specialist",
       a2a=A2AClientConfig(
           endpoint=os.getenv("K8S_AGENT_URL", "http://k8s-agent-a2a:8080"),
           timeout=120, max_turns=10
       ),
       llm=LLM(model="anthropic/claude-sonnet-4-5-20250929")
   )
   ```
2. Define GitHub delegate agent similarly with GITHUB_AGENT_URL
3. Both agents are thin proxies — they only delegate via A2A, no local tools

**Testing:**
- [ ] Agents initialize with A2AClientConfig
- [ ] Config reads URLs from environment variables

#### Task 6.2: Create CrewAI Flow with routing ✅
**Files:** `oncall-crewai/src/orchestrator/flow.py`
**Steps:**
1. Create `OncallFlow(Flow)` with:
   - `@start` method: classify incoming query (K8s, GitHub, or both)
   - `@router` method: route to "k8s_route", "github_route", or "combined_route"
   - `@listen("k8s_route")`: kick off K8s delegate Crew
   - `@listen("github_route")`: kick off GitHub delegate Crew
   - `@listen("combined_route")`: kick off K8s first, then GitHub with K8s results
2. Classification via keyword matching (start deterministic, upgrade to LLM later)
3. Flow state: Pydantic model with query, route, k8s_result, github_result

**Testing:**
- [ ] K8s-related queries route to k8s_route
- [ ] GitHub-related queries route to github_route
- [ ] Ambiguous queries handled gracefully

#### Task 6.3: Create FastAPI application ✅
**Files:** `oncall-crewai/src/orchestrator/main.py`
**Steps:**
1. FastAPI app with endpoints:
   - `GET /health` — health check
   - `GET /` — API info
   - `POST /query` — accepts query, runs Flow, returns result
2. Query endpoint: accept JSON body with `prompt` field, run `OncallFlow().kickoff()`, return result
3. Add CORS middleware
4. Add basic API key authentication (from `API_KEYS` env var)

**Testing:**
- [ ] `GET /health` returns 200
- [ ] `POST /query` with valid API key returns response
- [ ] Invalid API key returns 401

#### Task 6.4: Create orchestrator's A2A server ✅
**Files:** `oncall-crewai/src/orchestrator/main.py` (extend)
**Steps:**
1. Define orchestrator AgentCard: name "OnCall Orchestrator", skills: triage-incident, coordinate-investigation
2. Create OrchestratorExecutor that runs the Flow
3. Mount A2AStarletteApplication alongside FastAPI endpoints

**Testing:**
- [ ] `GET /.well-known/agent.json` returns orchestrator's AgentCard
- [ ] A2A message/send triggers the Flow

#### Task 6.5: Write orchestrator tests ✅
**Files:** `oncall-crewai/tests/test_orchestrator_routing.py`
**Steps:**
1. Test Flow routing logic (mock the Crew kickoff)
2. Test API endpoints (health, query)
3. Test authentication
4. Test that K8s queries are routed correctly
5. Test that GitHub queries are routed correctly

**Testing:**
- [ ] `pytest tests/test_orchestrator_routing.py -v` passes

---

### Phase 7: Docker Configuration (2/2 tasks) ✅

Create Dockerfiles and docker-compose for local development.

#### Task 7.1: Create Dockerfiles ✅
**Files:** `oncall-crewai/docker/Dockerfile.orchestrator`, `oncall-crewai/docker/Dockerfile.k8s-agent`, `oncall-crewai/docker/Dockerfile.github-agent`
**Steps:**
1. Base image: `python:3.11-slim`
2. Install dependencies from requirements.txt
3. Copy src/ and config/ directories
4. Set PYTHONPATH=/app/src
5. Health check: `curl -f http://localhost:{port}/health || exit 1`
6. Orchestrator CMD: `uvicorn orchestrator.main:app --host 0.0.0.0 --port 8000`
7. K8s agent CMD: `uvicorn k8s_agent.server:app --host 0.0.0.0 --port 8080`
8. GitHub agent CMD: `uvicorn github_agent.server:app --host 0.0.0.0 --port 8080`

**Testing:**
- [ ] Each Dockerfile builds without errors
- [ ] Built images start and respond to health checks

#### Task 7.2: Create docker-compose.yml ✅
**Files:** `oncall-crewai/docker-compose.yml`
**Steps:**
1. Three services: orchestrator (port 8000), k8s-agent (port 8081), github-agent (port 8082)
2. Shared .env file for ANTHROPIC_API_KEY
3. Orchestrator env: K8S_AGENT_URL=http://k8s-agent:8080, GITHUB_AGENT_URL=http://github-agent:8080
4. K8s agent: mount local kubeconfig for development
5. GitHub agent: GITHUB_TOKEN from env
6. Health checks on all three
7. Depends_on: orchestrator depends on both agents

**Testing:**
- [ ] `docker-compose up -d` starts all 3 services
- [ ] All 3 health checks pass
- [ ] Orchestrator can reach agent cards at internal URLs

---

### Phase 8: Kubernetes Manifests (4/4 tasks) ✅

Create K8s deployment manifests with proper RBAC isolation.

#### Task 8.1: Create namespace ✅
**Files:** `oncall-crewai/k8s/namespace.yaml`
**Steps:**
1. Namespace: `oncall-crewai` (separate from existing `oncall-agent`)
2. Labels for identification

**Testing:**
- [ ] `kubectl apply -f k8s/namespace.yaml` succeeds

#### Task 8.2: Create K8s agent manifests ✅
**Files:** `oncall-crewai/k8s/k8s-agent/deployment.yaml`, `rbac.yaml`, `configmap.yaml`, `secret.yaml`
**Steps:**
1. ServiceAccount: `k8s-diagnostics-agent`
2. ClusterRole: `k8s-agent-reader` — read-only rules (pods, pods/log, pods/status, events, deployments, replicasets, namespaces, services)
3. ClusterRoleBinding: bind to SA in oncall-crewai namespace
4. Deployment: 1 replica, port 8080, health/readiness probes
5. Service: ClusterIP on port 8080
6. ConfigMap: AGENT_LOG_LEVEL
7. Secret: ANTHROPIC_API_KEY
8. Resources: 256Mi/250m requests, 512Mi/500m limits

**Testing:**
- [ ] All manifests are valid YAML
- [ ] RBAC is read-only (no write verbs)
- [ ] ServiceAccount is in oncall-crewai namespace

#### Task 8.3: Create GitHub agent manifests ✅
**Files:** `oncall-crewai/k8s/github-agent/deployment.yaml`, `configmap.yaml`, `secret.yaml`
**Steps:**
1. ServiceAccount: `github-gitops-agent` (NO ClusterRole — no K8s access needed)
2. Deployment: 1 replica, port 8080, probes
3. Service: ClusterIP on port 8080
4. ConfigMap: GITOPS_REPO, GITOPS_BASE_PATH, GITOPS_BASE_BRANCH, GITHUB_ORG
5. Secret: ANTHROPIC_API_KEY, GITHUB_TOKEN

**Testing:**
- [ ] No ClusterRole/ClusterRoleBinding (GitHub agent has no K8s access)
- [ ] Secrets contain only what this agent needs

#### Task 8.4: Create orchestrator manifests ✅
**Files:** `oncall-crewai/k8s/orchestrator/deployment.yaml`, `configmap.yaml`, `secret.yaml`
**Steps:**
1. ServiceAccount: `crewai-orchestrator` (NO ClusterRole)
2. Deployment: 1 replica, port 8000, probes
3. Service: ClusterIP on port 80 → 8000
4. ConfigMap: K8S_AGENT_URL=http://k8s-agent-a2a.oncall-crewai.svc:8080, GITHUB_AGENT_URL=http://github-agent-a2a.oncall-crewai.svc:8080
5. Secret: ANTHROPIC_API_KEY, API_KEYS, SLACK_BOT_TOKEN (optional), SLACK_SIGNING_SECRET (optional)

**Testing:**
- [ ] ConfigMap contains correct service DNS names
- [ ] No ClusterRole (orchestrator has no direct K8s access)

---

### Phase 9: Integration & E2E Testing (4/4 tasks) ✅

Verify the complete system works end-to-end.

#### Task 9.1: Direct A2A agent tests ✅
**Steps:**
1. Start K8s agent locally (or in docker-compose)
2. Fetch agent card: `curl http://localhost:8081/.well-known/agent.json`
3. Send A2A message:
   ```bash
   curl -X POST http://localhost:8081/ \
     -H "Content-Type: application/json" \
     -d '{
       "jsonrpc": "2.0",
       "method": "message/send",
       "id": "1",
       "params": {
         "message": {
           "role": "user",
           "parts": [{"kind": "text", "text": "List pods in default namespace"}],
           "messageId": "test-1"
         }
       }
     }'
   ```
4. Verify response contains pod information
5. Repeat for GitHub agent with "List files in base-apps/chores-tracker"

**Testing:**
- [ ] K8s agent responds to direct A2A calls
- [ ] GitHub agent responds to direct A2A calls
- [ ] Responses contain expected tool results

#### Task 9.2: Orchestrator routing E2E tests ✅
**Steps:**
1. Start all 3 services via docker-compose
2. Send K8s query to orchestrator:
   ```bash
   curl -X POST http://localhost:8000/query \
     -H "Content-Type: application/json" \
     -H "X-API-Key: test-key" \
     -d '{"prompt": "Why is chores-tracker crashing?"}'
   ```
3. Verify orchestrator routes to K8s agent and returns diagnosis
4. Send GitHub query:
   ```bash
   curl -X POST http://localhost:8000/query \
     -H "Content-Type: application/json" \
     -H "X-API-Key: test-key" \
     -d '{"prompt": "Show me the deployment manifest for chores-tracker"}'
   ```
5. Verify orchestrator routes to GitHub agent and returns manifest content

**Testing:**
- [ ] K8s queries are routed to K8s agent
- [ ] GitHub queries are routed to GitHub agent
- [ ] Responses include agent attribution (which agent handled it)

#### Task 9.3: Multi-agent workflow E2E test ✅
**Steps:**
1. Send a combined query: "Diagnose chores-tracker and show me its current deployment manifest"
2. Verify orchestrator calls both agents (K8s for diagnosis, GitHub for manifest)
3. Verify combined response includes both results

**Testing:**
- [ ] Combined queries engage multiple agents
- [ ] Results are aggregated coherently

#### Task 9.4: Create project README ✅
**Files:** `oncall-crewai/README.md`
**Steps:**
1. Document architecture (3-service A2A design)
2. Quick start with docker-compose
3. Individual agent testing instructions (direct A2A calls)
4. K8s deployment instructions
5. Environment variables reference
6. Protocol overview (A2A for agent communication, tools in-process)

**Testing:**
- [ ] README covers all setup and usage scenarios

---

## End-to-End Verification Checklist

After all phases are complete:
- [ ] `docker-compose up -d` — all 3 services healthy
- [ ] Each agent's `/.well-known/agent.json` returns valid AgentCard
- [ ] Direct A2A calls to each agent work independently
- [ ] Orchestrator routes queries to correct specialist agent
- [ ] Multi-agent queries return combined results
- [ ] Existing `oncall-agent-api` still runs independently and unchanged
- [ ] `kubectl apply -f k8s/` deploys all resources to dev cluster
- [ ] All unit tests pass: `pytest tests/ -v`

## Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| CrewAI + Claude via LiteLLM has tool calling issues | Medium | High | Test early in Phase 3; fallback to direct Anthropic SDK if CrewAI doesn't work |
| A2A protocol overhead adds significant latency | Medium | Medium | Acceptable for exploration; measure and document actual latency |
| CrewAI Flow @router doesn't integrate cleanly with A2AClientConfig | Medium | High | Test in Phase 6; fallback to manual A2A client calls via a2a-sdk directly |
| a2a-sdk version compatibility with crewai[a2a] | Low | High | Pin compatible versions in pyproject.toml; test in Phase 1 |
| Docker-compose networking between services | Low | Medium | Use explicit service names and health check dependencies |
| Service catalog fragmentation between agents | Low | Low | Embed relevant subset in each agent's prompt; single source in shared/ |
| CrewAI @tool sync limitation with K8s async client | Low | Medium | K8s Python client supports sync calls natively; no adaptation needed |

## Notes

- User will handle building Docker images — Dockerfiles are provided, build/push is manual
- Memory/persistence deferred to a later phase
- Slack integration deferred — orchestrator has the endpoint stubs but full Slack wiring is future work
- Zeus, Datadog, and AWS cost tools are intentionally dropped from this project
- Existing `oncall-agent-api` continues running unchanged in its own namespace
