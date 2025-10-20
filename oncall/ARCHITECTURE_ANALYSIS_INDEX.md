# OnCall Agent Architecture Analysis - Complete Index

**Analysis Date**: October 19, 2025
**Status**: Complete & Ready for Implementation
**Repository**: `/Users/arisela/git/claude-agents/oncall`

---

## Documentation Files

This analysis consists of 3 comprehensive documents:

### 1. REFACTOR_ANALYSIS.md (12 KB)
**Purpose**: Complete technical analysis
**Audience**: Developers, architects
**Contents**:
- File classification (keep/delete/refactor)
- Dependency graph
- API vs Daemon comparison
- Size reduction impact analysis
- Implementation order (6 phases)
- Benefits and key features

**When to Read**: For complete understanding of what changes and why

### 2. QUICK_REFERENCE.md (6 KB)
**Purpose**: Quick lookup tables and checklists
**Audience**: Developers implementing the refactor
**Contents**:
- TL;DR summary
- File categories with line counts
- Dependency check quick tables
- Environment variable changes
- Breaking changes analysis
- Testing checklist
- Entry points before/after

**When to Read**: During implementation for quick decisions

### 3. ANALYSIS_SUMMARY.md (12 KB)
**Purpose**: Executive overview with insights
**Audience**: Decision makers, team leads
**Contents**:
- Executive summary
- Architecture overview
- Detailed dependency analysis
- Key insights (4 categories)
- Risk assessment
- Migration path
- Verification checklist
- Recommendations

**When to Read**: For approval and planning

---

## Key Findings Summary

### Architecture Status
- **Current**: Dual-mode (daemon + API)
- **Proposed**: API-only
- **Status**: Safe, low-risk refactor

### Code Impact
- **Delete**: ~3,200 lines (40% reduction)
- **Keep**: ~4,800 lines (100% API preserved)
- **Result**: Smaller, simpler codebase

### Files Affected
- **Delete**: 11 files (daemon-specific)
- **Keep**: 14 files (API + tools)
- **Refactor**: 10 files (docs + config)

### Safety Level
- **API Tests**: 100% preserved
- **API Functionality**: 100% preserved
- **API Interfaces**: 100% preserved
- **Daemon Code**: 0% used by API

---

## Quick Decision Matrix

| Question | Answer | Evidence |
|----------|--------|----------|
| Is API isolated from daemon? | **YES** | Zero cross-dependencies in imports |
| Will API functionality break? | **NO** | API doesn't import daemon code |
| Are tool libraries shared? | **YES** | Used by both, marked for keep |
| Can we safely delete daemon? | **YES** | Daemon doesn't affect API tests |
| Will this reduce code? | **YES** | 40% smaller codebase |
| Is this low-risk? | **YES** | Clear separation of concerns |

---

## Files to Delete (11 Total)

### Daemon Core (2 files, 1,022 lines)
```
src/integrations/orchestrator.py (293 lines)
src/integrations/k8s_event_watcher.py (729 lines)
```

### Incident Analysis (3 files, 1,244 lines)
```
src/agent/incident_triage.py (1,094 lines)
src/agent/oncall_agent.py (100+ lines)
src/agent/__main__.py (50+ lines)
```

### Notifications (1 file)
```
src/notifications/teams_notifier.py (250+ lines)
```

### Analysis Tools (1 file)
```
src/tools/k8s_analyzer.py (648 lines)
```

### Daemon Config (3 files)
```
config/k8s_monitoring.yaml
config/notifications.yaml
config/mcp_servers.json
```

### Daemon Scripts (2 files)
```
run_daemon.sh
run_agent.sh
```

---

## Files to Keep (14 Total)

### Core API (6 files)
```
src/api/api_server.py (565 lines)
src/api/agent_client.py (611 lines)
src/api/models.py
src/api/session_manager.py
src/api/middleware.py
src/api/custom_tools.py (1,358 lines)
```

### Shared Tools (5 files)
```
src/tools/aws_integrator.py (512 lines)
src/tools/github_integrator.py (335 lines)
src/tools/datadog_integrator.py (417 lines)
src/tools/nat_gateway_analyzer.py (466 lines)
src/tools/zeus_job_correlator.py (544 lines)
```

### Configuration (1 file)
```
config/service_mapping.yaml
```

### Tests (all)
```
tests/api/**
```

---

## Files to Refactor (10 Total)

### Docker/Container
```
docker-entrypoint.sh - Remove daemon mode cases
docker-compose.yml - Remove daemon service
Dockerfile - No changes needed
```

### Environment & Scripts
```
.env.example - Remove daemon variables
requirements.txt - Verify no daemon deps
build.sh, deploy-to-ecr.sh - Keep unchanged
run_api_server.sh, start_api.sh - Keep unchanged
```

### Documentation
```
CLAUDE.md - Remove daemon sections
README.md - Remove daemon options
```

---

## Dependency Graph (What Needs What)

```
KEEP: API Server
├── KEEP: OnCallAgentClient (agent_client.py)
│   └── KEEP: Custom Tools (custom_tools.py)
│       ├── KEEP: AWS Integrator
│       ├── KEEP: GitHub Integrator
│       ├── KEEP: Datadog Integrator
│       ├── KEEP: NAT Gateway Analyzer
│       └── KEEP: Zeus Correlator
├── KEEP: Session Manager
├── KEEP: Middleware
└── KEEP: Models

DELETE: Daemon Orchestrator
├── DELETE: Event Watcher
│   └── DELETE: k8s_monitoring.yaml
├── DELETE: Incident Triage Engine
│   ├── KEEP: GitHub Integrator (but delete incident_triage.py)
│   ├── KEEP: AWS Integrator (but delete incident_triage.py)
│   └── DELETE: teams_notifier.py
└── DELETE: notifications.yaml
```

---

## Environment Variables

### Keep (API needs these)
```
ANTHROPIC_API_KEY (Required)
GITHUB_TOKEN (Required)
AWS_ACCESS_KEY_ID (Optional)
AWS_SECRET_ACCESS_KEY (Optional)
AWS_REGION (Optional, default: us-east-1)
DATADOG_API_KEY (Optional)
DATADOG_APP_KEY (Optional)
DATADOG_SITE (Optional)
API_HOST (Optional)
API_PORT (Optional)
API_KEYS (Optional)
SESSION_TTL_MINUTES (Optional)
MAX_SESSIONS_PER_USER (Optional)
CORS_ORIGINS (Optional)
```

### Delete (Daemon-only)
```
TEAMS_WEBHOOK_URL
TEAMS_NOTIFICATIONS_ENABLED
K8S_CONTEXT
AGENT_LOG_LEVEL
AGENT_MAX_THINKING_TOKENS
RUN_MODE
ALLOWED_CLUSTERS
PROTECTED_CLUSTERS
```

---

## Implementation Phases

### Phase 1: Safety Check
- Run all API tests
- Verify no hidden daemon dependencies
- Clean git state

### Phase 2: Delete Daemon Code
- Delete 11 daemon-only files
- Delete daemon-specific scripts

### Phase 3: Update Configuration
- Delete k8s_monitoring.yaml
- Delete notifications.yaml
- Update .env.example
- Update requirements.txt

### Phase 4: Update Container
- Simplify docker-entrypoint.sh (API-only)
- Simplify docker-compose.yml (one service)
- Verify Dockerfile (no changes)

### Phase 5: Update Documentation
- Update CLAUDE.md
- Update README.md
- Add migration guide

### Phase 6: Test & Verify
- Run API tests
- Docker build test
- Container startup test
- HTTP endpoint test

---

## Success Criteria

After refactor, verify:

```
✅ All API tests pass
✅ API endpoints respond correctly
✅ Docker container builds
✅ Container starts API mode
✅ HTTP endpoints work
✅ No import errors
✅ No orphaned code
✅ Documentation updated
```

---

## Risks & Mitigations

| Risk | Severity | Mitigation |
|------|----------|-----------|
| Break API functionality | LOW | Zero cross-dependencies |
| Orphaned imports | LOW | Grep for deleted modules |
| Config file missing | LOW | Check service_mapping.yaml only |
| Docker build fails | LOW | Dockerfile unchanged |
| Tests fail | LOW | Tests are API-only |

---

## Next Steps

1. **Review** these 3 documents
2. **Discuss** with team (risk assessment: LOW)
3. **Approve** refactor plan
4. **Execute** 6-phase implementation
5. **Test** thoroughly
6. **Deploy** new API-only version

---

## Related Documentation

**Existing docs (keep/update)**:
- CLAUDE.md - Update (remove daemon sections)
- README.md - Update (remove daemon options)

**New docs (this analysis)**:
- REFACTOR_ANALYSIS.md - Technical deep dive
- QUICK_REFERENCE.md - Implementation guide
- ANALYSIS_SUMMARY.md - Executive summary
- ARCHITECTURE_ANALYSIS_INDEX.md - This file

---

## Questions?

### For Quick Answers
See **QUICK_REFERENCE.md** - Tables and checklists

### For Technical Details
See **REFACTOR_ANALYSIS.md** - Complete analysis

### For Decision Making
See **ANALYSIS_SUMMARY.md** - Risk and impact

---

## File Locations

All documents are in: `/Users/arisela/git/claude-agents/oncall/`

```
oncall/
├── REFACTOR_ANALYSIS.md (12 KB)
├── QUICK_REFERENCE.md (6 KB)
├── ANALYSIS_SUMMARY.md (12 KB)
└── ARCHITECTURE_ANALYSIS_INDEX.md (this file)
```

---

**Analysis Complete** - Ready for Implementation

Generated: October 19, 2025
Location: OnCall Agent Repository
Scope: Dual-Mode to API-Only Refactor
