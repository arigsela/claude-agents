# Agent Customization Guide - Hot-Reload Configuration

**Version**: 1.0
**Date**: 2025-10-20
**Status**: Production Ready ✅

## Overview

One of the most powerful features of k8s-monitor is **agent behavior hot-reload**: you can modify how the monitoring agents behave **without rebuilding or redeploying the container**.

All agent definitions are stored in Kubernetes ConfigMaps and loaded at runtime. This means you can:
- ✅ Update agent instructions
- ✅ Change analysis criteria
- ✅ Modify alert thresholds
- ✅ Customize Slack messages
- ✅ All **without rebuilding the container image**

## Architecture

### Traditional Approach (❌ No Hot-Reload)
```
Source Code → Build Container → Push to Registry → Deploy to K8s → Changes take effect
```
**Time**: 10-15 minutes, requires new image version

### With ConfigMap Strategy (✅ Hot-Reload)
```
ConfigMap → Mount in Pod → Load at Runtime → Changes take effect immediately
```
**Time**: 30 seconds, no image rebuild

## How It Works

### 1. ConfigMap Storage

Agent definitions live in `k8s/agents-configmap.yaml`:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: k8s-monitor-agents
  namespace: k8s-monitor
data:
  k8s-analyzer.md: |
    ---
    name: k8s-analyzer
    description: ...
    ---
    # Your agent instructions...
```

Each key in the ConfigMap becomes a file at runtime:
- `k8s-analyzer.md` → `/app/.claude/agents/k8s-analyzer.md`
- `escalation-manager.md` → `/app/.claude/agents/escalation-manager.md`
- `slack-notifier.md` → `/app/.claude/agents/slack-notifier.md`
- `github-reviewer.md` → `/app/.claude/agents/github-reviewer.md`

### 2. Runtime Loading

The Claude Agent SDK automatically loads agent definitions from `.claude/agents/` directory.

When the deployment reads the ConfigMap:
```bash
kubectl get configmap -n k8s-monitor k8s-monitor-agents -o yaml
# Shows all agent definitions as YAML data
```

### 3. Volume Mount

In `deployment.yaml`:
```yaml
containers:
  - name: k8s-monitor
    volumeMounts:
      - name: agent-definitions
        mountPath: /app/.claude/agents
        readOnly: true

volumes:
  - name: agent-definitions
    configMap:
      name: k8s-monitor-agents
```

## Customization Workflow

### Step 1: Edit ConfigMap

Get the current ConfigMap:
```bash
kubectl get configmap -n k8s-monitor k8s-monitor-agents -o yaml > agents.yaml
```

Edit the file:
```bash
vim agents.yaml
```

Or edit directly in the cluster:
```bash
kubectl edit configmap -n k8s-monitor k8s-monitor-agents
```

### Step 2: Apply Changes

```bash
# If you edited locally
kubectl apply -f agents.yaml

# Or wait for kubectl edit to save
# Changes are immediate!
```

### Step 3: Restart Pod (Optional)

The running pod will pick up changes:
- **On next run**: Pod automatically reads updated agents (SDK reloads .claude/agents/)
- **Immediate effect**: Force restart pod with:
  ```bash
  kubectl delete pod -n k8s-monitor -l app=k8s-monitor
  ```

## Examples

### Example 1: Update k8s-analyzer Instructions

**Scenario**: You want the analyzer to check more aggressively for memory issues.

```bash
# Edit configmap
kubectl edit configmap -n k8s-monitor k8s-monitor-agents

# Find the k8s-analyzer.md section
# Modify the "Look for" section:
# ADD MORE CHECKS or CHANGE THRESHOLDS

# Save (editor will apply automatically if using kubectl edit)
# OR: kubectl apply -f agents.yaml

# Next monitoring cycle, new analyzer runs with updated instructions
```

### Example 2: Modify Slack Alert Format

**Scenario**: You want Slack alerts to include more details or different formatting.

```bash
# Edit the slack-notifier.md section
kubectl edit configmap -n k8s-monitor k8s-monitor-agents

# Modify the "Example Message" section:
# - Add new fields
# - Change emoji indicators
# - Update formatting

# Save and next alert uses new format
```

### Example 3: Change Escalation Policy

**Scenario**: You want to escalate more aggressively (or less aggressively).

```bash
# Edit escalation-manager.md
kubectl edit configmap -n k8s-monitor k8s-monitor-agents

# Modify severity classification thresholds:
# - Lower P1 trigger point for SEV-2
# - Add new escalation rules
# - Change business hours escalation

# Next cycle uses new policy
```

### Example 4: Add GitHub Commit Search

**Scenario**: You want github-reviewer to search older commits (instead of last 30 min).

```bash
# Edit github-reviewer.md
kubectl edit configmap -n k8s-monitor k8s-monitor-agents

# Find "Correlation Window" section
# Change "Last 30 minutes" to "Last 60 minutes"

# Next issue detection with correlation window uses new timeframe
```

## Manual Edit Example

Here's what editing looks like:

```bash
$ kubectl edit configmap -n k8s-monitor k8s-monitor-agents

# Opens your default editor with:

apiVersion: v1
kind: ConfigMap
metadata:
  name: k8s-monitor-agents
  namespace: k8s-monitor
data:
  k8s-analyzer.md: |
    ---
    name: k8s-analyzer
    description: ...
    ---

    # EDIT BELOW HERE

    ### 1. Pod Health
    # ADD/MODIFY KUBECTL COMMANDS

    # MAKE YOUR CHANGES

    # SAVE AND CLOSE (vi: :wq, nano: Ctrl+X, Y, Enter)

# ConfigMap updates immediately
# Pod picks up changes on next cycle
```

## Verification

### Check if Changes Were Applied

```bash
# 1. View current ConfigMap
kubectl get configmap -n k8s-monitor k8s-monitor-agents -o yaml

# 2. Check pod reloaded agents
kubectl logs -n k8s-monitor -l app=k8s-monitor --tail=50

# 3. For next monitoring cycle, look for logs showing updated agent
kubectl logs -n k8s-monitor -l app=k8s-monitor -f
```

### Rollback if Needed

```bash
# Check previous version (if using version control in git)
git checkout k8s/agents-configmap.yaml

# Apply previous version
kubectl apply -f k8s/agents-configmap.yaml

# Or manually restore known-good ConfigMap
kubectl delete configmap -n k8s-monitor k8s-monitor-agents
kubectl apply -f k8s/agents-configmap.yaml
```

## Best Practices

### 1. Version Control Your ConfigMap

Keep `k8s/agents-configmap.yaml` in git:

```bash
# Changes to agent behavior = git commits
git add k8s/agents-configmap.yaml
git commit -m "Update k8s-analyzer to check disk usage"
git push
```

### 2. Comment Your Changes

```yaml
k8s-analyzer.md: |
  ---
  name: k8s-analyzer
  # UPDATED 2025-10-20: Added disk space checks
  # Reason: Saw OOMKilled events due to full disk
  ---
```

### 3. Test Changes in Dev First

```bash
# Edit locally
vim k8s/agents-configmap.yaml

# Deploy to dev cluster
kubectl apply -n k8s-monitor-dev -f k8s/agents-configmap.yaml

# Wait for next monitoring cycle
kubectl logs -n k8s-monitor-dev -l app=k8s-monitor -f

# Verify behavior, then push to prod
kubectl apply -n k8s-monitor -f k8s/agents-configmap.yaml
```

### 4. Document Your Changes

In the ConfigMap itself:

```yaml
data:
  escalation-manager.md: |
    ---
    name: escalation-manager
    ---

    # CHANGE LOG:
    # - 2025-10-20: Lowered P1→SEV-2 threshold from 10 min to 5 min downtime
    # - 2025-10-15: Added vault.unseal as known issue (SEV-4)
    # - 2025-10-10: Initial release
```

## Common Customizations

### Customization 1: Adjust Analysis Scope

**File**: `k8s-analyzer.md`

**What to change**: The kubectl commands in "Analysis Checklist"

```bash
# Current: Checks all namespaces
kubectl get pods --all-namespaces -o wide

# Customize: Check specific namespaces only
kubectl get pods -n chores-tracker-backend -o wide
kubectl get pods -n mysql -o wide
```

**Effect**: Faster analysis, more focused findings

---

### Customization 2: Change Severity Thresholds

**File**: `escalation-manager.md`

**What to change**: The "Severity Classification" section

```markdown
# Current:
SEV-1: Any P0 service down

# Customize to:
SEV-1: Any P0 service down for > 2 minutes
SEV-2: Any P0 service showing errors > 5%
```

**Effect**: Different escalation behavior

---

### Customization 3: Add Slack Details

**File**: `slack-notifier.md`

**What to change**: The "Example Message" section

```markdown
# Add to message:
**Suggested Rollback**:
`kubectl rollout undo deployment/SERVICE -n NAMESPACE`

**Runbook**: See https://wiki.company.com/runbooks/SERVICE
```

**Effect**: Richer, more actionable alerts

---

### Customization 4: Expand GitHub Search

**File**: `github-reviewer.md`

**What to change**: "Correlation Window" section

```markdown
# Current:
Time to check: Last 30 minutes

# Change to:
Time to check: Last 2 hours
```

**Effect**: Catches slower-acting deployment issues

---

## Troubleshooting

### Issue: Changes Don't Take Effect

**Solution 1**: Check if ConfigMap was updated
```bash
kubectl get configmap -n k8s-monitor k8s-monitor-agents -o yaml | grep "your-change"
```

**Solution 2**: Force pod restart to reload agents
```bash
kubectl delete pod -n k8s-monitor -l app=k8s-monitor
# Pod will be recreated with updated ConfigMap
```

**Solution 3**: Check logs for errors
```bash
kubectl logs -n k8s-monitor -l app=k8s-monitor | grep -i error
```

### Issue: ConfigMap Edit Syntax Error

**Solution**: Validate YAML before applying
```bash
# Check local file
kubectl apply -f k8s/agents-configmap.yaml --dry-run=client -o yaml

# Or validate against cluster
kubectl apply -f k8s/agents-configmap.yaml --dry-run=server
```

### Issue: Pod Can't Read ConfigMap

**Solution**: Check volume mount
```bash
# Verify mount is readable
kubectl exec -n k8s-monitor deployment/k8s-monitor -- ls -la /app/.claude/agents/

# Check ConfigMap exists
kubectl get configmap -n k8s-monitor k8s-monitor-agents
```

## Advanced: Direct Kubectl Patch

For quick changes without editing files:

```bash
# Update k8s-analyzer instructions directly
kubectl patch configmap -n k8s-monitor k8s-monitor-agents \
  -p '{"data":{"k8s-analyzer.md":"---\nname: k8s-analyzer\n---\nNEW INSTRUCTIONS HERE"}}'

# List all agent definitions
kubectl get configmap -n k8s-monitor k8s-monitor-agents -o jsonpath='{.data}'
```

## Performance Notes

### Reload Timing

- **ConfigMap Update → Pod Sees Changes**: < 1 second
- **Pod Loads New Agents**: Happens at start of next monitoring cycle
- **Agent Executes New Instructions**: Next cycle (typically within 1 hour)

### Cache Behavior

- ConfigMap is mounted as read-only volume
- SDK re-reads agent definitions each cycle
- No caching of old agent definitions

### No Downtime

- Updating ConfigMap doesn't restart pod
- Pod continues running with current agents
- Changes take effect gracefully on next cycle

## Comparison: ConfigMap vs. Traditional

| Aspect | ConfigMap | Traditional Image Rebuild |
|--------|-----------|---------------------------|
| **Change Time** | < 1 minute | 10-15 minutes |
| **Rebuild Required** | ❌ No | ✅ Yes |
| **Version Control** | ✅ Git config | ✅ Git code + image tags |
| **Rollback Speed** | < 1 minute | 10-15 minutes |
| **Downtime** | ❌ None | ⚠️ Pod restart |
| **Test Before Prod** | ✅ Easy (same code) | ⚠️ Different builds |
| **Learning Curve** | ✅ kubectl edit | ⚠️ Docker, registry |

## Next Steps

1. **Edit agents-configmap.yaml** in git
2. **Deploy to cluster**: `kubectl apply -f k8s/agents-configmap.yaml`
3. **Verify**: `kubectl get configmap -n k8s-monitor k8s-monitor-agents -o yaml`
4. **Wait for next cycle** (or restart pod)
5. **Check logs**: `kubectl logs -n k8s-monitor -l app=k8s-monitor`

## Support

Need help customizing?

1. **Check this guide** for examples
2. **Review agent documentation** in ConfigMap comments
3. **Check logs** for agent execution details
4. **Test changes** in dev cluster first
5. **Document your customization** in git commits

---

**Benefits of This Approach**:
✅ No container rebuilds needed
✅ Changes take effect within 1 hour (< 5 seconds with pod restart)
✅ Full version control of agent behavior
✅ Easy rollback to previous agent definitions
✅ Entire team can customize agents without Docker knowledge
✅ Production-grade flexibility without complexity

**You now have enterprise-grade agent customization! 🚀**
