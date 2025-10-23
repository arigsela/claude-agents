---
name: k8s-failure-patterns
description: Use when analyzing Kubernetes pod failures, crash events, OOM issues, or investigating cluster health problems. Provides common failure patterns, their causes, and investigation guidance.
---

# Kubernetes Failure Patterns & Known Issues

This skill provides common Kubernetes failure patterns, their root causes, and service-specific known issues for the K3s homelab cluster.

## Common Pod Status Patterns

### CrashLoopBackOff
**What it means**: Pod starts, crashes, Kubernetes waits progressively longer before restarting

**Common Causes**:
- Application startup error (missing config, failed dependency check)
- Liveness probe failing too early (before app fully initialized)
- Database connection failure
- Missing environment variables or secrets
- Port already in use (multiple containers trying to bind same port)

**Investigation Steps**:
1. Check pod logs: `kubectl logs -n <namespace> <pod-name> --tail=50`
2. Check previous logs if pod restarted: `kubectl logs -n <namespace> <pod-name> --previous`
3. Describe pod for events: `kubectl describe pod -n <namespace> <pod-name>`
4. Look for recent config changes in GitHub

### ImagePullBackOff
**What it means**: Kubernetes cannot pull the container image

**Common Causes**:
- Image doesn't exist (typo in tag or repository)
- Registry authentication failure (expired credentials)
- Network issues reaching registry
- Rate limiting (Docker Hub free tier)
- Wrong registry URL

**Investigation Steps**:
1. Check image name in deployment: `kubectl get deployment -n <namespace> -o yaml | grep image:`
2. Verify image exists in registry (ECR, Docker Hub, etc.)
3. Check imagePullSecrets are present and valid
4. Look for recent image tag updates in GitHub

### OOMKilled
**What it means**: Pod exceeded memory limit and was killed by the kernel

**Common Causes**:
- Memory limit set too low for workload
- Memory leak in application
- Sudden traffic spike causing memory growth
- Resource limits recently reduced (check Git history)
- Large dataset loaded into memory

**Investigation Steps**:
1. Check current memory limits: `kubectl get pod -n <namespace> <pod-name> -o jsonpath='{.spec.containers[0].resources.limits.memory}'`
2. Check actual memory usage before kill: `kubectl describe pod` (look for "Last State: Terminated, Reason: OOMKilled")
3. Review recent changes to resource limits in GitHub
4. Consider memory usage patterns (gradual increase = leak, sudden spike = traffic)

### Pending
**What it means**: Pod accepted by Kubernetes but cannot be scheduled to a node

**Common Causes**:
- No node has enough CPU/memory to satisfy resource requests
- Node selector doesn't match any available nodes
- Persistent volume claim cannot be fulfilled (no available PV)
- Taints/tolerations preventing scheduling
- Node affinity rules preventing placement

**Investigation Steps**:
1. Describe pod for scheduling events: `kubectl describe pod -n <namespace> <pod-name>`
2. Check node resources: `kubectl top nodes`
3. Check resource requests vs available: `kubectl describe nodes`
4. For PVC issues: `kubectl get pvc -n <namespace>`

### Init:Error
**What it means**: Init container failed, main container won't start

**Common Causes**:
- Init container script failure
- Database migration failure
- Volume mount issues
- Required dependency service not available

**Investigation Steps**:
1. Check init container logs: `kubectl logs -n <namespace> <pod-name> -c <init-container-name>`
2. Describe pod for init container events
3. Check if dependent services are healthy (e.g., database for migrations)

### Completed
**What it means**: Container finished execution (exit code 0)

**When this is normal**:
- CronJob pods (should complete)
- Job pods (one-time tasks)

**When this is a problem**:
- Deployment/StatefulSet pods showing Completed (should be Running)
- Application crashed successfully but shouldn't have exited

**Investigation Steps**:
1. Check pod logs to see why it exited
2. Verify deployment type (Job/CronJob vs Deployment)
3. Look for application logic that causes premature exit

## Service-Specific Known Issues

### chores-tracker-backend (P0 - Business Critical)
**Known Issue**: VERY SLOW STARTUP (5-6 minutes)
- **Expected Behavior**: Pods take 5-6 minutes to become Ready
- **Why**: Large initialization process (database migrations, cache warming)
- **Configuration**: `initialDelaySeconds: 300-360s` on health probes
- **Don't Flag As**: Unhealthy if pod age < 6 minutes
- **Architecture**: 2 replicas (HA enabled)

### mysql (P0 - Data Layer)
**Known Issue**: Single Replica (No HA)
- **Risk**: Single point of failure for data layer
- **Mitigation**: Automated S3 backup configured
- **Watch For**: High memory usage (approaching limits)
- **Don't Flag As**: Architecture issue (documented limitation)

### postgresql (P0 - Data Layer)
**Known Issue**: Single Replica (No HA)
- **Risk**: Single point of failure for n8n and other services
- **Mitigation**: Automated backup process
- **Watch For**: Memory pressure, disk usage
- **Don't Flag As**: Architecture issue (documented limitation)

### vault (P1 - Infrastructure)
**Known Issue**: Requires Manual Unsealing After Restart
- **Expected Behavior**: After pod restart, vault is sealed
- **Required Action**: Manual unseal operation by admin
- **Impact**: Pods continue working with existing secrets (external-secrets cached)
- **Don't Flag As**: Incident (this is normal Vault behavior)
- **Max Downtime**: 5-15 minutes (acceptable for P1 service)

### n8n (P0 - Business Critical)
**Dependencies**: PostgreSQL database
- **Watch For**: Database connection errors if postgresql is unhealthy
- **Known Pattern**: If postgresql restarts, n8n may need restart
- **Architecture**: Single replica

### oncall-agent (P0 - Business Critical)
**Architecture**: 2 replicas (HA enabled)
- **Expected**: Both pods should be Running
- **Watch For**: API endpoint health, Python application errors

### nginx-ingress (P0 - Infrastructure)
**Critical Impact**: If down, all external access lost
- **Namespace**: ingress-nginx
- **Watch For**: Pod failures immediately impact all services
- **Priority**: Highest priority for remediation

## Event Types to Focus On

### Critical Events (Always Investigate)
- **OOMKilled**: Memory limit issues
- **FailedScheduling**: Resource constraints
- **BackOff**: Application startup failures
- **Liveness/Readiness probe failures**: Health check issues

### Important Events (Investigate if Recurring)
- **Image pull errors**: Registry or auth issues
- **Volume mount failures**: Storage issues
- **Network errors**: CNI or service mesh issues

### Informational Events (Monitor Trends)
- **Pod scaling events**: Normal autoscaling
- **Certificate renewals**: Expected cert-manager operations
- **Completed Jobs**: Normal CronJob execution

## Investigation Patterns

### Pattern 1: Recent Deployment Correlation
**When**: Pod issues started within 5-30 minutes
**Action**:
1. Check GitHub for recent commits to service manifest
2. Look for resource limit changes
3. Look for image tag updates
4. Check ConfigMap or Secret changes

**High Correlation Indicators**:
- Issue timing matches deployment time
- Change type relates to symptom (e.g., memory limit reduction → OOMKilled)
- No other recent changes

### Pattern 2: Resource Pressure
**When**: Multiple pods showing memory/CPU issues
**Action**:
1. Check node-level resources: `kubectl top nodes`
2. Look for node conditions: MemoryPressure, DiskPressure
3. Check if cluster-wide or node-specific
4. Review cluster autoscaling (if enabled)

### Pattern 3: Dependency Cascade
**When**: Multiple related services failing
**Action**:
1. Identify dependency tree (e.g., backend → database → storage)
2. Start investigation at lowest layer (database/storage)
3. Check if dependent services failing due to upstream issue
4. Remediate root cause first, allow dependent services to recover

### Pattern 4: Known Issue Detection
**When**: Issue matches a known service-specific pattern
**Action**:
1. Cross-reference with service-specific known issues above
2. Verify if behavior is expected (e.g., vault unsealing)
3. Don't escalate if it's documented normal behavior
4. Apply standard remediation if documented

## Quick Reference: Failure → Likely Cause

| Status | First Check |
|--------|-------------|
| CrashLoopBackOff | Logs for startup errors |
| ImagePullBackOff | Image name/tag in deployment YAML |
| OOMKilled | Memory limits in resource spec |
| Pending | Node resources and PVC status |
| Init:Error | Init container logs |
| Evicted | Node disk pressure |
| Error | Describe pod for event details |

## Tips for Effective Troubleshooting

1. **Always check pod age**: Don't flag slow-starting services as unhealthy
2. **Check recent events timeframe**: Focus on last 2 hours for relevance
3. **Correlate timing**: Issue time vs deployment time vs event time
4. **Consider service criticality**: P0 issues are always escalated, P2/P3 may not need immediate action
5. **Look for patterns**: Single pod failure vs cluster-wide issue
6. **Read logs last**: Events and describe output often reveal issue without log diving
7. **Known issues first**: Check if issue matches documented behavior before escalating
