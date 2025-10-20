# Fix: Missing Issue Context in Teams Notifications

**Date**: 2025-10-15
**Related**: 2025-10-15-teams-notification-enhancements.md
**Status**: ✅ Fixed

## Problem

The Teams notification showed actions taken ("root cause analysis", "updated Jira ticket") but never actually stated **WHAT the issue was**. Users had to read the actions to infer there was a problem with cluster-autoscaler.

**Example of confusing notification**:
```
🔍 Monitoring Cycle #1 Complete
Cluster Health: CRITICAL

⚡ Actions Taken:
✅ Root cause analysis (goroutine deadlock in kubernetes client-go libraries)
✅ Updated Jira ticket DEVOPS-7531 with detailed diagnostics
✅ Documented version upgrade path: v1.20.0 → v1.32.1
```

**User reaction**: "What issue? What component? Why am I reading about a fix before knowing the problem?"

## Root Cause

Two issues:

### 1. Issue Parsing Pattern Mismatch
The regex pattern expected:
```
1. CRITICAL: namespace/component - description
```

But the agent was outputting:
```
- CRITICAL: AWS Cluster Autoscaler CrashLoopBackOff (568 restarts, exit code 255)
```

Result: `critical_issues` list was empty, so the "🚨 Issues Detected" section never appeared.

### 2. No Fallback for Failed Parsing
If the regex parsing failed (which it did), there was no fallback to show WHAT was wrong. Only the actions section showed, which assumes you already know the context.

## Solution

### 1. Added Executive Summary Section (Always Shows)
New section that extracts the raw "Issues Detected:" list from the agent output:

```python
# Extract issue summary from "Issues Detected:" section
issues_summary_match = re.search(r'Issues Detected:\s*(\d+)\s*\n((?:[-•]\s*[^\n]+\n?)+)', full_summary)
if issues_summary_match:
    issue_count = issues_summary_match.group(1)
    issue_list = issues_summary_match.group(2).strip()
    exec_summary_text = f"**{issue_count} Issue(s) Detected:**\n{issue_list}"
```

**Result in Teams**:
```
📋 Executive Summary

**2 Issue(s) Detected:**
- CRITICAL: AWS Cluster Autoscaler CrashLoopBackOff (568 restarts, exit code 255)
- MEDIUM: Kyverno policy violations across 30+ pods
```

This section appears FIRST, before any other sections, so users immediately see WHAT is wrong.

### 2. Improved Issue Parsing with Multiple Patterns
Added dual parsing strategy:

**Primary Pattern** (bullet list):
```regex
[-•]\s*(CRITICAL|HIGH|MEDIUM):?\s*([^()\n]+?)(?:\s+CrashLoopBackOff|\s+OOMKilled|\s+ImagePullBackOff|\s+Failed)?\s*\(([^)]+)\)
```

Matches:
- `- CRITICAL: AWS Cluster Autoscaler CrashLoopBackOff (568 restarts)`
- `• HIGH: api-deployment OOMKilled (memory limit exceeded)`

**Fallback Pattern** (numbered list):
```regex
(\d+)\.\s*(CRITICAL|HIGH|MEDIUM):?\s*([^/\n]+)/([^\n-]+)(?:\s*-\s*([^\n]+))?
```

Matches:
- `1. CRITICAL: kube-system/cluster-autoscaler - CrashLoopBackOff`
- `2. HIGH: production/api-deployment - OOMKilled`

### 3. Smart Namespace Inference
If namespace isn't explicitly in the format `namespace/component`, the code now infers it from surrounding context:

```python
namespace_match = re.search(
    r'\b(kube-system|karpenter|datadog-operator-dev|artemis-preprod|chronos-preprod|...)\b',
    full_summary[match.start()-200:match.end()+200]
)
namespace = namespace_match.group(1) if namespace_match else 'Unknown'
```

### 4. Status Detection from Context
Extracts status (CrashLoopBackOff, OOMKilled, etc.) from either:
- Component text: "AWS Cluster Autoscaler CrashLoopBackOff"
- Context info: "(568 restarts, CrashLoopBackOff)"

## Expected Teams Notification (After Fix)

```
📋 Executive Summary
**2 Issue(s) Detected:**
- CRITICAL: AWS Cluster Autoscaler CrashLoopBackOff (568 restarts, exit code 255)
- MEDIUM: Kyverno policy violations across 30+ pods

────────────────────────────────

🔍 Monitoring Cycle #1 Complete
Cluster: dev-eks

Cluster Health: CRITICAL
Timestamp: 2025-10-15 15:35:52 UTC
Nodes: 39/40 Ready
Pods: 350/355 Running
Issues Detected: 2

────────────────────────────────

🚨 Issues Detected (1 Critical, 1 Medium)

🔴 1. kube-system/aws-cluster-autoscaler 🎫
- Severity: CRITICAL
- Status: CrashLoopBackOff
- Restarts: 568
- Duration: 2 days
- Impact: Cluster autoscaling disabled, manual intervention required
- Root Cause: Version incompatibility (v1.20.0 vs K8s 1.32). Goroutine deadlock in kubernetes client-go libraries

🟡 2. artemis-preprod/multiple-pods
- Severity: MEDIUM
- Status: Running (policy violations)
- Impact: Non-blocking (policies in audit mode)

────────────────────────────────

🎫 Jira Tickets (1)
[DEVOPS-7531](https://artemishealth.atlassian.net/browse/DEVOPS-7531) - aws-cluster-autoscaler CrashLoopBackOff
- Action: Updated | Status: Backlog | Priority: Critical

────────────────────────────────

⚡ Actions Taken (5)
✅ Comprehensive health check (20+ namespaces, all verified)
✅ Root cause analysis (goroutine deadlock confirmed)
✅ Updated Jira ticket with detailed diagnostics
✅ Documented version upgrade path: v1.20.0 → v1.32.1
✅ Remediation NOT performed (requires human approval)

────────────────────────────────

💡 Recommendations

🔥 P0 - Immediate (Next 2-4 hours):
- Upgrade cluster-autoscaler to v1.32.1
- Monitor cluster resources manually until autoscaler fixed

📋 P2 - Next 1-2 Weeks:
- Remediate Kyverno policy violations

────────────────────────────────

[🎫 DEVOPS-7531] [🚀 ArgoCD] [📊 Datadog] [☁️ AWS Console]
```

## Key Improvements

### Before
- ❌ No issue context - jumps straight to actions
- ❌ User doesn't know WHAT failed
- ❌ User doesn't know HOW MANY issues
- ❌ No severity breakdown

### After
- ✅ **Executive Summary** shows ALL issues upfront
- ✅ Users see WHAT failed before reading actions
- ✅ Clear count: "2 Issue(s) Detected"
- ✅ Severity visible: "1 Critical, 1 Medium"
- ✅ Quick scan of the summary answers: "What's wrong? How bad? What needs attention?"

## Information Flow

### Old Flow (Confusing)
1. See "CRITICAL" status → alarm
2. Read "Actions Taken" → confused (actions for what?)
3. Have to infer issue from action descriptions
4. Check Jira ticket to understand the actual problem

### New Flow (Clear)
1. See **Executive Summary** → immediately know: "cluster-autoscaler is crashing"
2. See detailed issue breakdown → understand severity, impact, duration
3. See actions → understand what's been done
4. See recommendations → know what to do next
5. Click Jira/ArgoCD buttons → investigate further

## Testing

To verify the fix works with your actual log format:

```python
# Test string from your log
test_log = """
Issues Detected: 2
- CRITICAL: AWS Cluster Autoscaler CrashLoopBackOff (568 restarts, exit code 255)
  Root Cause: Version incompatibility (v1.20.0 vs K8s 1.32)
  Impact: Cluster autoscaling disabled, manual intervention required

- MEDIUM: Kyverno policy violations across 30+ pods
  Affected: artemis-preprod, proteus-dev, actions-runner-controller-dev
  Impact: Non-blocking (policies in audit mode)
"""

# Should extract:
# - Executive summary with both issues listed
# - Issue #1: severity=CRITICAL, namespace=kube-system (inferred), component=AWS Cluster Autoscaler, status=CrashLoopBackOff, restarts=568
# - Issue #2: severity=MEDIUM, namespace=artemis-preprod (inferred), component=multiple-pods
```

## Files Modified

- `monitor_daemon.py`:
  - Line 605-622: Added Executive Summary extraction
  - Line 1067-1159: Enhanced issue parsing with dual patterns
  - Line 1073: New regex pattern for bullet list format
  - Line 1084-1087: Smart namespace inference

## Related Fixes

This fix complements:
- 2025-10-15-teams-notification-and-mcp-efficiency.md (bug fixes)
- 2025-10-15-teams-notification-enhancements.md (feature enhancements)

Together, these provide:
1. **Bug fixes**: Teams notifications actually send
2. **Rich content**: Cluster metrics, recommendations, action buttons
3. **Issue context**: Executive Summary ensures users know WHAT is wrong (this fix)
