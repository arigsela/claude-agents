# CopilotKit Session Persistence & Sidebar — Implementation Plan

## Overview

Add conversation persistence and a session sidebar to the oncall-crewai CopilotKit frontend, enabling users to view past investigations, switch between sessions, and resume conversations across page reloads.

## Success Criteria

- [ ] Conversations persist across browser refreshes
- [ ] Sidebar displays list of past sessions with titles and timestamps
- [ ] Clicking a session loads its full message history into the chat
- [ ] "New Chat" button creates a fresh session
- [ ] Sessions can be deleted from the sidebar
- [ ] Sessions auto-expire after 24 hours of inactivity
- [ ] Data survives pod restarts (SQLite on PersistentVolume)

## Research Findings

### CopilotKit Capabilities
- `threadId` prop on `<CopilotKit>` provider identifies a conversation thread
- `useCopilotMessagesContext()` exposes `messages` and `setMessages()` for state manipulation
- `useCopilotChat()` provides `messages` read access
- **No built-in**: persistence, session list UI, or storage adapters
- [PR #2328](https://github.com/CopilotKit/CopilotKit/pull/2328) (thread support for AG-UI) was closed without merging

### Existing Pattern: oncall-agent-api SessionManager
- `oncall-agent-api/src/api/session_manager.py` — production-tested, SQLite + in-memory cache
- Schema: `session_id`, `user_id`, `created_at`, `last_accessed`, `metadata`, `conversation_history`
- Features: TTL expiration, background cleanup, max sessions per user, WAL mode
- **Can be adapted** with minimal changes for the orchestrator

### Current State
- `copilotkit_endpoint.py` already extracts `thread_id` from `RunAgentInput` but discards it
- Frontend has no session management — messages lost on refresh
- Orchestrator is stateless — no database, no persistent storage

## Architecture Decisions

### Decision 1: Where does persistence live?
**Options:**
1. Frontend-only (localStorage) — simple but lost across devices/browsers
2. Backend SQLite — durable, proven pattern exists in oncall-agent-api
3. Hybrid (backend + localStorage cache) — complex, sync issues

**Chosen:** Option 2 — Backend SQLite. Reuses the proven oncall-agent-api pattern. Durable across devices. Single source of truth. This is a personal homelab tool behind IP whitelist so SQLite single-writer is fine.

### Decision 2: How do sessions get created?
**Options:**
1. Explicit — user clicks "New Chat", frontend POSTs to create session
2. Implicit — backend auto-creates session on first message if thread_id is new
3. Hybrid — auto-create on first message, explicit "New Chat" resets the UI

**Chosen:** Option 3 — Hybrid. Backend auto-creates sessions when a new thread_id arrives. Frontend "New Chat" generates a fresh UUID and clears the chat. No explicit create endpoint needed.

### Decision 3: User identity
**Options:**
1. Auth system (JWT, OAuth) — overkill for IP-whitelisted homelab
2. Browser UUID in localStorage — simple, per-browser identity
3. Single default user — simplest possible

**Chosen:** Option 3 — Single default user (`"default"`). The app is behind IP-restricted ingress. No auth needed. Keeps the implementation minimal.

### Decision 4: Message storage format
**Options:**
1. Store raw AG-UI messages (complex nested objects with content parts)
2. Store simplified `{role, content, timestamp}` format

**Chosen:** Option 2 — Simplified format. Store `{role: "user"|"assistant", content: string, timestamp: ISO}`. This is what we need to restore into CopilotKit via `setMessages()` and avoids dealing with AG-UI's complex message schema.

---

## Implementation

### Phase 1: Backend Session Manager (4 tasks)

Adapt the proven SessionManager from oncall-agent-api for the orchestrator.

#### Task 1.1: Create session_manager.py
**Files:** `src/orchestrator/session_manager.py` (new)
**Steps:**
1. Copy `SessionManager` class pattern from `oncall-agent-api/src/api/session_manager.py`
2. Simplify: remove `user_id` tracking (single user), remove `max_sessions_per_user`
3. Add `title` field to Session (first 60 chars of first user message)
4. Change TTL from 30 minutes to 24 hours
5. Max total sessions: 50 (auto-delete oldest when exceeded)
6. SQLite path: configurable via `SESSION_DB_PATH` env var (default: `/data/sessions.db`)
**Testing:**
- [ ] Unit test: create session, retrieve it, verify fields
- [ ] Unit test: update session with messages, verify persistence
- [ ] Unit test: TTL expiration removes old sessions
- [ ] Unit test: max sessions limit deletes oldest

#### Task 1.2: Define Session schema
**Files:** `src/orchestrator/session_manager.py`
**Steps:**
1. SQLite table:
   ```sql
   CREATE TABLE sessions (
       session_id TEXT PRIMARY KEY,
       title TEXT DEFAULT 'New Chat',
       created_at TEXT NOT NULL,
       last_accessed TEXT NOT NULL,
       messages TEXT DEFAULT '[]'
   );
   CREATE INDEX idx_sessions_last_accessed ON sessions(last_accessed);
   ```
2. Message format in JSON array:
   ```json
   [
     {"role": "user", "content": "Why is vault crashing?", "timestamp": "2026-02-25T12:00:00Z"},
     {"role": "assistant", "content": "Vault is in CrashLoopBackOff...", "timestamp": "2026-02-25T12:00:15Z"}
   ]
   ```
**Testing:**
- [ ] DB creates table on init
- [ ] Messages serialize/deserialize correctly

#### Task 1.3: Implement CRUD operations
**Files:** `src/orchestrator/session_manager.py`
**Steps:**
1. `get_or_create_session(session_id) -> Session` — loads from DB or creates new
2. `append_messages(session_id, user_msg, assistant_msg)` — adds exchange, updates title if first message
3. `list_sessions() -> List[SessionSummary]` — returns id, title, created_at, last_accessed, message_count (sorted by last_accessed desc)
4. `get_session(session_id) -> Session | None` — full session with messages
5. `delete_session(session_id) -> bool`
**Testing:**
- [ ] CRUD operations work end-to-end
- [ ] list_sessions returns correct ordering
- [ ] Title auto-set from first user message

#### Task 1.4: Background cleanup task
**Files:** `src/orchestrator/session_manager.py`
**Steps:**
1. `async cleanup_expired_sessions()` — deletes sessions older than TTL
2. `start_cleanup_task()` / `stop_cleanup_task()` — background asyncio loop (every 10 min)
3. Wire into FastAPI lifespan in main.py
**Testing:**
- [ ] Expired sessions are cleaned up
- [ ] Cleanup task starts/stops cleanly

### Phase 2: Backend REST Endpoints (3 tasks)

Add session management endpoints to the orchestrator.

#### Task 2.1: GET /sessions endpoint
**Files:** `src/orchestrator/main.py`
**Steps:**
1. Add `GET /sessions` endpoint (protected by API key auth)
2. Returns list of `{session_id, title, created_at, last_accessed, message_count}`
3. Sorted by `last_accessed` descending (most recent first)
**Testing:**
- [ ] Returns empty list when no sessions
- [ ] Returns sessions in correct order
- [ ] Auth required

#### Task 2.2: GET /sessions/{session_id} endpoint
**Files:** `src/orchestrator/main.py`
**Steps:**
1. Add `GET /sessions/{session_id}` endpoint
2. Returns full session including messages array
3. Returns 404 if session not found
**Testing:**
- [ ] Returns session with messages
- [ ] 404 for non-existent session

#### Task 2.3: DELETE /sessions/{session_id} endpoint
**Files:** `src/orchestrator/main.py`
**Steps:**
1. Add `DELETE /sessions/{session_id}` endpoint
2. Returns 204 on success, 404 if not found
**Testing:**
- [ ] Session deleted from DB
- [ ] 404 for non-existent session

### Phase 3: Wire Persistence into CopilotKit Endpoint (2 tasks)

Automatically save conversations as they happen.

#### Task 3.1: Initialize SessionManager in app startup
**Files:** `src/orchestrator/main.py`
**Steps:**
1. Create `SessionManager` instance in FastAPI lifespan
2. Store as `app.state.session_manager`
3. Start cleanup task on startup, stop on shutdown
4. Add `SESSION_DB_PATH` to shared config
**Testing:**
- [ ] SessionManager initializes on app start
- [ ] Cleanup task runs in background

#### Task 3.2: Save exchanges in copilotkit_endpoint
**Files:** `src/orchestrator/copilotkit_endpoint.py`
**Steps:**
1. After flow completes and result is ready, save to session:
   ```python
   session_mgr = request.app.state.session_manager
   session_mgr.append_messages(
       session_id=thread_id,
       user_msg=user_message,
       assistant_msg=result_text,
   )
   ```
2. This auto-creates the session if thread_id is new
3. Title auto-set from first user message
**Testing:**
- [ ] First message creates session with title
- [ ] Subsequent messages append to session
- [ ] Session accessible via GET /sessions/{thread_id}

### Phase 4: Frontend Session Sidebar (3 tasks)

Build a custom sidebar component for session management.

#### Task 4.1: Create sessions API client
**Files:** `frontend/app/lib/sessions.ts` (new)
**Steps:**
1. Type definitions: `SessionSummary`, `SessionDetail`
2. `fetchSessions(): Promise<SessionSummary[]>` — GET /sessions (via /api proxy)
3. `fetchSession(id: string): Promise<SessionDetail>` — GET /sessions/{id}
4. `deleteSession(id: string): Promise<void>` — DELETE /sessions/{id}
5. All requests go through Next.js API route to avoid CORS (or direct if same-origin)
**Testing:**
- [ ] API client fetches/parses sessions correctly

#### Task 4.2: Create Next.js API proxy routes
**Files:** `frontend/app/api/sessions/route.ts` (new), `frontend/app/api/sessions/[id]/route.ts` (new)
**Steps:**
1. `GET /api/sessions` → proxy to orchestrator `GET /sessions` with API key header
2. `GET /api/sessions/[id]` → proxy to orchestrator `GET /sessions/{id}`
3. `DELETE /api/sessions/[id]` → proxy to orchestrator `DELETE /sessions/{id}`
**Testing:**
- [ ] Proxy routes forward correctly with auth

#### Task 4.3: Build SessionSidebar component
**Files:** `frontend/app/components/SessionSidebar.tsx` (new)
**Steps:**
1. Left sidebar panel (w-64, full height, dark theme)
2. "New Chat" button at top (generates new UUID, clears chat)
3. Session list: each item shows title, relative timestamp ("2h ago")
4. Active session highlighted
5. Delete button (X icon) on hover per session
6. Auto-refresh session list after new messages
7. Collapsible toggle for mobile (hamburger icon)
**Testing:**
- [ ] Renders session list
- [ ] New Chat creates fresh session
- [ ] Delete removes session from list
- [ ] Active session is highlighted

### Phase 5: Frontend Session Integration (3 tasks)

Wire the sidebar into CopilotKit's state management.

#### Task 5.1: Session state management hook
**Files:** `frontend/app/hooks/useSessionManager.ts` (new)
**Steps:**
1. Custom hook managing:
   - `sessions: SessionSummary[]` — loaded from backend
   - `activeSessionId: string | null` — current session
   - `loadSessions()` — refresh session list
   - `switchSession(id)` — fetch messages, set in CopilotKit, update activeSessionId
   - `newChat()` — generate UUID, clear messages, set activeSessionId
   - `deleteSession(id)` — delete from backend, switch to next session or new chat
2. Use `useCopilotMessagesContext()` for `setMessages()`
3. Store `activeSessionId` in localStorage for persistence across refreshes
**Testing:**
- [ ] Session switch loads messages into chat
- [ ] New chat clears messages and creates fresh ID
- [ ] Active session persists in localStorage

#### Task 5.2: Update providers with threadId
**Files:** `frontend/app/providers.tsx` (modify)
**Steps:**
1. Accept `threadId` prop (or manage internally)
2. Pass `threadId` to CopilotKit provider (maps to AG-UI thread_id)
3. When threadId changes, CopilotKit uses it for subsequent requests
**Testing:**
- [ ] threadId passed correctly to backend in AG-UI requests

#### Task 5.3: Update page layout with sidebar
**Files:** `frontend/app/page.tsx` (modify)
**Steps:**
1. Restructure layout: sidebar (left) + chat (right)
2. Pass session state from hook to SessionSidebar
3. Pass session callbacks (switch, new, delete) to sidebar
4. Responsive: sidebar hidden by default on mobile, toggle button in header
**Testing:**
- [ ] Full layout renders correctly
- [ ] Session switch updates chat
- [ ] Mobile responsive behavior works

### Phase 6: Storage & Deployment (2 tasks)

#### Task 6.1: Add PersistentVolumeClaim for orchestrator
**Files:** `k8s/orchestrator/deployment.yaml` (modify), `docs/reference/kubernetes/base-apps/oncall-crewai/orchestrator-deployment.yaml` (modify)
**Steps:**
1. Add PVC: `crewai-orchestrator-data` (1Gi, ReadWriteOnce)
2. Mount at `/data` in orchestrator container
3. Set `SESSION_DB_PATH=/data/sessions.db` in ConfigMap
**Testing:**
- [ ] Pod starts with volume mounted
- [ ] Sessions persist across pod restarts

#### Task 6.2: Update ConfigMaps
**Files:** `k8s/orchestrator/configmap.yaml` (modify), `docs/reference/kubernetes/base-apps/oncall-crewai/orchestrator-configmap.yaml` (modify)
**Steps:**
1. Add `SESSION_DB_PATH: "/data/sessions.db"`
2. Add `SESSION_TTL_HOURS: "24"`
**Testing:**
- [ ] ConfigMap applied, env vars available in pod

---

## End-to-End Testing

1. Open `oncall-crewai.arigsela.com` in browser
2. Sidebar shows empty state ("No conversations yet")
3. Type "What pods are running in oncall-crewai?" → agent responds
4. Sidebar now shows session with title "What pods are running in oncall-crewai?"
5. Click "New Chat" → chat clears, new session
6. Type "Show me the kubernetes repo structure" → agent responds
7. Sidebar shows 2 sessions
8. Click first session → chat loads previous K8s conversation
9. Refresh browser → sidebar still shows 2 sessions, last active session loaded
10. Delete a session → removed from sidebar
11. Restart orchestrator pod → sessions still present (PVC)

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| `setMessages()` may not perfectly restore CopilotKit state | Store simplified `{role, content}` format that maps cleanly to CopilotKit Message type |
| SQLite single-writer limits concurrency | Fine for single-user homelab. WAL mode allows concurrent reads. |
| Session data grows unbounded | TTL cleanup (24h) + max sessions cap (50) + background cleanup task |
| Message format mismatch between CopilotKit and storage | Define clear serialization/deserialization in sessions API client |
| PVC not available on first deploy | Create PVC manifest before deployment. Fallback: in-memory only if DB path not writable |

## Progress Tracking

- Phase 1: Backend Session Manager: ✅ (4/4 tasks)
- Phase 2: Backend REST Endpoints: ✅ (3/3 tasks)
- Phase 3: Wire into CopilotKit Endpoint: ✅ (2/2 tasks)
- Phase 4: Frontend Session Sidebar: ✅ (3/3 tasks)
- Phase 5: Frontend Session Integration: ✅ (3/3 tasks)
- Phase 6: Storage & Deployment: ✅ (2/2 tasks)
- **Overall: 17/17 tasks (100%)**

Last Updated: 2026-02-25
Current Status: Implementation complete. Ready for image builds and deployment.
