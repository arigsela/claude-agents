# K3s Monitor - Deployment Cheat Sheet

Quick reference for deploying k8s-monitor to production.

## ⚡ Quick Deploy (5 minutes)

```bash
# 1. Prepare secrets file
cp k8s/secret.yaml k8s/secret.prod.yaml
# Edit with: ANTHROPIC_API_KEY, GITHUB_TOKEN, SLACK_BOT_TOKEN, SLACK_CHANNEL

# 2. Deploy all manifests (in order)
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/serviceaccount.yaml
kubectl apply -f k8s/persistentvolumeclaim.yaml
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/secret.prod.yaml
# Update deployment.yaml with your image first!
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/networkpolicy.yaml
kubectl apply -f k8s/servicemonitor.yaml  # Optional: only if Prometheus Operator

# 3. Verify
kubectl get pods -n k8s-monitor -w
kubectl logs -n k8s-monitor -l app=k8s-monitor -f
```

## 📋 Complete Manifest List

| File | Purpose | Required? | Size |
|------|---------|-----------|------|
| `namespace.yaml` | Create k8s-monitor namespace | ✅ YES | 108B |
| `serviceaccount.yaml` | RBAC (SA + ClusterRole + binding) | ✅ YES | 1.4KB |
| `configmap.yaml` | Non-sensitive configuration | ✅ YES | 870B |
| `secret.yaml` | Credentials template | ✅ YES | 632B |
| `persistentvolumeclaim.yaml` | 5GB log storage | ✅ YES | 411B |
| `deployment.yaml` | Main pod deployment | ✅ YES | 3.5KB |
| `networkpolicy.yaml` | Security (ingress/egress) | ⚠️ RECOMMENDED | 2.0KB |
| `servicemonitor.yaml` | Prometheus integration | ⏸️ OPTIONAL | 1.5KB |

**Total size**: ~10KB (excluding application image)

## 🚀 Deployment Workflow

```
1. namespace.yaml          Create namespace
   ↓
2. serviceaccount.yaml     Set up RBAC
   ↓
3. persistentvolumeclaim   Create storage
   ↓
4. configmap.yaml          Add configuration
5. secret.yaml             Add credentials
   ↓
6. deployment.yaml         Deploy application
   ↓
7. networkpolicy.yaml      Secure network
   ↓
8. servicemonitor.yaml     (Optional) Enable Prometheus
```

## ✅ Verification Commands

```bash
# Check all resources
kubectl get all -n k8s-monitor

# Pod status
kubectl get pods -n k8s-monitor

# Logs (follow)
kubectl logs -n k8s-monitor -l app=k8s-monitor -f

# Storage status
kubectl get pvc -n k8s-monitor

# RBAC
kubectl get sa,clusterrole,clusterrolebinding -n k8s-monitor

# Security policies
kubectl get networkpolicy -n k8s-monitor

# Prometheus (if available)
kubectl get servicemonitor -n k8s-monitor

# Events
kubectl get events -n k8s-monitor --sort-by='.lastTimestamp'
```

## 🔧 Common Tasks

### View Configuration
```bash
kubectl get cm -n k8s-monitor k8s-monitor-config -o yaml
```

### Update Secrets
```bash
# Edit secret
kubectl edit secret -n k8s-monitor k8s-monitor-secrets

# Or replace entirely
kubectl delete secret -n k8s-monitor k8s-monitor-secrets
kubectl apply -f k8s/secret.prod.yaml
```

### Update Configuration
```bash
# Edit configmap
kubectl edit cm -n k8s-monitor k8s-monitor-config

# Or replace
kubectl delete cm -n k8s-monitor k8s-monitor-config
kubectl apply -f k8s/configmap.yaml
```

### Update Image
```bash
# New version
docker build -t your-registry/k8s-monitor:v1.1.0 .
docker push your-registry/k8s-monitor:v1.1.0

# Update deployment
kubectl set image deployment/k8s-monitor \
  k8s-monitor=your-registry/k8s-monitor:v1.1.0 \
  -n k8s-monitor

# Monitor rollout
kubectl rollout status deployment/k8s-monitor -n k8s-monitor
```

### Check Logs
```bash
# Current
kubectl logs -n k8s-monitor -l app=k8s-monitor

# Previous (if crashed)
kubectl logs -n k8s-monitor -l app=k8s-monitor --previous

# All events
kubectl get events -n k8s-monitor -o wide
```

### Access Data
```bash
# Copy logs locally
kubectl cp k8s-monitor/deployment/k8s-monitor:/app/logs ./logs -n k8s-monitor

# Or list files
kubectl exec -n k8s-monitor deployment/k8s-monitor -- ls -la /app/logs
```

## 🎯 Success Indicators

```bash
# All should show ✅

# 1. Pod running
kubectl get pods -n k8s-monitor  # Status: Running

# 2. PVC bound
kubectl get pvc -n k8s-monitor   # Status: Bound

# 3. No errors in logs
kubectl logs -n k8s-monitor -l app=k8s-monitor | grep -i error

# 4. Configuration valid
kubectl logs -n k8s-monitor -l app=k8s-monitor | grep "Configuration valid"

# 5. Scheduler started
kubectl logs -n k8s-monitor -l app=k8s-monitor | grep "Scheduler starting"
```

## 🆘 Troubleshooting

```bash
# Pod not running?
kubectl describe pod -n k8s-monitor -l app=k8s-monitor

# Image pull error?
kubectl get events -n k8s-monitor | grep -i image

# Config error?
kubectl exec -n k8s-monitor deployment/k8s-monitor -- \
  python -c "from src.config import Settings; Settings().validate_all()"

# Network issue?
kubectl exec -n k8s-monitor deployment/k8s-monitor -- \
  python -c "import requests; print(requests.head('https://api.anthropic.com'))"

# Storage issue?
kubectl get pvc -n k8s-monitor -o wide
kubectl describe pvc -n k8s-monitor k8s-monitor-logs
```

## 🔄 Rollback

```bash
# See history
kubectl rollout history deployment/k8s-monitor -n k8s-monitor

# Rollback
kubectl rollout undo deployment/k8s-monitor -n k8s-monitor
```

## 🗑️ Complete Removal

```bash
# Delete everything (keeps PVC data)
kubectl delete namespace k8s-monitor

# Also delete persistent data
kubectl delete pvc -n k8s-monitor k8s-monitor-logs
```

## 📞 For Full Details

See: `docs/PRODUCTION-DEPLOYMENT-GUIDE.md`
