# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is an **Intelligent On-Call Troubleshooting Agent API Server** built with Anthropic's Claude and FastAPI. It provides HTTP endpoints for n8n integration to analyze Kubernetes clusters (dev-eks) and provide intelligent troubleshooting recommendations.

**Key Architecture**: The API uses **direct API access** (kubernetes, PyGithub, boto3) with Claude LLM providing intelligent analysis through the Anthropic Agent SDK.

## Development Environment Setup

### Initial Setup
```bash
# Navigate to project
cd /Users/arisela/git/claude-agents/oncall

# Activate virtual environment
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with: ANTHROPIC_API_KEY, GITHUB_TOKEN, AWS credentials, API_KEYS
```

### Required Environment Variables
- `ANTHROPIC_API_KEY`: Claude API key for LLM analysis
- `GITHUB_TOKEN`: GitHub PAT with repo and workflow access
- `K8S_CONTEXT`: Must be "dev-eks" (cluster protection enforced)
- `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`: For EKS authentication (Docker containers)
- `DATADOG_API_KEY` / `DATADOG_APP_KEY`: Datadog credentials for metrics queries (optional)
- `API_KEYS`: Comma-separated API keys for authentication (leave empty for dev mode)

## Common Commands

### Running the API Server

**Local Development**:
```bash
# Start API server
./run_api_server.sh

# Or directly with uvicorn
uvicorn api.api_server:app --reload --app-dir src --port 8000

# Test the API
curl http://localhost:8000/health
open http://localhost:8000/docs  # Interactive API documentation
```

**Production (Docker)**:
```bash
# Docker (recommended)
docker compose up              # Foreground with logs
docker compose up -d           # Background
docker compose logs -f         # Watch logs
docker compose down            # Stop

# Build custom image
docker build -t oncall-agent .
./build.sh                     # Helper script
```

### Testing

```bash
# Run API tests
pytest tests/api/ -v
pytest --cov=src/api --cov-report=html

# Quick API test
./test_query.sh
curl http://localhost:8000/health
```

### Code Quality
```bash
black src/                     # Format code
ruff check src/                # Lint code
mypy src/                      # Type checking
```

### Container Operations
```bash
# Generate kubeconfig for containers
./scripts/generate_container_kubeconfig.sh
```

## Project Architecture

### Core Components

**`src/api/`** - FastAPI server and API endpoints
- `api_server.py`: **Main entry point** - FastAPI application with 8 HTTP endpoints
- `agent_client.py`: Anthropic Agent SDK wrapper for Claude interactions
- `custom_tools.py`: K8s/GitHub/AWS/Datadog tool implementations (1,358 lines)
- `session_manager.py`: Session-based conversation management (30-min TTL)
- `middleware.py`: API key authentication and rate limiting
- `models.py`: Pydantic models for request/response validation

**`src/tools/`** - Helper modules (used by custom_tools.py)
- `k8s_analyzer.py`: Kubernetes cluster analysis helpers
- `github_integrator.py`: GitHub deployment correlation logic
- `datadog_integrator.py`: Datadog metrics queries for historical analysis
- `nat_gateway_analyzer.py`: NAT gateway traffic analysis
- `zeus_job_correlator.py`: Zeus refresh job correlation

**`config/`** - Configuration files
- `service_mapping.yaml`: Service → GitHub repo mapping + criticality levels
- `mcp_servers.json`: (Legacy) MCP server config - not actively used

### API Endpoints

The API server provides 8 HTTP endpoints:

1. **`POST /query`** - Send queries to the agent for K8s troubleshooting
2. **`POST /incident`** - Report K8s incidents for analysis (deprecated - use /query)
3. **`POST /session`** - Create session for multi-turn conversations
4. **`GET /session/{id}`** - Retrieve session with history
5. **`DELETE /session/{id}`** - Delete session
6. **`GET /sessions/stats`** - Session statistics
7. **`GET /health`** - Health check endpoint
8. **`GET /docs`** - Interactive Swagger UI documentation

### Data Flow

```
HTTP Request (n8n/webhook)
    ↓
FastAPI Endpoint (/query or /session)
    ↓
Authentication & Rate Limiting (middleware.py)
    ↓
OnCallAgentClient (agent_client.py)
    ↓
Anthropic Agent SDK + Custom Tools
    ↓
K8s API / GitHub API / AWS API / Datadog API
    ↓
Claude LLM Analysis
    ↓
JSON Response to Client
```

### Key Design Patterns

**1. Stateless API with Session Support**:
- Each query is independent (stateless)
- Optional session support for multi-turn conversations
- 30-minute session TTL, automatic cleanup

**2. Custom Tools Pattern** (`custom_tools.py`):
- 14 tools available to Claude: K8s operations, GitHub queries, AWS verification, Datadog metrics
- Tools are pure Python functions decorated for Agent SDK
- Direct API access (no MCP overhead)

**3. Cluster Protection** (Hard-coded safety):
- API validates `K8S_CONTEXT=dev-eks` only
- Protected clusters (`prod-eks`, `staging-eks`) rejected at middleware level

**4. Service Mapping** (`config/service_mapping.yaml`):
- Maps K8s pod names → GitHub repositories
- Defines criticality levels (critical/high/medium)
- Used for enrichment and correlation

## Important Concepts

### The Agent SDK

This project uses **Anthropic Agent SDK** for Claude interactions:
- **Agent Client** (`src/api/agent_client.py`): Wrapper around Agent SDK
- **Custom Tools**: Direct K8s/GitHub/AWS APIs exposed as tools
- **Session Management**: Optional multi-turn conversations

### API Authentication

The API supports two modes:
- **Production Mode**: API key authentication via `X-API-Key` header (set `API_KEYS` in .env)
- **Development Mode**: No authentication required (when `API_KEYS` is empty)

Rate limiting is enforced per endpoint:
- `/query`: 60 req/min (authenticated), 10 req/min (unauthenticated)
- `/incident`: 30 req/min (authenticated), 5 req/min (unauthenticated)
- `/session`: 10 req/min (authenticated)

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
- **Unit Tests**: Test individual API endpoints, authentication, rate limiting
- **Integration Tests**: Mock Anthropic SDK responses, K8s API calls
- **E2E Tests**: Use pytest fixtures for full query workflows
- **Coverage Target**: Focus on `src/api/` components

Use `pytest-asyncio` for async test support.

## Deployment Modes

### Local Development
```bash
./run_api_server.sh            # Local API server
curl http://localhost:8000/docs # Interactive API docs
```

### Production (Docker)
```bash
docker compose up -d           # Containerized API
kubectl apply -f k8s/          # Kubernetes deployment
```

### Production (Kubernetes)
```bash
# See k8s/ directory for manifests
kubectl apply -f k8s/api-deployment.yaml
kubectl logs -f deployment/oncall-agent-api -n oncall-agent
```

Requires:
- Kubernetes RBAC (serviceAccount with read access)
- AWS IAM authentication (for EKS)
- Secrets for ANTHROPIC_API_KEY, GITHUB_TOKEN, API_KEYS

## Safety and Guardrails

**Hard-coded Cluster Protection**:
- Only `dev-eks` is allowed for operations
- `prod-eks`, `staging-eks` are protected
- Check enforced at middleware level

**API Security**:
- API key authentication via `X-API-Key` header
- Rate limiting per endpoint
- Dev mode support (no auth when API_KEYS not set)
- CORS configuration

**Audit Trail**:
- All API requests logged with timestamps
- Session history maintained for multi-turn conversations
- No automated remediation (recommendations only)

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

2. **Test**: `./test_query.sh` to verify configuration loads

### Adding a New Tool

1. **Implement tool function** in `src/api/custom_tools.py`:
   ```python
   def my_new_tool(param: str) -> dict:
       """Tool description for Claude."""
       # Implementation
       return {"result": "..."}
   ```

2. **Register in agent_client.py**: Add to `self.tools` list

3. **Test**: Send query via API that requires the tool

### Extending API Endpoints

Edit `src/api/api_server.py`:
```python
@app.post("/new-endpoint")
async def new_endpoint(request: NewRequest):
    # Implementation
    return {"status": "success"}
```

## Troubleshooting

### "Import errors" when running API
```bash
# Ensure PYTHONPATH includes src/
export PYTHONPATH="${PYTHONPATH}:$(pwd)/src"
# Or run from project root
cd /Users/arisela/git/claude-agents/oncall
```

### "Permission denied" for cluster
- Check `K8S_CONTEXT` is set to `dev-eks`
- Verify you're not targeting protected clusters
- Review cluster protection in `middleware.py`

### "ANTHROPIC_API_KEY not found"
- Ensure `.env` file exists with valid key
- API server requires this for LLM analysis

### Docker container can't access EKS
- Set AWS credentials in `.env`: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`
- Generate container kubeconfig: `./scripts/generate_container_kubeconfig.sh`
- Mount kubeconfig in docker-compose.yml

### API returns 401 Unauthorized
- Check `X-API-Key` header is set
- Verify API key is in `API_KEYS` environment variable
- Or set `API_KEYS=` (empty) for development mode

## Important Notes

1. **API-Only Architecture**: This agent provides HTTP endpoints for n8n integration. No autonomous monitoring.

2. **No Automated Remediation**: Agent provides recommendations only. Human approval required for any cluster changes.

3. **Session Management**: Optional sessions for multi-turn conversations, 30-min TTL.

4. **Rate Limiting**: Enforced per endpoint to prevent abuse.

5. **Development Mode**: Set `API_KEYS=` (empty) to disable authentication for local testing.

## References

- Anthropic Agent SDK: https://github.com/anthropics/anthropic-agent-sdk
- FastAPI Docs: https://fastapi.tiangolo.com/
- Kubernetes Python Client: https://github.com/kubernetes-client/python
- PyGithub: https://pygithub.readthedocs.io/
- Interactive API Docs: http://localhost:8000/docs (when server is running)
