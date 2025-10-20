# OnCall Refactor: Quick Reference

## TL;DR - What's Being Removed

The OnCall agent is being refactored from **dual-mode (daemon + API) to API-only**.

### Files to DELETE (11 files, ~3,200 lines)
```
DAEMON ORCHESTRATION:
- src/integrations/orchestrator.py (293 lines)
- src/integrations/k8s_event_watcher.py (729 lines)

INCIDENT TRIAGE (DAEMON-ONLY):
- src/agent/incident_triage.py (1094 lines)
- src/agent/oncall_agent.py (100+ lines)
- src/agent/__main__.py (50+ lines)

NOTIFICATIONS (DAEMON-ONLY):
- src/notifications/teams_notifier.py (250+ lines)

ANALYSIS TOOLS (REFERENCED ONLY BY AGENT):
- src/tools/k8s_analyzer.py (648 lines)

DAEMON CONFIG:
- config/k8s_monitoring.yaml
- config/notifications.yaml
- config/mcp_servers.json

DAEMON SCRIPTS:
- run_daemon.sh
- run_agent.sh
```

### Files to KEEP (API + Shared Tools)

**Core API (6 files)**
```
src/api/api_server.py (565 lines) ✅ Keep as-is
src/api/agent_client.py (611 lines) ✅ Keep as-is
src/api/models.py ✅ Keep as-is
src/api/session_manager.py ✅ Keep as-is
src/api/middleware.py ✅ Keep as-is
src/api/custom_tools.py (1358 lines) ✅ Keep as-is
```

**Shared Tools Used by API (5 files)**
```
src/tools/aws_integrator.py (512 lines) ✅ Keep (used by API)
src/tools/github_integrator.py (335 lines) ✅ Keep (used by API)
src/tools/datadog_integrator.py (417 lines) ✅ Keep (used by API)
src/tools/nat_gateway_analyzer.py (466 lines) ✅ Keep (used by API)
src/tools/zeus_job_correlator.py (544 lines) ✅ Keep (used by API)
```

**Config**
```
config/service_mapping.yaml ✅ Keep (used by API tools)
```

**Tests**
```
tests/api/** ✅ Keep all API tests
```

### Files to REFACTOR (10 files)

```
docker-entrypoint.sh
  - Remove daemon mode case
  - Remove both mode case
  - Keep api mode only

docker-compose.yml
  - Remove oncall-agent-daemon service
  - Keep oncall-agent-api service only
  - Remove TEAMS_WEBHOOK_URL, TEAMS_NOTIFICATIONS_ENABLED vars

.env.example
  - Remove daemon vars: TEAMS_WEBHOOK_URL, TEAMS_NOTIFICATIONS_ENABLED
  - Keep API vars

requirements.txt
  - Verify no daemon-specific deps

CLAUDE.md
  - Remove daemon setup instructions
  - Remove daemon deployment options
  - Remove Teams notification setup
  - Keep API documentation

README.md
  - Remove daemon mode references
  - Simplify to API-only deployment

run_api_server.sh, start_api.sh, etc.
  - Keep unchanged (already API-only)
```

## Dependency Check

### What API Depends On (KEEP ALL)
```
api_server.py
  ├── agent_client.py (Anthropic SDK wrapper)
  │   └── custom_tools.py (K8s, GitHub, AWS, Datadog APIs)
  │       ├── aws_integrator.py
  │       ├── github_integrator.py
  │       ├── datadog_integrator.py
  │       ├── nat_gateway_analyzer.py
  │       └── zeus_job_correlator.py
  ├── session_manager.py
  ├── middleware.py (rate limiting, auth)
  └── models.py (Pydantic models)
```

### What Daemon Depends On (DELETE ALL)
```
orchestrator.py (MAIN DAEMON ENTRY POINT)
  ├── k8s_event_watcher.py
  │   └── kubernetes Python library + k8s_monitoring.yaml
  ├── incident_triage.py
  │   ├── anthropic SDK
  │   ├── github_integrator.py (also used by API)
  │   ├── aws_integrator.py (also used by API)
  │   └── kubernetes Python library
  ├── teams_notifier.py
  ├── service_mapping.yaml (also used by API)
  └── notifications.yaml
```

### Cross Dependencies
```
github_integrator.py: Used by API AND incident_triage
→ KEEP (used by API)

aws_integrator.py: Used by API AND incident_triage
→ KEEP (used by API)

k8s_analyzer.py: ONLY used by oncall_agent.py (which is deleted)
→ DELETE (orphaned)

service_mapping.yaml: Used by API AND orchestrator
→ KEEP (used by API)

custom_tools.py: ONLY used by agent_client.py (API)
→ KEEP (core to API)
```

## Environment Variables

### Keep (API needs these)
```
ANTHROPIC_API_KEY=sk-... (Required)
GITHUB_TOKEN=ghp_... (Required)
AWS_ACCESS_KEY_ID (Optional, for ECR/Secrets Manager checks)
AWS_SECRET_ACCESS_KEY (Optional)
AWS_REGION (Optional, default: us-east-1)
DATADOG_API_KEY (Optional, for metrics)
DATADOG_APP_KEY (Optional, for metrics)
DATADOG_SITE (Optional, default: datadoghq.com)
API_HOST=0.0.0.0 (Optional, default: 0.0.0.0)
API_PORT=8000 (Optional, default: 8000)
API_KEYS=... (Optional, for auth)
SESSION_TTL_MINUTES=30 (Optional)
MAX_SESSIONS_PER_USER=5 (Optional)
CORS_ORIGINS=* (Optional)
```

### Delete (Daemon-only)
```
TEAMS_WEBHOOK_URL (Daemon only)
TEAMS_NOTIFICATIONS_ENABLED (Daemon only)
K8S_CONTEXT (Daemon only - event watcher needs it)
AGENT_LOG_LEVEL (Daemon only)
AGENT_MAX_THINKING_TOKENS (Daemon only)
RUN_MODE (Only for multi-mode support)
ALLOWED_CLUSTERS (Daemon safety)
PROTECTED_CLUSTERS (Daemon safety)
```

## Breaking Changes

**None for API users!** The HTTP endpoints remain the same:
- POST /query - Still works
- POST /incident - Still works
- POST /session - Still works
- GET /session/{id} - Still works
- DELETE /session/{id} - Still works
- GET /sessions/stats - Still works
- GET /health - Still works

**Changes for infrastructure:**
- Daemon monitoring capability removed (use external monitoring tools)
- Teams notifications removed (API responses can trigger external notification systems)
- Event-based triggering removed (use external systems to call HTTP API)

## Size Reduction
```
Before: ~8,000 lines (dual-mode)
After:  ~4,800 lines (API-only)
Reduction: 40% less code ✅
```

## Testing Checklist
```
□ Delete 11 daemon files
□ Verify tests still pass
□ Check docker build works
□ Test API endpoints with curl
□ Verify all imports resolve
□ Check no broken dependencies
□ Update documentation
□ Commit changes
```

## Files by Category

| Category | Count | Action |
|----------|-------|--------|
| Delete | 11 | Remove completely |
| Keep | 14 | No changes needed |
| Refactor | 10 | Update (mostly docs) |
| Tests | All API | Keep unchanged |

## Entry Points After Refactor
```
BEFORE:
- python src/integrations/orchestrator.py (daemon)
- uvicorn api.api_server:app (API)

AFTER:
- uvicorn api.api_server:app (ONLY)

Docker:
- BEFORE: RUN_MODE={daemon,api,both}
- AFTER: RUN_MODE=api (only)
```

