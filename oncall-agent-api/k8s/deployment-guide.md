# OnCall Agent API - Kubernetes Deployment Guide

## Quick Start

```bash
# 1. Edit api-deployment.yaml and update:
#    - Secrets (ANTHROPIC_API_KEY, GITHUB_TOKEN, API_KEYS)
#    - Image URL (YOUR_ECR_REPO/oncall-agent:latest)

# 2. Apply manifests
kubectl apply -f api-deployment.yaml

# 3. Verify
kubectl get pods -n oncall-agent
kubectl port-forward -n oncall-agent svc/oncall-agent-api 8000:80

# 4. Test
curl http://localhost:8000/health
```

## For n8n Integration

**API URL (from within cluster):**
```
http://oncall-agent-api.oncall-agent.svc.cluster.local/query
```

See `docs/n8n-integration-complete-guide.md` for complete n8n setup.
