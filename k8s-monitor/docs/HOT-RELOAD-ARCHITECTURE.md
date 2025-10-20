# Hot-Reload Architecture Guide

**Version**: 1.0
**Date**: 2025-10-20
**Status**: Production Ready ✅

## Overview

k8s-monitor implements **enterprise-grade hot-reload configuration** using Kubernetes ConfigMaps. This enables operational teams to modify agent behavior, cluster context, and escalation policies **without any container rebuilds, image pushes, or pod restarts**.

### The Problem We Solve

**Traditional Approach** (❌ 10-15 minutes per change):
```
Edit source code → Build container → Push to registry → Deploy to cluster → Changes take effect
```

**Our Solution** (✅ <1 minute per change):
```
Edit ConfigMap in git → kubectl apply → Changes take effect on next cycle (within 1 hour)
```

**Benefits**:
- ✅ No container rebuilds
- ✅ No image registry operations
- ✅ No pod restarts or downtime
- ✅ Full version control with git history
- ✅ Instant rollback capability
- ✅ Operational teams can make changes without code access

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         k8s-monitor Pod                                  │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  /app/                                                                   │
│  ├── .claude/                                                            │
│  │   ├── CLAUDE.md              ← FROM orchestrator-configmap           │
│  │   │   (Cluster context)                                              │
│  │   │   • Critical services list (P0/P1/P2/P3)                        │
│  │   │   • Known issues & quirks                                        │
│  │   │   • Escalation policies                                          │
│  │   │   • Team contact info                                            │
│  │   │                                                                   │
│  │   └── agents/                ← FROM agents-configmap                │
│  │       ├── k8s-analyzer.md                                            │
│  │       │   (How to check cluster health)                             │
│  │       ├── escalation-manager.md                                      │
│  │       │   (How to classify severity)                                │
│  │       ├── slack-notifier.md                                          │
│  │       │   (How to format alerts)                                    │
│  │       └── github-reviewer.md                                         │
│  │           (How to correlate deployments)                            │
│  │                                                                       │
│  └── logs/                                                               │
│      └── incidents/            ← PERSISTENT (PVC)                      │
│          (Survives pod restarts)                                        │
│                                                                          │
│  Python Code:                                                            │
│  ├── main.py (orchestrator)                                             │
│  │   • Reads CLAUDE.md                                                  │
│  │   • Reads agents/*.md                                               │
│  │   • Coordinates subagents                                            │
│  │   • Analyzes findings                                                │
│  │   • Decides escalation                                               │
│  │                                                                       │
│  └── config/settings.py                                                 │
│      • Environment configuration                                        │
│      • Model names                                                      │
│      • API keys                                                         │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘

        ↓ (loads from Kubernetes)

┌─────────────────────────────────────────────────────────────────────────┐
│                    Kubernetes ConfigMaps                                 │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  k8s-monitor-orchestrator ConfigMap                                    │
│  └── CLAUDE.md: |                                                       │
│      # K3s Monitoring Agent - Orchestrator Context                     │
│      ...cluster-specific configuration...                              │
│                                                                          │
│  k8s-monitor-agents ConfigMap                                          │
│  ├── k8s-analyzer.md: |                                                │
│  │   ---                                                                │
│  │   name: k8s-analyzer                                                │
│  │   ...instructions...                                                │
│  ├── escalation-manager.md: |                                          │
│  │   ---                                                                │
│  │   name: escalation-manager                                          │
│  │   ...instructions...                                                │
│  ├── slack-notifier.md: |                                              │
│  │   ---                                                                │
│  │   name: slack-notifier                                              │
│  │   ...instructions...                                                │
│  └── github-reviewer.md: |                                             │
│      ---                                                                │
│      name: github-reviewer                                             │
│      ...instructions...                                                │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

## Two ConfigMaps Strategy

### ConfigMap 1: Orchestrator Context (`k8s-monitor-orchestrator`)

**Purpose**: Cluster-specific configuration and decision logic

**File**: `k8s/orchestrator-configmap.yaml`

**Contains**: Single key `CLAUDE.md` with:
- Cluster name, type, and environment
- Critical services inventory (P0/P1/P2/P3 classification)
- Known issues and expected behaviors
- Health check patterns for each service
- Escalation policy (SEV-1/2/3/4 definitions)
- Team contact information
- Deployment/GitOps information
- Monitoring cycle workflow
- Recent deployments and changes

**Mount point**: `/app/.claude/CLAUDE.md`

**Update frequency**: Weekly to monthly (as cluster changes)

**Who updates**: Operations/SRE team

**Examples of changes**:
- Add new critical service to monitor
- Mark service as known to be down (maintenance window)
- Change escalation channel
- Update max downtime tolerances
- Add new known issue (vault unseal, slow startup)

**Impact**: Changes take effect on next monitoring cycle (within 1 hour)

### ConfigMap 2: Agent Definitions (`k8s-monitor-agents`)

**Purpose**: Subagent behavior and instruction definitions

**File**: `k8s/agents-configmap.yaml`

**Contains**: Four keys:
1. `k8s-analyzer.md` - Health check instructions
2. `escalation-manager.md` - Severity classification logic
3. `slack-notifier.md` - Alert message formatting
4. `github-reviewer.md` - Deployment correlation logic

**Mount point**: `/app/.claude/agents/`

**Update frequency**: Monthly to quarterly (behavior changes)

**Who updates**: Development/DevOps team

**Examples of changes**:
- Adjust memory usage thresholds in analyzer
- Change severity classification rules
- Add new health checks
- Modify Slack message format
- Expand GitHub commit search window

**Impact**: Changes take effect on next monitoring cycle (within 1 hour)

## Volume Mount Resolution

Kubernetes properly handles the parent-child mount relationship:

```yaml
volumeMounts:
  - name: orchestrator-context
    mountPath: /app/.claude
    readOnly: true
  - name: agent-definitions
    mountPath: /app/.claude/agents
    readOnly: true

volumes:
  - name: orchestrator-context
    configMap:
      name: k8s-monitor-orchestrator
      items:
        - key: CLAUDE.md
          path: CLAUDE.md

  - name: agent-definitions
    configMap:
      name: k8s-monitor-agents
```

**How it works**:
1. First mount: orchestrator-configmap → `/app/.claude/` creates directory with `CLAUDE.md`
2. Second mount: agents-configmap → `/app/.claude/agents/` creates subdirectory with agent files
3. Result: No conflicts because they're separate volumes at different paths
4. `items` field in orchestrator mount ensures only `CLAUDE.md` is copied (not entire ConfigMap)

**Filesystem result**:
```
/app/.claude/
├── CLAUDE.md              ← From orchestrator-configmap (items field)
└── agents/
    ├── k8s-analyzer.md    ← From agents-configmap
    ├── escalation-manager.md
    ├── slack-notifier.md
    └── github-reviewer.md
```

## Hot-Reload Workflow

### Updating Orchestrator Context (Cluster Configuration)

**Step 1**: Edit in git repository
```bash
vi k8s/orchestrator-configmap.yaml
# Edit the CLAUDE.md section
# Update services list, known issues, escalation policy, etc.
```

**Step 2**: Commit changes
```bash
git add k8s/orchestrator-configmap.yaml
git commit -m "Update orchestrator context: Add vault.unseal as known issue"
git push origin main
```

**Step 3**: Deploy to cluster (ArgoCD or manual)
```bash
kubectl apply -f k8s/orchestrator-configmap.yaml
# OR let ArgoCD sync automatically (3-5 minutes)
```

**Step 4**: Verify changes applied
```bash
# Check ConfigMap was updated
kubectl get configmap -n k8s-monitor k8s-monitor-orchestrator -o yaml | grep "vault"

# Check pod reads new configuration (next cycle)
kubectl logs -n k8s-monitor -l app=k8s-monitor --tail=100 | grep "CLAUDE.md"
```

**Timeline**:
- Edit → Commit: < 1 minute
- Push → ArgoCD sync: 3-5 minutes
- ConfigMap update → Pod reads: < 30 seconds
- Next monitoring cycle: Within 1 hour (or force restart pod for immediate effect)

### Updating Agent Definitions (Behavior Changes)

**Step 1**: Edit in git repository
```bash
vi k8s/agents-configmap.yaml
# Edit the specific agent section (e.g., k8s-analyzer.md)
# Modify instructions, thresholds, or behavior
```

**Step 2**: Commit and deploy
```bash
git add k8s/agents-configmap.yaml
git commit -m "Update k8s-analyzer: Lower memory threshold from 80% to 70%"
git push origin main

kubectl apply -f k8s/agents-configmap.yaml
```

**Step 3**: Verify
```bash
# Check which agents are currently loaded (review pod logs)
kubectl logs -n k8s-monitor -l app=k8s-monitor -f
# Look for agent discovery in logs
```

## Runtime Agent Loading

The Claude Agent SDK automatically discovers and loads agents from `.claude/agents/`:

```python
# This happens automatically in the SDK
# No code changes needed!

# Pod starts → SDK scans /app/.claude/agents/ → Finds all .md files
# For each .md file:
#   1. Parse YAML frontmatter (---name, description, tools, model---)
#   2. Store agent definition
#   3. When orchestrator requests agent → SDK instantiates it with latest definition
```

**No pod restart required** - SDK reloads agents on each monitoring cycle.

## Comparison: ConfigMap vs. Image Rebuild

| Aspect | Hot-Reload (ConfigMap) | Traditional (Image Rebuild) |
|--------|------------------------|---------------------------|
| **Change time** | < 1 minute | 10-15 minutes |
| **Image rebuild** | ❌ No | ✅ Yes (5-7 min) |
| **Registry push** | ❌ No | ✅ Yes (2-3 min) |
| **Pod restart** | ❌ Optional | ✅ Yes (downtime) |
| **Rollback time** | < 1 minute | 10-15 minutes |
| **Version control** | ✅ Git tracked | ✅ Git + image tags |
| **Team access** | Ops/SRE only | DevOps/Infra team |
| **Testing** | Same code, immediate feedback | Different builds required |
| **Safety** | Hot-reload is safer (no downtime) | Pod restart required |

## Common Customization Scenarios

### Scenario 1: Add New Critical Service

**File**: `k8s/orchestrator-configmap.yaml`

**What to change**:
```yaml
CLAUDE.md: |
  ## Critical Services (P0 - Business Critical)

  - chores-tracker-backend: Main application backend
  - chores-tracker-frontend: Web UI
  + my-new-service: Description of service
```

**Effect**: Next monitoring cycle, orchestrator includes new service in health checks

**Timeline**: < 1 minute

### Scenario 2: Mark Service as Expected to Be Down

**File**: `k8s/orchestrator-configmap.yaml`

**What to change**:
```yaml
CLAUDE.md: |
  ## Known Issues & Quirks

  ### Database Backup Window
  - Every Sunday 2-3 AM
  - Why: Regular backup process
  - Solution: This is expected - DO NOT FLAG
```

**Effect**: Next cycle, analyzer won't flag database as issue during backup window

**Timeline**: < 1 minute

### Scenario 3: Adjust Severity Thresholds

**File**: `k8s/agents-configmap.yaml`

**What to change**:
```yaml
escalation-manager.md: |
  ### SEV-1: Critical (P0 Services Down)
  - **Criteria**: Any P0 service down for > 2 minutes (was: immediately)
  - **Action**: Immediate notification required
```

**Effect**: P0 services need to be down for 2+ minutes before triggering SEV-1

**Timeline**: < 1 minute

### Scenario 4: Add Memory Check to Analyzer

**File**: `k8s/agents-configmap.yaml`

**What to change**:
```yaml
k8s-analyzer.md: |
  ### 5. Memory Usage Alerts

  ```bash
  # New check: Find pods using >80% of limit
  kubectl get pods --all-namespaces -o json | \
    jq '.items[] | select(.spec.containers[].resources.limits.memory)'
  ```
```

**Effect**: Next cycle, analyzer checks memory usage per specification

**Timeline**: < 1 minute

## Verification Commands

### Check ConfigMaps are in sync

```bash
# View orchestrator ConfigMap
kubectl get configmap -n k8s-monitor k8s-monitor-orchestrator -o yaml

# View agent definitions ConfigMap
kubectl get configmap -n k8s-monitor k8s-monitor-agents -o yaml

# Verify both are mounted in pod
kubectl exec -n k8s-monitor deployment/k8s-monitor -- \
  ls -la /app/.claude/

kubectl exec -n k8s-monitor deployment/k8s-monitor -- \
  ls -la /app/.claude/agents/
```

### Check pod sees changes

```bash
# View pod logs (shows which agents are loaded)
kubectl logs -n k8s-monitor -l app=k8s-monitor -f

# For next monitoring cycle, look for:
# "Loading orchestrator context from CLAUDE.md"
# "Discovered agents: k8s-analyzer, escalation-manager, ..."
```

### Verify specific configuration

```bash
# Check orchestrator context was loaded
kubectl exec -n k8s-monitor deployment/k8s-monitor -- \
  grep -i "critical services" /app/.claude/CLAUDE.md

# Check specific agent loaded
kubectl exec -n k8s-monitor deployment/k8s-monitor -- \
  head -20 /app/.claude/agents/k8s-analyzer.md
```

## Safety and Rollback

### Preventing Configuration Errors

**Best Practice 1**: Validate YAML before applying
```bash
# Dry-run test
kubectl apply -f k8s/orchestrator-configmap.yaml --dry-run=client -o yaml

# Server-side validation
kubectl apply -f k8s/orchestrator-configmap.yaml --dry-run=server
```

**Best Practice 2**: Use version control branches
```bash
# Test changes in dev first
git checkout -b feature/update-escalation-policy
# Make changes
git push origin feature/update-escalation-policy
# Test in dev environment

# Then merge to main
git checkout main
git merge feature/update-escalation-policy
git push
```

**Best Practice 3**: Monitor logs after changes
```bash
# Watch logs for any errors
kubectl logs -n k8s-monitor -l app=k8s-monitor -f
```

### Quick Rollback

```bash
# Revert to previous version in git
git revert HEAD~1 k8s/orchestrator-configmap.yaml

# Apply previous version to cluster
git checkout HEAD~1 k8s/orchestrator-configmap.yaml
kubectl apply -f k8s/orchestrator-configmap.yaml

# Or manually restore from kubectl
kubectl patch configmap -n k8s-monitor k8s-monitor-orchestrator \
  --patch '{"data":{"CLAUDE.md":"<previous-content>"}}'
```

## Performance Characteristics

### Configuration Reload Timing

- **ConfigMap update → Pod sees files**: < 1 second (Kubernetes mounts are live)
- **Pod loads new configuration**: On next monitoring cycle start
- **Agent definition reload**: Automatic by SDK
- **Changes take effect**: Within monitoring cycle interval (typically 1 hour)

### Optimization Notes

- ✅ No performance penalty for ConfigMap mounts (read-only)
- ✅ No rebuilds or image operations (faster)
- ✅ SDK automatically reloads agents (no code changes)
- ✅ Can test changes immediately in logs (next cycle)

## Best Practices

### 1. Version Control Everything

```bash
# All ConfigMaps in git
git add k8s/orchestrator-configmap.yaml
git add k8s/agents-configmap.yaml

# Track changes
git log --oneline k8s/orchestrator-configmap.yaml
```

### 2. Add Comments to Document Changes

```yaml
CLAUDE.md: |
  # CHANGE LOG:
  # - 2025-10-20: Added memory threshold checks to k8s-analyzer
  # - 2025-10-19: Increased P1→SEV-2 timeout from 5 to 10 minutes
  # - 2025-10-15: Initial release
```

### 3. Separate Concerns

- **orchestrator-configmap**: Cluster-specific context (ops team)
- **agents-configmap**: Behavior definitions (dev team)
- Change independently, version separately

### 4. Test in Dev First

```bash
# Deploy to dev cluster first
kubectl apply -n k8s-monitor-dev -f k8s/orchestrator-configmap.yaml

# Verify behavior in logs
kubectl logs -n k8s-monitor-dev -l app=k8s-monitor -f

# Then deploy to production
kubectl apply -n k8s-monitor -f k8s/orchestrator-configmap.yaml
```

### 5. Document Customizations

Keep a changelog in the ConfigMap:
```yaml
CLAUDE.md: |
  ## Customization History

  ### 2025-10-20
  - Added vault.unseal as known issue
  - Reason: Post-restart manual unseal required by design

  ### 2025-10-15
  - Initial cluster context created
```

## Troubleshooting

### Issue: Changes not taking effect

**Solution 1**: Verify ConfigMap was applied
```bash
kubectl get configmap -n k8s-monitor k8s-monitor-orchestrator -o yaml | grep "your-change"
```

**Solution 2**: Force pod restart to reload agents
```bash
kubectl delete pod -n k8s-monitor -l app=k8s-monitor
# Pod will restart and reload fresh ConfigMaps
```

**Solution 3**: Check for syntax errors
```bash
# Check pod logs for errors
kubectl logs -n k8s-monitor -l app=k8s-monitor --tail=50

# Validate YAML
kubectl apply -f k8s/orchestrator-configmap.yaml --dry-run=server
```

### Issue: Pod can't read ConfigMap

**Solution**: Verify volume mounts
```bash
kubectl exec -n k8s-monitor deployment/k8s-monitor -- ls -la /app/.claude/

# Should show:
# CLAUDE.md
# agents/
```

### Issue: Kubernetes rejects ConfigMap

**Solution**: Check YAML syntax
```bash
# Validate YAML
kubectl apply -f k8s/orchestrator-configmap.yaml --dry-run=client -o yaml

# Check for YAML formatting issues
yamllint k8s/orchestrator-configmap.yaml
```

## Next Steps

1. **Deploy ConfigMaps**: `kubectl apply -f k8s/orchestrator-configmap.yaml k8s/agents-configmap.yaml`
2. **Verify mounts**: `kubectl exec -n k8s-monitor deployment/k8s-monitor -- ls -la /app/.claude/`
3. **Wait for next cycle**: Monitor logs to confirm configuration loaded
4. **Test update**: Make small change to orchestrator-configmap.yaml, apply, verify in logs
5. **Document in git**: Commit all ConfigMaps and deployment.yaml

## Reference

- **Orchestrator ConfigMap**: `k8s/orchestrator-configmap.yaml`
- **Agent Definitions ConfigMap**: `k8s/agents-configmap.yaml`
- **Deployment**: `k8s/deployment.yaml`
- **Customization Guide**: `docs/AGENT-CUSTOMIZATION-GUIDE.md`
- **Production Deployment**: `docs/PRODUCTION-DEPLOYMENT-GUIDE.md`

---

**Benefits of This Approach**:
✅ No container rebuilds needed
✅ Changes take effect within 1 hour (< 5 seconds with pod restart)
✅ Full version control of all configuration
✅ Easy rollback to previous behavior
✅ Entire team can customize without Docker knowledge
✅ Production-grade flexibility without operational complexity

**You now have enterprise-grade hot-reload configuration! 🚀**
