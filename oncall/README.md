# OnCall Troubleshooting Agent API

Intelligent on-call troubleshooting agent providing **HTTP API endpoints** for n8n AI Agent integration. Analyzes Kubernetes clusters (K3s homelab) using Claude LLM with **service catalog awareness** and **business logic** for context-aware incident response.

## 🎯 Key Capabilities

- **HTTP API** for n8n AI Agent integration (8 RESTful endpoints)
- **Service Catalog Integration** - Context-aware troubleshooting for K3s homelab services
- **Business Logic** - Priority classification (P0/P1/P2), known issues, dependency awareness
- **Natural language queries** for cluster troubleshooting
- **18 Custom Tools** - Kubernetes, GitHub, AWS, Datadog integration
- **GitOps Awareness** - Correlate incidents with ArgoCD deployments and GitHub PRs
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

### Option 2: Docker (Recommended)

```bash
# Start API server
docker compose up -d

# Check status
docker compose ps

# View logs
docker compose logs -f

# Test API
curl http://localhost:8000/health
open http://localhost:8000/docs  # Swagger UI
```

## 📋 Project Structure

```
oncall/
├── src/
│   ├── api/                       # HTTP API (API-only, no daemon)
│   │   ├── api_server.py          # FastAPI application (8 endpoints)
│   │   ├── agent_client.py        # Anthropic SDK wrapper with service catalog
│   │   ├── custom_tools.py        # 18 tools: K8s/GitHub/AWS/Datadog (1,359 lines)
│   │   ├── models.py              # Pydantic request/response models
│   │   ├── session_manager.py     # Session lifecycle management
│   │   └── middleware.py          # Auth & rate limiting
│   └── tools/                     # Helper modules (used by custom_tools.py)
│       ├── k8s_analyzer.py        # Kubernetes analysis helpers
│       ├── github_integrator.py   # GitHub deployment correlation
│       ├── aws_integrator.py      # AWS resource verification
│       ├── datadog_integrator.py  # Datadog metrics queries
│       ├── nat_gateway_analyzer.py # NAT gateway traffic analysis
│       └── zeus_job_correlator.py # Zeus refresh job correlation
├── config/                        # Configuration
│   └── kubeconfig-container.yaml  # Kubernetes config for containers
├── tests/                         # Test suite
│   ├── api/                       # API endpoint tests
│   └── tools/                     # Tool integration tests
├── docs/                          # Documentation
│   └── n8n-workflows/             # n8n workflow examples
├── examples/                      # Usage examples
├── scripts/                       # Utility scripts
│   └── generate_container_kubeconfig.sh
└── *.sh                           # Helper scripts
```

## 🧠 Service Catalog & Business Logic

The agent has **built-in knowledge** of your K3s homelab services, embedded in the system prompt for intelligent troubleshooting:

### Critical Services (P0 - Customer Facing)
- **chores-tracker-backend** - FastAPI service, 2 replicas, **5-6min startup is NORMAL**
- **chores-tracker-frontend** - HTMX UI
- **mysql** - **Single replica, data loss risk**, S3 backups
- **n8n** - **Runs THIS agent's Slack bot**, depends on PostgreSQL
- **postgresql** - **Single replica, conversation history risk**
- **nginx-ingress** - **Platform-wide outage if down**

### Infrastructure Services (P1)
- **vault** - **Manual unseal required** after pod restart
- **external-secrets** - Syncs from Vault
- **cert-manager** - Let's Encrypt, pfSense→Route53 DNS
- **ecr-auth** - CronJob syncs ECR credentials every 12h

### Known Issues (Built-in Intelligence)
1. **chores-tracker slow startup** - 5-6min is NORMAL (Python initialization)
2. **Vault unsealing** - Required after every pod restart, manual procedure
3. **Single replica risks** - mysql (data loss), postgresql (memory loss), vault
4. **ImagePullBackOff on ECR** - Check ecr-auth cronjob, verify vault unsealed

### Service Dependencies
- `mysql down` → chores-tracker-backend down (P0 impact)
- `vault sealed` → ALL services can't get secrets (P1 impact)
- `n8n down` → Slack bot broken (P0 impact)
- `nginx-ingress down` → Platform-wide outage (P0 impact)

### GitOps Workflow Integration
1. Code change → GitHub Actions → ECR push
2. PR to kubernetes repo → update base-apps/{service}/deployment.yaml
3. Merge → **ArgoCD auto-sync** → rolling update

**Correlation**: Pod restart loops (5+) → Check recent ArgoCD sync, GitHub PR, ECR push

## 🔧 Configuration

### Environment Variables

Create `.env` from `.env.example`:

```bash
# Core (Required)
ANTHROPIC_API_KEY=sk-ant-...
GITHUB_TOKEN=ghp_...
GITHUB_ORG=artemishealth

# API Configuration
API_HOST=0.0.0.0
API_PORT=8000
API_KEYS=your-secret-key-123  # Leave empty for dev mode (no auth)
SESSION_TTL_MINUTES=30
MAX_SESSIONS_PER_USER=5
RATE_LIMIT_AUTHENTICATED=60
RATE_LIMIT_UNAUTHENTICATED=10
CORS_ORIGINS=*  # Restrict in production

# AWS (Optional - for EKS/ECR/NAT gateway analysis)
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
- `POST /query` - **Primary endpoint** - Send queries to the agent for K8s troubleshooting
  - Request: `{"prompt": "Check chores-tracker service"}`
  - Response: Claude's analysis with tool usage, service catalog context
  - **Supports session_id** for multi-turn conversations
- `POST /incident` - Report K8s incidents (deprecated - use `/query` instead)

### Session Management
- `POST /session` - Create session for multi-turn conversations
- `GET /session/{id}` - Retrieve session with history
- `DELETE /session/{id}` - Delete session
- `GET /sessions/stats` - Session statistics

### Authentication

**Production Mode** (API key required):
```bash
curl -H "X-API-Key: your-api-key" http://localhost:8000/query \
  -d '{"prompt":"Check chores-tracker pods"}'
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

# Test service catalog integration
./test_service_catalog.sh

# Quick API test
./test_query.sh
curl http://localhost:8000/health

# Interactive API docs
open http://localhost:8000/docs
```

## 🛠️ Available Tools (18 Total)

The agent has access to 18 custom tools organized by category:

### Kubernetes Tools (6)
- `list_namespaces` - List all K8s namespaces, optionally filtered by pattern
- `list_pods` - List pods with status, restarts, container details
- `get_pod_logs` - Fetch recent pod logs (stdout/stderr)
- `get_pod_events` - Get Kubernetes events for debugging
- `get_deployment_status` - Deployment replicas and status
- `list_services` - List Kubernetes services in namespace

### GitHub Tools (2)
- `search_recent_deployments` - Find recent deployments for service (GitHub Actions)
- `get_recent_commits` - Get recent commits for repository

### AWS Tools (2)
- `check_secrets_manager` - Verify AWS Secrets Manager secret exists
- `check_ecr_image` - Verify ECR container image exists

### NAT Gateway Tools (3)
- `check_nat_gateway_metrics` - NAT gateway traffic analysis (CloudWatch)
- `find_zeus_jobs_during_timeframe` - Find Zeus refresh jobs in timeframe
- `correlate_nat_spike_with_zeus_jobs` - Correlate NAT traffic spikes with Zeus jobs

### Datadog Tools (3)
- `query_datadog_metrics` - Query any Datadog metric with filtering
- `get_resource_usage_trends` - Batch query CPU/memory trends
- `check_network_traffic` - Network TX/RX analysis

### Analysis Tools (2)
- `analyze_service_health` - Comprehensive health analysis (pods + deployment + events)
- `correlate_deployment_with_incidents` - Correlate K8s incidents with GitHub deployments

## 🔐 Security

### API Security
- API key authentication via `X-API-Key` header
- Rate limiting per endpoint
- Dev mode support (no auth when `API_KEYS` is empty)
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

## 📊 Monitoring

### Health Check
```bash
curl http://localhost:8000/health
```

Returns:
```json
{
  "status": "healthy",
  "agent": "initialized",
  "version": "1.0.0"
}
```

### Logs
```bash
# Docker
docker compose logs -f oncall-agent-api

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
   - Body: `{"prompt": "Check chores-tracker service health"}`
3. **Process Response**: Parse Claude's analysis with service catalog context
4. **Action**: Send to Slack/Teams/Discord

### Multi-turn Conversations

```javascript
// Create session
POST /session
{"user_id": "n8n-user"}
// Returns: {"session_id": "abc-123", ...}

// Query with context
POST /query
{"prompt": "Check chores-tracker pods", "session_id": "abc-123"}

// Follow-up (agent remembers previous context)
POST /query
{"prompt": "Show logs for the failing one", "session_id": "abc-123"}
```

### Example Queries with Service Catalog

```bash
# Known issue check (slow startup)
curl -X POST http://localhost:8000/query \
  -H "X-API-Key: your-key" \
  -d '{"prompt": "chores-tracker pod has been starting for 5 minutes, is this normal?"}'
# Response: "5-6min startup is NORMAL for chores-tracker-backend..."

# Vault unsealing procedure
curl -X POST http://localhost:8000/query \
  -H "X-API-Key: your-key" \
  -d '{"prompt": "vault pod restarted, what do I need to do?"}'
# Response: "Manual unseal required: kubectl exec -n vault vault-0 -- vault operator unseal..."

# Service dependency impact
curl -X POST http://localhost:8000/query \
  -H "X-API-Key: your-key" \
  -d '{"prompt": "mysql is down, what services are affected?"}'
# Response: "P0 IMPACT: chores-tracker-backend depends on mysql..."

# GitOps correlation
curl -X POST http://localhost:8000/query \
  -H "X-API-Key: your-key" \
  -d '{"prompt": "chores-tracker pods restarting 10 times, check recent deployments"}'
# Response: "Checking ArgoCD sync and GitHub PRs in kubernetes repo..."
```

## 📚 Documentation

- **API Docs**: http://localhost:8000/docs (Swagger UI)
- **CLAUDE.md**: Development guide for Claude Code
- **docs/datadog-integration.md**: Datadog metrics guide
- **docs/n8n-workflows/**: n8n workflow examples

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

## 🔍 What's Different?

This project recently underwent a major simplification:

### Removed (Simplified)
- ❌ **Daemon mode** - No autonomous monitoring, API-only
- ❌ **src/integrations/** - Removed orchestrator and k8s_event_watcher
- ❌ **k8s/** deployment manifests - Runs in Docker only
- ❌ **Complex config files** - No service_mapping.yaml, notifications.yaml

### Added (Enhanced)
- ✅ **Service catalog** - Built-in knowledge of K3s homelab services
- ✅ **Business logic** - Priority classification, known issues, dependencies
- ✅ **GitOps awareness** - ArgoCD sync correlation, GitHub PR tracking
- ✅ **Simplified architecture** - API-only, single Docker container
- ✅ **18 custom tools** - Expanded from 14 tools

### Architecture
- **Before**: Daemon + API (dual mode) with external config files
- **After**: API-only with embedded service catalog in system prompt
- **Benefit**: Simpler deployment, context-aware responses, no config management
