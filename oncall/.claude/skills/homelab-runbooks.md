---
name: homelab-runbooks
description: Standard operating procedures for K3s homelab troubleshooting
version: 1.0.0
author: DevOps Team
---

# K3s Homelab Runbooks

Standardized procedures for common troubleshooting scenarios in the K3s homelab cluster.

---

## 🔐 Vault Unsealing Procedure

### When to Use
- After any vault pod restart
- When vault shows "Sealed" status
- When ExternalSecrets show "SecretSyncedError"

### Symptoms
- Pods can't start (waiting for secrets)
- ExternalSecret resources showing errors
- `vault status` shows `Sealed: true`

### Procedure

1. **Check vault pod status**:
   ```bash
   kubectl get pods -n vault
   # Should show: vault-0   0/1 Running (if sealed)
   ```

2. **Verify vault is sealed**:
   ```bash
   kubectl exec -n vault vault-0 -- vault status
   # Look for: Sealed: true
   ```

3. **Manual unseal** (requires unseal keys):
   ```bash
   kubectl exec -n vault vault-0 -- vault operator unseal
   # Enter unseal key when prompted
   # Repeat 3 times (threshold: 3 of 5 keys)
   ```

4. **Verify unsealed**:
   ```bash
   kubectl exec -n vault vault-0 -- vault status
   # Should show: Sealed: false, Initialized: true
   ```

5. **Check ExternalSecrets recovery**:
   ```bash
   kubectl get externalsecrets -A
   # All should show: SecretSynced
   ```

### Notes
- Vault requires manual unsealing after EVERY pod restart (by design)
- This is NOT a bug - architectural choice for security
- Pods with existing secrets can continue running until restart
- Priority: P1 (affects new pod starts, not running pods)

---

## 📦 ECR Authentication Issues

### When to Use
- ImagePullBackOff errors
- "failed to pull image" from ECR
- "Unable to retrieve image pull secrets"

### Symptoms
- Pods stuck in ImagePullBackOff
- Events showing "Failed to pull image from ECR"
- Pod describe shows: `ImagePullBackOff` or `ErrImagePull`

### Procedure

1. **Check ecr-auth cronjob status**:
   ```bash
   kubectl get cronjob -n kube-system ecr-auth
   # Schedule: Every 12 hours
   ```

2. **Verify last cronjob run**:
   ```bash
   kubectl get job -n kube-system --sort-by=.metadata.creationTimestamp | grep ecr-auth
   # Check if run within last 12 hours
   ```

3. **Check ecr-registry secret exists**:
   ```bash
   kubectl get secret -n kube-system ecr-registry
   # Should exist and be recent
   ```

4. **Check if secret synced to namespace**:
   ```bash
   kubectl get secret -n <namespace> ecr-registry
   # Must exist in pod's namespace
   ```

5. **Manual sync if needed**:
   ```bash
   # Copy secret from kube-system to target namespace
   kubectl get secret -n kube-system ecr-registry -o yaml | \
     sed 's/namespace: kube-system/namespace: <target-namespace>/' | \
     kubectl apply -f -
   ```

6. **Verify vault is unsealed** (ecr-auth depends on vault):
   ```bash
   kubectl exec -n vault vault-0 -- vault status
   # Sealed: false (if sealed, unseal first)
   ```

7. **Force cronjob run if needed**:
   ```bash
   kubectl create job -n kube-system ecr-auth-manual --from=cronjob/ecr-auth
   ```

### Root Causes
- **Vault sealed**: ecr-auth can't retrieve AWS credentials
- **Secret not synced**: Missing ecr-registry secret in pod's namespace
- **Expired credentials**: Cronjob didn't run in last 12 hours
- **Wrong image tag**: Check if image actually exists in ECR

### Notes
- ECR credentials expire after 12 hours
- ecr-auth cronjob runs every 12 hours to refresh
- Vault must be unsealed for ecr-auth to work
- Priority: P1 (affects deployments, not running pods)

---

## 🐘 MySQL Troubleshooting

### When to Use
- MySQL pod in CrashLoopBackOff
- chores-tracker-backend can't connect to database
- Database performance issues

### Known Issues
- ⚠️ **Single replica** (no HA) - data loss risk on pod failure
- Has automated S3 backup CronJob
- Memory pressure can cause OOM kills

### Symptoms
- Pod status: CrashLoopBackOff or Error
- chores-tracker-backend logs: "Can't connect to MySQL"
- Health check failures on port 3306

### Procedure

1. **Check pod status**:
   ```bash
   kubectl get pods -n mysql
   kubectl describe pod -n mysql <pod-name>
   ```

2. **Check pod logs**:
   ```bash
   kubectl logs -n mysql <pod-name> --tail=100
   # Look for: initialization errors, OOM, disk space issues
   ```

3. **Check events**:
   ```bash
   kubectl get events -n mysql --sort-by='.lastTimestamp'
   # Look for: OOMKilled, FailedScheduling, FailedMount
   ```

4. **Verify PVC status**:
   ```bash
   kubectl get pvc -n mysql
   # Should be: Bound
   ```

5. **Check resource usage**:
   ```bash
   kubectl top pod -n mysql
   # Look for: high memory usage (near limit)
   ```

6. **Common Fixes**:

   **If OOMKilled**:
   - Increase memory limits in deployment
   - Check for memory leaks in queries
   - Review backup job memory usage

   **If PVC issues**:
   ```bash
   kubectl describe pvc -n mysql <pvc-name>
   # Check for: mount errors, storage class issues
   ```

   **If initialization errors**:
   - Check init container logs
   - Verify database directory permissions
   - Check for corrupted data files

7. **Verify backup job**:
   ```bash
   kubectl get cronjob -n mysql
   kubectl logs -n mysql job/<latest-backup-job>
   ```

### Impact Assessment
- **chores-tracker-backend**: Cannot function (P0 impact)
- **Data loss risk**: Single replica, no HA
- **Recovery time**: Depends on backup age

### Notes
- MySQL is P0 critical (data layer for customer app)
- Single replica = data loss risk on node failure
- S3 backups run daily (verify with cronjob logs)
- Max downtime: 0 minutes (business critical)

---

## 🎯 chores-tracker-backend Slow Startup

### When to Use
- Pod shows "Running" but 0/1 Ready for 3-6 minutes
- Health checks failing during startup
- "Is this normal?" questions

### IMPORTANT: This is NORMAL behavior!

**Expected startup time**: **5-6 minutes** (300-360 seconds)

### Why So Slow?
- Python application with large dependency tree
- FastAPI initialization
- Database connection pool setup
- JWT key generation
- Health check delayed (initialDelaySeconds: 300s)

### Symptoms (All NORMAL during startup)
- Pod status: `0/1 Running` for 3-6 minutes
- Health check failures (expected during initialization)
- Logs show: "Loading dependencies..." or "Initializing..."

### What to Check

1. **Verify it's actually still starting**:
   ```bash
   kubectl get pods -n chores-tracker-backend
   # Check AGE - if < 6 minutes, just wait
   ```

2. **Check if making progress**:
   ```bash
   kubectl logs -n chores-tracker-backend <pod-name> --tail=20
   # Should show ongoing initialization, not stuck
   ```

3. **Only investigate if**:
   - Startup exceeds 10 minutes (abnormal)
   - Logs show errors or exceptions
   - Pod keeps restarting (CrashLoopBackOff)
   - Resource limits exceeded

### NOT Issues
- ✅ Taking 5-6 minutes to reach Ready state
- ✅ Health checks failing during first 5 minutes
- ✅ "Connection refused" on health endpoint initially

### Actual Issues
- ❌ Startup exceeds 10 minutes
- ❌ CrashLoopBackOff (restart count increasing)
- ❌ OOMKilled events
- ❌ Database connection errors after startup

### Notes
- Has 2 replicas for HA (rolling updates are non-disruptive)
- Max downtime: 0 minutes (P0 service)
- Health check uses `/health` endpoint on port 8000
- Dependencies: mysql (required), postgresql (optional)

---

## 🔄 ArgoCD Deployment Correlation

### When to Use
- Pod restart loops (5+ restarts in short time)
- Recent service degradation
- Need to identify what changed

### Symptoms
- Pods restarting frequently after working fine
- New errors appearing in logs
- Performance degradation started recently

### Procedure

1. **Check ArgoCD sync status**:
   ```bash
   # Via ArgoCD UI: https://argocd.yourdomain.com
   # Or via CLI:
   argocd app list
   argocd app get <app-name>
   ```

2. **Check recent ArgoCD syncs**:
   ```bash
   argocd app history <app-name>
   # Look for syncs in last 30 minutes
   ```

3. **Check recent GitHub commits** (kubernetes repo):
   ```bash
   # Via GitHub API or UI
   # Look for commits to: base-apps/<service-name>/
   ```

4. **Correlation window**: 5-30 minutes
   - ArgoCD sync → 3-5 minutes → pods restart
   - If timing matches, likely deployment-related

5. **Identify changes**:
   ```bash
   # Check specific commit
   git show <commit-sha>
   # Focus on: deployment.yaml, configmap.yaml, secrets
   ```

6. **Common deployment issues**:
   - Resource limit changes (memory, CPU)
   - New environment variables
   - Image tag updates
   - ConfigMap/Secret changes
   - Volume mount changes

### Rollback Procedure

1. **Via ArgoCD** (recommended):
   ```bash
   argocd app rollback <app-name> <revision>
   # Or via UI: Application → History → Rollback
   ```

2. **Via Git** (manual):
   ```bash
   # Revert commit in kubernetes repo
   git revert <commit-sha>
   git push origin main
   # Wait 3-5 minutes for ArgoCD sync
   ```

### Notes
- GitOps pattern: All changes via kubernetes repo
- ArgoCD auto-syncs every 3-5 minutes
- Check ArgoCD application health before investigating pods
- Priority: Depends on affected service (P0/P1/P2)

---

## 📊 Common Service Dependencies

### Dependency Chain

```
vault (unsealed)
  ↓
external-secrets-operator → ecr-auth cronjob
  ↓                              ↓
All services                ECR image pulls
  ↓
nginx-ingress → external traffic
```

### Impact Assessment

| Service Down | Immediate Impact | Affected Services | Priority |
|--------------|------------------|-------------------|----------|
| **vault (sealed)** | New pods can't start | All services (new pods only) | P1 |
| **mysql** | Database unavailable | chores-tracker-backend | P0 |
| **nginx-ingress** | Platform-wide outage | ALL external access | P0 |
| **n8n** | Automation broken | Slack bot, workflows | P0 |
| **postgresql** | n8n data layer | n8n (conversation history) | P0 |
| **ecr-auth** | Can't pull images | All ECR-based services | P1 |
| **cert-manager** | TLS cert renewal fails | External HTTPS (eventually) | P1 |

### Troubleshooting Order

1. **Check vault first** (if multiple services failing)
   - Sealed vault blocks ExternalSecrets
   - Affects new pod starts only

2. **Check ingress** (if all external access down)
   - nginx-ingress pods healthy?
   - Ingress resources exist?

3. **Check data layers** (if app-specific issues)
   - mysql for chores-tracker-backend
   - postgresql for n8n

4. **Check GitOps** (if multiple services degraded)
   - Recent ArgoCD syncs?
   - Recent GitHub commits?

---

## 🚨 Priority Classification

### P0 - Business Critical (0 min max downtime)
- chores-tracker-backend
- chores-tracker-frontend
- mysql (data layer)
- n8n (automation)
- postgresql (n8n data)
- nginx-ingress (all traffic)

**Action**: Immediate investigation and escalation

### P1 - Infrastructure (5-15 min max downtime)
- vault (sealed state)
- external-secrets-operator
- cert-manager
- ecr-auth
- crossplane

**Action**: Investigate if affecting P0 or exceeding tolerance

### P2-P3 - Support (hours to days)
- monitoring tools
- test services
- development tools

**Action**: Log only, investigate during business hours

---

## 📝 General Troubleshooting Checklist

For any service issue:

1. ☑️ **Check pod status**: `kubectl get pods -n <namespace>`
2. ☑️ **Check pod events**: `kubectl describe pod -n <namespace> <pod-name>`
3. ☑️ **Check pod logs**: `kubectl logs -n <namespace> <pod-name> --tail=100`
4. ☑️ **Check resource usage**: `kubectl top pod -n <namespace>`
5. ☑️ **Check PVC status**: `kubectl get pvc -n <namespace>` (if persistent)
6. ☑️ **Check dependencies**: Is vault unsealed? Is mysql running?
7. ☑️ **Check recent changes**: ArgoCD syncs? GitHub commits?
8. ☑️ **Check known issues**: Refer to service-specific sections above

---

## 🔗 Related Documentation

- **Service Criticality**: See `docs/reference/services.txt`
- **GitOps Repository**: https://github.com/arigsela/kubernetes
- **ArgoCD**: Manages all deployments via GitOps
- **Backup Procedures**: See individual service runbooks

---

**Last Updated**: 2025-10-23
**Maintainer**: DevOps Team
**Review Frequency**: Quarterly
