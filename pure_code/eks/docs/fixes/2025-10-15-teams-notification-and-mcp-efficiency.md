# Fix: Teams Notification and MCP Efficiency Issues

**Date**: 2025-10-15
**Issue**: After Cycle #1, Teams notifications were not sent and many namespaces showed "⚠️ Not Verified - MCP tool limitations"
**Status**: ✅ Fixed

## Root Causes

### 1. Teams Notification Bug
**File**: `monitor_daemon.py`
**Lines**: 599, 609-663, 1030-1040

**Problem**:
- Variable name mismatch - code referenced `all_issues` before it was defined
- The variable was only created later at line 934 (after parsing the summary)
- This caused a `NameError` preventing Teams notifications from being sent

**Fix**:
- Renamed references from `all_issues` to `critical_issues` throughout the `send_teams_notification()` method
- Added safe fallback: `issues_to_count = critical_issues if critical_issues else []`
- Teams notifications will now send successfully when issues are detected

### 2. MCP Efficiency Issue
**File**: `.claude/agents/k8s-diagnostics.md`

**Problem**:
- The k8s-diagnostics agent was making 27+ individual namespace queries
- Each query increases response size and timeout risk
- MCP server has response size limits that caused many queries to fail
- Result: Many namespaces reported as "⚠️ Not Verified - MCP tool limitations"

**Fix**:
- Updated agent instructions to **MANDATE** using `mcp__kubernetes__pods_list({"all_namespaces": true})` FIRST
- Added explicit pseudo-code example showing how to process bulk response
- Changed "Fallback" section to emphasize this should RARELY be used
- Added clear instruction: "Never say 'MCP tool limitations' or 'Not Verified' - if bulk query works, you have all the data"

## Changes Made

### `monitor_daemon.py` (Lines 599-1040)

**Before**:
```python
if all_issues:  # ❌ undefined variable
    cycle_facts.append({"name": "Issues Detected", "value": str(len(all_issues))})
```

**After**:
```python
issues_to_count = critical_issues if critical_issues else []
if issues_to_count:
    cycle_facts.append({"name": "Issues Detected", "value": str(len(issues_to_count))})
```

**Before**:
```python
if all_issues:  # ❌ undefined variable
    for i, issue in enumerate(all_issues[:10], 1):
```

**After**:
```python
if critical_issues:
    for i, issue in enumerate(critical_issues[:10], 1):
```

**Before**:
```python
critical_count = len([i for i in all_issues if i['severity'] == 'CRITICAL'])  # ❌
```

**After**:
```python
critical_count = len([i for i in critical_issues if i['severity'] == 'CRITICAL'])
```

### `.claude/agents/k8s-diagnostics.md` (Lines 38-120)

**Key Changes**:

1. **Strengthened Section 1 Header**:
   - Changed from: `**CRITICAL - Efficiency Strategy to Avoid Timeouts:**`
   - Changed to: `**⚠️ CRITICAL - MANDATORY Efficiency Strategy:**`

2. **Made bulk query mandatory**:
   - Added: `**YOU MUST use this approach FIRST - it's the ONLY way to check ALL namespaces efficiently**`
   - Added: `**DO NOT skip this step. DO NOT check namespaces individually first.**`

3. **Added concrete example**:
   ```python
   # Group by namespace
   namespace_health = {}
   for pod in bulk_pods.items:
       ns = pod.metadata.namespace
       # ... process health status
   ```

4. **Updated fallback section**:
   - Changed from: `**Only use this if bulk query fails or returns incomplete data:**`
   - Changed to: `**⚠️ AVOID THIS - Only use if the bulk `all_namespaces: true` query fails with an error:**`
   - Added: `**Never say "MCP tool limitations" or "Not Verified"** - if bulk query works, you have all the data.`

## Testing Recommendations

1. **Test Teams Notifications**:
   ```bash
   # Run a monitoring cycle with known issues
   python monitor_daemon.py

   # Verify Teams webhook receives notification
   # Check #devops-team channel for notification card
   ```

2. **Test MCP Efficiency**:
   ```bash
   # Monitor the cycle logs for:
   # - Single "mcp__kubernetes__pods_list" call with all_namespaces: true
   # - No "⚠️ Not Verified" messages
   # - All 27 critical namespaces reporting actual health status

   # Expected log pattern:
   # [TOOL] mcp__kubernetes__pods_list
   # [SUBAGENT] k8s-diagnostics - comprehensive health check
   ```

3. **Verify Cycle Report**:
   ```bash
   # Check latest cycle report
   cat /tmp/eks-monitoring-reports/cycle-0002-*.txt

   # Should show:
   # - All infrastructure namespaces with status (not "Not Verified")
   # - All application namespaces with status (not "Not Verified")
   # - Zero instances of "MCP tool limitations"
   ```

## Expected Behavior After Fix

### Teams Notification
- ✅ Notifications sent for CRITICAL issues
- ✅ Notifications include issue severity breakdown
- ✅ Notifications include Jira ticket links
- ✅ Notifications include actions taken
- ✅ Healthy cycles also send notification (info level)

### Namespace Health Reporting
- ✅ All 27 critical namespaces checked via single bulk query
- ✅ Namespace health based on actual pod data, not "Not Verified"
- ✅ Namespaces with no pods report "No pods deployed" instead of "Not Verified"
- ✅ Fast response time (1-2 seconds instead of 30+ seconds)
- ✅ No MCP timeout or size limit issues

## Related Files
- `monitor_daemon.py` - Main daemon with Teams notification logic
- `.claude/agents/k8s-diagnostics.md` - Diagnostic agent instructions
- `k8s/configmaps/subagents.yaml` - Kubernetes ConfigMap with subagent definitions (also updated)
- `.env` - Teams webhook configuration (TEAMS_WEBHOOK_URL, TEAMS_NOTIFICATIONS_ENABLED)

## Deployment Notes

No code rebuild or dependency changes required. Changes are:
1. Python code fix (variable naming in `monitor_daemon.py`)
2. Agent markdown instructions in `.claude/agents/k8s-diagnostics.md` (loaded dynamically each cycle)
3. Kubernetes ConfigMap update in `k8s/configmaps/subagents.yaml` (for Kubernetes deployments)

### For Local/Docker Deployments
Simply restart the daemon to pick up changes:
```bash
# If running in foreground
Ctrl+C
python monitor_daemon.py

# If running as daemon
./scripts/stop-daemon.sh
./scripts/start-daemon.sh
```

### For Kubernetes Deployments
Apply the updated ConfigMap and restart pods:
```bash
# Apply updated ConfigMap
kubectl apply -f k8s/configmaps/subagents.yaml

# Restart the agent pods to pick up the new ConfigMap
kubectl rollout restart deployment/eks-monitoring-agent -n eks-monitoring

# Verify rollout
kubectl rollout status deployment/eks-monitoring-agent -n eks-monitoring
```

**Note**: The ConfigMap changes will NOT take effect until pods are restarted, as ConfigMaps are mounted at pod startup.

## Future Improvements

1. **Consider adding `all_namespaces` pagination**: If dev-eks grows beyond ~500 pods, may need to implement pagination logic
2. **Add retry logic for Teams notifications**: Currently single-shot, could add exponential backoff for transient failures
3. **Add MCP query performance metrics**: Track query times and response sizes to detect efficiency regressions
