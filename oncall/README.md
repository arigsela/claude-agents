# OnCall Troubleshooting Agent API

Intelligent on-call troubleshooting agent providing **HTTP API endpoints** for n8n AI Agent integration. Analyzes Kubernetes clusters using Claude LLM with custom K8s/GitHub/AWS/Datadog tools.

## 🎯 Key Capabilities

- **HTTP API** for n8n AI Agent integration
- **Natural language queries** for cluster troubleshooting
- **Custom K8s tools** - pod analysis, log inspection, event correlation
- **GitHub integration** - deployment correlation and recent changes
- **AWS verification** - Secrets Manager, ECR images, CloudWatch metrics
- **Datadog metrics** - Historical resource usage and trend analysis
- **Session management** for multi-turn conversations (30-min TTL)
- **Rate limiting** and API key authentication
- **RESTful endpoints** with OpenAPI/Swagger documentation

## 🚀 Quick Start

### Option 1: Local Development (Fastest)

```bash
# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with: ANTHROPIC_API_KEY, GITHUB_TOKEN, AWS credentials

# Start API server
./run_api_server.sh

# Test
curl http://localhost:8000/health
open http://localhost:8000/docs  # Interactive API documentation
```

### Option 2: Docker (Recommended for Production)

```bash
# Start API server
docker compose up -d

# Check status
docker compose ps

# View logs
docker compose logs -f

# Test API
curl http://localhost:8000/health
curl http://localhost:8000/docs  # Swagger UI
```

### Option 3: Kubernetes (Production)

```bash
# Deploy API
kubectl apply -f k8s/

# Verify
kubectl get pods -n oncall-agent
kubectl logs -f deployment/oncall-agent-api -n oncall-agent
```

## 📋 Project Structure

```
oncall/
├── src/
│   ├── api/                       # HTTP API for n8n
│   │   ├── api_server.py          # FastAPI application (8 endpoints)
│   │   ├── agent_client.py        # Anthropic Agent SDK wrapper
│   │   ├── custom_tools.py        # K8s/GitHub/AWS/Datadog tools (1,358 lines)
│   │   ├── models.py              # Pydantic request/response models
│   │   ├── session_manager.py     # Session lifecycle management
│   │   └── middleware.py          # Auth & rate limiting
│   ├── tools/                     # Helper modules
│   │   ├── k8s_analyzer.py        # Kubernetes analysis helpers
│   │   ├── github_integrator.py   # GitHub correlation logic
│   │   ├── aws_integrator.py      # AWS resource verification
│   │   ├── datadog_integrator.py  # Datadog metrics queries
│   │   ├── nat_gateway_analyzer.py # NAT gateway analysis
│   │   └── zeus_job_correlator.py # Zeus job correlation
├── config/                        # Configuration
│   ├── service_mapping.yaml       # Service → GitHub repo + criticality
│   └── mcp_servers.json           # (Legacy) MCP config
├── k8s/                           # Kubernetes manifests
│   ├── api-deployment.yaml        # API deployment
│   ├── rbac.yaml                  # Service account & RBAC
│   ├── secret.yaml                # Secrets template
│   └── namespace.yaml             # Namespace definition
├── tests/                         # Test suite
│   └── api/                       # API tests
├── docs/                          # Documentation
├── scripts/                       # Utility scripts
└── *.sh                           # Helper scripts
```

## 🔧 Configuration

### Environment Variables

Create `.env` from `.env.example`:

```bash
# Core (Required)
ANTHROPIC_API_KEY=sk-ant-...
GITHUB_TOKEN=ghp_...
GITHUB_ORG=artemishealth
K8S_CONTEXT=dev-eks

# API Configuration
API_HOST=0.0.0.0
API_PORT=8000
API_KEYS=your-secret-key-123  # Leave empty for dev mode (no auth)
SESSION_TTL_MINUTES=30
MAX_SESSIONS_PER_USER=5
RATE_LIMIT_AUTHENTICATED=60
RATE_LIMIT_UNAUTHENTICATED=10
CORS_ORIGINS=*  # Restrict in production

# AWS (for EKS access in Docker)
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_REGION=us-east-1

# Datadog (Optional - for metrics)
DATADOG_API_KEY=...
DATADOG_APP_KEY=...
DATADOG_SITE=datadoghq.com
```

## 📡 API Endpoints

### Core Endpoints
- `GET /` - API information
- `GET /health` - Health check
- `GET /docs` - Interactive Swagger UI documentation

### Query Endpoints
- `POST /query` - Send queries to the agent for K8s troubleshooting
  - Request: `{"prompt": "Check proteus-dev pods"}`
  - Response: Claude's analysis with tool usage
- `POST /incident` - Report K8s incidents (deprecated - use `/query`)

### Session Management
- `POST /session` - Create session for multi-turn conversations
- `GET /session/{id}` - Retrieve session with history
- `DELETE /session/{id}` - Delete session
- `GET /sessions/stats` - Session statistics

### Authentication

**Production Mode** (API key required):
```bash
curl -H "X-API-Key: your-api-key" http://localhost:8000/query \
  -d '{"prompt":"Check pods"}'
```

**Development Mode** (no auth):
```bash
# Set API_KEYS= (empty) in .env
curl http://localhost:8000/query -d '{"prompt":"Check pods"}'
```

### Rate Limits

- `/query`: 60 req/min (authenticated), 10 req/min (unauthenticated)
- `/incident`: 30 req/min (authenticated), 5 req/min (unauthenticated)
- `/session`: 10 req/min (authenticated only)

## 🧪 Testing

```bash
# Run API tests
pytest tests/api/ -v
pytest --cov=src/api --cov-report=html

# Quick test
./test_query.sh
curl http://localhost:8000/health

# Interactive API docs
open http://localhost:8000/docs
```

## 🛠️ Available Tools

The agent has access to 14 custom tools:

### Kubernetes Tools
- `list_all_namespaces` - Get all K8s namespaces
- `get_pods_in_namespace` - List pods with status
- `get_pod_logs` - Fetch recent pod logs
- `describe_pod` - Detailed pod information
- `get_recent_k8s_events` - Recent cluster events
- `get_deployment_info` - Deployment details

### GitHub Tools
- `get_recent_deployment_activity` - Recent deployments for service
- `search_recent_config_changes` - Config changes in last 7 days

### AWS Tools
- `verify_aws_secret_exists` - Check Secrets Manager
- `verify_ecr_image_exists` - Verify ECR images

### NAT Gateway Tools
- `check_nat_gateway_metrics` - NAT gateway traffic analysis
- `find_zeus_jobs_in_timeframe` - Find Zeus refresh jobs
- `correlate_nat_spike_with_jobs` - Correlate NAT spikes with Zeus

### Datadog Tools
- `query_datadog_metrics` - Query any Datadog metric

## 🔐 Security

### Cluster Protection
- **Allowed**: `dev-eks` only
- **Protected**: `prod-eks`, `staging-eks`
- Protection enforced at middleware level

### API Security
- API key authentication via `X-API-Key` header
- Rate limiting per endpoint
- CORS configuration
- Request validation via Pydantic models

### Audit Trail
- All API requests logged with timestamps
- Session history maintained
- No automated remediation (recommendations only)

## 🐳 Docker

### Build
```bash
docker build -t oncall-agent .
./build.sh  # Helper script
```

### Run
```bash
docker compose up -d
docker compose logs -f oncall-agent-api
```

### Environment
- Requires `config/kubeconfig-container.yaml` for K8s access
- Generate with: `./scripts/generate_container_kubeconfig.sh`

## ☸️ Kubernetes Deployment

### Prerequisites
- Kubernetes cluster with RBAC enabled
- AWS IAM authentication for EKS
- Secrets for API keys

### Deploy
```bash
# Create namespace
kubectl apply -f k8s/namespace.yaml

# Create secrets (edit first!)
kubectl apply -f k8s/secret.yaml

# Deploy RBAC
kubectl apply -f k8s/rbac.yaml

# Deploy API
kubectl apply -f k8s/api-deployment.yaml

# Verify
kubectl get pods -n oncall-agent
kubectl logs -f deployment/oncall-agent-api -n oncall-agent
```

### Access API
```bash
# Port forward
kubectl port-forward -n oncall-agent svc/oncall-agent-api 8000:8000

# Test
curl http://localhost:8000/health
```

## 📊 Monitoring

### Health Check
```bash
curl http://localhost:8000/health
```

Returns:
```json
{
  "status": "healthy",
  "timestamp": "2025-10-19T12:00:00Z",
  "version": "1.0.0"
}
```

### Logs
```bash
# Docker
docker compose logs -f oncall-agent-api

# Kubernetes
kubectl logs -f deployment/oncall-agent-api -n oncall-agent

# Local
tail -f logs/api-server.log
```

## 🔄 n8n Integration

### Workflow Example

1. **Trigger**: Webhook or schedule
2. **HTTP Request Node**:
   - URL: `http://oncall-agent-api:8000/query`
   - Method: POST
   - Headers: `X-API-Key: your-key`
   - Body: `{"prompt": "Check proteus-dev pods"}`
3. **Process Response**: Parse Claude's analysis
4. **Action**: Send to Slack/Teams/PagerDuty

### Multi-turn Conversations

```javascript
// Create session
POST /session
{"user_id": "n8n-user"}
// Returns: {"session_id": "abc-123", ...}

// Query with context
POST /query
{"prompt": "Check pods", "session_id": "abc-123"}

// Follow-up
POST /query
{"prompt": "Show logs for the failing one", "session_id": "abc-123"}
```

## 📚 Documentation

- **API Docs**: http://localhost:8000/docs (Swagger UI)
- **CLAUDE.md**: Development guide for Claude Code
- **docs/datadog-integration.md**: Datadog metrics guide
- **docs/deployment-guide.md**: Deployment instructions

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make changes and add tests
4. Run `pytest tests/api/ -v`
5. Submit a pull request

## 📝 License

MIT License - see LICENSE file for details

## 🆘 Support

For issues or questions:
- Check `docs/` directory
- Review API docs at `/docs` endpoint
- Check logs for error details
- File an issue in GitHub

## 🙏 Acknowledgments

- Built with [Anthropic Claude](https://www.anthropic.com/)
- Uses [FastAPI](https://fastapi.tiangolo.com/)
- Kubernetes integration via [kubernetes-python](https://github.com/kubernetes-client/python)
- GitHub integration via [PyGithub](https://pygithub.readthedocs.io/)
