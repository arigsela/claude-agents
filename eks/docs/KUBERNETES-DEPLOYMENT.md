# Kubernetes Deployment Guide

## Cluster Name Detection

The monitoring agent automatically detects which cluster it's monitoring using this priority:

### Priority 1: CLUSTER_NAME Environment Variable (Override)
```bash
# In .env file (local) or deployment.yaml (Kubernetes)
CLUSTER_NAME=dev-eks
```

**Use when:** You want to override auto-detection (e.g., friendly name vs ARN)

### Priority 2: KUBE_CONTEXT Environment Variable (Specify Context)
```bash
# In .env file (local testing with multiple clusters)
KUBE_CONTEXT=dev-eks
```

**Use when:**
- Local testing with multiple clusters in same kubeconfig
- Want to monitor a specific cluster without switching context
- All subagents will use this context for Kubernetes operations

### Priority 3: Current Kubectl Context (Auto-detect)
```bash
# Reads from:
kubectl config current-context
# Example: "arn:aws:eks:us-east-1:123456789:cluster/dev-eks"
# Extracts: "dev-eks"
```

**Use when:** Single cluster or current context is always correct

### Priority 4: Fallback
```
unknown-cluster
```

## Local Development vs Kubernetes Deployment

### Local Development - Option 1: Use Current Context (Easiest)

**No configuration needed** - auto-detects from current context:
```bash
# Your context is set to dev-eks
kubectl config current-context
# Output: dev-eks

# Agent auto-detects cluster name from this context
python monitor_daemon.py
# Logs:
#   [INFO] Cluster: dev-eks
#   [INFO] Kubectl context: auto-detect from current context
```

**Result:** GitHub issues titled `[dev-eks] Component: Issue`

### Local Development - Option 2: Specify Context Explicitly (Multi-Cluster Testing)

**Set KUBE_CONTEXT** to monitor specific cluster without switching context:

```bash
# Your kubeconfig has multiple clusters:
kubectl config get-contexts
# CURRENT   NAME          CLUSTER       AUTHINFO
# *         staging-eks   staging-eks   staging-user
#           dev-eks       dev-eks       dev-user
#           prod-eks      prod-eks      prod-user

# Set in .env
KUBE_CONTEXT=dev-eks

# Agent uses dev-eks regardless of current context (*)
python monitor_daemon.py
# Logs:
#   [INFO] Cluster: dev-eks
#   [INFO] Kubectl context: dev-eks (explicit)

# All Kubernetes operations use dev-eks context
# Even though staging-eks is marked as current (*)
```

**Benefit:** Monitor dev-eks without switching your working context

**Use case:**
- You're working in staging-eks (current context)
- But want to monitor dev-eks
- Don't want to keep switching contexts

### Kubernetes Deployment (Production)

**Authentication:** In-cluster ServiceAccount (no kubeconfig)

**Deployment manifest (k8s/deployment.yaml):**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: eks-monitoring-agent
  namespace: monitoring
spec:
  template:
    spec:
      # In-cluster authentication
      serviceAccountName: eks-monitoring-agent

      containers:
      - name: agent
        image: your-registry/eks-monitoring-agent:latest
        env:
          # CRITICAL: Set cluster name explicitly
          - name: CLUSTER_NAME
            value: "dev-eks"  # or "staging-eks", "prod-eks"

          # Other config from ConfigMap/Secret
          - name: ANTHROPIC_API_KEY
            valueFrom:
              secretKeyRef:
                name: agent-secrets
                key: anthropic-api-key

          - name: GITHUB_PERSONAL_ACCESS_TOKEN
            valueFrom:
              secretKeyRef:
                name: agent-secrets
                key: github-token

          - name: CHECK_INTERVAL
            value: "300"

          - name: LOG_LEVEL
            value: "NORMAL"

          - name: LOG_TO_FILE
            value: "false"  # Stdout only for Datadog
```

**What happens:**
1. Pod starts with `CLUSTER_NAME=dev-eks` environment variable
2. Agent detects cluster name: `dev-eks` (from env var)
3. Uses in-cluster ServiceAccount for Kubernetes API access
4. Creates issues: `[dev-eks] Component: Issue`
5. Datadog captures all stdout/stderr logs

## Multi-Cluster Deployment

To monitor multiple clusters, deploy separate instances:

```yaml
# dev-eks deployment
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: eks-monitoring-agent-dev
  namespace: monitoring
spec:
  template:
    spec:
      containers:
      - name: agent
        env:
          - name: CLUSTER_NAME
            value: "dev-eks"

---
# staging-eks deployment
apiVersion: apps/v1
kind: Deployment
metadata:
  name: eks-monitoring-agent-staging
  namespace: monitoring
spec:
  template:
    spec:
      containers:
      - name: agent
        env:
          - name: CLUSTER_NAME
            value: "staging-eks"
```

**Result:** GitHub issues clearly labeled:
- `[dev-eks] Karpenter: Missing SQS queue`
- `[staging-eks] AWS LB Controller: IRSA failure`

## Why Cluster Name Matters

### Without Explicit Name
❌ GitHub issue: `AWS Load Balancer Controller: IRSA failure`
- Which cluster? dev? staging? prod?
- Causes confusion when managing multiple environments

### With Cluster Name
✅ GitHub issue: `[dev-eks] AWS Load Balancer Controller: IRSA failure`
- Clear which cluster is affected
- Easier to prioritize and track
- Search/filter issues by cluster

## Verification

After starting the daemon, check logs:

```bash
# Local
python monitor_daemon.py
# Output: [INFO] Cluster: dev-eks

# Kubernetes
kubectl logs deployment/eks-monitoring-agent -n monitoring | head -20
# Output: [INFO] Cluster: dev-eks
```

If you see `Cluster: unknown-cluster`, then:
1. kubectl is not installed/available
2. No kubectl context is set
3. CLUSTER_NAME environment variable not set

**Fix:** Set `CLUSTER_NAME` in `.env` (local) or deployment manifest (Kubernetes).

## Best Practices

### Local Development
- Let auto-detection work (reads from kubectl context)
- Only override with CLUSTER_NAME if testing multi-cluster scenarios

### Kubernetes Production
- **ALWAYS set CLUSTER_NAME explicitly** in deployment manifest
- Don't rely on auto-detection in containers
- Makes deployments portable and clear

### Multi-Environment
- Use ConfigMaps per environment:
  ```yaml
  apiVersion: v1
  kind: ConfigMap
  metadata:
    name: agent-config-dev
  data:
    CLUSTER_NAME: "dev-eks"
    CHECK_INTERVAL: "300"
    LOG_LEVEL: "NORMAL"
  ```

- Reference in deployment:
  ```yaml
  envFrom:
    - configMapRef:
        name: agent-config-dev
  ```
