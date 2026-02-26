# Frontend User Authentication - Implementation Plan

## Overview
Add password-based user authentication to the oncall-crewai system, enabling per-user session isolation. Users log in with username/password, receive a JWT token, and all sessions are scoped to their user account.

## Success Criteria
- [x] Users can register and log in with username/password
- [x] JWT tokens authenticate all API requests
- [x] Sessions are scoped per user (users only see their own sessions)
- [x] Existing API_KEY auth continues working for service-to-service calls
- [x] Frontend shows login page for unauthenticated users
- [x] Frontend displays logged-in username and logout button

## Architecture Decisions

### Auth Strategy
- **JWT tokens** for user-facing auth (frontend <-> orchestrator)
- **API_KEY** remains for service-to-service (orchestrator <-> sub-agents, frontend server <-> orchestrator)
- Backend `verify_auth()` accepts EITHER JWT Bearer token OR API_KEY
- JWT_SECRET stored in Vault alongside existing secrets

### Password Storage
- bcrypt hashing (already in requirements.txt)
- SQLite `users` table co-located with sessions DB on existing PVC

### Session Scoping
- Add `user_id` column to existing `sessions` table
- `ALTER TABLE` migration with default value for backwards compatibility
- All session CRUD operations filtered by `user_id`

### Frontend Auth Flow
- Login page at `/login` (unprotected)
- JWT stored in `localStorage` as `oncall-jwt`
- All API calls include `Authorization: Bearer <jwt>` header
- AuthProvider context wraps app, redirects unauthenticated users to login

---

## Phase 1: Backend User Management (4 tasks)

### Task 1.1: Add auth dependencies to pyproject.toml
**Steps:**
1. Add `PyJWT>=2.8.0` and `bcrypt>=4.0.0` to `[project.dependencies]` in `pyproject.toml`
2. Verify they're already in `requirements.txt` (they are: PyJWT==2.11.0, bcrypt==5.0.0)

**Test:** `python -c "import jwt; import bcrypt; print('OK')"`

### Task 1.2: Add JWT config to shared/config.py
**Steps:**
1. Add `JWT_SECRET` env var (required for production, defaults to dev secret)
2. Add `JWT_EXPIRY_HOURS` env var (default 24)
3. Add `USERS_DB_PATH` env var (default `/data/users.db`)

**Test:** Import config and verify new vars exist.

### Task 1.3: Create orchestrator/user_manager.py
**Steps:**
1. Create `UserManager` class with SQLite-backed user storage
2. Schema: `users(id TEXT PK, username TEXT UNIQUE, password_hash TEXT, created_at TEXT)`
3. Methods: `create_user(username, password)`, `authenticate(username, password)`, `get_user(user_id)`, `list_users()`
4. bcrypt for password hashing
5. UUID for user IDs

**Test:** Unit test creating user, authenticating with correct/wrong password.

### Task 1.4: Create orchestrator/auth.py
**Steps:**
1. Create `create_jwt(user_id, username)` — returns signed JWT with exp claim
2. Create `verify_jwt(token)` — returns `{user_id, username}` or raises
3. Create `verify_auth(request)` — accepts JWT Bearer OR API_KEY, returns `{user_id, username}` or `None` for API_KEY

**Test:** Unit test JWT creation, verification, expiry, and dual auth.

---

## Phase 2: Backend Auth Endpoints (3 tasks)

### Task 2.1: Add login/register endpoints to main.py
**Steps:**
1. Add `POST /auth/login` — accepts `{username, password}`, returns `{token, user_id, username}`
2. Add `POST /auth/register` — accepts `{username, password}`, returns `{token, user_id, username}`
3. Add `GET /auth/me` — returns current user info (requires JWT)
4. These endpoints do NOT require API_KEY auth (login is public)

**Test:** Integration test register + login + /auth/me flow.

### Task 2.2: Initialize UserManager in app lifespan
**Steps:**
1. Add `app.state.user_manager = UserManager()` in lifespan startup
2. Pass user_manager to auth endpoints via `request.app.state.user_manager`

**Test:** Health endpoint still works after changes.

### Task 2.3: Migrate verify_api_key to verify_auth
**Steps:**
1. Replace existing `verify_api_key` dependency with new `verify_auth`
2. `verify_auth` accepts: JWT Bearer token (returns user info) OR API_KEY (returns None for user_id)
3. Update all `Depends(verify_api_key)` to `Depends(verify_auth)`
4. Session endpoints extract `user_id` from auth result

**Test:** Existing API_KEY auth still works. JWT auth also works.

---

## Phase 3: Session Scoping by User (3 tasks)

### Task 3.1: Add user_id column to sessions table
**Steps:**
1. Add `ALTER TABLE sessions ADD COLUMN user_id TEXT DEFAULT ''` migration in `_init_db()`
2. Add index on `user_id`
3. Backwards compatible: existing sessions get `user_id=''`

**Test:** DB migration runs without error on fresh and existing DBs.

### Task 3.2: Update SessionManager for user scoping
**Steps:**
1. Add `user_id` parameter to: `get_or_create_session()`, `list_sessions()`, `append_messages()`
2. `list_sessions(user_id)` filters by `user_id`
3. `get_session()` verifies ownership (returns None if wrong user)
4. `delete_session()` verifies ownership

**Test:** Two users can't see each other's sessions.

### Task 3.3: Wire user_id through orchestrator endpoints
**Steps:**
1. Session endpoints extract `user_id` from `verify_auth` result
2. Pass `user_id` to all SessionManager calls
3. CopilotKit endpoint extracts `user_id` from request auth
4. API_KEY requests (no user_id) see all sessions (admin mode)

**Test:** Integration test: JWT user only sees own sessions.

---

## Phase 4: Frontend Login Page (3 tasks)

### Task 4.1: Create frontend auth API client
**Steps:**
1. Create `app/lib/auth.ts` with `login()`, `register()`, `getMe()` functions
2. Functions call `/api/auth/*` proxy routes
3. Store JWT in `localStorage` as `oncall-jwt`

**Test:** TypeScript compiles without errors.

### Task 4.2: Create API proxy routes for auth
**Steps:**
1. Create `app/api/auth/login/route.ts` — proxy to orchestrator `/auth/login`
2. Create `app/api/auth/register/route.ts` — proxy to orchestrator `/auth/register`
3. Create `app/api/auth/me/route.ts` — proxy to orchestrator `/auth/me`

**Test:** Routes exist and proxy correctly.

### Task 4.3: Create login page component
**Steps:**
1. Create `app/login/page.tsx` with username/password form
2. Toggle between login and register mode
3. On success: store JWT, redirect to `/`
4. Show error messages on failure
5. Style consistent with existing dark theme

**Test:** Login page renders without errors.

---

## Phase 5: Frontend Auth Integration (4 tasks)

### Task 5.1: Create AuthProvider context
**Steps:**
1. Create `app/contexts/AuthContext.tsx`
2. Provides: `user`, `token`, `login()`, `register()`, `logout()`, `isAuthenticated`
3. On mount: check localStorage for JWT, validate with `/api/auth/me`
4. If invalid: clear token, set unauthenticated

**Test:** AuthProvider loads without errors.

### Task 5.2: Add JWT to all API calls
**Steps:**
1. Update `app/lib/sessions.ts` to include `Authorization: Bearer <jwt>` header
2. Update `app/api/copilotkit/route.ts` to forward JWT from client
3. Update `app/api/sessions/route.ts` and `[id]/route.ts` to forward JWT

**Test:** API calls include auth header.

### Task 5.3: Update sidebar with user display and logout
**Steps:**
1. Add user info section at bottom of SessionSidebar
2. Show username and logout button
3. Logout clears JWT and redirects to `/login`

**Test:** Sidebar shows username when logged in.

### Task 5.4: Add auth guard to main page
**Steps:**
1. Wrap main page content with auth check
2. Redirect to `/login` if not authenticated
3. Update `layout.tsx` to include AuthProvider

**Test:** Unauthenticated users redirected to login.

---

## Phase 6: Config & Deployment (3 tasks)

### Task 6.1: Add JWT_SECRET to Vault and ExternalSecret
**Steps:**
1. Add `jwt-secret` to orchestrator ExternalSecret
2. Add `JWT_SECRET` env var to orchestrator deployment
3. Add to `.env.example`
4. Add to orchestrator secret.yaml template

**Test:** Config files are valid YAML.

### Task 6.2: Update frontend ConfigMap
**Steps:**
1. No changes needed — frontend already proxies through Next.js API routes
2. Verify frontend deployment doesn't need JWT_SECRET (it doesn't — JWT is orchestrator-side)

**Test:** ConfigMap is valid.

### Task 6.3: Create user management script
**Steps:**
1. Create `scripts/create-user.py` — CLI tool to create users
2. Usage: `python scripts/create-user.py --username admin --password changeme`
3. Connects directly to SQLite DB

**Test:** Script creates a user successfully.

---

## End-to-End Test Plan
1. Start orchestrator with JWT_SECRET set
2. Create user via script
3. Login via `/auth/login` endpoint
4. Use JWT to create sessions and query agents
5. Verify session isolation between users
6. Verify API_KEY auth still works for service-to-service

## Estimated Scope
- ~6 new files (Python: user_manager.py, auth.py, create-user.py; TS: auth.ts, AuthContext.tsx, login page)
- ~4 modified files (main.py, session_manager.py, config.py, providers.tsx)
- ~3 modified K8s manifests (external-secret.yaml, orchestrator deployment, .env.example)
- ~200-300 lines new Python code
- ~200-300 lines new TypeScript code
