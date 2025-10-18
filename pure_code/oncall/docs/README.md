# OnCall Agent Documentation

## Quick Links

### Getting Started
- **[API Quick Start](api-quick-start.md)** - Get the API running in 5 minutes
- **[Deployment Guide](deployment-guide.md)** - All deployment methods (local/Docker/K8s)
- **[Deployment Modes Explained](deployment-modes-explained.md)** - Daemon vs API vs Both

### n8n Integration
All n8n-related documentation in **[n8n-integrations/](n8n-integrations/)**:
- **[n8n Integration Guide](n8n-integrations/n8n-integration-complete-guide.md)** - Complete setup instructions
- **[n8n Workflow Example](n8n-integrations/n8n-workflow-example.json)** - Import this to n8n
- **[n8n AI Agent Integration](n8n-integrations/n8n-ai-agent-integration.md)** - Architecture and patterns
- **[Implementation Plan](n8n-integrations/n8n-api-wrapper-implementation-plan.md)** - Complete implementation details (Phases 1-3)

## Documentation Structure

### Root Level (Core Guides)
- `api-quick-start.md` - Start here for API usage
- `deployment-guide.md` - All deployment methods
- `deployment-modes-explained.md` - Daemon vs API vs Both
- `README.md` - This file (documentation index)

### n8n-integrations/ (All n8n-Related Docs)
- `n8n-integration-complete-guide.md` - Complete n8n setup
- `n8n-workflow-example.json` - Ready-to-import workflow
- `n8n-ai-agent-integration.md` - Architecture patterns
- `n8n-api-wrapper-implementation-plan.md` - Full implementation plan (Phases 1-3)

## Quick Command Reference

### Local Development
```bash
./run_api_server.sh
curl http://localhost:8000/health
open http://localhost:8000/docs
```

### Docker
```bash
docker compose up -d              # Both modes
docker compose up oncall-agent-api    # API only
docker compose up oncall-agent-daemon # Daemon only
docker compose logs -f
```

### Kubernetes
```bash
kubectl apply -f k8s/api-deployment.yaml
kubectl get pods -n oncall-agent
kubectl port-forward -n oncall-agent svc/oncall-agent-api 8000:80
```

## Need Help?

**For API usage:** Start with `api-quick-start.md`
**For n8n integration:** Start with `n8n-integration-complete-guide.md`
**For deployment:** Start with `deployment-guide.md`
**For understanding modes:** Read `deployment-modes-explained.md`
