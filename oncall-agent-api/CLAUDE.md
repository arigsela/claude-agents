# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is an **Intelligent On-Call Troubleshooting Agent API** built with FastAPI and Claude LLM. It provides REST API endpoints for Kubernetes incident analysis, cluster health checks, and intelligent remediation recommendations.

**Key Architecture**: The agent uses **direct API access** (kubernetes, PyGithub, boto3, Datadog) with Claude LLM providing intelligent analysis through the Anthropic API. All functionality is exposed via FastAPI endpoints.

**Key Capabilities**:
- REST API for on-demand incident analysis
- Kubernetes cluster health monitoring via API endpoints
- Two-turn LLM investigation methodology for deep analysis
- AWS resource verification (Secrets Manager, ECR)
- GitHub deployment correlation
- Datadog metrics integration for historical analysis
- NAT gateway traffic analysis
- Slack integration (`/oncall` slash commands + proactive incident alerts)

## Development Environment Setup

### Initial Setup
```bash
# Navigate to project
cd /Users/ari.sela/git/claude-agents/oncall-agent-api

# Activate virtual environment
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with: ANTHROPIC_API_KEY, GITHUB_TOKEN, AWS credentials
```

### Required Environment Variables
- `ANTHROPIC_API_KEY`: **REQUIRED** - Claude API key for LLM analysis. The incident triage engine will fail to start without this.
- `ANTHROPIC_MODEL`: Claude model to use (default: "claude-sonnet-4-5-20250929")
- `GITHUB_TOKEN`: GitHub PAT with repo and workflow access
- `K8S_CONTEXT`: Kubernetes context (default: "dev-eks")
- `ALLOWED_CLUSTERS`: Comma-separated list of allowed clusters (default: "dev-eks")
- `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`: For EKS authentication
- `DATADOG_API_KEY` / `DATADOG_APP_KEY`: Datadog credentials for metrics queries (optional)

## Common Commands

### Running the API Server

**Local Development** (with hot reload):
```bash
# Start API server
uvicorn src.api.server:app --reload --host 0.0.0.0 --port 8000

# Or use the helper script
./run_api.sh
```

**Docker** (production):
```bash
# Build and run with docker-compose
docker compose up              # Foreground with logs
docker compose up -d           # Background
docker compose logs -f         # Watch logs
docker compose down            # Stop

# Build container manually
docker build -t oncall-agent-api .
./build.sh                     # Helper script
```

**Testing the API**:
```bash
# Health check
curl http://localhost:8000/health

# List available endpoints
curl http://localhost:8000/

# Analyze an incident
curl -X POST http://localhost:8000/incident \
  -H "Content-Type: application/json" \
  -d '{"pod_name": "proteus-api-abc123", "namespace": "proteus-dev"}'

# Check cluster health
curl http://localhost:8000/cluster/health

# Get pod logs
curl "http://localhost:8000/pod/logs?namespace=proteus-dev&pod_name=proteus-api-abc123"
```

### Testing

**Note**: Test infrastructure is configured but tests are not yet implemented.

```bash
# Run quick validation tests
./test_agent.sh

# When tests are implemented:
pytest                                    # Run all tests
pytest --cov=src --cov-report=html       # With coverage
pytest tests/test_api.py                 # Specific test
```

### Code Quality
```bash
black src/                     # Format code
ruff check src/                # Lint code
mypy src/                      # Type checking
```

### Container Operations
```bash
# Build container
docker build -t oncall-agent-api .
./build.sh                     # Helper script

# Generate kubeconfig for containers
./scripts/generate_container_kubeconfig.sh
```

## Project Architecture

### Directory Structure

```
oncall-agent-api/
├── src/
│   ├── api/                    # FastAPI application
│   │   ├── server.py           # MAIN ENTRY POINT - FastAPI server
│   │   ├── endpoints/          # API route handlers
│   │   │   ├── incident.py     # Incident analysis endpoint
│   │   │   ├── cluster.py      # Cluster health endpoints
│   │   │   ├── pod.py          # Pod operations endpoints
│   │   │   └── nat_gateway.py  # NAT gateway analysis endpoints
│   │   └── models/             # Pydantic request/response models
│   ├── tools/                  # Helper modules
│   │   ├── k8s_analyzer.py     # Kubernetes analysis helpers
│   │   ├── github_integrator.py # GitHub deployment correlation
│   │   ├── datadog_integrator.py # Datadog metrics queries
│   │   ├── nat_gateway_analyzer.py # NAT gateway traffic analysis
│   │   └── zeus_job_correlator.py # Zeus refresh job correlation
│   └── config/                 # Configuration management
├── config/                     # Configuration files
│   └── service_mapping.yaml    # Service → GitHub repo mapping
├── tests/                      # Test suite (infrastructure ready)
├── scripts/                    # Utility scripts
└── docs/                       # Documentation
```

### Core Components

**`src/api/server.py`** - FastAPI application
- Main entry point for API server
- Configures routes, middleware, CORS
- Provides OpenAPI documentation at `/docs`

**`src/api/endpoints/`** - API route handlers
- `incident.py`: POST /incident - Analyze Kubernetes incidents
- `cluster.py`: GET /cluster/health - Check cluster health
- `pod.py`: GET /pod/logs - Retrieve pod logs
- `nat_gateway.py`: GET /nat-gateway/analyze - Analyze NAT traffic

**`src/tools/`** - Helper modules (not MCP servers)
- `k8s_analyzer.py`: Kubernetes cluster analysis helpers
- `github_integrator.py`: GitHub deployment correlation logic
- `datadog_integrator.py`: Datadog metrics queries for historical analysis
- `nat_gateway_analyzer.py`: NAT gateway traffic analysis
- `zeus_job_correlator.py`: Zeus refresh job correlation

### API Endpoints

**Core Endpoints**:

```
GET  /                    - List all available endpoints
GET  /health              - Health check (liveness probe)
GET  /ready               - Readiness check

POST /incident            - Analyze Kubernetes incident
  Body: {
    "pod_name": "string",
    "namespace": "string",
    "severity": "critical|high|medium|low" (optional)
  }
  Response: {
    "status": "success",
    "severity": "critical",
    "analysis": {...},
    "recommendations": [...]
  }

GET  /cluster/health      - Check cluster health
  Query: ?namespace=proteus-dev (optional)
  Response: {
    "status": "healthy|degraded|critical",
    "pod_health": {...},
    "issues": [...]
  }

GET  /pod/logs            - Get pod logs
  Query: ?namespace=proteus-dev&pod_name=proteus-api-abc123&tail_lines=100
  Response: {
    "logs": "...",
    "container": "main",
    "pod_name": "..."
  }

GET  /nat-gateway/analyze - Analyze NAT gateway traffic
  Response: {
    "traffic_analysis": {...},
    "top_consumers": [...],
    "recommendations": [...]
  }
```

**OpenAPI Documentation**: Available at `http://localhost:8000/docs` when server is running.

### Data Flow

```
API Request (e.g., POST /incident)
    ↓
FastAPI Endpoint Handler (src/api/endpoints/incident.py)
    ↓
Service Enrichment (service_mapping.yaml → GitHub repo, criticality)
    ↓
Turn 1: Claude Initial Assessment (severity, investigation plan)
    ↓
Data Collection (logs, events, AWS verification, GitHub correlation)
    ↓
Turn 2: Claude Refined Analysis (root cause, specific remediation)
    ↓
JSON Response with Analysis + Recommendations
```

### Key Design Patterns

**1. Cluster Protection** (Configurable via environment):
- `ALLOWED_CLUSTERS` env var controls which clusters are permitted (comma-separated)
- Defaults to `dev-eks` if not set
- Unauthorized cluster access raises `ValidationError` with 422 response

**2. Service Mapping** (`config/service_mapping.yaml`):
- Maps K8s pod names → GitHub repositories
- Defines criticality levels (critical/high/medium)
- Used for enrichment and correlation

## Important Concepts

### API-First Architecture

This project is designed as a **REST API** that other services can integrate with:
- **Synchronous**: All endpoints return results immediately
- **Stateless**: No session management or background processing
- **JSON-based**: All requests and responses use JSON
- **OpenAPI**: Full API documentation available at `/docs`

The API uses **Anthropic API** directly for LLM analysis (no Claude Agent SDK) with direct K8s/GitHub/AWS API integration.

### Severity Classification

Severity levels:
- **Critical**: Service outage, OOMKilled with 10+ restarts, immediate action
- **High**: CrashLoopBackOff, 3+ restarts, automated remediation
- **Medium**: Warning signs, 1-2 restarts, queue for review
- **Low**: Informational, document and learn

### AWS Integration

The agent verifies AWS resources when diagnosing incidents:
- **Secrets Manager**: Checks if ExternalSecret references exist
- **ECR**: Verifies container images exist (ImagePullBackOff diagnosis)
- **CloudWatch**: NAT gateway traffic metrics

Requires AWS credentials in environment for boto3 access.

### Datadog Integration

The agent queries Datadog for historical Kubernetes metrics:
- **CPU/Memory Trends**: Track resource usage over time (hours to weeks)
- **Network Traffic**: Analyze pod-level network patterns
- **Memory Leak Detection**: Identify gradual memory increases
- **Performance Correlation**: Compare metrics before/after deployments

**Available Tools**:
- `query_datadog_metrics`: Query any Datadog metric with filtering
- `get_resource_usage_trends`: Batch query CPU/memory for trend analysis
- `check_network_traffic`: Network TX/RX with totals in GB

Requires `DATADOG_API_KEY` and `DATADOG_APP_KEY` in environment. See `docs/datadog-integration.md` for full guide.

## Testing Strategy

When implementing tests:
- **Unit Tests**: Test individual triage rules, severity classification
- **Integration Tests**: Mock Anthropic API responses, K8s events
- **API Tests**: Test FastAPI endpoints with pytest and httpx
- **E2E Tests**: Use pytest fixtures for full incident workflows
- **Coverage Target**: Focus on `src/api/endpoints/` and `src/api/agent_client.py`

Use `pytest-asyncio` for async test support.

## Deployment Modes

### Local Development (API Server)
```bash
# Start API server with hot reload
uvicorn src.api.server:app --reload --host 0.0.0.0 --port 8000

# Or use helper script
./run_api.sh
```

### Docker (Local/Production)
```bash
# Run with docker-compose
docker compose up                # Foreground
docker compose up -d             # Background
```

### Production (Kubernetes)
```bash
# Deploy API server to Kubernetes
kubectl apply -f k8s/
kubectl logs -f deployment/oncall-agent-api -n oncall-agent

# Check API health
kubectl port-forward -n oncall-agent svc/oncall-agent-api 8000:8000
curl http://localhost:8000/health
```

Requires:
- Kubernetes RBAC (serviceAccount with read access)
- AWS IAM authentication (for EKS)
- Secrets for ANTHROPIC_API_KEY, GITHUB_TOKEN
- Ingress/Service for external access

## Safety and Guardrails

**Configurable Cluster Protection**:
- `ALLOWED_CLUSTERS` env var controls permitted clusters (comma-separated, default: "dev-eks")
- Set via Kubernetes ConfigMap for production deployments
- Unauthorized cluster access returns 422 validation error

**API Rate Limiting**:
- Can be implemented via middleware if needed
- Currently unlimited for internal use

**Audit Trail**:
- All API requests logged with timestamps
- LLM interactions logged for debugging
- No automated actions (recommendations only)

**Read-Only Operations**:
- All API endpoints are read-only
- No cluster modifications permitted
- GitOps workflow for any changes

## Configuration Files

### `config/service_mapping.yaml`
Maps service names to GitHub repos and criticality:
```yaml
service_mappings:
  proteus:
    github_repo: artemishealth/proteus
    criticality: critical
    health_check_endpoint: /api/proteus/.well-known/ready
```

## Common Patterns

### Adding a New Service to Monitor

1. **Add to service mapping** (`config/service_mapping.yaml`):
   ```yaml
   new-service:
     github_repo: artemishealth/new-service
     criticality: high
     health_check_endpoint: /health
   ```

2. **Update monitoring config** (`config/k8s_monitoring.yaml`):
   - Add namespace if needed
   - Service will be auto-detected by pod name matching

3. **Test**:
   ```bash
   curl -X POST http://localhost:8000/incident \
     -H "Content-Type: application/json" \
     -d '{"pod_name": "new-service-abc123", "namespace": "new-service-dev"}'
   ```

### Adding a New API Endpoint

1. **Create endpoint handler** in `src/api/endpoints/`:
   ```python
   from fastapi import APIRouter

   router = APIRouter()

   @router.get("/new-endpoint")
   async def new_endpoint():
       return {"status": "success"}
   ```

2. **Register in server.py**:
   ```python
   from src.api.endpoints import new_endpoint
   app.include_router(new_endpoint.router)
   ```

3. **Add request/response models** in `src/api/models/` if needed

4. **Test**:
   ```bash
   curl http://localhost:8000/new-endpoint
   ```

### Extending Alert Rules

Edit `config/k8s_monitoring.yaml`:
```yaml
alert_rules:
  - name: custom-rule
    conditions:
      event_reason: ["CustomError"]
      restart_count_threshold: 5
    severity: high
    investigation_priority: 2
```

The triage engine will automatically evaluate new rules.

## Troubleshooting

### "Import errors" when running API
```bash
# Ensure PYTHONPATH includes src/
export PYTHONPATH="${PYTHONPATH}:$(pwd)/src"
# Or run from project root
cd /Users/ari.sela/git/claude-agents/oncall-agent-api
```

### "Permission denied" for cluster
- Check `K8S_CONTEXT` is set to `dev-eks`
- Verify you're not targeting protected clusters
- Review cluster protection in code

### "ANTHROPIC_API_KEY not found" or "ANTHROPIC_API_KEY environment variable is required"
- This is a **hard requirement** - the incident triage engine will not start without it
- Ensure `.env` file exists with valid key
- Check environment variable is loaded: `echo $ANTHROPIC_API_KEY`
- The API uses LLM for incident analysis - there is no rule-based fallback

### Docker container can't access EKS
- Set AWS credentials in `.env`: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`
- Generate container kubeconfig: `./scripts/generate_container_kubeconfig.sh`
- Mount kubeconfig in docker-compose.yml

### API returns 500 errors
- Check API logs: `docker compose logs -f` or `uvicorn` output
- Verify all required environment variables are set
- Test connectivity to K8s cluster: `kubectl cluster-info`
- Check Anthropic API key is valid

### API documentation not loading
- Ensure server is running: `curl http://localhost:8000/health`
- Access OpenAPI docs at: `http://localhost:8000/docs`
- Redoc alternative: `http://localhost:8000/redoc`

## Important Notes

1. **Project Location**: Currently at `/Users/ari.sela/git/claude-agents/oncall-agent-api`. This is the API-only version of the oncall agent.

2. **API-Only Architecture**: This project provides REST API endpoints only. For daemon/continuous monitoring mode, see the separate oncall-agent-poc project.

3. **No Automated Actions**: API provides recommendations only. Human approval required for any cluster modifications.

4. **Read-Only Access**: All API operations are read-only (GET, POST for analysis). No PUT/PATCH/DELETE operations that modify cluster state.

5. **OpenAPI Documentation**: Full API documentation automatically generated and available at `/docs` endpoint.

## Slack Integration

The API supports native Slack integration via `/oncall` slash commands and proactive incident alerts.

### Architecture

```
User: /oncall check cluster health
  -> Slack POST to /slack/command
  -> Immediate 200 ack ("Thinking...")
  -> Background: agent.query() -> Block Kit response -> POST to response_url

Proactive alerts:
  POST /incident -> agent analysis -> severity >= threshold -> Slack alert
```

### Environment Variables

| Variable | Source | Description |
|----------|--------|-------------|
| `SLACK_ENABLED` | ConfigMap | Enable Slack integration (`true`/`false`) |
| `SLACK_ALERT_CHANNEL` | ConfigMap | Channel for proactive alerts (e.g., `#oncall-alerts`) |
| `SLACK_ALERT_MIN_SEVERITY` | ConfigMap | Minimum severity for alerts (`high`, `critical`) |
| `SLACK_BOT_TOKEN` | Vault Secret | Bot User OAuth Token (`xoxb-...`) |
| `SLACK_SIGNING_SECRET` | Vault Secret | App Signing Secret for request verification |

### Endpoints

```
POST /slack/command  - Slash command handler (receives x-www-form-urlencoded)
GET  /slack/health   - Integration health/config check
POST /slack/events   - Events API (URL verification + future @mention support)
```

### Key Files

- `src/api/slack_integration.py` - Router, command handler, proactive alert posting
- `src/api/slack_models.py` - Pydantic models, Block Kit formatters
- `src/api/middleware.py` - `validate_slack_signature()` for HMAC-SHA256 verification
- `tests/api/test_slack_integration.py` - Test suite

### Slack App Setup

1. Create app at https://api.slack.com/apps
2. Add `/oncall` slash command pointing to `https://oncall.arigsela.com/slack/command`
3. OAuth scopes: `commands`, `chat:write`, `chat:write.public`
4. Install to workspace, store Bot Token and Signing Secret in Vault

### Testing

```bash
# Run Slack tests
pytest tests/api/test_slack_integration.py -v

# Test health check
curl https://oncall.arigsela.com/slack/health

# Simulate slash command locally
curl -X POST http://localhost:8000/slack/command \
  -d "token=test&command=/oncall&text=check+health&response_url=https://hooks.slack.com/...&user_id=U123&channel_id=C123"
```

## References

- FastAPI Docs: https://fastapi.tiangolo.com/
- Kubernetes Python Client: https://github.com/kubernetes-client/python
- PyGithub: https://pygithub.readthedocs.io/
- Anthropic API: https://docs.anthropic.com/
- Datadog API: https://docs.datadoghq.com/api/
- Slack API: https://api.slack.com/
