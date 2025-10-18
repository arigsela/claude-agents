# Teams Notification Enhancements

**Date**: 2025-10-15
**Related**: 2025-10-15-teams-notification-and-mcp-efficiency.md
**Status**: ✅ Implemented

## Overview

Enhanced Teams notifications to be more actionable and feature-rich, bridging the gap between the concise Teams cards and the detailed monitoring cycle reports.

## Enhancements Implemented

### 1. **Cluster Metrics Overview** ✅
Added real-time cluster health metrics to the main summary card:

**Before**:
```
Cluster Health: CRITICAL
Timestamp: 2025-10-15 15:05:49 UTC
```

**After**:
```
Cluster Health: CRITICAL
Timestamp: 2025-10-15 15:05:49 UTC
Nodes: 39/40 Ready
Pods: 350/355 Running
Namespaces: 24/27 Healthy
Issues Detected: 2
```

**Parsed from**:
- "Node Status: 39/40 Ready"
- "Total: X, Running: Y"
- Section 1 namespace health status emojis

### 2. **Enhanced Issue Details** ✅
Added impact, duration, and better root cause formatting:

**Before**:
```
🔴 1. kube-system/aws-cluster-autoscaler
- Severity: CRITICAL (Jira ticket created)
- Status: CrashLoopBackOff
- Restarts: 568
- Root Cause: Version incompatibility (v1.20.0 on K8s 1.32...
```

**After**:
```
🔴 1. kube-system/aws-cluster-autoscaler 🎫
- Severity: CRITICAL
- Status: CrashLoopBackOff
- Restarts: 568
- Duration: 2 days
- Impact: Cluster autoscaling disabled, manual intervention required
- Root Cause: Version incompatibility (v1.20.0 vs K8s 1.32 = 12-version gap). Exit code 255 indicates goroutine deadlock...
```

**New Fields**:
- `duration`: How long the issue has been active (e.g., "2 days", "35+ hours")
- `impact`: Business/operational impact description
- `jira_ticket`: Visual indicator (🎫) when Jira ticket created for this issue
- `root_cause`: Increased truncation limit from 150 to 200 chars

### 3. **Improved Jira Ticket Section** ✅
Shows actual ticket summary instead of just the key:

**Before**:
```
🎫 Jira Tickets (1 tickets)
DEVOPS-7531: DEVOPS-7531
- Action: Updated
```

**After**:
```
🎫 Jira Tickets (1)
[DEVOPS-7531](https://artemishealth.atlassian.net/browse/DEVOPS-7531) - aws-cluster-autoscaler CrashLoopBackOff
- Action: Updated | Status: Backlog | Priority: Critical
```

**Improvements**:
- Clickable ticket links
- Actual ticket summary extracted from context
- Ticket status and priority (when available)
- Removed redundant count in title ("1 tickets" → "1")

### 4. **Recommendations Section** ✅
Added prioritized P0/P1/P2 recommendations for actionable next steps:

**New Section**:
```
💡 Recommendations

🔥 P0 - Immediate (Next 2-4 hours):
- Upgrade cluster-autoscaler to v1.32.0 or v1.31.x
- Monitor cluster resources manually until autoscaler fixed

⚠️ P1 - This Week:
- Review Kyverno policy violations in artemis-preprod

📋 P2 - Next 1-2 Weeks:
- Remediate Kyverno policy violations via deployment manifest updates
```

**Parsed from**: "Recommendations:" section with P0/P1/P2 subsections

### 5. **Quick Action Buttons** ✅
Added one-click access to relevant dashboards and tools:

**New Buttons**:
- 🎫 **DEVOPS-7531** → Direct link to Jira ticket (top 2 tickets)
- 🚀 **ArgoCD (dev-eks)** → Cluster deployment view
- 📊 **Datadog Cluster View** → Container monitoring dashboard
- ☁️ **AWS EKS Console** → AWS management console for the cluster
- 📄 **Full Report** → Link to detailed report (if `REPORT_VIEWER_URL` configured)

**Example URLs Generated**:
```
ArgoCD: https://argocd-dev.nomihealth.com/applications
Datadog: https://app.datadoghq.com/containers?query=kube_cluster_name%3Adev-eks
AWS Console: https://console.aws.amazon.com/eks/home?region=us-east-1#/clusters/dev-eks
```

### 6. **Cleaned Up Actions Formatting** ✅
Removed duplicate checkmarks that made the text hard to read:

**Before**:
```
⚡ Actions Taken (6)
✅ ✅ Comprehensive diagnostics performed...
✅ ✅ Deep log analysis on cluster-autoscaler...
✅ ⏭️ Comment skipped: Less than 24 hours...
✅ ❌ Auto-remediation NOT APPROVED...
```

**After**:
```
⚡ Actions Taken (6)
✅ Comprehensive diagnostics performed across all critical namespaces
✅ Deep log analysis on cluster-autoscaler (confirmed version incompatibility)
✅ Root cause identified with HIGH confidence
✅ Jira ticket verified: DEVOPS-7531 (already exists, well-documented)
✅ Comment skipped: Less than 24 hours since last update (7 hours ago)
✅ Auto-remediation NOT APPROVED: kube-system requires human approval
```

**Logic**: Strips leading emojis (`✅✓❌⏭️`) from action text, then adds consistent `✅` prefix

## Implementation Details

### New Function Parameters

```python
def send_teams_notification(
    title: str,
    summary: str,
    severity: str = "info",
    critical_issues: list = None,
    jira_tickets: list = None,
    actions_taken: list = None,
    full_summary: str = None,
    cluster_metrics: dict = None,     # NEW
    recommendations: dict = None       # NEW
):
```

### Cluster Metrics Schema

```python
cluster_metrics = {
    'node_count': 40,              # Total nodes in cluster
    'nodes_ready': 39,             # Nodes in Ready state
    'pod_count': 355,              # Total pods across all namespaces
    'pods_running': 350,           # Pods in Running state
    'healthy_namespaces': 24,      # Count of ✅ Healthy namespaces
    'total_namespaces': 27         # Total critical namespaces monitored
}
```

### Recommendations Schema

```python
recommendations = {
    'p0': [                        # Immediate (next 2-4 hours)
        'Upgrade cluster-autoscaler to v1.32.0',
        'Monitor cluster resources manually'
    ],
    'p1': [                        # This week
        'Review Kyverno policy violations'
    ],
    'p2': [                        # Next 1-2 weeks
        'Remediate policy violations via deployment updates'
    ]
}
```

### Issue Schema (Enhanced)

```python
issue = {
    'severity': 'CRITICAL',                           # Existing
    'component': 'aws-cluster-autoscaler',            # Existing
    'namespace': 'kube-system',                       # Existing
    'status': 'CrashLoopBackOff',                     # Existing
    'restart_count': '568',                           # Existing
    'root_cause': 'Version incompatibility...',       # Existing
    'jira_ticket': True,                              # Existing
    'duration': '2 days',                             # NEW
    'impact': 'Cluster autoscaling disabled...'       # NEW
}
```

## Parsing Logic

### Cluster Metrics Extraction

```python
# Node status: "Node Status: 39/40 Ready"
node_status_match = re.search(r'Node(?:\s+Status)?:\s*(\d+)/(\d+)\s*Ready', full_summary)

# Pod counts: "Total: X, Running: Y"
pod_total_match = re.search(r'(?:Total|Pods):\s*(\d+)', full_summary)
pod_running_match = re.search(r'Running:\s*(\d+)', full_summary)

# Namespace health: Count emojis in Section 1
healthy_ns = len(re.findall(r'✅\s*\*\*Healthy\*\*', full_summary))
total_ns = len(re.findall(r'(?:✅|⚠️|❌)\s*\*\*(?:Healthy|Degraded|CRITICAL)\*\*', full_summary))
```

### Recommendations Extraction

```python
# Pattern: "P0 (Next 2-4 hours):" followed by bulleted list
p0_section_match = re.search(r'P0\s*\([^)]+\):([^\n]+(?:\n\s*[-•]\s*[^\n]+)*)', full_summary)
if p0_section_match:
    p0_text = p0_section_match.group(1)
    p0_items = re.findall(r'[-•]\s*([^\n]+)', p0_text)
    recommendations['p0'] = [item.strip() for item in p0_items]
```

### Impact & Duration Extraction

```python
# Duration: "2 days", "35+ hours", "45 minutes"
duration_match = re.search(r'(\d+\+?\s*(?:day|hour|minute)s?)', issue_section)

# Impact: "Impact: Cluster autoscaling disabled..."
impact_match = re.search(r'Impact:?\s*([^\n]+)', issue_section)
```

## Expected Teams Notification Output

```
🔍 Monitoring Cycle #1 Complete
Cluster: dev-eks

Cluster Health: CRITICAL
Timestamp: 2025-10-15 15:05:49 UTC
Nodes: 39/40 Ready
Pods: 350/355 Running
Namespaces: 24/27 Healthy
Issues Detected: 2

─────────────────────────────────────

🚨 Issues Detected (1 Critical, 1 Medium)

🔴 1. kube-system/aws-cluster-autoscaler 🎫
- Severity: CRITICAL
- Status: CrashLoopBackOff
- Restarts: 568
- Duration: 2 days
- Impact: Cluster autoscaling disabled, manual intervention required
- Root Cause: Version incompatibility (v1.20.0 vs K8s 1.32 = 12-version gap). Exit code 255 indicates goroutine deadlock caused by API version mismatch.

🟡 2. artemis-preprod/multiple-pods
- Severity: MEDIUM
- Status: Running (policy violations)
- Impact: Non-blocking (policies in audit mode), pods currently running

─────────────────────────────────────

🎫 Jira Tickets (1)

[DEVOPS-7531](https://artemishealth.atlassian.net/browse/DEVOPS-7531) - aws-cluster-autoscaler CrashLoopBackOff
- Action: Updated | Status: Backlog | Priority: Critical

─────────────────────────────────────

⚡ Actions Taken (6)

✅ Comprehensive diagnostics performed across all critical namespaces
✅ Deep log analysis on cluster-autoscaler (confirmed version incompatibility)
✅ Root cause identified with HIGH confidence
✅ Jira ticket verified: DEVOPS-7531 (already exists, well-documented)
✅ Comment skipped: Less than 24 hours since last update (7 hours ago)
✅ Auto-remediation NOT APPROVED: kube-system requires human approval

─────────────────────────────────────

💡 Recommendations

🔥 P0 - Immediate (Next 2-4 hours):
- Upgrade cluster-autoscaler to v1.32.0 or v1.31.x
- Monitor cluster resources manually until autoscaler fixed

📋 P2 - Next 1-2 Weeks:
- Remediate Kyverno policy violations via deployment manifest updates

─────────────────────────────────────

[🎫 DEVOPS-7531] [🚀 ArgoCD (dev-eks)] [📊 Datadog Cluster View] [☁️ AWS EKS Console]
```

## Configuration

### Required Environment Variables
```bash
# Teams webhook (required)
TEAMS_WEBHOOK_URL=https://...webhook.office.com/...
TEAMS_NOTIFICATIONS_ENABLED=true

# AWS region for console links
AWS_REGION=us-east-1

# Optional: Host reports on web server for direct access
REPORT_VIEWER_URL=https://reports.example.com/eks-monitoring
```

### ArgoCD URL Mapping

Currently hardcoded for dev-eks cluster:
```python
if self.cluster_name == 'dev-eks':
    url = "https://argocd-dev.nomihealth.com/applications"
```

**To extend for other clusters**, add to `.env`:
```bash
ARGOCD_URL_dev-eks=https://argocd-dev.nomihealth.com/applications
ARGOCD_URL_prod-eks=https://argocd.nomihealth.com/applications
ARGOCD_URL_staging-eks=https://argocd-staging.nomihealth.com/applications
```

Then update code to read from environment:
```python
argocd_url = os.getenv(f'ARGOCD_URL_{self.cluster_name.replace("-", "_")}')
if argocd_url:
    potential_actions.append({
        "@type": "OpenUri",
        "name": f"🚀 ArgoCD ({self.cluster_name})",
        "targets": [{"os": "default", "uri": argocd_url}]
    })
```

## Benefits

### For On-Call Engineers
- **Faster Triage**: Cluster metrics visible at a glance (no need to check Datadog/AWS Console)
- **Actionable Steps**: P0/P1/P2 recommendations prioritize work
- **One-Click Access**: Quick action buttons eliminate context switching
- **Better Context**: Impact and duration help assess urgency

### For Management
- **Cluster Health Summary**: "24/27 namespaces healthy" is easier to understand than scrolling through lists
- **Issue Prioritization**: Clear severity breakdown (1 Critical, 1 Medium)
- **Remediation Status**: Actions taken section shows what the agent has done

### For Audit/Compliance
- **Action Trail**: All automated actions visible in Teams channel
- **Jira Integration**: Links to formal incident tickets
- **Recommendation History**: Documented troubleshooting steps

## Comparison: Before vs After

### Before (Cycle #1 Original)
**Sections**: 3
1. Cycle summary (2 facts)
2. Jira tickets (ticket key only)
3. Actions taken (with duplicate emojis)

**Action Buttons**: 1 (Jira ticket link only)
**Total Information**: ~120 words

### After (Cycle #1 Enhanced)
**Sections**: 5-6 (depending on content)
1. Cycle summary (6-7 facts including cluster metrics)
2. Issues detected (with severity breakdown, impact, duration)
3. Jira tickets (with summary, status, priority)
4. Actions taken (cleaned up formatting)
5. Recommendations (P0/P1/P2 prioritized)
6. Infrastructure health (if degraded namespaces > 3)

**Action Buttons**: 4-5
- Jira ticket links (top 2)
- ArgoCD cluster view
- Datadog container monitoring
- AWS EKS Console
- Full report (optional)

**Total Information**: ~300-400 words (3-4x more actionable information)

## Edge Cases Handled

### No Cluster Metrics Available
- Gracefully skips metrics section
- Notification still sends with available data

### No Recommendations
- Skips recommendations section entirely
- Useful for "healthy" cycles where no actions needed

### Multiple Issues (10+)
- Shows first 10 issues only
- Title indicates total: "Issues Detected (5 Critical, 8 High, 12 Medium)"

### Long Root Causes/Impacts
- Truncates at 200 chars for root cause
- Truncates at 150 chars for impact
- Adds "..." to indicate truncation

### Missing Jira Ticket Summary
- Falls back to ticket key if summary can't be extracted
- Still provides clickable link

## Testing Checklist

- [ ] Run monitoring cycle with CRITICAL issues
- [ ] Verify Teams notification includes all 6 sections
- [ ] Click each action button to verify URLs
- [ ] Verify cluster metrics match actual cluster state
- [ ] Verify recommendations parsed from P0/P1/P2 sections
- [ ] Test with 0 issues (healthy cycle)
- [ ] Test with 10+ issues (verify truncation)
- [ ] Test with missing cluster metrics (verify graceful degradation)
- [ ] Test ArgoCD link for dev-eks cluster
- [ ] Verify Datadog link uses correct cluster name

## Future Enhancements

### 1. **Trend Analysis** (Next Sprint)
Add comparison with previous cycle:
```
Cluster Health: CRITICAL (↓ from DEGRADED)
Nodes: 39/40 Ready (↔ no change)
Pods: 350/355 Running (↓ -5 from last cycle)
Issues: 2 (↑ +1 new issue)
```

### 2. **Infrastructure Health Grid** (Visual Enhancement)
For large clusters, add visual health grid:
```
📦 Infrastructure (13 namespaces):
✅✅✅✅✅✅✅✅✅✅✅⚠️❌ (11 healthy, 1 degraded, 1 critical)

🚀 Applications (14 namespaces):
✅✅✅✅✅✅✅✅✅✅✅✅⚠️⚠️ (12 healthy, 2 degraded)
```

### 3. **Smart Suppression** (Reduce Noise)
For HEALTHY cycles, send notifications less frequently:
```python
# Send notification only if:
# - Status changed (DEGRADED → HEALTHY)
# - Issues resolved (>0 → 0)
# - Every 10th cycle (heartbeat)
if overall_status == "HEALTHY":
    send_only_if_status_changed_or_milestone_cycle()
```

### 4. **Cost Impact** (From cost-optimizer)
For resource-related issues, show cost impact:
```
🔴 1. production/api-deployment 🎫
- Severity: CRITICAL
- Status: OOMKilled
- Impact: Service degraded, 30% request failures
- Recommended Fix: Increase memory 1Gi → 2Gi (+$15/month)
- ROI: Prevents $2000/hour in lost revenue
```

### 5. **Deployment Correlation** (From GitHub)
When k8s-github finds correlation, show in issues:
```
🔴 1. production/api-service 🎫
- Severity: CRITICAL
- Status: CrashLoopBackOff
- Duration: 15 minutes
- Deployment Correlation: PR #1234 merged 20 min ago (likely cause)
  └─ [View PR](https://github.com/artemishealth/deployments/pull/1234)
```

### 6. **Adaptive Card Format** (Future)
Migrate from MessageCard (deprecated) to Adaptive Cards for richer formatting:
- Collapsible sections for long content
- Table view for multiple issues
- Action.Submit for remediation approval
- Images/charts for trend data

## Related Files

- `monitor_daemon.py` - Enhanced Teams notification logic (lines 563-839, 1044-1218)
- `docs/fixes/2025-10-15-teams-notification-and-mcp-efficiency.md` - Related bug fixes

## Deployment Notes

No configuration changes required. Enhancements activate automatically on daemon restart.

**Optional**: Set `REPORT_VIEWER_URL` in `.env` to enable "Full Report" button:
```bash
# Example: Host reports via nginx or S3 static site
REPORT_VIEWER_URL=https://eks-reports.example.com
```

Then reports at `/tmp/eks-monitoring-reports/cycle-0001-*.txt` should be accessible at that URL.
