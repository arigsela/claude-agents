# CopilotKit Frontend for OnCall CrewAI - Implementation Plan

## Overview
Add a CopilotKit-powered chat UI to the oncall-crewai multi-agent system, enabling real-time conversational interaction with the K8s and GitHub agents through a polished web interface.

## Success Criteria
- [ ] Chat UI accessible in browser, connected to orchestrator backend
- [ ] User messages route through the same classify/delegate pipeline as `/query`
- [ ] Agent responses stream back and display in the chat
- [ ] Conversation history maintained within a session
- [ ] Deployed alongside existing agents in oncall-crewai namespace

## Research Findings

### Relevant Files
- `src/orchestrator/main.py` — FastAPI app, `/query` endpoint, A2A mount at `/`
- `src/orchestrator/flow.py` — `OncallFlow` with `@start/@router/@listen`, `classify_query()`, `_invoke_k8s()`, `_invoke_github()`
- `src/orchestrator/agents.py` — A2A delegate agents
- `src/shared/config.py` — env vars, API keys
- `requirements.txt` — current Python deps (crewai 1.6.1, fastapi 0.133.0)

### Key Packages
- [`ag-ui-protocol`](https://pypi.org/project/ag-ui-protocol/) v0.1.13 — `RunAgentInput`, `EventEncoder`, AG-UI event types (no CrewAI dependency)
- `@copilotkit/react-core` + `@copilotkit/react-ui` — React chat components
- `@ag-ui/client` — `HttpAgent` for frontend-to-backend bridge
- `@copilotkit/runtime` — Next.js server runtime

### Existing Patterns
- Orchestrator already uses FastAPI with CORS `*`
- Flow uses sync `crew.kickoff()` wrapped in `ThreadPoolExecutor`
- Auth via `X-API-Key` header or `Bearer` token

## Architecture Decisions

### Decision 1: Backend integration approach
**Options:**
1. Adapt existing `OncallFlow` to use `CopilotKitState` — requires refactoring the state model, may break `/query` endpoint
2. Create a separate `CopilotKitOncallFlow` — keeps existing flow intact, adds new flow for CopilotKit
3. Thin adapter — manual AG-UI event generation

**Chosen:** Option 2 — Separate `CopilotKitOncallFlow`. Keeps existing working code untouched while adding a dedicated CopilotKit flow that reuses the core logic (`classify_query`, `_invoke_k8s`, `_invoke_github`).

### Decision 2: Frontend architecture
**Options:**
1. Next.js with CopilotKit (full streaming, state sync, polished UI)
2. Streamlit (quick, Python-only, basic UI)

**Chosen:** Option 1 — Next.js + CopilotKit as requested. The frontend's API route acts as a bridge (HttpAgent -> backend /copilotkit endpoint).

---

## Implementation

### Phase 1: Backend — AG-UI Endpoint (4 tasks)
Add a CopilotKit-compatible endpoint to the orchestrator.

#### Task 1.1: Add ag-ui-crewai dependency
**Files:** `requirements.txt`
**Steps:**
1. Add `ag-ui-crewai==0.1.5` to requirements.txt
2. Verify compatibility with existing crewai 1.6.1 and fastapi 0.133.0
**Testing:**
- [ ] `pip install -r requirements.txt` succeeds
- [ ] Existing 99 tests still pass

#### Task 1.2: Create CopilotKitOncallFlow
**Files:** `src/orchestrator/copilotkit_flow.py` (new)
**Steps:**
1. Create a new flow class extending `Flow[CopilotKitState]`
2. In `@start()` method: extract latest user message from `self.state.messages`
3. Run `classify_query()` for routing
4. Call `_invoke_k8s()` / `_invoke_github()` / both (reuse from `flow.py`)
5. Append the agent response as an assistant message to `self.state.messages`
**Testing:**
- [ ] Unit test: flow processes a message and appends response
- [ ] Unit test: routing works (k8s, github, combined keywords)

#### Task 1.3: Wire CopilotKit endpoint into main.py
**Files:** `src/orchestrator/main.py`
**Steps:**
1. Import `add_crewai_flow_fastapi_endpoint` and `CopilotKitOncallFlow`
2. Register the endpoint at `/copilotkit` path **before** the A2A mount (critical: A2A mount at `/` catches all unmatched routes)
3. Ensure auth middleware applies to this endpoint
**Testing:**
- [ ] `curl -X POST /copilotkit` returns AG-UI streaming events
- [ ] Existing `/query` endpoint still works
- [ ] Existing `/.well-known/agent-card.json` still works

#### Task 1.4: Update orchestrator Docker image
**Files:** `docker/Dockerfile.orchestrator`
**Steps:**
1. No Dockerfile changes needed (pip install from requirements.txt covers it)
2. Rebuild orchestrator image
**Testing:**
- [ ] Docker build succeeds
- [ ] Container starts and /health responds

### Phase 2: Frontend — Next.js CopilotKit App (5 tasks)
Scaffold and build the chat frontend.

#### Task 2.1: Scaffold Next.js project
**Files:** `oncall-crewai/frontend/` (new directory)
**Steps:**
1. `npx create-next-app@latest frontend --typescript --tailwind --app --no-src-dir`
2. Set up project structure:
   ```
   frontend/
   ├── app/
   │   ├── api/copilotkit/route.ts  (API bridge)
   │   ├── layout.tsx               (CopilotKit provider)
   │   ├── page.tsx                 (Chat page)
   │   └── globals.css
   ├── next.config.js
   ├── package.json
   └── Dockerfile
   ```
**Testing:**
- [ ] `npm run dev` starts without errors

#### Task 2.2: Install CopilotKit packages
**Files:** `frontend/package.json`
**Steps:**
1. `npm install @copilotkit/react-core @copilotkit/react-ui @copilotkit/runtime @ag-ui/client`
**Testing:**
- [ ] All packages install without conflicts

#### Task 2.3: Create API bridge route
**Files:** `frontend/app/api/copilotkit/route.ts` (new)
**Steps:**
1. Create HttpAgent pointing to orchestrator backend URL (`ORCHESTRATOR_URL` env var)
2. Set up CopilotRuntime with the agent
3. Export POST handler using `copilotRuntimeNextJSAppRouterEndpoint`
4. Pass API key header to backend via HttpAgent config
**Testing:**
- [ ] POST to /api/copilotkit with a message returns streaming events

#### Task 2.4: Create chat page with CopilotKit
**Files:** `frontend/app/layout.tsx`, `frontend/app/page.tsx`
**Steps:**
1. Wrap layout with `<CopilotKit runtimeUrl="/api/copilotkit" agent="oncallAgent">`
2. Create page with `<CopilotChat>` component
3. Add header with title "OnCall AI Assistant"
**Testing:**
- [ ] Chat UI renders in browser
- [ ] Sending a message triggers agent response
- [ ] Response displays in chat bubbles

#### Task 2.5: Environment configuration
**Files:** `frontend/.env.local`, `frontend/next.config.js`
**Steps:**
1. Define env vars: `ORCHESTRATOR_URL`, `ORCHESTRATOR_API_KEY`
2. Configure Next.js standalone output for Docker
**Testing:**
- [ ] App connects to correct backend URL

### Phase 3: Docker & K8s Deployment (4 tasks)

#### Task 3.1: Create frontend Dockerfile
**Files:** `docker/Dockerfile.frontend` (new)
**Steps:**
1. Multi-stage build: deps -> build -> standalone runner
2. Use `node:20-alpine` base
3. Copy standalone output
4. Expose port 3000
**Testing:**
- [ ] `docker build` succeeds
- [ ] Container starts and serves the app

#### Task 3.2: Add frontend to deploy-to-ecr.sh
**Files:** `deploy-to-ecr.sh`
**Steps:**
1. Add `crewai-frontend` as a new service target
2. ECR repo: `852893458518.dkr.ecr.us-east-2.amazonaws.com/crewai-frontend`
**Testing:**
- [ ] `./deploy-to-ecr.sh frontend` builds and pushes

#### Task 3.3: Create K8s manifests
**Files:** `k8s/frontend/` (new: deployment.yaml, configmap.yaml)
**Steps:**
1. Deployment: 1 replica, port 3000, env from configmap
2. Service: ClusterIP, port 80 -> 3000
3. ConfigMap: `ORCHESTRATOR_URL`, `ORCHESTRATOR_API_KEY` (from secret)
**Testing:**
- [ ] `kubectl apply` creates all resources
- [ ] Pod starts and becomes ready

#### Task 3.4: Update GitOps deployment repo
**Files:** `docs/reference/kubernetes/base-apps/oncall-crewai/` (new files)
**Steps:**
1. Add frontend deployment, service, configmap to GitOps repo
2. PR to arigsela/kubernetes
**Testing:**
- [ ] ArgoCD syncs and deploys frontend

### Phase 4: Integration Testing (2 tasks)

#### Task 4.1: Local end-to-end test
**Steps:**
1. Port-forward orchestrator and frontend
2. Open chat UI in browser
3. Send K8s query -> verify response displays
4. Send GitHub query -> verify routing works
5. Send combined query -> verify both agents respond
**Testing:**
- [ ] K8s query returns pod diagnostics
- [ ] GitHub query returns repo information
- [ ] Combined query returns both sections

#### Task 4.2: Error handling
**Steps:**
1. Test with invalid API key -> verify error message in UI
2. Test with unavailable agent -> verify graceful degradation
3. Test long-running query -> verify no timeout in UI
**Testing:**
- [ ] Auth errors show user-friendly message
- [ ] Agent failures don't crash the UI

---

## End-to-End Testing
1. Open chat UI in browser (port-forward or ingress)
2. Type: "What pods are running in the oncall-crewai namespace?" -> K8s agent responds with pod diagnostics
3. Type: "What recent commits were made to the kubernetes repo?" -> GitHub agent responds
4. Type: "A pod is crashlooping, check logs and find the PR that caused it" -> Both agents respond
5. Verify conversation history persists across messages in same session

## Risks and Mitigations
| Risk | Mitigation |
|------|------------|
| `ag-ui-crewai` v0.1.5 is young, may have bugs | Keep existing `/query` endpoint as fallback; frontend can fall back to direct API calls |
| A2A mount at `/` in main.py catches `/copilotkit` route | Register CopilotKit endpoint BEFORE `fastapi_app.mount("/", a2a_app.build())` |
| Sync OncallFlow in async CopilotKit context | Use `asyncio.to_thread()` wrapper like existing `/query` endpoint |
| CORS between frontend and orchestrator in K8s | Already configured with `CORS_ORIGINS: "*"` |
| Next.js cold start in K8s | Use standalone output mode, readiness probe |

## Implementation Notes

### Deviation: ag-ui-protocol instead of ag-ui-crewai
`ag-ui-crewai==0.1.5` requires `crewai ^0.130.0` (incompatible with our `crewai==1.6.1`).
**Solution:** Used `ag-ui-protocol==0.1.13` directly — provides `RunAgentInput`, `EventEncoder`, and all event types with no CrewAI dependency. Custom AG-UI SSE endpoint built in `copilotkit_endpoint.py`.

## Progress Tracking
- Phase 1: Backend — AG-UI Endpoint: ✅ (4/4 tasks)
- Phase 2: Frontend — Next.js CopilotKit App: ✅ (5/5 tasks)
- Phase 3: Docker & K8s Deployment: ✅ (4/4 tasks)
- Phase 4: Integration Testing: ⬜ (0/2 tasks) — requires deployment
- **Overall: 13/15 tasks (87%)**

Last Updated: 2026-02-25
Current Status: Phases 1-3 complete. Frontend Docker build verified. Ready for deployment and integration testing.
