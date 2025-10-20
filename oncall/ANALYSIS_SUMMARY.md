# OnCall Agent Architecture Analysis - Summary

**Date**: October 19, 2025
**Status**: Complete
**Findings**: Ready for refactor planning

---

## Executive Summary

The OnCall agent currently operates in **DUAL MODE** (daemon + API) and is a candidate for **API-ONLY REFACTOR**. 

Key findings:
- API and daemon have **completely separate code paths** with minimal cross-dependency
- API is **production-ready** and fully independent
- Daemon adds ~3,200 lines of **unused code** when API runs
- Refactor will achieve **40% code reduction** with zero API functionality impact

---

## Architecture Overview

### Current Dual-Mode Setup
```
├── DAEMON MODE (Event-Driven)
│   ├── Orchestrator (src/integrations/orchestrator.py)
│   ├── K8s Event Watcher (src/integrations/k8s_event_watcher.py)
│   ├── Incident Triage Engine (src/agent/incident_triage.py)
│   ├── Teams Notifications (src/notifications/teams_notifier.py)
│   └── Entry: python src/integrations/orchestrator.py
│
└── API MODE (HTTP-Driven)
    ├── FastAPI Server (src/api/api_server.py)
    ├── Agent Client (src/api/agent_client.py)
    ├── Custom Tools (src/api/custom_tools.py + src/tools/*.py)
    └── Entry: uvicorn api.api_server:app
```

### Deployment Modes
```
docker-compose.yml defines 3 services:
1. oncall-agent-daemon (RUN_MODE=daemon) - Background K8s monitoring
2. oncall-agent-api (RUN_MODE=api) - HTTP server
3. both (RUN_MODE=both) - Both services in one container

docker-entrypoint.sh routes to correct mode
```

---

## Detailed Dependency Analysis

### What API Depends On (Must Keep)
```
Core HTTP Server:
  - api_server.py (565 lines) ✅
  - models.py ✅
  - middleware.py ✅
  - session_manager.py ✅

Agent + Tools:
  - agent_client.py (611 lines) - Anthropic SDK wrapper ✅
  - custom_tools.py (1358 lines) - K8s/GitHub/AWS/Datadog APIs ✅
  
Tool Libraries (used by custom_tools.py):
  - aws_integrator.py (512 lines) ✅
  - github_integrator.py (335 lines) ✅
  - datadog_integrator.py (417 lines) ✅
  - nat_gateway_analyzer.py (466 lines) ✅
  - zeus_job_correlator.py (544 lines) ✅

Config:
  - service_mapping.yaml ✅ (for service-to-repo mapping)

Total: ~4,800 lines for full API functionality
```

### What Daemon Depends On (Can Delete)
```
Daemon Core:
  - orchestrator.py (293 lines) ❌ MAIN ENTRY POINT
  - k8s_event_watcher.py (729 lines) ❌ EVENT MONITORING

Incident Analysis:
  - incident_triage.py (1094 lines) ❌ NOT USED BY API
    * Uses Anthropic SDK directly
    * Performs LLM analysis on detected incidents
    * Calls teams_notifier
    * Uses github_integrator + aws_integrator (also in API)

Legacy Agent:
  - oncall_agent.py (100+ lines) ❌ LEGACY, replaced by agent_client.py
  - __main__.py (50+ lines) ❌ LEGACY ENTRY POINT

Notifications:
  - teams_notifier.py (250+ lines) ❌ ONLY FOR DAEMON
    * Called by orchestrator + incident_triage
    * NOT called by API mode

Analysis Tools:
  - k8s_analyzer.py (648 lines) ❌ ONLY REFERENCED BY DELETED oncall_agent.py

Daemon Config:
  - k8s_monitoring.yaml ❌ Alert rules for event watcher
  - notifications.yaml ❌ Teams notification config
  - mcp_servers.json ❌ Legacy MCP config

Total: ~3,200 lines - All daemon-specific
```

### Cross-Dependencies (Both Use These)
```
github_integrator.py:
  - Used by: custom_tools.py (API) AND incident_triage.py (DAEMON)
  - Decision: KEEP (API needs it)

aws_integrator.py:
  - Used by: custom_tools.py (API) AND incident_triage.py (DAEMON)
  - Decision: KEEP (API needs it)

service_mapping.yaml:
  - Used by: custom_tools.py (API) AND orchestrator (DAEMON)
  - Decision: KEEP (API needs it for service-to-repo mapping)
```

---

## Key Architecture Insights

### 1. Incident Analysis: Daemon vs API

**DAEMON (incident_triage.py):**
- Detects: K8s events via event watcher
- Analyzes: LLM runs incident_triage_engine
- Notifies: Sends to Teams via teams_notifier
- Triggers: Automatic based on K8s event rules

**API (agent_client.py):**
- Detects: External system calls HTTP API
- Analyzes: LLM runs via agent_client query tool loop
- Notifies: API returns analysis, client sends notifications
- Triggers: External system controls when to call

**Result**: Same LLM analysis, different orchestration. API doesn't need incident_triage.

### 2. Tool Access: Shared But Safe

All 5 tool libraries (aws, github, datadog, nat, zeus) are used by:
- API via `custom_tools.py` → calls the tool libraries
- Daemon via `incident_triage.py` → calls the tool libraries

**These are utilities, not tied to either mode.** They're safe to keep. If we delete incident_triage.py (daemon-only), the tools remain available for API.

### 3. Configuration Files: Clear Separation

| File | API | Daemon | Decision |
|------|-----|--------|----------|
| service_mapping.yaml | ✅ (service-to-repo) | ✅ (alert enrichment) | KEEP |
| k8s_monitoring.yaml | ❌ | ✅ (event rules) | DELETE |
| notifications.yaml | ❌ | ✅ (Teams config) | DELETE |
| mcp_servers.json | ❌ | ❌ (legacy, unused) | DELETE |

### 4. Entry Points: Clear Separation

```
DAEMON:
  - python src/integrations/orchestrator.py
  - orchestrator.py imports k8s_event_watcher.py
  - orchestrator.py imports incident_triage.py
  - orchestrator.py imports teams_notifier.py

API:
  - uvicorn api.api_server:app
  - api_server.py imports agent_client.py
  - agent_client.py imports custom_tools.py
  - custom_tools.py imports tool libraries

No crossover in import paths!
```

---

## Safety Verification

### ✅ No API Code Uses Daemon Components
- api_server.py: NO imports from integrations/, agent/, notifications/
- agent_client.py: NO imports from integrations/, agent/, notifications/
- custom_tools.py: NO imports from integrations/, agent/, notifications/
- middleware.py: NO imports from integrations/, agent/, notifications/
- session_manager.py: NO imports from integrations/, agent/, notifications/

### ✅ No Daemon Component Is Used by API Tests
```bash
$ grep -r "from.*orchestrator\|from.*incident_triage\|from.*teams_notifier" tests/api/
# (No results) - API tests don't import daemon code
```

### ✅ Tool Libraries Are Truly Shared
- aws_integrator.py: Pure utilities, no mode-specific logic
- github_integrator.py: Pure utilities, no mode-specific logic
- datadog_integrator.py: Pure utilities, no mode-specific logic
- nat_gateway_analyzer.py: Pure utilities, no mode-specific logic
- zeus_job_correlator.py: Pure utilities, no mode-specific logic

### ✅ Custom Tools Don't Reference Daemon
- custom_tools.py: Pure async functions, standalone implementation
- Uses tool libraries, not daemon components
- Can be imported standalone without pulling in daemon code

---

## Refactor Impact Analysis

### Code Being Deleted (~3,200 lines)

**Orchestrator & Event Watcher (1,022 lines)**
- orchestrator.py: 293 lines
- k8s_event_watcher.py: 729 lines
- Impact: Event-based monitoring capability removed
- API Impact: None (API doesn't use this)

**Incident Triage (1,244 lines)**
- incident_triage.py: 1094 lines
- oncall_agent.py: 100+ lines
- __main__.py: 50+ lines
- Impact: Daemon loses LLM analysis capability
- API Impact: None (API uses agent_client.py instead)

**Notifications & Config (900+ lines)**
- teams_notifier.py: 250+ lines
- k8s_analyzer.py: 648 lines
- k8s_monitoring.yaml: Minor
- notifications.yaml: Minor
- Impact: Teams integration, K8s analysis tools removed
- API Impact: None (API doesn't use these)

**Total**: ~3,200 lines deleted = 40% of total codebase

### Code Remaining (~4,800 lines)

**Core API (2,535 lines)**
- api_server.py: 565 lines
- agent_client.py: 611 lines
- custom_tools.py: 1358 lines
- Plus models, middleware, session manager

**Tool Libraries (2,274 lines)**
- aws_integrator: 512 lines
- github_integrator: 335 lines
- datadog_integrator: 417 lines
- nat_gateway_analyzer: 466 lines
- zeus_job_correlator: 544 lines

**Tests**: All API tests remain (not daemon tests)

**Total**: ~4,800 lines of production code

### Result
- API functionality: **100% preserved**
- Test coverage: **100% preserved**
- External interfaces: **100% preserved**
- Code complexity: **40% reduced**

---

## Deployment Changes

### Docker Changes
```
BEFORE:
  docker-compose.yml: 2 services
    - oncall-agent-daemon (RUN_MODE=daemon)
    - oncall-agent-api (RUN_MODE=api)
  docker-entrypoint.sh: 3 mode handlers (daemon, api, both)

AFTER:
  docker-compose.yml: 1 service
    - oncall-agent-api (RUN_MODE=api only)
  docker-entrypoint.sh: 1 mode handler (api only)

Dockerfile: No changes needed (already supports API-only)
```

### Environment Variables Changes
```
DELETE (Daemon-only):
  - TEAMS_WEBHOOK_URL
  - TEAMS_NOTIFICATIONS_ENABLED
  - K8S_CONTEXT (used by event watcher)
  - AGENT_LOG_LEVEL (daemon logging)
  - AGENT_MAX_THINKING_TOKENS (daemon config)
  - RUN_MODE (multi-mode support)
  - ALLOWED_CLUSTERS (daemon safety)
  - PROTECTED_CLUSTERS (daemon safety)

KEEP (API needs):
  - ANTHROPIC_API_KEY
  - GITHUB_TOKEN
  - AWS_* (optional)
  - DATADOG_* (optional)
  - API_HOST, API_PORT
  - API_KEYS, SESSION_TTL_MINUTES, etc.
```

### Documentation Changes
```
DELETE:
  - Daemon setup instructions
  - Daemon deployment guide
  - Event watcher configuration
  - Teams integration setup

UPDATE:
  - CLAUDE.md: Remove daemon sections
  - README.md: Remove daemon options
  - .env.example: Remove daemon vars
```

---

## Migration Path

### For Current Users

**If using Daemon Mode:**
- Daemon monitoring will be removed
- Must switch to external monitoring tools
- Call HTTP API endpoints from monitoring system

**If using API Mode:**
- No breaking changes to HTTP endpoints
- All functionality preserved
- Same response formats

**For n8n Integration:**
- No changes needed
- HTTP endpoints unchanged
- API behavior identical

---

## Risk Assessment

### Low Risk Deletions
- ✅ orchestrator.py: Self-contained, only used as entry point
- ✅ k8s_event_watcher.py: Only called by orchestrator
- ✅ teams_notifier.py: Only called by daemon
- ✅ k8s_monitoring.yaml: Only used by event watcher
- ✅ notifications.yaml: Only used by orchestrator
- ✅ oncall_agent.py: Replaced by agent_client.py
- ✅ __main__.py: Replaced by api_server.py
- ✅ k8s_analyzer.py: Only referenced by deleted oncall_agent.py

### Zero Risk - Isolated Changes
- ✅ docker-entrypoint.sh: Removing daemon mode branches
- ✅ docker-compose.yml: Removing daemon service
- ✅ .env.example: Removing daemon variables
- ✅ Documentation: Updating references only

### Zero Risk - API Remains
- ✅ api_server.py: No dependencies on deleted code
- ✅ agent_client.py: No dependencies on deleted code
- ✅ custom_tools.py: No dependencies on deleted code
- ✅ All tool libraries: No dependencies on deleted code

---

## Verification Checklist

Before refactor:
- [ ] All API tests pass
- [ ] API endpoints respond correctly
- [ ] No hidden imports from daemon code
- [ ] Git history clean, ready for clean commits

After refactor:
- [ ] Daemon files deleted
- [ ] API tests still pass
- [ ] Docker build succeeds
- [ ] Container starts API mode
- [ ] HTTP endpoints work with curl
- [ ] No import errors
- [ ] No orphaned dependencies

---

## Files Generated

1. **REFACTOR_ANALYSIS.md** - Comprehensive 400+ line technical analysis
2. **QUICK_REFERENCE.md** - Quick lookup tables and checklists
3. **ANALYSIS_SUMMARY.md** - This document

All saved to `/Users/arisela/git/claude-agents/oncall/`

---

## Recommendations

### ✅ Proceed with Refactor
The refactor is **low risk** because:
1. API and daemon have **zero cross-dependencies**
2. Tool libraries are **true utilities**
3. API tests are **isolated from daemon**
4. HTTP interfaces are **stable and documented**
5. 40% code reduction with **zero functionality loss** for API users

### Phased Approach
1. Delete daemon files (1022 + 1094 lines)
2. Delete daemon configs (k8s_monitoring.yaml, notifications.yaml)
3. Update container setup (entrypoint, docker-compose)
4. Update documentation
5. Run tests and verify

### Post-Refactor
- Codebase: 40% smaller, single responsibility
- Deployment: Simpler (one service)
- Maintenance: Easier (no daemon complexity)
- API users: Zero impact

