# OnCall Agent Architecture Analysis: Dual-Mode to API-Only Refactor

## Overview
The OnCall agent currently supports DUAL modes:
1. **Daemon Mode** - Proactive K8s monitoring with event watcher
2. **API Mode** - HTTP endpoints for n8n integration

**Goal**: Refactor to **API-Only** by removing all daemon/event-watcher code.

---

## File Classification

### FILES TO KEEP (API-Only)

#### Core API Server
- **`src/api/api_server.py`** (565 lines)
  - FastAPI application with 8 HTTP endpoints
  - Session management, rate limiting, authentication
  - NO dependencies on daemon/orchestrator/k8s_event_watcher
  - ✅ Can keep as-is

- **`src/api/agent_client.py`** (611 lines)
  - OnCallAgentClient wrapper around Anthropic SDK
  - Tool definitions and execution for API mode
  - Used by api_server.py for all queries
  - ✅ Can keep as-is

- **`src/api/models.py`**
  - Pydantic models for requests/responses
  - ✅ Can keep as-is

- **`src/api/session_manager.py`**
  - Session state management (30-min TTL)
  - ✅ Can keep as-is

- **`src/api/middleware.py`**
  - Rate limiting, authentication, CORS
  - ✅ Can keep as-is

- **`src/api/custom_tools.py`** (1358 lines)
  - Direct K8s/GitHub/AWS/Datadog tools
  - Pure Python implementations (no MCP, no CLI)
  - Used by agent_client.py
  - ✅ Can keep as-is

#### Shared Tool Libraries
All these are USED by API mode for queries:
- **`src/tools/aws_integrator.py`** (512 lines)
  - AWS Secrets Manager, ECR verification
  - Used by custom_tools.py and incident_triage.py
  - ✅ KEEP (used by API)

- **`src/tools/github_integrator.py`** (335 lines)
  - GitHub deployment tracking
  - Used by custom_tools.py and incident_triage.py
  - ✅ KEEP (used by API)

- **`src/tools/datadog_integrator.py`** (417 lines)
  - Datadog metrics querying
  - Used by custom_tools.py
  - ✅ KEEP (used by API)

- **`src/tools/nat_gateway_analyzer.py`** (466 lines)
  - CloudWatch NAT metrics
  - Used by custom_tools.py
  - ✅ KEEP (used by API)

- **`src/tools/zeus_job_correlator.py`** (544 lines)
  - Zeus job correlation
  - Used by custom_tools.py
  - ✅ KEEP (used by API)

#### Configuration
- **`config/service_mapping.yaml`**
  - Service to GitHub repo mapping
  - Used by both daemon and API, but more relevant to API
  - ✅ KEEP

- **`config/k8s_monitoring.yaml`**
  - Alert rules and monitoring config
  - **ONLY used by daemon mode** for event filtering
  - ❌ DELETE (daemon-specific)

- **`config/notifications.yaml`**
  - Teams notification config
  - **ONLY used by daemon mode** for orchestrator
  - ❌ DELETE (daemon-specific)

#### Tests
- **`tests/api/**`** (All API tests)
  - ✅ KEEP (these test API functionality)

#### Config files
- **`.env.example`** (already API-friendly)
  - ✅ UPDATE to remove daemon-specific vars

---

### FILES TO DELETE (Daemon-Only)

#### Daemon Components
1. **`src/integrations/orchestrator.py`** (293 lines)
   - Main daemon orchestrator
   - Depends on k8s_event_watcher, teams_notifier
   - Only used by daemon mode
   - Entry point: `python src/integrations/orchestrator.py`
   - ❌ DELETE

2. **`src/integrations/k8s_event_watcher.py`** (729 lines)
   - Kubernetes event watcher
   - Proactive pod health checks
   - Only used by orchestrator
   - Entry point: `await watcher.start()` in orchestrator
   - ❌ DELETE

#### Deprecated Agent Components
3. **`src/agent/oncall_agent.py`** (100+ lines)
   - Claude SDK client (legacy, not used by API)
   - SDK client tries to load MCP servers
   - API uses `agent_client.py` instead (Anthropic SDK directly)
   - ❌ DELETE (replaced by agent_client.py)

4. **`src/agent/incident_triage.py`** (1094 lines)
   - LLM-based incident analysis
   - **ONLY used by daemon** (via orchestrator)
   - NOT used by API mode
   - Depends on: anthropic.Anthropic, k8s API, teams_notifier
   - ❌ DELETE (daemon-specific)

5. **`src/agent/__main__.py`**
   - Legacy agent entry point
   - Not used in API mode
   - ❌ DELETE

#### Notification Components
6. **`src/notifications/teams_notifier.py`**
   - Teams notifications for daemon mode
   - **ONLY called by orchestrator and incident_triage**
   - **NOT used by API mode** (API is stateless, client manages notifications)
   - ❌ DELETE

#### Daemon-Only Scripts
- `run_daemon.sh` - ❌ DELETE
- `run_agent.sh` - ❌ DELETE (unless for testing API)
- `setup_api.sh` - ✅ UPDATE (if references daemon)
- `test_query.sh` - ✅ KEEP/UPDATE (test API)
- `docker-entrypoint.sh` - ✅ REFACTOR (remove daemon modes)
- `docker-compose.yml` - ✅ REFACTOR (remove daemon service)
- `build.sh` - ✅ KEEP (for container builds)
- `build_api.sh` - ✅ KEEP (if separate)
- `start_api.sh` - ✅ KEEP
- `start_api_local.sh` - ✅ KEEP
- `deploy-to-ecr.sh` - ✅ KEEP

---

## Dependency Graph: What API Depends On

```
API Server (api_server.py)
├── OnCallAgentClient (agent_client.py)
│   └── Custom Tools (custom_tools.py)
│       ├── K8s API (kubernetes library)
│       ├── GitHub API (PyGithub)
│       ├── AWS (boto3)
│       ├── DatadogIntegrator (tools/datadog_integrator.py)
│       ├── NAT Gateway Analyzer (tools/nat_gateway_analyzer.py)
│       ├── Zeus Correlator (tools/zeus_job_correlator.py)
│       └── GitHub Integrator (tools/github_integrator.py)
├── SessionManager (session_manager.py)
├── Middleware (middleware.py)
└── Models (models.py)

DAEMON (REMOVE):
├── Orchestrator (integrations/orchestrator.py)
│   ├── K8sEventWatcher (integrations/k8s_event_watcher.py)
│   │   ├── K8s API (kubernetes library)
│   │   └── Alert Rules (config/k8s_monitoring.yaml)
│   ├── IncidentTriageEngine (agent/incident_triage.py)
│   │   ├── Anthropic SDK
│   │   ├── GitHub Integrator
│   │   ├── AWS Integrator
│   │   └── K8s API calls
│   └── TeamsNotifier (notifications/teams_notifier.py)

STANDALONE (NOT used by either):
├── OnCallAgent (agent/oncall_agent.py) - SDK client, not used
├── k8s_analyzer.py - referenced in oncall_agent.py only
```

---

## What MUST Be Kept

### Core API Functionality
1. **HTTP Server** - api_server.py, models.py, middleware.py
2. **Agent Client** - agent_client.py (Anthropic SDK, NOT Claude SDK)
3. **Custom Tools** - custom_tools.py + all tools/*.py (except k8s_analyzer.py)
4. **Sessions** - session_manager.py
5. **Config** - service_mapping.yaml only

### Dependencies
- Python libraries: kubernetes, PyGithub, boto3, anthropic, fastapi, uvicorn
- Environment: ANTHROPIC_API_KEY, GITHUB_TOKEN, AWS credentials (optional), Datadog keys (optional)

### Scripts to Keep
- `run_api_server.sh` - API startup
- `start_api_local.sh` - Local development
- `build.sh` - Docker build
- `deploy-to-ecr.sh` - ECR deployment

---

## What MUST Be Deleted

### Daemon Components
- `src/integrations/orchestrator.py` - MAIN DAEMON ENTRY POINT
- `src/integrations/k8s_event_watcher.py` - EVENT WATCHER

### Incident Triage (Daemon-only)
- `src/agent/incident_triage.py` - NOT USED BY API
- `src/agent/oncall_agent.py` - LEGACY SDK CLIENT (API uses agent_client.py)
- `src/agent/__main__.py` - LEGACY ENTRY POINT

### Notifications (Daemon-only)
- `src/notifications/teams_notifier.py` - ONLY FOR DAEMON

### Daemon Config
- `config/k8s_monitoring.yaml` - DAEMON ALERT RULES
- `config/notifications.yaml` - DAEMON NOTIFICATIONS

### Daemon Scripts
- `run_daemon.sh` - START DAEMON
- `run_agent.sh` - RUN AGENT (legacy)

---

## Refactoring Required

### 1. docker-entrypoint.sh
**Current**: Supports 3 modes (daemon, api, both)
**New**: API mode only
```bash
# Remove daemon mode case
# Remove both mode case
# Keep api mode case
exec uvicorn api.api_server:app \
  --host "${API_HOST:-0.0.0.0}" \
  --port "${API_PORT:-8000}" \
  --app-dir /app/src
```

### 2. docker-compose.yml
**Current**: 2 services (daemon + api)
**New**: API only
```yaml
# Remove oncall-agent-daemon service
# Keep oncall-agent-api service
# Remove TEAMS_WEBHOOK_URL, TEAMS_NOTIFICATIONS_ENABLED
```

### 3. Dockerfile
**Current**: No changes needed
**New**: No changes needed (already supports API-only)
```dockerfile
# Already multi-stage build
# Already skips Claude CLI
```

### 4. .env and .env.example
**Current**: Mix of daemon and API variables
**New**: API-only variables
```bash
# REMOVE:
TEAMS_WEBHOOK_URL
TEAMS_NOTIFICATIONS_ENABLED
K8S_CONTEXT (or make optional)

# KEEP:
ANTHROPIC_API_KEY
GITHUB_TOKEN
AWS_ACCESS_KEY_ID
AWS_SECRET_ACCESS_KEY
AWS_REGION
DATADOG_API_KEY
DATADOG_APP_KEY
DATADOG_SITE
API_HOST
API_PORT
API_KEYS
SESSION_TTL_MINUTES
MAX_SESSIONS_PER_USER
CORS_ORIGINS
```

### 5. CLAUDE.md / Project Documentation
**Current**: Describes dual-mode architecture
**New**: Remove all daemon mode references, keep API-only docs
```markdown
# Remove:
- Daemon mode setup instructions
- Orchestrator description
- Event watcher documentation
- Teams notification webhook setup

# Keep:
- API mode setup
- HTTP endpoints documentation
- Session management
- Query examples
```

### 6. README.md / docs
**Current**: Mentions daemon mode options
**New**: API-only mode only
```markdown
# Simplify to just API deployment options
```

---

## Files Summary

### Keep (API-Only - 9 files)
```
src/api/
  ├── api_server.py ✅
  ├── agent_client.py ✅
  ├── models.py ✅
  ├── session_manager.py ✅
  ├── middleware.py ✅
  └── custom_tools.py ✅
src/tools/
  ├── aws_integrator.py ✅
  ├── github_integrator.py ✅
  ├── datadog_integrator.py ✅
  ├── nat_gateway_analyzer.py ✅
  └── zeus_job_correlator.py ✅
config/
  └── service_mapping.yaml ✅
tests/api/ ✅ (all tests)
```

### Delete (Daemon-Only - 11 files)
```
src/integrations/
  ├── orchestrator.py ❌
  └── k8s_event_watcher.py ❌
src/agent/
  ├── oncall_agent.py ❌
  ├── incident_triage.py ❌
  ├── __main__.py ❌
  └── k8s_analyzer.py ❌ (only referenced by oncall_agent.py)
src/notifications/
  └── teams_notifier.py ❌
config/
  ├── k8s_monitoring.yaml ❌
  ├── notifications.yaml ❌
  └── mcp_servers.json ❌ (legacy, not used)
```

### Refactor (Update - 10 files)
```
docker-entrypoint.sh - Remove daemon modes
docker-compose.yml - Remove daemon service
.env.example - Remove daemon vars
run_daemon.sh - DELETE
run_agent.sh - DELETE (legacy)
CLAUDE.md - Remove daemon docs
README.md - Remove daemon docs
pyproject.toml - Remove daemon dependencies (if any)
requirements.txt - Remove orchestrator/triage dependencies
setup.py - Update entry points
```

---

## Size Reduction Impact

### Code Deleted
- orchestrator.py: 293 lines
- k8s_event_watcher.py: 729 lines
- incident_triage.py: 1094 lines
- oncall_agent.py: 100+ lines
- teams_notifier.py: 250+ lines
- k8s_analyzer.py: 648 lines
- Agent __main__.py: 50+ lines
**Total: ~3,200 lines deleted (~35% code reduction)**

### Code Kept
- API: 565 + 611 + custom_tools (1358) = ~2,500 lines
- Tools: 512 + 335 + 417 + 466 + 544 = ~2,300 lines
- Tests: All API tests = kept
**Total: ~4,800 lines kept (production API code)**

### Result
- **Before**: ~8,000 lines total (dual-mode)
- **After**: ~4,800 lines (API-only)
- **Reduction**: 40% less code, single responsibility

---

## Implementation Order

1. **Phase 1: Safety**
   - Tag/backup current code in git
   - Ensure tests pass before changes
   
2. **Phase 2: Delete Daemon Code**
   - Delete 11 daemon-only files (see list above)
   - Delete daemon-specific scripts (run_daemon.sh, etc.)
   
3. **Phase 3: Update Config**
   - Delete k8s_monitoring.yaml
   - Delete notifications.yaml
   - Update .env.example to remove daemon vars
   - Update requirements.txt (remove any daemon-only deps)
   
4. **Phase 4: Update Container**
   - Simplify docker-entrypoint.sh (API-only)
   - Simplify docker-compose.yml (API-only)
   - Verify Dockerfile needs no changes
   
5. **Phase 5: Update Documentation**
   - Update CLAUDE.md (remove all daemon references)
   - Update README.md (API-only)
   - Delete old daemon deployment guides
   
6. **Phase 6: Test**
   - Run API tests
   - Manual API testing with curl
   - Docker container test

---

## Key Benefits

✅ **40% code reduction** - Simpler codebase
✅ **Single responsibility** - API only, no background daemon confusion
✅ **Simpler deployment** - One service, not two
✅ **Easier maintenance** - No event watcher complexity
✅ **Clearer purpose** - HTTP API wrapper, not autonomous agent
✅ **Better testability** - Stateless API vs complex daemon interactions
✅ **Lower operational cost** - No continuous monitoring overhead

