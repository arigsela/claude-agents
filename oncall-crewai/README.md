# OnCall CrewAI — Multi-Agent Kubernetes Oncall System

A production-ready multi-agent system for Kubernetes incident triage. Three independently deployable services communicate via Google's **A2A (Agent-to-Agent) protocol**, with a **CopilotKit** chat UI for real-time interaction.

## What's Deployed

Four pods running in the `oncall-crewai` namespace on a k3s cluster:

| Pod | Image | Port | Role |
|-----|-------|------|------|
| `crewai-orchestrator` | `crewai-orchestrator:latest` | 8000 | Query router — classifies queries and delegates to agents |
| `k8s-agent-a2a` | `crewai-k8s-agent:latest` | 8080 | Kubernetes diagnostics — read-only cluster access |
| `github-agent-a2a` | `crewai-github-agent:latest` | 8080 | GitOps operations — manifest inspection, PR creation |
| `crewai-frontend` | `crewai-frontend:latest` | 3000 | CopilotKit chat UI at `oncall-crewai.arigsela.com` |

All images are pushed to ECR (`852893458518.dkr.ecr.us-east-2.amazonaws.com`) and deployed via ArgoCD GitOps from `arigsela/kubernetes` repo (`base-apps/oncall-crewai/`).

## Architecture

```
  Browser (oncall-crewai.arigsela.com)
       │
       ▼
┌─────────────────┐    AG-UI SSE     ┌──────────────────────────────────┐
│  Frontend       │ ──────────────►  │  Orchestrator (port 8000)        │
│  Next.js 16     │  /copilotkit     │  CrewAI Flow: classify → route   │
│  CopilotKit     │                  │  POST /query (REST)              │
│  Session Sidebar│  /api/sessions   │  GET/DELETE /sessions (REST)     │
│  port 3000      │ ◄──────────────  │  A2A server at /                 │
└─────────────────┘                  │  SQLite session DB (/data/)      │
                                     └──────────┬──────────────┬────────┘
                                          A2A   │              │  A2A
                                       delegate │              │ delegate
                                     ┌──────────▼────────┐  ┌─▼──────────────────┐
                                     │  K8s Agent         │  │  GitHub Agent       │
                                     │  port 8080         │  │  port 8080          │
                                     │  7 diagnostic tools│  │  5 GitOps tools     │
                                     │  Read-only RBAC    │  │  No cluster access  │
                                     └───────────────────┘  └────────────────────┘
```

### How a Query Flows

1. User types in the CopilotKit chat UI (or selects an existing session from the sidebar)
2. Frontend sends the message to its Next.js API route (`/api/copilotkit`) with a `thread_id`
3. The API route forwards it to the orchestrator's `/copilotkit` endpoint via AG-UI `HttpAgent`
4. Orchestrator loads conversation history from the session DB (last 5 exchanges) and prepends it as context
5. Orchestrator classifies the query using keyword matching:
   - **K8s keywords** (pod, crash, logs, deployment, etc.) → routes to K8s agent
   - **GitHub keywords** (PR, manifest, gitops, yaml, commit, etc.) → routes to GitHub agent
   - **Both present** → runs K8s agent first, then passes results to GitHub agent for context
   - **No match** → defaults to K8s agent (most oncall queries are K8s)
6. Orchestrator delegates to agents via CrewAI's A2A protocol (JSON-RPC `message/send`)
7. Each agent runs its CrewAI crew with specialized tools, returns results
8. Orchestrator persists the user message + agent response to the session DB
9. Orchestrator streams the response back as AG-UI SSE events
10. CopilotKit renders the response in the chat UI; sidebar refreshes to show updated session

### Query Routing Examples

| Query | Route | Why |
|-------|-------|-----|
| "Why is vault crashing?" | `k8s` | "crash" is a K8s keyword |
| "Show me the chores-tracker deployment.yaml" | `github` | "deployment.yaml" is a GitHub keyword |
| "Pod is crashlooping, create a PR to fix it" | `combined` | "pod"+"crashloop" (K8s) + "PR" (GitHub) |
| "Help me investigate this issue" | `k8s` | No keywords → default to K8s |

### Session Persistence

Conversations persist across browser refreshes and pod restarts via a custom session management layer. CopilotKit has no built-in persistence for AG-UI agents, so we built it ourselves.

**How it works:**

- **Backend**: `SessionManager` (SQLite + in-memory cache) stores conversations on a PersistentVolume at `/data/sessions.db`
- **Frontend**: Custom `SessionSidebar` component with `useSessionManager` hook manages session state via `useCopilotMessagesContext()` and a `ThreadContext` provider
- **Conversation memory**: On each request, the orchestrator loads the last 5 exchanges from the session and prepends them as context to the agent query, enabling follow-up questions ("show me the logs" after discussing a specific namespace)
- **Auto-title**: Sessions are titled from the first user message (truncated to 60 chars)
- **Cleanup**: Background task runs every 10 minutes, deleting sessions older than 24 hours. Max 50 sessions total.

**Session REST API** (orchestrator, protected by API key):

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/sessions` | GET | List all sessions (id, title, timestamps, message count) |
| `/sessions/{id}` | GET | Full session with message history |
| `/sessions/{id}` | DELETE | Delete a session |

**Frontend session flow:**

1. On page load, `useSessionManager` fetches session list and restores the last active session from localStorage
2. Clicking a session loads its messages into CopilotKit via `setMessages()` and updates `threadId`
3. "New Chat" generates a fresh UUID, clears messages, and starts a new thread
4. After each agent response completes (`isLoading` → false), the session list auto-refreshes
5. Sessions can be deleted via the X button on hover

## Open Source vs Custom Built

### Open Source Frameworks

| Component | Package | Version | What It Does |
|-----------|---------|---------|--------------|
| **CrewAI** | `crewai[a2a,anthropic]` | 1.6.1 | Agent framework — defines agents, tasks, crews, and flows |
| **A2A SDK** | `a2a-sdk[http-server]` | 0.3.10 | Google's Agent-to-Agent protocol — JSON-RPC communication between agents |
| **FastAPI** | `fastapi` | 0.133.0 | HTTP server for all services |
| **CopilotKit** | `@copilotkit/react-core`, `react-ui`, `runtime` | 1.51.4 | Provides the entire chat UI (`<CopilotChat>` component), context provider, and Next.js runtime. We configured it and wrote the API bridge route — the UI itself is theirs. |
| **AG-UI Protocol** | `ag-ui-protocol` (Python), `@ag-ui/client` (JS) | 0.1.13 / 0.0.45 | Agent-UI streaming protocol for CopilotKit integration |
| **Next.js** | `next` | 16.1.6 | Frontend framework for the chat UI |
| **Kubernetes Python Client** | `kubernetes` | 31.0.0 | Talks to the K8s API from the K8s agent |
| **PyGithub** | `PyGithub` | 2.5.0 | Talks to GitHub API from the GitHub agent |
| **Anthropic Claude** | via CrewAI's native provider | — | LLM powering all agent reasoning |

### Custom Built (by us)

| Component | Files | What It Does |
|-----------|-------|--------------|
| **Orchestrator Flow** | `src/orchestrator/flow.py` | CrewAI Flow with `@start`/`@router`/`@listen` for deterministic keyword-based query routing |
| **CopilotKit Endpoint** | `src/orchestrator/copilotkit_endpoint.py` | Custom AG-UI SSE endpoint with conversation context injection. Manual event generation since `ag-ui-crewai` is incompatible with crewai 1.6.1 |
| **Session Manager** | `src/orchestrator/session_manager.py` | SQLite + in-memory cache for conversation persistence. WAL mode, TTL expiration, background cleanup, auto-titling |
| **K8s Diagnostic Tools** | `src/k8s_agent/tools.py` | 7 tools: `list_namespaces`, `list_pods`, `get_pod_logs`, `get_pod_events`, `get_deployment_status`, `list_services`, `analyze_service_health` |
| **GitHub/GitOps Tools** | `src/github_agent/tools.py` | 5 tools: `search_recent_deployments`, `get_gitops_file`, `list_gitops_directory`, `create_remediation_pr`, `create_document_pr` |
| **A2A Executors** | `src/*/executor.py` | Bridges between A2A JSON-RPC protocol and CrewAI agent invocation |
| **A2A Servers** | `src/*/server.py` | FastAPI apps with A2A server mounts, agent card definitions, health checks |
| **Agent Prompts** | `src/*/prompts.py` | System prompts with domain knowledge (known issues, troubleshooting workflows, safety rules) |
| **Service Catalog** | `config/service_mapping.yaml` | Maps K8s services to GitHub repos, namespaces, criticality levels |
| **Session Sidebar** | `frontend/app/components/SessionSidebar.tsx` | Custom sidebar with session list, new chat button, delete, mobile responsive toggle |
| **Session Hook** | `frontend/app/hooks/useSessionManager.ts` | React hook managing session state, message restoration via `useCopilotMessagesContext()`, localStorage persistence |
| **Session API Client** | `frontend/app/lib/sessions.ts`, `app/api/sessions/` | TypeScript API client + Next.js proxy routes to orchestrator session endpoints |
| **Frontend Wiring** | `frontend/app/providers.tsx`, `page.tsx` | `ThreadContext` provider managing `threadId` for CopilotKit, sidebar + chat layout. The chat UI itself is CopilotKit's `<CopilotChat>` component out of the box. |
| **Deploy Script** | `deploy-to-ecr.sh` | Builds all 4 Docker images (AMD64) and pushes to ECR |
| **K8s Manifests** | `k8s/` | Deployments, services, RBAC, Vault secret store, external secrets |
| **Test Suite** | `tests/` | 99 tests covering tools, A2A protocol, routing, and E2E integration |

### Key Design Decisions

- **Keyword routing instead of LLM routing** — Fast, deterministic, zero extra API calls. No ambiguity.
- **ag-ui-protocol instead of ag-ui-crewai** — `ag-ui-crewai==0.1.5` requires `crewai ^0.130.0` which is incompatible with our `crewai==1.6.1`. We built the AG-UI SSE endpoint manually using the low-level protocol SDK.
- **A2A protocol for agent communication** — Each agent is independently deployable and discoverable via `/.well-known/agent.json`. The orchestrator delegates without needing local tool knowledge.
- **Read-only RBAC for K8s agent** — Only `get`, `list`, `watch` permissions on pods, deployments, services, events, namespaces. Cannot modify anything.
- **Path-validated PR creation** — All GitHub changes must be under `base-apps/`. Patch-based updates require exact string matching. No auto-merge — all PRs require human review.
- **Backend session persistence instead of localStorage** — SQLite on a PersistentVolume survives pod restarts and works across devices. Reuses the proven SessionManager pattern from oncall-agent-api.
- **Conversation context injection** — Last 5 exchanges prepended to agent queries. Assistant responses truncated to 500 chars to keep context manageable. Classification still uses raw user message to avoid keyword confusion.

## Tools Reference

### K8s Agent — 7 Tools

| Tool | Arguments | Description |
|------|-----------|-------------|
| `list_namespaces` | `pattern?` | List cluster namespaces, optional regex filter |
| `list_pods` | `namespace`, `label_selector?` | Pods with status, readiness, restarts, container states |
| `get_pod_logs` | `namespace`, `pod_name`, `container?`, `tail_lines?` | Container logs (default 100 lines) |
| `get_pod_events` | `namespace`, `pod_name?` | Events sorted by most recent first |
| `get_deployment_status` | `namespace`, `deployment_name?` | Replica counts, conditions, rollout health |
| `list_services` | `namespace?`, `service_name?`, `check_label?` | Services with selectors, ports, label detection |
| `analyze_service_health` | `service_name`, `namespace` | Composite: pods + deployments + events + health score |

### GitHub Agent — 5 Tools

| Tool | Arguments | Description |
|------|-----------|-------------|
| `search_recent_deployments` | `repo_name`, `hours_back?`, `workflow_name?` | GitHub Actions workflow runs |
| `get_gitops_file` | `file_path` | Read file from GitOps repo (must be under `base-apps/`) |
| `list_gitops_directory` | `dir_path?` | Directory listing in GitOps repo |
| `create_remediation_pr` | `service`, `action_summary`, `changes_json`, `incident_context?` | Create PR with manifest patches (requires explicit user approval) |
| `create_document_pr` | `filename`, `content`, `description` | Create PR to add docs to the docs repo |

## Security Model

```
Orchestrator (no cluster access)
    │
    ├── K8s Agent: ClusterRole "k8s-diagnostics-read"
    │   └── Verbs: get, list, watch
    │   └── Resources: pods, pods/log, deployments, services, events, namespaces
    │
    └── GitHub Agent (no cluster access)
        └── GitHub PAT with repo + workflow scope
        └── All PRs scoped to base-apps/ directory
        └── Patch validation: old_string must be unique, must match exactly
        └── No auto-merge — human review required
```

- **API Authentication**: Optional `X-API-Key` header or `Bearer` token. Configurable via `API_KEYS` env var (comma-separated).
- **Secrets**: Managed via Vault + External Secrets Operator. Secrets synced to K8s secrets at 15-second intervals.
- **Ingress**: IP-whitelisted nginx ingress with TLS (cert-manager + Let's Encrypt).

## Environment Variables

| Variable | Required | Default | Used By |
|----------|----------|---------|---------|
| `ANTHROPIC_API_KEY` | Yes | — | All agents |
| `ANTHROPIC_MODEL` | No | `claude-haiku-4-5-20251001` | All agents |
| `API_KEYS` | No | — (no auth) | Orchestrator |
| `GITHUB_TOKEN` | Yes* | — | GitHub agent |
| `GITHUB_ORG` | No | `arigsela` | GitHub agent |
| `GITOPS_REPO` | No | `arigsela/kubernetes` | GitHub agent |
| `GITOPS_BASE_PATH` | No | `base-apps/` | GitHub agent |
| `GITOPS_BASE_BRANCH` | No | `main` | GitHub agent |
| `DOCS_REPO` | No | `arigsela/claude-agents` | GitHub agent |
| `K8S_AGENT_URL` | No | `http://k8s-agent-a2a:8080` | Orchestrator |
| `GITHUB_AGENT_URL` | No | `http://github-agent-a2a:8080` | Orchestrator |
| `CORS_ORIGINS` | No | `*` | Orchestrator |
| `AGENT_LOG_LEVEL` | No | `INFO` | All |
| `SESSION_DB_PATH` | No | `/data/sessions.db` | Orchestrator |
| `SESSION_TTL_HOURS` | No | `24` | Orchestrator |
| `ORCHESTRATOR_URL` | No | `http://localhost:8000` | Frontend |
| `ORCHESTRATOR_API_KEY` | No | — | Frontend |

*Required only for the GitHub agent.

## Development

### Prerequisites

- Python 3.11+
- Node.js 20+ (for frontend)
- Docker (for container builds)
- `kubectl` with cluster access (for K8s agent local testing)

### Local Development

```bash
# Python backend
python -m venv venv && source venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # fill in your keys

# Run tests (99 tests, no real cluster/API needed)
pytest tests/ -v

# Frontend
cd frontend && npm install && npm run dev
```

### Docker Compose (all 4 services)

```bash
cp .env.example .env   # fill in your keys
docker compose up -d

# Verify
curl http://localhost:8000/health   # orchestrator
curl http://localhost:8081/health   # k8s agent
curl http://localhost:8082/health   # github agent
open http://localhost:3000          # frontend
```

### Build and Deploy to ECR

```bash
# Build all services
./deploy-to-ecr.sh v1.1.0

# Build a specific service
./deploy-to-ecr.sh v1.1.0 orchestrator
./deploy-to-ecr.sh v1.1.0 k8s-agent
./deploy-to-ecr.sh v1.1.0 github-agent
./deploy-to-ecr.sh v1.1.0 frontend
```

After pushing, ArgoCD auto-syncs from the `arigsela/kubernetes` repo. Pods will pull the new `:latest` image on next rollout.

### Testing

```bash
pytest tests/ -v                           # All 99 tests

# By component
pytest tests/test_k8s_tools.py -v          # 19 K8s tool unit tests
pytest tests/test_k8s_agent_a2a.py -v      # 9 K8s A2A protocol tests
pytest tests/test_github_tools.py -v       # 26 GitHub tool unit tests
pytest tests/test_github_agent_a2a.py -v   # 9 GitHub A2A protocol tests
pytest tests/test_orchestrator_routing.py -v  # 18 routing + auth tests
pytest tests/test_e2e.py -v                # 18 end-to-end integration tests
```

## Project Structure

```
oncall-crewai/
├── src/
│   ├── shared/                  # Shared config and logging
│   │   ├── config.py            #   Environment variables, service catalog loader
│   │   └── logging_config.py    #   Structured logging setup
│   ├── orchestrator/            # Query router service
│   │   ├── main.py              #   FastAPI app, /query, /copilotkit, /sessions, A2A mount
│   │   ├── flow.py              #   CrewAI Flow with @start/@router/@listen
│   │   ├── agents.py            #   A2A delegate agent definitions
│   │   ├── prompts.py           #   Keywords and system prompts
│   │   ├── session_manager.py   #   SQLite session persistence + in-memory cache
│   │   └── copilotkit_endpoint.py  # AG-UI SSE streaming with conversation context
│   ├── k8s_agent/               # Kubernetes diagnostics agent
│   │   ├── server.py            #   A2A FastAPI server with agent card
│   │   ├── agent.py             #   CrewAI agent with 7 K8s tools
│   │   ├── executor.py          #   A2A → CrewAI bridge
│   │   ├── prompts.py           #   K8s domain knowledge + known issues
│   │   └── tools.py             #   7 diagnostic tools (read-only)
│   └── github_agent/            # GitHub/GitOps agent
│       ├── server.py            #   A2A FastAPI server with agent card
│       ├── agent.py             #   CrewAI agent with 5 GitOps tools
│       ├── executor.py          #   A2A → CrewAI bridge
│       ├── prompts.py           #   GitOps workflow + safety rules
│       └── tools.py             #   5 GitHub tools (PR creation, file ops)
├── frontend/                    # CopilotKit chat UI (Next.js)
│   ├── app/
│   │   ├── api/
│   │   │   ├── copilotkit/route.ts  # HttpAgent bridge to orchestrator
│   │   │   └── sessions/        #   Proxy routes to orchestrator session API
│   │   │       ├── route.ts     #     GET /api/sessions
│   │   │       └── [id]/route.ts #    GET/DELETE /api/sessions/:id
│   │   ├── components/
│   │   │   └── SessionSidebar.tsx #  Session list sidebar with new/delete/switch
│   │   ├── hooks/
│   │   │   └── useSessionManager.ts # Session state management hook
│   │   ├── lib/
│   │   │   └── sessions.ts      #   TypeScript API client for sessions
│   │   ├── layout.tsx           #   Root layout with Providers wrapper
│   │   ├── page.tsx             #   Sidebar + chat layout
│   │   └── providers.tsx        #   CopilotKit + ThreadContext provider
│   ├── package.json
│   └── next.config.ts           #   Standalone output for Docker
├── config/
│   └── service_mapping.yaml     # Service → repo/namespace/criticality mapping
├── docker/
│   ├── Dockerfile.orchestrator  # Python 3.11-slim, port 8000
│   ├── Dockerfile.k8s-agent     # Python 3.11-slim, port 8080
│   ├── Dockerfile.github-agent  # Python 3.11-slim, port 8080
│   └── Dockerfile.frontend      # Node 20-alpine, multi-stage, port 3000
├── k8s/
│   ├── namespace.yaml           # oncall-crewai namespace
│   ├── secret-store.yaml        # Vault SecretStore for external-secrets
│   ├── external-secret.yaml     # Syncs secrets from Vault → K8s
│   ├── orchestrator/            # Deployment + Service + ConfigMap + PVC
│   ├── k8s-agent/               # Deployment + Service + RBAC (ClusterRole)
│   ├── github-agent/            # Deployment + Service + ConfigMap
│   └── frontend/                # Deployment + Service + ConfigMap
├── tests/                       # 99 tests (unit, A2A, routing, E2E)
├── docker-compose.yml           # Local 4-service development
├── deploy-to-ecr.sh             # Build + push all images to ECR
├── pyproject.toml               # Python dependencies and tool config
├── requirements.txt             # ag-ui-protocol pinned dependency
└── .env.example                 # Environment variable template
```

## GitOps Deployment Files

The production K8s manifests live in the `arigsela/kubernetes` repo under `base-apps/oncall-crewai/`:

| File | What It Deploys |
|------|-----------------|
| `orchestrator-deployment.yaml` | Orchestrator Deployment + Service (with /data volume mount) |
| `orchestrator-configmap.yaml` | Agent URLs, CORS, log level, session DB path + TTL |
| `orchestrator-pvc.yaml` | 1Gi PersistentVolumeClaim for session SQLite database |
| `k8s-agent-deployment.yaml` | K8s Agent Deployment + Service + RBAC |
| `github-agent-deployment.yaml` | GitHub Agent Deployment + Service |
| `github-agent-configmap.yaml` | GitHub org, repos, base paths |
| `frontend-deployment.yaml` | Frontend Deployment + Service |
| `frontend-configmap.yaml` | Orchestrator URL for frontend |
| `frontend-ingress.yaml` | Nginx ingress at `oncall-crewai.arigsela.com` (IP-whitelisted, TLS) |
| `external-secret.yaml` | Vault → K8s secret sync |
| `secret-store.yaml` | Vault connection config |
| `oncall-crewai.yaml` | ArgoCD Application (master app entry) |
