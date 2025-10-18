# OnCall Agent API - Complete Deployment Guide

## Deployment Options

You have 3 deployment options:

1. **Local Development** - Direct Python execution
2. **Docker** - Containerized local deployment
3. **Kubernetes** - Production deployment to EKS

## Option 1: Local Development (Already Working!)

```bash
# Install dependencies
pip install -r requirements.txt

# Start API server
./run_api_server.sh

# Test
curl http://localhost:8000/health
```

✅ **You're already using this!**

## Option 2: Docker Deployment

### Build the Image

```bash
./build_api.sh
```

This creates:
- `oncall-agent:latest` - Local image
- Uses multi-stage build with Python + Node
- Supports ARM64 (Mac) and AMD64 (Cloud)

### Run with Docker Compose

**Three run modes available:**

```bash
# API server only
docker compose up oncall-agent-api

# Daemon only (K8s monitoring)
docker compose up oncall-agent-daemon

# Both (API + monitoring)
docker compose up
```

### Configuration

Environment variables from `.env`:

```bash
# Required
ANTHROPIC_API_KEY=sk-ant-...
GITHUB_TOKEN=ghp_...

# API Configuration
API_KEYS=your-secret-key-123  # Leave empty for dev mode
SESSION_TTL_MINUTES=30
MAX_SESSIONS_PER_USER=5
RATE_LIMIT_AUTHENTICATED=60

# AWS (for EKS access from container)
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_REGION=us-east-1
```

### Test Docker Deployment

```bash
# Automated test
./test_docker_api.sh

# Or manually:
docker compose up oncall-agent-api -d
docker compose logs -f oncall-agent-api
curl http://localhost:8000/health
docker compose down
```

### Docker Run Modes

The `docker-entrypoint.sh` script supports:

**API Mode:**
```bash
docker run -e RUN_MODE=api -p 8000:8000 oncall-agent:latest
```

**Daemon Mode:**
```bash
docker run -e RUN_MODE=daemon oncall-agent:latest
```

**Both Modes:**
```bash
docker run -e RUN_MODE=both -p 8000:8000 oncall-agent:latest
```

## Option 3: Kubernetes Deployment

### Prerequisites

1. **EKS Cluster Access** (dev-eks)
2. **kubectl configured:**
   ```bash
   kubectl config current-context  # Should show dev-eks
   ```

3. **ECR Repository** (or other container registry)

4. **Secrets ready:**
   - Anthropic API key
   - GitHub token
   - API keys for authentication

### Step-by-Step Deployment

#### 1. Build and Push Image

```bash
# Build for AMD64 (EKS runs on x86)
docker buildx build \
  --platform linux/amd64 \
  -t YOUR_ECR_REPO/oncall-agent:v1.0.0 \
  --push \
  .

# Or use existing build script and tag
./build_api.sh v1.0.0
docker tag oncall-agent:v1.0.0 YOUR_ECR_REPO/oncall-agent:v1.0.0
docker push YOUR_ECR_REPO/oncall-agent:v1.0.0
```

#### 2. Configure Secrets

**Option A: Edit manifest directly**

Edit `k8s/api-deployment.yaml` and replace:
```yaml
stringData:
  anthropic-api-key: "sk-ant-your-actual-key-here"
  github-token: "ghp_your-actual-token-here"
  api-keys: "n8n-prod-key-123,monitoring-key-456"
```

**Option B: Create secret via kubectl**

```bash
kubectl create secret generic oncall-agent-api-secrets \
  -n oncall-agent \
  --from-literal=anthropic-api-key="sk-ant-..." \
  --from-literal=github-token="ghp_..." \
  --from-literal=api-keys="key1,key2"

# Then remove the Secret from api-deployment.yaml before applying
```

#### 3. Update Image URL

Edit `k8s/api-deployment.yaml`:

```yaml
spec:
  template:
    spec:
      containers:
      - name: api
        image: YOUR_ECR_REPO/oncall-agent:v1.0.0  # ← Update this
```

#### 4. Apply Manifests

```bash
# Dry-run first
kubectl apply -f k8s/api-deployment.yaml --dry-run=client

# Apply for real
kubectl apply -f k8s/api-deployment.yaml
```

#### 5. Verify Deployment

```bash
# Check pods
kubectl get pods -n oncall-agent
# Should show: oncall-agent-api-xxx-xxx  2/2  Running

# Check service
kubectl get svc -n oncall-agent

# View logs
kubectl logs -f deployment/oncall-agent-api -n oncall-agent
```

#### 6. Test API

**From within cluster:**
```bash
# Start test pod
kubectl run test-pod --rm -it --image=curlimages/curl:latest -n oncall-agent -- sh

# Inside pod:
curl http://oncall-agent-api/health
curl -X POST http://oncall-agent-api/query \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-key" \
  -d '{"prompt": "What services are you monitoring?"}'
```

**From local machine (port-forward):**
```bash
kubectl port-forward -n oncall-agent svc/oncall-agent-api 8000:80

# In another terminal:
curl http://localhost:8000/health
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-key" \
  -d '{"prompt": "test"}'
```

### n8n Integration in Kubernetes

**If n8n is in the same cluster:**

Configure n8n HTTP Request tool with:
```
URL: http://oncall-agent-api.oncall-agent.svc.cluster.local/query
Method: POST
Headers: X-API-Key: your-key
Body: { "prompt": "{{ $parameter.prompt }}" }
```

**If n8n is external:**

Option 1: Use Ingress (uncomment in `api-deployment.yaml`)
Option 2: Use port-forward for testing
Option 3: Use LoadBalancer service (change service type)

## Deployment Modes Comparison

| Mode | When to Use | Pros | Cons |
|------|------------|------|------|
| **Local** | Development, testing | Fast iteration, easy debugging | Not HA, manual startup |
| **Docker** | Local staging, team testing | Consistent environment, easy sharing | Still local only |
| **Kubernetes** | Production, n8n integration | HA, auto-scaling, monitoring | More complex setup |

## Production Deployment Checklist

- [ ] Secrets created in Kubernetes
- [ ] Image pushed to ECR with version tag
- [ ] `api-deployment.yaml` updated with correct image URL
- [ ] RBAC permissions verified (ServiceAccount can read K8s resources)
- [ ] Resource limits tuned for your workload
- [ ] API_KEYS configured for authentication
- [ ] CORS_ORIGINS restricted (not `*`)
- [ ] Health checks passing
- [ ] Logs being collected (CloudWatch, DataDog, etc.)
- [ ] Monitoring/alerts configured
- [ ] n8n configured with correct service URL

## Monitoring

### Check Pod Health

```bash
# Pod status
kubectl get pods -n oncall-agent -w

# Describe pod
kubectl describe pod oncall-agent-api-xxx -n oncall-agent

# Check events
kubectl get events -n oncall-agent --sort-by='.lastTimestamp'
```

### View Logs

```bash
# Follow logs
kubectl logs -f deployment/oncall-agent-api -n oncall-agent

# Get logs from all pods
kubectl logs -l app=oncall-agent-api -n oncall-agent --tail=100

# Previous logs (if crashed)
kubectl logs oncall-agent-api-xxx -n oncall-agent --previous
```

### Check API Metrics

```bash
# Port-forward to access API
kubectl port-forward -n oncall-agent svc/oncall-agent-api 8000:80

# Check session stats
curl http://localhost:8000/sessions/stats

# Check health
curl http://localhost:8000/health
```

## Scaling

### Horizontal Scaling

```bash
# Manual scaling
kubectl scale deployment/oncall-agent-api -n oncall-agent --replicas=5

# Or edit deployment
kubectl edit deployment/oncall-agent-api -n oncall-agent
```

### Auto-scaling (HPA)

```bash
kubectl autoscale deployment/oncall-agent-api \
  -n oncall-agent \
  --cpu-percent=70 \
  --min=2 \
  --max=10
```

## Troubleshooting

### Pods Not Starting

```bash
# Check events
kubectl describe pod oncall-agent-api-xxx -n oncall-agent

# Common issues:
# - Image pull errors: Check ECR permissions
# - Secret not found: Verify secret created
# - OOMKilled: Increase memory limits
```

### API Returns 503

```bash
# Check if agent initialized
kubectl logs oncall-agent-api-xxx -n oncall-agent | grep "Agent initialized"

# Common causes:
# - Missing ANTHROPIC_API_KEY
# - Invalid secret values
# - Permissions issues
```

### Rate Limiting Too Aggressive

```bash
# Increase limits
kubectl set env deployment/oncall-agent-api \
  -n oncall-agent \
  RATE_LIMIT_AUTHENTICATED=120
```

## Updates and Rollbacks

```bash
# Update to new version
kubectl set image deployment/oncall-agent-api \
  -n oncall-agent \
  api=YOUR_ECR_REPO/oncall-agent:v1.1.0

# Watch rollout
kubectl rollout status deployment/oncall-agent-api -n oncall-agent

# Rollback if needed
kubectl rollout undo deployment/oncall-agent-api -n oncall-agent

# View history
kubectl rollout history deployment/oncall-agent-api -n oncall-agent
```

## Clean Up

```bash
# Delete everything
kubectl delete -f k8s/api-deployment.yaml

# Or keep RBAC, delete deployment only
kubectl delete deployment,service oncall-agent-api -n oncall-agent
```

---

**Next Steps:**
1. Choose your deployment method
2. Follow the appropriate section above
3. Configure n8n to use the API (see `docs/n8n-integration-complete-guide.md`)
