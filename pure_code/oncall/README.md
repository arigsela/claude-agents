# OnCall Troubleshooting Agent

Intelligent on-call troubleshooting agent with **dual operation modes**: proactive Kubernetes monitoring with automatic incident detection AND on-demand query API for n8n AI Agent integration.

## 🎯 Key Capabilities

### Daemon Mode (Proactive Monitoring)
- **Monitors Kubernetes** cluster health every 60 seconds (pod status, restarts, failures)
- **Analyzes incidents** using Claude LLM with two-turn investigation methodology
- **Verifies AWS infrastructure** (Secrets Manager, ECR images)
- **Correlates** incidents with GitHub deployment activities
- **Sends Teams notifications** with intelligent remediation recommendations

### API Mode (On-Demand Analysis)
- **HTTP API** for n8n AI Agent integration
- **Natural language queries** for cluster troubleshooting
- **Session management** for multi-turn conversations
- **Rate limiting** and API key authentication
- **RESTful endpoints** with OpenAPI/Swagger documentation

### Why Both Modes?

**Daemon finds issues automatically** → Teams alerts
**API answers questions on-demand** → n8n interactive troubleshooting

**Together:** Complete observability + interactive diagnosis!

## 🚀 Quick Start

### Option 1: Local Development (Fastest)

```bash
# Install dependencies
pip install -r requirements.txt

# Start API server
./run_api_server.sh

# Test
curl http://localhost:8000/health
open http://localhost:8000/docs  # Interactive API documentation
```

### Option 2: Docker (Both Modes)

```bash
# Start both daemon and API
docker compose up -d

# Check status
docker compose ps

# View logs
docker compose logs -f

# Test API
curl http://localhost:8000/health
```

### Option 3: Kubernetes (Production)

```bash
# Deploy both modes
kubectl apply -f k8s/

# Or deploy individually:
kubectl apply -f k8s/deployment.yaml      # Daemon (proactive monitoring)
kubectl apply -f k8s/api-deployment.yaml  # API (n8n integration)

# Verify
kubectl get pods -n oncall-agent
```

## 📋 Project Structure

```
oncall-agent-api/
├── src/
│   ├── agent/                     # Core agent implementation
│   │   ├── oncall_agent.py        # Claude Agent SDK wrapper
│   │   └── incident_triage.py     # Two-turn LLM investigation engine
│   ├── api/                       # HTTP API for n8n
│   │   ├── api_server.py          # FastAPI application (8 endpoints)
│   │   ├── agent_client.py        # Agent client wrapper
│   │   ├── custom_tools.py        # K8s tools for API mode
│   │   ├── models.py              # Pydantic request/response models
│   │   ├── session_manager.py     # Session lifecycle management
│   │   └── middleware.py          # Auth & rate limiting
│   ├── integrations/              # Monitoring coordination
│   │   ├── orchestrator.py        # MAIN ENTRY for daemon mode
│   │   └── k8s_event_watcher.py   # Proactive health monitoring
│   ├── tools/                     # Helper modules
│   │   ├── k8s_analyzer.py        # Kubernetes analysis
│   │   ├── github_integrator.py   # GitHub correlation
│   │   └── aws_integrator.py      # AWS verification
│   └── notifications/             # Teams integration
│       └── teams_notifier.py      # Adaptive Cards
├── config/                        # Configuration
│   ├── service_mapping.yaml       # Service → GitHub repo + criticality
│   ├── k8s_monitoring.yaml        # Alert rules
│   └── notifications.yaml         # Teams config
├── k8s/                           # Kubernetes manifests
│   ├── deployment.yaml            # Daemon deployment
│   ├── api-deployment.yaml        # API deployment
│   ├── rbac.yaml                  # Service account & RBAC
│   ├── secret.yaml                # Secrets template
│   └── namespace.yaml             # Namespace definition
├── tests/                         # Test suite
│   └── api/                       # API tests
├── docs/                          # Documentation
├── scripts/                       # Utility scripts
└── *.sh                           # Various helper scripts
```

## 🔧 Configuration

### Environment Variables

Create `.env` from `.env.example`:

```bash
# Core (Required for both modes)
ANTHROPIC_API_KEY=sk-ant-...
GITHUB_TOKEN=ghp_...
GITHUB_ORG=artemishealth
K8S_CONTEXT=dev-eks

# Daemon Mode
TEAMS_WEBHOOK_URL=https://...
TEAMS_NOTIFICATIONS_ENABLED=true

# API Mode
API_HOST=0.0.0.0
API_PORT=8000
API_KEYS=your-secret-key-123  # Leave empty for dev mode (no auth)
SESSION_TTL_MINUTES=30
MAX_SESSIONS_PER_USER=5
RATE_LIMIT_AUTHENTICATED=60
CORS_ORIGINS=*  # Restrict in production

# AWS (for EKS access in Docker)
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_REGION=us-east-1
```

## 📡 API Endpoints

### Core Endpoints
- `GET /` - API information
- `GET /health` - Health check
- `GET /docs` - Interactive Swagger UI
- `POST /query` - Send queries to the agent
- `POST /incident` - Report K8s incidents

### Session Management
- `POST /session` - Create session for multi-turn conversations
- `GET /session/{id}` - Retrieve session with history
- `DELETE /session/{id}` - Delete session
- `GET /sessions/stats` - Session statistics

### Features
- ✅ Session-based conversations (30-min TTL)
- ✅ API key authentication (dev mode when API_KEYS not set)
- ✅ Rate limiting (60/30/10 req/min per endpoint)
- ✅ Cluster protection (dev-eks only, rejects prod-eks)
- ✅ Auto severity classification (critical/high/medium/low)

## 🔌 n8n Integration

### Setup
1. Configure API URL in n8n:
   - Local: `http://localhost:8000/query`
   - Docker: `http://host.docker.internal:8000/query`
   - K8s: `http://oncall-agent-api.oncall-agent.svc.cluster.local/query`

2. See documentation:
   - `docs/n8n-integrations/n8n-ai-agent-integration.md`
   - `docs/n8n-integrations/n8n-api-wrapper-implementation-plan.md`

### Example n8n Conversation

```
User: "Is proteus having any issues?"
  ↓
n8n AI Agent → Your OnCall API
  POST /query {"prompt": "Check proteus service status in proteus-dev"}
  ↓
OnCall Agent analyzes K8s cluster
  ↓
Returns: "Proteus is healthy, 3 pods running normally"
  ↓
n8n AI Agent → User: "Proteus looks good!"
```

## 🐳 Deployment Modes

### Run Mode Configuration

The Docker image supports three modes via `RUN_MODE` environment variable:

| Mode | Use Case | Command |
|------|----------|---------|
| `daemon` | Proactive monitoring only | `docker run -e RUN_MODE=daemon` |
| `api` | n8n integration only | `docker run -e RUN_MODE=api -p 8000:8000` |
| `both` | Monitoring + n8n | `docker run -e RUN_MODE=both -p 8000:8000` |

### Recommended: Run Both (Separate Containers)

```bash
# Docker Compose (separate containers)
docker compose up -d

# Results:
# - oncall-agent-daemon: Monitors cluster → Teams alerts
# - oncall-agent-api: HTTP API → n8n queries
```

### Kubernetes Deployment

**Daemon (Proactive Monitoring):**
```bash
kubectl apply -f k8s/deployment.yaml
# 1 replica, monitors cluster
```

**API (n8n Integration):**
```bash
kubectl apply -f k8s/api-deployment.yaml
# 2 replicas, HTTP API for n8n
```

**Both together:**
```bash
kubectl apply -f k8s/
# Deploys both daemon and API
```

## 🧪 Testing

### API Tests

```bash
# Run all API tests
pytest tests/api/ -v

# Run specific test file
pytest tests/api/test_api_server.py -v

# Run with coverage
pytest tests/api/ --cov=src/api --cov-report=html
```

## 🛡️ Safety Features

### Cluster Protection

Hard-coded safeguards:
- **ALLOWED_CLUSTERS**: `["dev-eks"]`
- **PROTECTED_CLUSTERS**: `["prod-eks", "staging-eks"]`

Any action targeting protected clusters raises `PermissionError`.

### Rate Limiting

- `/query`: 60 requests/minute (authenticated)
- `/incident`: 30 requests/minute
- `/session`: 10 requests/minute

### Authentication

- **Development:** No API key required (API_KEYS not set)
- **Production:** Require `X-API-Key` header
- Configure via `API_KEYS` environment variable

## 📚 Documentation

### Available Guides
- **[docs/README.md](docs/README.md)** - Documentation index
- **[docs/deployment-guide.md](docs/deployment-guide.md)** - Deploy to Docker or K8s
- **[docs/n8n-integrations/](docs/n8n-integrations/)** - n8n integration guides
- **[k8s/README.md](k8s/README.md)** - Kubernetes deployment details

## 🏗️ Architecture

```
┌────────────────────────────────────────────────────────────┐
│  OnCall Agent - Dual Mode Architecture                     │
├────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────────────────┐  ┌────────────────────────────┐ │
│  │   Daemon Mode        │  │      API Mode              │ │
│  │   ──────────         │  │      ────────              │ │
│  │                      │  │                            │ │
│  │  orchestrator.py     │  │  FastAPI Server           │ │
│  │         ↓            │  │         ↓                  │ │
│  │  K8s Event Watcher   │  │  8 HTTP Endpoints         │ │
│  │  (every 60s)         │  │  - /query                  │ │
│  │         ↓            │  │  - /incident               │ │
│  │  Auto-detect         │  │  - /session                │ │
│  │  incidents           │  │         ↓                  │ │
│  │         ↓            │  │  Session Manager          │ │
│  │  Claude Analysis     │  │  (30-min TTL)             │ │
│  │  (2-turn)            │  │         ↓                  │ │
│  │         ↓            │  │  Rate Limiting            │ │
│  │  Teams Alerts 🔔     │  │  & Auth                    │ │
│  │                      │  │         ↓                  │ │
│  │                      │  │  JSON Responses           │ │
│  └──────────────────────┘  └────────────────────────────┘ │
│           │                           │                    │
│           └──────────┬────────────────┘                    │
│                      │                                     │
│         Shared: Agent Logic, K8s Access, Configs          │
│                                                             │
└────────────────────────────────────────────────────────────┘
           │                      │
           ↓                      ↓
    Teams Channel            n8n AI Agent
```

## 🔑 Key Features

### Intelligent Analysis
- **Two-turn investigation**: Claude assesses → gather data → Claude refines
- **Root cause identification** with specific evidence
- **Exact remediation steps** (e.g., "increase memory 256M → 512M")
- **Deployment correlation** (links incidents to recent GitHub Actions)

### Monitoring
- **Proactive health checks** every 60 seconds
- **Event watching** for K8s warnings (OOM, CrashLoop, etc.)
- **Incident correlation** (30-min window, reduces LLM calls by ~75%)
- **Service mapping** to GitHub repos and criticality levels

### Integration
- **Teams notifications** with Adaptive Cards and ArgoCD links
- **n8n AI Agent** integration for interactive troubleshooting
- **GitHub deployment tracking** via PyGithub
- **AWS resource verification** via boto3

### Production Ready
- **High availability** (API: 2+ replicas)
- **Resource limits** configured
- **RBAC** with least-privilege (read-only ClusterRole)
- **Secrets management** via K8s Secrets
- **Health checks** and graceful shutdown

## 📊 Metrics & Performance

- **Incident correlation**: ~75% reduction in LLM API costs
- **Response time**: ~2-15 seconds for queries
- **Monitoring frequency**: 60 seconds (proactive), instant (API)
- **Session TTL**: 30 minutes with auto-cleanup
- **Max sessions per user**: 5 concurrent

## 🎬 Usage Examples

### Daemon Mode (Automatic)

```bash
# Runs continuously, no interaction needed
docker compose up oncall-agent-daemon -d

# Automatically:
# - Monitors cluster health
# - Detects incidents
# - Sends Teams alerts
```

### API Mode (Interactive)

```bash
# Start API server
./run_api_server.sh

# Create session for multi-turn conversation
SESSION=$(curl -s -X POST http://localhost:8000/session \
  -H "Content-Type: application/json" \
  -d '{"user_id": "devops@example.com"}' | jq -r '.session_id')

# Query 1
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d "{\"prompt\": \"Check proteus service status\", \"session_id\": \"$SESSION\"}"

# Query 2 (remembers context!)
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d "{\"prompt\": \"What about recent deployments?\", \"session_id\": \"$SESSION\"}"
```

### Both Modes Together

```bash
# Deploy both to Kubernetes
kubectl apply -f k8s/

# Result:
# - Daemon monitors 24/7 → Teams alerts
# - API responds to n8n → Interactive queries
```

## 🔐 Security & Safety

### Cluster Protection
- Only `dev-eks` is allowed for operations
- `prod-eks` and `staging-eks` are protected (requests rejected)
- Multiple enforcement layers in code

### API Security
- API key authentication via `X-API-Key` header
- Rate limiting per endpoint (60/30/10 req/min)
- Dev mode support (no auth when API_KEYS not set)
- CORS configuration (restrict in production)

### Audit Trail
- All queries logged with timestamps
- Session history tracked
- Teams notifications document all actions
- GitOps workflow (no automated rollbacks)

## 🧰 Available Commands

### Local Development
```bash
./run_api_server.sh          # Start API server
./run_daemon.sh start        # Start daemon in background
./run_daemon.sh logs         # View daemon logs
./run_daemon.sh stop         # Stop daemon
./setup_api.sh               # Install dependencies
./start_api_local.sh         # Alternative API starter
./generate-api-keys.sh       # Generate API keys
```

### Docker
```bash
./build_api.sh               # Build Docker image
./build.sh                   # Build Docker image (alternative)
docker compose up -d         # Start both modes
docker compose logs -f       # View logs
docker compose down          # Stop services
```

### AWS Deployment
```bash
./deploy-to-ecr.sh           # Deploy to AWS ECR
```

### Testing
```bash
pytest tests/api/ -v         # Run API tests
./test_query.sh              # Quick API query test
```

## 🎯 Use Cases

### Use Case 1: Proactive Monitoring
```
Deploy: Daemon mode only
Result: Automatic incident detection → Teams alerts
Who: DevOps team passive monitoring
```

### Use Case 2: Interactive Troubleshooting
```
Deploy: API mode only
Result: n8n AI Agent answers questions on-demand
Who: DevOps team active investigation
```

### Use Case 3: Complete Observability (Recommended)
```
Deploy: Both modes
Result: Auto-detection + interactive queries
Who: Full DevOps workflow
```

## 🚦 Current Status

### ✅ Production Ready

**Daemon Mode:**
- ✅ Kubernetes monitoring active
- ✅ Claude LLM integration working
- ✅ Teams notifications configured
- ✅ AWS & GitHub integration complete
- ✅ Incident correlation reducing costs by ~75%

**API Mode:**
- ✅ FastAPI HTTP server operational
- ✅ 8 endpoints implemented (query, incident, session CRUD, health, root, stats)
- ✅ Session management with TTL
- ✅ Rate limiting and authentication
- ✅ OpenAPI/Swagger documentation
- ✅ Comprehensive test suite

**Infrastructure:**
- ✅ Docker multi-mode support (daemon/api/both)
- ✅ Docker Compose dual-service configuration
- ✅ Kubernetes manifests for both modes
- ✅ Build and deployment automation scripts

## 📞 Support & Troubleshooting

### Common Issues

**"Module not found" errors:**
```bash
pip install -r requirements.txt
```

**"Permission denied" for cluster:**
```bash
# Verify K8S_CONTEXT=dev-eks in .env
```

**API not responding:**
```bash
# Check server is running
curl http://localhost:8000/health

# Check logs
docker compose logs oncall-agent-api
```

**Docker containers not starting:**
```bash
# Rebuild with latest changes
docker compose build
docker compose up -d
```

### Getting Help

**For deployment:** Read `docs/deployment-guide.md` or `k8s/README.md`

**For n8n integration:** Read docs in `docs/n8n-integrations/`

**For API details:** Visit `http://localhost:8000/docs` when running

## 🏃 Next Steps

### Immediate Use

1. **For local testing:**
   ```bash
   ./run_api_server.sh
   open http://localhost:8000/docs
   ```

2. **For n8n integration:**
   - Configure URL: `http://localhost:8000/query`
   - Start chatting!

3. **For Docker deployment:**
   ```bash
   docker compose build  # Rebuild with latest
   docker compose up -d  # Start both modes
   ```

4. **For K8s deployment:**
   - Follow `docs/deployment-guide.md`
   - Deploy both daemon and API: `kubectl apply -f k8s/`

## 📝 License

Internal ArtemisHealth project - All rights reserved

## 👥 Contributing

1. Create feature branch
2. Make changes with tests
3. Update relevant documentation
4. Submit PR

For questions, contact the DevOps team.

---

**Status:** Production Ready - Both daemon and API modes operational
**Last Updated:** 2024-10-10
