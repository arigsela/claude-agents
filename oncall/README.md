# OnCall Troubleshooting Agent API

Intelligent troubleshooting agent providing HTTP API endpoints for Kubernetes cluster analysis. Uses Claude LLM with service catalog awareness for context-aware incident response.

## Key Features

- **HTTP API** with 8 RESTful endpoints for n8n integration
- **18 Custom Tools** - Kubernetes, GitHub, AWS, Datadog integration
- **Service Catalog** - Built-in knowledge of service priorities (P0/P1/P2), known issues, dependencies
- **GitOps Awareness** - Correlate incidents with ArgoCD deployments and GitHub PRs
- **Session Management** - Multi-turn conversations with 30-min TTL
- **Security** - API key authentication, rate limiting, CORS

## Quick Start

### Local Development

```bash
pip install -r requirements.txt
cp .env.example .env
# Edit .env with: ANTHROPIC_API_KEY, GITHUB_TOKEN

./run_api_server.sh
open http://localhost:8000/docs  # Swagger UI
```

### Docker

```bash
docker compose up -d
curl http://localhost:8000/health
```

## Architecture

```
src/api/
├── api_server.py      # FastAPI application (8 endpoints)
├── agent_client.py    # Anthropic SDK wrapper with service catalog
├── custom_tools.py    # 18 tools: K8s/GitHub/AWS/Datadog
├── session_manager.py # Session lifecycle (30-min TTL)
└── middleware.py      # Auth & rate limiting
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/query` | POST | Primary troubleshooting endpoint |
| `/session` | POST | Create conversation session |
| `/session/{id}` | GET | Get session with history |
| `/session/{id}` | DELETE | Delete session |
| `/sessions/stats` | GET | Session statistics |
| `/health` | GET | Health check |
| `/docs` | GET | Interactive Swagger UI |

## Custom Tools

### Kubernetes (6 tools)
- `list_namespaces` - Discover namespaces
- `list_pods` - List pods with status/restarts
- `get_pod_logs` - Fetch pod logs
- `get_pod_events` - K8s events for debugging
- `get_deployment_status` - Deployment replica status
- `list_services` - K8s Services with selectors

### GitHub (2 tools)
- `search_recent_deployments` - Find recent GitHub Actions workflows
- `get_recent_commits` - Get repository commit history

### AWS (2 tools)
- `check_secrets_manager` - Verify AWS secrets exist
- `check_ecr_image` - Verify ECR container images

### Analysis (2 tools)
- `analyze_service_health` - Comprehensive health check
- `correlate_deployment_with_incidents` - Link issues to deployments

## Configuration

```bash
# Required
ANTHROPIC_API_KEY=sk-ant-...
GITHUB_TOKEN=ghp_...

# API Configuration
API_PORT=8000
API_KEYS=your-secret-key  # Empty for dev mode (no auth)
SESSION_TTL_MINUTES=30
RATE_LIMIT_AUTHENTICATED=60

# Optional
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
DATADOG_API_KEY=...
```

## Example Queries

```bash
# Basic health check
curl -X POST http://localhost:8000/query \
  -H "X-API-Key: your-key" \
  -d '{"prompt": "Check pod status in default namespace"}'

# Multi-turn conversation
curl -X POST http://localhost:8000/session \
  -H "X-API-Key: your-key" \
  -d '{"user_id": "oncall-engineer"}'
# Returns session_id for follow-up queries
```

## Testing

```bash
pytest tests/api/ -v
./test_query.sh
```

## License

MIT
