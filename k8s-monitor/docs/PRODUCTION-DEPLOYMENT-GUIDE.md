# K3s Monitor - Production Deployment Guide

**Version**: 1.0
**Last Updated**: 2025-10-20
**Status**: Production Ready ✅

---

## Table of Contents

1. [Overview](#overview)
2. [Prerequisites](#prerequisites)
3. [Pre-Deployment Checklist](#pre-deployment-checklist)
4. [Deployment Steps](#deployment-steps)
5. [Verification](#verification)
6. [Configuration](#configuration)
7. [Troubleshooting](#troubleshooting)
8. [Rollback](#rollback)
9. [Monitoring & Operations](#monitoring--operations)

---

## Overview

This guide walks through deploying the k8s-monitor to a production K3s cluster. The deployment includes:

- **Namespace**: `k8s-monitor` (isolated environment)
- **RBAC**: ServiceAccount with ClusterRole (read-only cluster access)
- **Persistent Storage**: 5GB PVC for logs and incident history
- **Security**: NetworkPolicy for ingress/egress control
- **Monitoring**: ServiceMonitor for Prometheus integration (optional)
- **Configuration**: ConfigMap + Secret for environment setup

### Key Manifests

```
k8s/
├── namespace.yaml              # k8s-monitor namespace
├── serviceaccount.yaml         # RBAC configuration
├── configmap.yaml              # Non-sensitive configuration
├── secret.yaml                 # Secrets template (create from this)
├── persistentvolumeclaim.yaml  # 5GB log storage
├── deployment.yaml             # Main pod deployment
├── networkpolicy.yaml          # Security policies
└── servicemonitor.yaml         # Prometheus monitoring (optional)
```

---

## Prerequisites

### Infrastructure Requirements

- **K3s Cluster** v1.21+
- **kubectl** access with admin permissions
- **Container Registry** (or use local images with `imagePullPolicy: Never`)
- **Storage Backend** (K3s default: local-path provisioner)
- **Optional**: Prometheus Operator (for metrics collection)

### Before You Start

```bash
# Verify kubectl access
kubectl cluster-info
kubectl get nodes

# Check available storage classes
kubectl get storageclass

# Verify default storage class exists (K3s uses 'local-path')
kubectl get storageclass -o jsonpath='{.items[0].metadata.name}'
```

---

## Pre-Deployment Checklist

### 1. Container Image Setup

Choose one of these options:

**Option A: Use Pre-built Image** (Recommended for production)
```bash
# Build and push to your registry
docker build -t your-registry/k8s-monitor:v1.0.0 .
docker push your-registry/k8s-monitor:v1.0.0

# Update deployment.yaml:
# image: your-registry/k8s-monitor:v1.0.0
# imagePullPolicy: IfNotPresent
```

**Option B: Use Local Image** (For testing on single-node clusters)
```bash
# Build locally
docker build -t k8s-monitor:v1.0.0 .

# Update deployment.yaml:
# image: k8s-monitor:v1.0.0
# imagePullPolicy: Never
```

**Option C: Load Image into K3s**
```bash
# For K3s, you can load docker images directly
docker save k8s-monitor:v1.0.0 -o k8s-monitor.tar
# Transfer tar file to cluster node
docker load -i k8s-monitor.tar
```

### 2. Create Secrets File

```bash
# Copy the template
cp k8s/secret.yaml k8s/secret.prod.yaml

# Edit with your actual credentials
vim k8s/secret.prod.yaml
```

Required secrets:
- `ANTHROPIC_API_KEY`: Claude API key
- `GITHUB_TOKEN`: GitHub personal access token
- `SLACK_BOT_TOKEN`: Slack bot token
- `SLACK_CHANNEL`: Slack channel ID

### 3. Configure ConfigMap

Edit `k8s/configmap.yaml` for your cluster:

```yaml
data:
  K3S_CONTEXT: "default"                    # Your cluster context name
  MONITORING_INTERVAL_HOURS: "1"            # Monitoring frequency
  LOG_LEVEL: "INFO"                         # INFO, DEBUG, WARNING, ERROR
```

### 4. Plan Storage

```bash
# Check available storage on nodes
kubectl get nodes -o json | jq '.items[].status.allocatable'

# For 5GB logs, ensure you have at least 20GB free on selected nodes
```

---

## Deployment Steps

### Step 1: Create Namespace and RBAC

```bash
# Deploy in order
kubectl apply -f k8s/namespace.yaml

# Verify namespace
kubectl get ns k8s-monitor
```

```bash
# Deploy RBAC (ServiceAccount + ClusterRole + ClusterRoleBinding)
kubectl apply -f k8s/serviceaccount.yaml

# Verify
kubectl get sa -n k8s-monitor
kubectl get clusterrole k8s-monitor
```

### Step 2: Create Storage

```bash
# Deploy PersistentVolumeClaim
kubectl apply -f k8s/persistentvolumeclaim.yaml

# Verify (should show 'Pending' until deployment uses it)
kubectl get pvc -n k8s-monitor
```

### Step 3: Configure Application

```bash
# Deploy ConfigMap
kubectl apply -f k8s/configmap.yaml

# Deploy Secrets (use your prepared secret.prod.yaml)
kubectl apply -f k8s/secret.prod.yaml

# Verify
kubectl get cm -n k8s-monitor
kubectl get secrets -n k8s-monitor
```

### Step 4: Deploy Application

Before deploying, update `k8s/deployment.yaml` with your image:

```yaml
spec:
  template:
    spec:
      containers:
        - name: k8s-monitor
          image: your-registry/k8s-monitor:v1.0.0  # ← Update this
          imagePullPolicy: IfNotPresent             # or 'Never' for local
```

Then deploy:

```bash
# Deploy the main application
kubectl apply -f k8s/deployment.yaml

# Verify deployment
kubectl get deployment -n k8s-monitor
kubectl get pods -n k8s-monitor
```

### Step 5: Apply Security Policies

```bash
# Deploy NetworkPolicy (restrict ingress/egress)
kubectl apply -f k8s/networkpolicy.yaml

# Verify
kubectl get networkpolicy -n k8s-monitor
```

### Step 6: Optional - Enable Monitoring

If you have Prometheus Operator installed:

```bash
# Deploy ServiceMonitor
kubectl apply -f k8s/servicemonitor.yaml

# Verify
kubectl get servicemonitor -n k8s-monitor
```

---

## Verification

### 1. Pod Status

```bash
# Check if pod is running
kubectl get pods -n k8s-monitor -w

# Expected output:
# k8s-monitor-xxxxx   1/1     Running   0          30s
```

### 2. Pod Logs

```bash
# View application logs
kubectl logs -n k8s-monitor -l app=k8s-monitor -f

# Expected output:
# 2025-10-20 14:35:00,123 - __main__ - INFO - K3s Monitor starting...
# 2025-10-20 14:35:00,124 - src.utils.scheduler - INFO - Scheduler starting
```

### 3. Health Check

```bash
# Execute configuration validation
kubectl exec -n k8s-monitor deployment/k8s-monitor -- \
  python -c "from src.config import Settings; s=Settings(); s.validate_all(); print('✓ Configuration valid')"
```

### 4. Storage

```bash
# Verify PVC is bound
kubectl get pvc -n k8s-monitor

# Expected output:
# k8s-monitor-logs   Bound    pvc-xxxxx   5Gi   RWO   local-path   30s
```

### 5. Monitoring Cycle

```bash
# Wait for first cycle (1 hour by default)
# Or check logs for cycle completion

kubectl logs -n k8s-monitor -l app=k8s-monitor --tail=50

# Look for: "Cycle completed: healthy"
```

---

## Configuration

### Environment Variables

Edit `k8s/configmap.yaml`:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: k8s-monitor-config
  namespace: k8s-monitor
data:
  # Kubernetes
  K3S_CONTEXT: "default"

  # Monitoring
  MONITORING_INTERVAL_HOURS: "1"    # Check cluster every 1 hour
  LOG_LEVEL: "INFO"                 # INFO, DEBUG, WARNING, ERROR

  # Model configuration (optional)
  ORCHESTRATOR_MODEL: "claude-sonnet-4-5-20250929"
  K8S_ANALYZER_MODEL: "claude-haiku-4-5-20251001"
  ESCALATION_MANAGER_MODEL: "claude-sonnet-4-5-20250929"
  SLACK_NOTIFIER_MODEL: "claude-haiku-4-5-20251001"
  GITHUB_REVIEWER_MODEL: "claude-sonnet-4-5-20250929"
```

### Secrets

Edit `k8s/secret.prod.yaml`:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: k8s-monitor-secrets
  namespace: k8s-monitor
type: Opaque
stringData:
  ANTHROPIC_API_KEY: "sk-ant-..."          # Get from Anthropic console
  GITHUB_TOKEN: "ghp_..."                   # Create in GitHub settings
  SLACK_BOT_TOKEN: "xoxb-..."               # Create in Slack app
  SLACK_CHANNEL: "C123456789"               # Channel ID (starts with C)
```

---

## Troubleshooting

### Pod Not Starting

```bash
# Check pod status
kubectl describe pod -n k8s-monitor -l app=k8s-monitor

# Check events
kubectl get events -n k8s-monitor --sort-by='.lastTimestamp'

# Common issues:
# - Image pull errors: Check registry access
# - PVC not binding: Check storage class and node resources
# - Secret missing: Verify secret was created
```

### Configuration Errors

```bash
# Validate configuration
kubectl exec -n k8s-monitor deployment/k8s-monitor -- \
  python -c "from src.config import Settings; Settings().validate_all()"

# Check environment variables
kubectl exec -n k8s-monitor deployment/k8s-monitor -- env | grep -E "ANTHROPIC|GITHUB|SLACK"
```

### Network Issues

```bash
# Test DNS resolution
kubectl exec -n k8s-monitor deployment/k8s-monitor -- nslookup api.anthropic.com

# Test API connectivity
kubectl exec -n k8s-monitor deployment/k8s-monitor -- \
  python -c "import requests; print(requests.head('https://api.anthropic.com').status_code)"
```

### Storage Issues

```bash
# Check PVC status
kubectl get pvc -n k8s-monitor -o wide

# Describe PVC for details
kubectl describe pvc -n k8s-monitor k8s-monitor-logs

# Check node disk space
kubectl top nodes
```

---

## Rollback

### Rollback to Previous Deployment

```bash
# View rollout history
kubectl rollout history deployment/k8s-monitor -n k8s-monitor

# Rollback to previous version
kubectl rollout undo deployment/k8s-monitor -n k8s-monitor

# Rollback to specific revision
kubectl rollout undo deployment/k8s-monitor -n k8s-monitor --to-revision=1

# Check rollout status
kubectl rollout status deployment/k8s-monitor -n k8s-monitor
```

### Complete Removal

```bash
# Delete entire deployment (keeps PVC data)
kubectl delete namespace k8s-monitor

# Verify deletion
kubectl get ns k8s-monitor  # Should show error: not found

# To also delete persistent data:
kubectl delete pvc k8s-monitor-logs -n k8s-monitor
```

---

## Monitoring & Operations

### View Logs

```bash
# Current logs
kubectl logs -n k8s-monitor -l app=k8s-monitor -f

# Previous pod logs (if pod crashed/restarted)
kubectl logs -n k8s-monitor -l app=k8s-monitor --previous

# Last 100 lines
kubectl logs -n k8s-monitor -l app=k8s-monitor --tail=100
```

### Access Log Files

```bash
# Port-forward to access persistent logs
kubectl port-forward -n k8s-monitor deployment/k8s-monitor 8080:8080

# In another terminal, copy logs
kubectl cp k8s-monitor/deployment/k8s-monitor:/app/logs ./logs

# Or access directly
kubectl exec -n k8s-monitor deployment/k8s-monitor -- ls -la /app/logs
```

### Monitor Resource Usage

```bash
# CPU and memory usage
kubectl top pod -n k8s-monitor

# Detailed resource info
kubectl get pods -n k8s-monitor -o json | jq '.items[0].spec.containers[0].resources'
```

### Health Status

```bash
# Check pod readiness
kubectl get pods -n k8s-monitor -o jsonpath='{.items[*].status.conditions[?(@.type=="Ready")].status}'

# Check container status
kubectl get pods -n k8s-monitor -o jsonpath='{.items[0].status.containerStatuses[0]}'
```

### Scale Operations

```bash
# Note: k8s-monitor runs as single replica (monitors the cluster, not load-balanced)
# To update without downtime, update deployment and let K8s handle rolling update

# Manual pod restart (if needed)
kubectl delete pod -n k8s-monitor -l app=k8s-monitor

# K8s will automatically create a new pod
```

---

## Maintenance

### Regular Tasks

| Task | Frequency | Command |
|------|-----------|---------|
| Check pod health | Daily | `kubectl get pods -n k8s-monitor` |
| Review logs for errors | Weekly | `kubectl logs -n k8s-monitor -l app=k8s-monitor` |
| Verify storage usage | Monthly | `kubectl exec -n k8s-monitor deployment/k8s-monitor -- du -sh /app/logs` |
| Rotate secrets | Quarterly | Update `k8s/secret.prod.yaml` and redeploy |
| Update container image | As needed | New version → rebuild → push → update deployment |

### Upgrade Process

```bash
# 1. Build new image
docker build -t your-registry/k8s-monitor:v1.1.0 .

# 2. Push to registry
docker push your-registry/k8s-monitor:v1.1.0

# 3. Update deployment image
kubectl set image deployment/k8s-monitor \
  k8s-monitor=your-registry/k8s-monitor:v1.1.0 \
  -n k8s-monitor

# 4. Monitor rollout
kubectl rollout status deployment/k8s-monitor -n k8s-monitor

# 5. Verify new version
kubectl get pods -n k8s-monitor -o jsonpath='{.items[0].spec.containers[0].image}'
```

---

## Support & Issues

### Getting Help

1. Check logs: `kubectl logs -n k8s-monitor -l app=k8s-monitor`
2. Verify configuration: Use troubleshooting section above
3. Review documentation in `docs/` directory
4. Check implementation plan: `docs/IMPLEMENTATION-PLAN.md`

### Reporting Issues

Include:
- Pod logs: `kubectl logs -n k8s-monitor -l app=k8s-monitor --tail=50`
- Pod description: `kubectl describe pod -n k8s-monitor -l app=k8s-monitor`
- Events: `kubectl get events -n k8s-monitor`
- Configuration: `kubectl get configmap,secret -n k8s-monitor`
- Storage status: `kubectl get pvc -n k8s-monitor`

---

## Success Criteria

Deployment is complete when:

- ✅ Pod is running: `kubectl get pods -n k8s-monitor` shows `Running` status
- ✅ Configuration valid: No errors in logs, "Configuration valid" message
- ✅ Storage bound: PVC shows `Bound` status
- ✅ Monitoring started: See "Scheduler starting" in logs
- ✅ First cycle complete: After 1 hour, see "Cycle completed: healthy" (or with findings)
- ✅ Slack notifications working: Check Slack channel for alerts (if configured)

---

**Last Updated**: 2025-10-20
**Next Review**: When deploying to production cluster
