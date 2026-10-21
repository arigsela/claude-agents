# OnCall Troubleshooting Agent API

Intelligent on-call troubleshooting API with **autonomous conversation handling**, providing on-demand Kubernetes cluster analysis and natural language troubleshooting capabilities with Claude AI. Integrates directly with **Microsoft Teams via Power Automate** for seamless DevOps chat interactions.

## 🎯 Key Capabilities

- **Microsoft Teams Integration** - Chat with the agent directly in Teams channels via Power Automate
- **Autonomous Conversations** - Built-in session management with conversation history (no external orchestrator needed)
- **REST API** for on-demand cluster troubleshooting
- **Natural language queries** - ask questions in plain English
- **Session management** for multi-turn conversations (30-min TTL, last 5 exchanges preserved)
- **Incident triage engine** using two-turn investigation methodology
- **GitHub deployment correlation** for root cause analysis
- **AWS Cost Explorer** with EC2 tag-based cost analysis
- **AWS resource verification** (Secrets Manager, ECR)
- **Datadog metrics integration** for historical performance analysis
- **NAT Gateway traffic analysis** for cost optimization
- **Zeus job correlation** for batch job troubleshooting
- **Incident Memory** with semantic search for historical incident lookup (sqlite-vec)
- **Rate limiting** and API key authentication
- **OpenAPI/Swagger** documentation

## 🏗️ Architecture

**Pattern**: REST API with autonomous conversation handling and direct Anthropic API integration

```
┌─────────────────────────────────────────────────────────────┐
│              Microsoft Teams Channel                         │
│                    @OnCall Bot                               │
└──────────────────────┬──────────────────────────────────────┘
                       │ Power Automate HTTP Action
                       ↓
┌─────────────────────────────────────────────────────────────┐
│  FastAPI Server (src/api/api_server.py)                     │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  HTTP Endpoints:                                            │
│  ├── POST /teams/webhook    → Teams/Power Automate entry    │
│  ├── GET  /teams/health     → Teams integration status      │
│  ├── POST /query            → Natural language queries      │
│  ├── POST /incident         → K8s incident analysis         │
│  ├── POST /session          → Create session                │
│  ├── GET  /session/{id}     → Get session + history         │
│  ├── DELETE /session/{id}   → Delete session                │
│  ├── GET  /sessions/stats   → Session statistics            │
│  ├── GET  /health           → Health check                  │
│  └── GET  /docs             → Interactive Swagger UI        │
│                                                              │
│  Core Components:                                           │
│  ├── Session Manager        → 30-min TTL, conversation hist │
│  ├── Conversation History   → Last 5 exchanges preserved    │
│  ├── Rate Limiting          → 60/30/10 req/min              │
│  ├── API Key Auth           → Teams + standard API keys     │
│  └── Agent Client           → Anthropic API wrapper         │
│                                                              │
│  Analysis Engine:                                           │
│  ├── Incident Triage        → Two-turn investigation        │
│  ├── K8s Analyzer           → Pod/deployment analysis       │
│  ├── GitHub Integrator      → Deployment correlation        │
│  ├── AWS Cost Explorer      → EC2 cost by tags              │
│  ├── AWS Integrator         → Resource verification         │
│  ├── Datadog Integrator     → Metrics queries               │
│  ├── NAT Gateway Analyzer   → Traffic analysis              │
│  ├── Zeus Job Correlator    → Batch job tracking            │
│  └── Incident Memory Store  → sqlite-vec vector similarity   │
└─────────────────────────────────────────────────────────────┘
                       │
                       ↓
      Teams / Web Apps / External Systems (via REST API)
```

## 🚀 Quick Start

### Option 1: Local Development (Fastest)

```bash
# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with: ANTHROPIC_API_KEY, GITHUB_TOKEN, AWS credentials

# Start API server (with hot reload)
./run_api_server.sh
# OR
uvicorn src.api.api_server:app --reload --host 0.0.0.0 --port 8000

# Test API
curl http://localhost:8000/health
open http://localhost:8000/docs  # Interactive API documentation
```

### Option 2: Docker (Recommended)

```bash
# Build and start API
docker compose up -d

# Check status
docker compose ps

# View logs
docker compose logs -f

# Test API
curl http://localhost:8000/health
open http://localhost:8000/docs
```

### Option 3: Kubernetes (Production)

```bash
# Deploy API
kubectl apply -f k8s/

# Verify
kubectl get pods -n oncall-agent
kubectl logs -f deployment/oncall-agent-api -n oncall-agent

# Port forward for testing
kubectl port-forward -n oncall-agent svc/oncall-agent-api 8000:8000
curl http://localhost:8000/health
```

## 📋 Project Structure

```
oncall-agent-api/
├── src/
│   ├── api/                       # HTTP API for external integrations
│   │   ├── api_server.py          # FastAPI application (MAIN ENTRY POINT)
│   │   ├── agent_client.py        # Agent client wrapper
│   │   ├── custom_tools.py        # K8s tools for API mode
│   │   ├── models.py              # Pydantic request/response models
│   │   ├── validation.py          # RFC 1123 input validation
│   │   ├── session_manager.py     # Session lifecycle management
│   │   ├── middleware.py          # Auth & rate limiting
│   │   ├── memory.py              # Incident memory API endpoints
│   │   ├── hermes_chartdata.py    # Hermes ChartData monitoring
│   │   ├── cost_explorer.py       # AWS Cost Explorer endpoints
│   │   ├── athena_costs.py        # AWS Athena cost queries
│   │   ├── teams_webhook.py       # Teams webhook handler
│   │   └── teams_models.py        # Teams Adaptive Card models
│   ├── tools/                     # Helper modules
│   │   ├── k8s_analyzer.py        # Kubernetes analysis
│   │   ├── github_integrator.py   # GitHub correlation
│   │   ├── aws_integrator.py      # AWS verification
│   │   ├── aws_cost_explorer.py   # AWS Cost Explorer queries
│   │   ├── aws_athena_querier.py  # AWS Athena cost queries
│   │   ├── datadog_integrator.py  # Datadog metrics queries
│   │   ├── nat_gateway_analyzer.py # NAT traffic analysis
│   │   └── zeus_analyzer.py       # Zeus job analysis
│   ├── memory/                    # Incident memory system
│   │   ├── __init__.py            # Memory module exports
│   │   ├── incident_store.py      # sqlite-vec-based incident storage
│   │   ├── embeddings.py          # Text embedding utilities
│   │   └── models.py              # StoredIncident, SimilarIncident models
│   └── notifications/             # Teams integration
│       └── teams_notifier.py      # Adaptive Cards
├── config/                        # Configuration
│   └── service_mapping.yaml       # Service → GitHub repo + criticality
├── k8s/                           # Kubernetes manifests
│   ├── api-deployment.yaml        # API deployment
│   ├── rbac.yaml                  # Service account & RBAC
│   └── namespace.yaml             # Namespace definition
├── tests/                         # Test suite
│   ├── api/                       # API tests (validation, endpoints, middleware)
│   ├── memory/                    # Memory module tests
│   └── tools/                     # Tool module tests
├── docs/                          # Documentation
├── scripts/                       # Utility scripts
├── *.sh                           # Helper scripts
├── requirements.txt
├── Dockerfile
└── README.md                      # This file
```

## 🔧 Configuration

### Environment Variables

Create `.env` from `.env.example`:

```bash
# Core (Required - API will fail to start without these)
ANTHROPIC_API_KEY=sk-ant-...   # REQUIRED: LLM analysis for incident triage
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
CORS_ORIGINS=*  # Restrict in production

# AWS (for EKS access in Docker)
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_REGION=us-east-1

# Datadog (Optional - for metrics queries)
DATADOG_API_KEY=...
DATADOG_APP_KEY=...
DATADOG_SITE=datadoghq.com

# Logging
AGENT_LOG_LEVEL=INFO

# LLM Configuration (Optional)
ANTHROPIC_MODEL=claude-sonnet-4-5-20250929  # Claude model to use

# Severity Thresholds (Optional - adjust based on operational needs)
TRIAGE_CRITICAL_OOM_RESTARTS=10        # OOMKilled restarts → critical
TRIAGE_CRITICAL_SERVICE_RESTARTS=5     # Critical service restarts → critical
TRIAGE_HIGH_RESTARTS=3                 # Restarts → high severity
TRIAGE_MEDIUM_RESTARTS=1               # Restarts → medium severity
TRIAGE_HUMAN_INTERVENTION_RESTARTS=15  # Restarts requiring human intervention
TRIAGE_ROLLBACK_CONFIDENCE=0.8         # Confidence for rollback (0.0-1.0)
```

## 📡 API Endpoints

### Core Endpoints

```
GET  /                    - API information
GET  /health              - Health check (liveness probe)
GET  /docs                - Interactive Swagger UI
GET  /openapi.json        - OpenAPI specification
```

### Teams Integration (NEW!)

**POST /teams/webhook** - Receive Teams @mention messages via Power Automate
- Automatically creates/retrieves sessions based on Teams conversation ID
- Preserves last 5 exchanges of conversation history
- Returns Adaptive Card responses for rich Teams display
- Supports HMAC or API key authentication

**GET /teams/health** - Teams integration health check
```json
{
  "status": "healthy",
  "authentication": {
    "hmac_configured": false,
    "api_key_configured": true,
    "any_configured": true
  },
  "agent_initialized": true,
  "session_manager_initialized": true,
  "endpoint": "/teams/webhook"
}
```

### Agent Interaction

**POST /query** - Send natural language queries
```json
{
  "prompt": "Check proteus service status",
  "session_id": "optional-session-id",
  "namespace": "proteus-dev",
  "context": {"key": "value"}
}
```
Rate limit: 60 requests/minute (authenticated)

**POST /incident** - Report Kubernetes incidents
```json
{
  "service": "proteus",
  "namespace": "proteus-dev",
  "error": "CrashLoopBackOff",
  "pod": "proteus-api-abc123",
  "restart_count": 5,
  "cluster": "dev-eks"
}
```
Rate limit: 30 requests/minute

### Session Management

**POST /session** - Create session for multi-turn conversations
```json
{
  "user_id": "devops@example.com"
}
```
Returns: `{"session_id": "...", "expires_at": "..."}`
Rate limit: 10 requests/minute

**GET /session/{session_id}** - Retrieve session with history

**DELETE /session/{session_id}** - Delete session

**GET /sessions/stats** - Get session statistics

### AWS Cost Explorer (NEW! 🆕)

**GET /cost-explorer/health** - Health check for Cost Explorer integration
```
Response:
  {
    "status": "healthy",
    "boto3_available": true,
    "region": "us-east-1",
    "client_initialized": true,
    "message": "Cost Explorer integration is healthy"
  }
```
Rate limit: None | Purpose: Verify AWS Cost Explorer configuration

---

**POST /cost-explorer/anomalies** - Detect AWS cost anomalies
```json
{
  "days_back": 7,
  "min_impact": 10.0,
  "service_filter": "Amazon EC2",
  "max_results": 50
}
```
```
Response:
  {
    "status": "success",
    "anomalies": [
      {
        "anomaly_id": "abc-123-def",
        "service": "Amazon EC2",
        "impact_amount": 125.50,
        "impact_percentage": 45.2,
        "start_date": "2025-01-15",
        "end_date": "2025-01-16",
        "root_cause": "Increased instance usage in us-east-1",
        "dimension_value": "us-east-1"
      }
    ],
    "total_impact": 125.50,
    "anomaly_count": 1,
    "recommendations": ["Review instance scaling policies", ...]
  }
```
Rate limit: 30 requests/minute | Purpose: Detect unusual AWS spending patterns using ML

---

**POST /cost-explorer/daily-costs** - Get daily cost breakdown
```json
{
  "days_back": 30,
  "group_by": "SERVICE",
  "granularity": "DAILY"
}
```
```
Response:
  {
    "status": "success",
    "total_cost": 1250.75,
    "start_date": "2024-12-15",
    "end_date": "2025-01-15",
    "daily_breakdown": [
      {
        "date": "2025-01-15",
        "total": 42.50,
        "services": {
          "Amazon EC2": 25.00,
          "Amazon RDS": 17.50
        }
      }
    ],
    "top_services": [
      {"service": "Amazon EC2", "cost": 750.00},
      {"service": "Amazon RDS", "cost": 500.75}
    ]
  }
```
Rate limit: 30 requests/minute | Purpose: Analyze cost trends and service-level spending

---

**Configuration for AWS Cost Explorer:**
- Requires: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`
- IAM Permissions: `ce:GetAnomalies`, `ce:GetCostAndUsage`
- AWS Cost Anomaly Detection must be enabled in your AWS account

**EC2 Tag-Based Cost Analysis** 🎯
- Break down EC2 costs by tags (node groups, Karpenter pools, etc.)
- Identify which node pools/groups are most expensive
- Agent automatically detects tag-based cost questions
- Example: "What node groups are causing the biggest EC2 costs?"

### Hermes ChartData Monitoring

**GET /hermes-chartdata/health** - Real-time health check combining Datadog + logs
```
Query Parameters:
  - namespace: artemis-preprod (required, enum)
  - time_window_minutes: 15 (optional, default: 15)

Response:
  {
    "status": "healthy|degraded|critical",
    "pod_count": 2,
    "avg_snowflake_duration": 12.96,
    "p95_snowflake_duration": 62.51,
    "error_rate": 0.0,
    "checks_passed": ["pod_count", "cpu", "memory", "avg_snowflake", "error_rate"],
    "checks_failed": []
  }
```
Rate limit: 60 requests/minute | Purpose: Health monitoring via Datadog + log analysis

---

**GET /hermes-chartdata/metrics** - Detailed performance metrics
```
Query Parameters:
  - namespace: artemis-preprod (required, enum)
  - time_window_minutes: 60 (optional, default: 60)

Response:
  {
    "namespace": "artemis-preprod",
    "pod_count": 2,
    "cpu_usage_percent": null,
    "memory_usage_percent": null,
    "snowflake_avg_duration": 12.96,
    "snowflake_p95_duration": 62.51,
    "snowflake_max_duration": 75.47,
    "query_count": ~6/minute,
    "error_rate": 0.0,
    "measurement_period_minutes": 60
  }
```
Rate limit: 60 requests/minute | Purpose: Track Snowflake query performance metrics

---

**GET /hermes-chartdata/slow-queries** - Find slow Snowflake queries
```
Query Parameters:
  - namespace: artemis-preprod (required, enum)
  - threshold_seconds: 30 (optional, default: 30)
  - time_window_minutes: 60 (optional, default: 60)
  - limit: 10 (optional, default: 10)

Response:
  {
    "slow_queries": [
      {
        "query_id": "abc123def456",
        "client": "test_direct_small",
        "duration_snowflake": 35.6,
        "duration_total": 36.2,
        "timestamp": "2025-10-22T15:30:45Z"
      }
    ],
    "total_slow_queries": 20,
    "threshold_seconds": 30,
    "measurement_period_minutes": 60
  }
```
Rate limit: 60 requests/minute | Purpose: Identify and debug slow queries affecting performance

---

**POST /hermes-chartdata/analyze-performance** - AI-powered performance analysis
```
Query Parameters:
  - namespace: artemis-preprod (required, enum)
  - time_window_minutes: 60 (optional, default: 60)

Response:
  {
    "analysis": "Service is healthy with minor tail latency concerns...",
    "status": "healthy",
    "key_findings": ["P95 slightly elevated (62.51s vs 60s threshold)", ...],
    "recommendations": ["Monitor P95 trend", "Consider query optimization", ...],
    "metrics_summary": {...}
  }
```
Rate limit: 10 requests/minute (expensive operation) | Purpose: Deep analysis with LLM insights

---

**Configuration for Hermes ChartData:**
- Requires: `DATADOG_API_KEY`, `DATADOG_APP_KEY`, `K8S_CONTEXT=dev-eks`
- Kubernetes pod label: `app=hermes-app-chartdata`
- Log parsing: Extracts Snowflake query duration and metadata from application logs
- Monitoring threshold: 60-second average duration (P95 should stay < 60s)

### Incident Memory (NEW! 🧠)

**POST /memory/search** - Search for similar past incidents
```json
{
  "service": "proteus-api",
  "namespace": "proteus-dev",
  "error_type": "OOMKilled",
  "error_message": "Container killed due to memory limit",
  "limit": 5
}
```
```
Response:
  {
    "status": "success",
    "query": {"service": "proteus-api", "error_type": "OOMKilled"},
    "incidents_found": 2,
    "summary": "Found 2 similar incidents for proteus-api",
    "incidents": [
      {
        "id": "550e8400-e29b-41d4-a716-446655440000",
        "timestamp": "2025-01-15T10:30:00Z",
        "service": "proteus-api",
        "namespace": "proteus-dev",
        "error_type": "OOMKilled",
        "root_cause": "Memory limit too low for batch processing",
        "remediation_steps": ["Increased memory limit from 512Mi to 1Gi"],
        "similarity_score": 0.92,
        "match_reasons": ["same service", "same error type", "same namespace"]
      }
    ]
  }
```
Rate limit: 30 requests/minute | Purpose: Find similar past incidents for context

---

**POST /memory/store** - Store a new incident for future reference
```json
{
  "service": "proteus-api",
  "namespace": "proteus-dev",
  "pod_name": "proteus-api-xyz789",
  "error_type": "OOMKilled",
  "error_message": "Container killed due to memory limit exceeded",
  "severity": "high",
  "root_cause": "Memory limit too low for large data export jobs",
  "remediation_steps": ["Increased memory limit from 512Mi to 1Gi", "Added HPA for auto-scaling"],
  "resolution_status": "resolved",
  "tags": ["memory", "oom", "scaling"]
}
```
```
Response:
  {
    "status": "success",
    "incident_id": "550e8400-e29b-41d4-a716-446655440001",
    "message": "Incident stored successfully"
  }
```
Rate limit: 30 requests/minute | Purpose: Save incidents for future reference and learning

---

**GET /memory/stats** - Get incident memory statistics
```
Response:
  {
    "total_incidents": 42,
    "services": ["proteus-api", "hermes-chartdata", "atlas-auth"],
    "error_types": ["OOMKilled", "CrashLoopBackOff", "ImagePullBackOff"],
    "storage_path": "/app/data/incidents",
    "oldest_incident": "2024-06-15T08:00:00Z",
    "newest_incident": "2025-01-28T10:30:00Z"
  }
```
Rate limit: 60 requests/minute | Purpose: View memory store statistics

---

**GET /memory/health** - Health check for incident memory
```
Response:
  {
    "status": "healthy",
    "sqlite_vec_available": true,
    "storage_initialized": true,
    "total_incidents": 42
  }
```
Rate limit: None | Purpose: Verify incident memory is operational

---

**Configuration for Incident Memory:**
- Requires: `sqlite-vec>=0.1.6` (included in requirements.txt)
- Storage: SQLite database with sqlite-vec extension (persists to `/app/data/incidents` in Docker)
- Vector Search: Semantic similarity using 384-dim text embeddings with L2 distance
- Optional: Configure `INCIDENT_MEMORY_PATH` for custom storage location
- No AVX2/SIMD requirement — runs on any CPU (including Sandy Bridge)

**Teams Bot Integration:**
The agent automatically has access to incident memory via tools:
- `search_past_incidents`: Search for similar historical incidents
- `store_incident`: Save new incidents for future reference

Example Teams queries:
- "Have we seen OOMKilled issues in proteus-api before?"
- "What was the root cause of past CrashLoopBackOff incidents?"
- "Remember this incident for future reference"

## 🔌 Integration Examples

### Microsoft Teams Integration (via Power Automate)

The API includes a dedicated Teams webhook endpoint that handles @mention interactions with full conversation history support.

**Teams Webhook Endpoint:**
```
POST /teams/webhook    - Receive Teams @mention messages
GET  /teams/health     - Teams integration health check
```

**Power Automate Flow Configuration:**
1. **Trigger**: "When a new channel message is added" (Teams connector)
2. **Filter**: Check if bot is @mentioned
3. **HTTP Action**: POST to `https://your-api-url/teams/webhook`
   - Body: Teams activity payload (from trigger)
   - Headers: `X-API-Key: your-teams-api-key` or `Authorization: Bearer your-key`
4. **Response**: Reply to channel with Adaptive Card from response

**Authentication Options:**
- **HMAC-SHA256**: Native Teams Outgoing Webhook (set `TEAMS_WEBHOOK_SECRET`)
- **API Key**: Power Automate HTTP connector (set `TEAMS_API_KEY`)

**Environment Variables:**
```bash
# Option 1: HMAC Authentication (Teams Outgoing Webhook)
TEAMS_WEBHOOK_SECRET=your-base64-secret-from-teams

# Option 2: API Key Authentication (Power Automate)
TEAMS_API_KEY=your-api-key-for-teams
```

### Example Conversation Flow (Teams)

```
User in Teams: "@OnCall Is proteus having any issues?"
  ↓
Power Automate → POST /teams/webhook
  ↓
OnCall API strips @mention, creates/retrieves session
  ↓
Agent analyzes K8s cluster
  ↓
Returns Adaptive Card: "Proteus is healthy, 3 pods running normally"
  ↓
Power Automate posts reply in Teams channel

User in Teams: "@OnCall What about recent deployments?"
  ↓
Power Automate → POST /teams/webhook (same conversation ID)
  ↓
OnCall API retrieves session, includes conversation history
  ↓
Agent remembers context from previous query
  ↓
Returns: "Last deployment was 2 hours ago (v1.2.3), no issues"
```

**Key Features:**
- **Automatic session management**: Session ID derived from Teams conversation ID
- **Conversation history**: Last 5 exchanges preserved and passed to agent
- **30-minute TTL**: Sessions expire after 30 minutes of inactivity
- **Adaptive Cards**: Responses formatted for rich Teams display

### Direct API Integration

### cURL Examples

```bash
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

# Report an incident
curl -X POST http://localhost:8000/incident \
  -H "Content-Type: application/json" \
  -d '{
    "service": "proteus",
    "namespace": "proteus-dev",
    "error": "CrashLoopBackOff",
    "pod": "proteus-api-xyz",
    "restart_count": 5,
    "cluster": "dev-eks"
  }'

# Check API health
curl http://localhost:8000/health

# Get session statistics
curl http://localhost:8000/sessions/stats
```

## 🔑 Key Features

### Intelligent Analysis
- **Two-turn investigation**: Claude assesses → gather data → Claude refines
- **Root cause identification** with specific evidence
- **Exact remediation steps** (e.g., "increase memory 256M → 512M")
- **Deployment correlation** (links incidents to recent GitHub Actions)

### Tools Integration
- **Kubernetes analysis**: Pod status, events, logs, resource usage
- **GitHub deployment tracking** via PyGithub
- **AWS resource verification** via boto3 (Secrets Manager, ECR)
- **Datadog metrics** for historical performance analysis
- **NAT Gateway analysis** for cost optimization insights
- **Zeus job correlation** for batch job troubleshooting
- **Incident Memory**: sqlite-vec-powered semantic search for past incidents

### Session Management
- **30-minute TTL** with automatic cleanup
- **Multi-turn conversations** with context preservation
- **5 concurrent sessions** per user maximum
- **Session history** tracking for audit trail

### Production Ready
- **High availability** (2+ replicas recommended)
- **Resource limits** configured in K8s manifests
- **RBAC** with least-privilege (read-only ClusterRole)
- **Secrets management** via K8s Secrets
- **Health checks** and graceful shutdown
- **Rate limiting** per endpoint (60/30/10 req/min)

## 📊 Analysis Capabilities

### Kubernetes Diagnostics
- Pod health and status checks
- Container restart analysis
- Resource constraint detection
- Event correlation and timeline analysis
- Log pattern recognition

### GitHub Deployment Correlation
- Recent commit analysis (last 48 hours)
- GitHub Actions workflow status
- Deployment timing correlation
- PR and commit change analysis

### AWS Resource Verification
- **Secrets Manager**: Validates ExternalSecret references exist
- **ECR**: Checks container images are available (ImagePullBackOff diagnosis)
- CloudWatch metrics access

### Datadog Metrics Integration
- **CPU/Memory Trends**: Track resource usage over time (hours to weeks)
- **Network Traffic**: Analyze pod-level network patterns
- **Memory Leak Detection**: Identify gradual memory increases
- **Performance Correlation**: Compare metrics before/after deployments

**Available Metrics:**
- `kubernetes.cpu.usage` - CPU usage by pod/container
- `kubernetes.memory.usage` - Memory usage by pod/container
- `kubernetes.network.tx_bytes` - Network transmission
- `kubernetes.network.rx_bytes` - Network reception

**Requires**: `DATADOG_API_KEY` and `DATADOG_APP_KEY` in environment

### NAT Gateway Analysis
- **Traffic pattern analysis** from CloudWatch metrics
- **Top bandwidth consumers** identification
- **Cost optimization** recommendations
- **Zeus job correlation** (batch upload detection)
- **VPC endpoint opportunities** for S3/Databricks traffic

**Requires**: AWS credentials with CloudWatch and EC2 permissions

### Zeus Job Correlation
- **Job execution tracking** via Kubernetes Job resources
- **Upload bandwidth correlation** with NAT gateway spikes
- **Failed job detection** and diagnosis
- **Job timing analysis** for cost optimization

### Incident Memory
- **Semantic similarity search** via sqlite-vec (SQLite extension)
- **Historical incident lookup** by service, namespace, error type
- **Root cause retrieval** from past resolutions
- **Remediation suggestions** based on similar incidents
- **Teams bot integration** for natural language queries

**Features:**
- Store incidents with full context (error, root cause, remediation steps)
- Search by service name, error type, or natural language description
- Similarity scoring to find most relevant past incidents
- Persistent storage across restarts (SQLite with PVC)
- Graceful fallback when memory not available
- No AVX2/SIMD requirement — runs on any CPU architecture

**Example Use Cases:**
- "Have we seen this OOMKilled error before?"
- "What fixed the CrashLoopBackOff issue in proteus last month?"
- "Show me similar incidents to this ImagePullBackOff"

## 🐳 Docker Deployment

### Local Docker

```bash
# Build and start
docker compose up -d

# Results:
# - oncall-agent-api: HTTP API on port 8000

# View logs
docker compose logs -f oncall-agent-api

# Test API
curl http://localhost:8000/health

# Stop
docker compose down
```

### Docker Configuration

The Docker image is configured for API-only mode:
- Platform: `linux/arm64` (local development)
- Port: `8000` exposed
- Health check: `/health` endpoint every 30s
- Logging: JSON driver with rotation (10MB max, 3 files)

## ☸️ Kubernetes Deployment

### Deploy API Server

```bash
# Deploy API to Kubernetes
kubectl apply -f k8s/

# This creates:
# - Namespace: oncall-agent
# - ServiceAccount: oncall-agent (read-only RBAC)
# - Deployment: oncall-agent-api (2 replicas)
# - Service: oncall-agent-api (ClusterIP)
# - Secret: oncall-agent-credentials

# Verify deployment
kubectl get pods -n oncall-agent
kubectl logs -f deployment/oncall-agent-api -n oncall-agent
```

### Access API

**From within cluster:**
```
http://oncall-agent-api.oncall-agent.svc.cluster.local:8000
```

**From localhost (port-forward):**
```bash
kubectl port-forward -n oncall-agent svc/oncall-agent-api 8000:8000
curl http://localhost:8000/health
```

**Production (Ingress):**
Configure ingress in `k8s/` for external access

## 🧪 Testing

### API Tests

```bash
# Run all API tests (when implemented)
pytest tests/api/ -v

# Run specific test file
pytest tests/api/test_api_server.py -v

# Run with coverage
pytest tests/api/ --cov=src/api --cov-report=html

# Quick API validation
./test_query.sh
```

**Note**: Test infrastructure is configured but tests are not yet fully implemented.

### Manual Testing

```bash
# Start API server
./run_api_server.sh

# In another terminal
# Test health check
curl http://localhost:8000/health

# Test query endpoint
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Check cluster health"}'

# Test incident endpoint
curl -X POST http://localhost:8000/incident \
  -H "Content-Type: application/json" \
  -d '{
    "service": "test-service",
    "namespace": "default",
    "error": "CrashLoopBackOff",
    "restart_count": 3
  }'
```

## 🛡️ Safety Features

### Cluster Protection

Hard-coded safeguards:
- **ALLOWED_CLUSTERS**: `["dev-eks"]`
- **PROTECTED_CLUSTERS**: `["prod-eks", "staging-eks"]`

Any action targeting protected clusters raises `PermissionError`.

### Rate Limiting

Per-endpoint limits (authenticated):
- `/query`: 60 requests/minute
- `/incident`: 30 requests/minute
- `/session`: 10 requests/minute

Unauthenticated requests have lower limits.

### Authentication

- **Development:** No API key required (when `API_KEYS` not set)
- **Production:** Require `X-API-Key` header
- Configure via `API_KEYS` environment variable (comma-separated)

### Audit Trail

- All API requests logged with timestamps
- Session history tracked per user
- Query/response pairs saved in session
- No automated cluster modifications (analysis only)

### Read-Only Operations

- All API endpoints are **read-only**
- No cluster modifications permitted
- Agent provides recommendations only
- GitOps workflow required for changes

## 📚 Documentation

### Available Guides
- **[docs/README.md](docs/README.md)** - Documentation index
- **[docs/teams-power-automate-setup.md](docs/teams-power-automate-setup.md)** - Microsoft Teams integration via Power Automate
- **[k8s/README.md](k8s/README.md)** - Kubernetes deployment details

### Code Quality
- **[pyproject.toml](pyproject.toml)** - Ruff, Black, and MyPy configuration
- **[docs/plans/oncall-agent-api-code-remediation-plan.md](../docs/plans/oncall-agent-api-code-remediation-plan.md)** - Code quality remediation plan (Phases 1-4 complete)

### Interactive Documentation

When the API server is running, visit:
- **Swagger UI**: `http://localhost:8000/docs` - Interactive API testing
- **ReDoc**: `http://localhost:8000/redoc` - Alternative documentation view
- **OpenAPI Spec**: `http://localhost:8000/openapi.json` - Raw OpenAPI schema

## 🧰 Available Commands

### Local Development
```bash
./run_api_server.sh          # Start API server (with hot reload)
./setup_api.sh               # Install dependencies
./start_api_local.sh         # Alternative API starter
```

### Docker
```bash
./build_api.sh               # Build Docker image
./build.sh                   # Build Docker image (alternative)
docker compose up -d         # Start API
docker compose logs -f       # View logs
docker compose down          # Stop services
```

### AWS Deployment
```bash
./deploy-to-ecr.sh v1.0.0    # Deploy to AWS ECR
```

### Testing
```bash
pytest tests/api/ -v         # Run API tests
./test_query.sh              # Quick API query test
```

### Code Quality
```bash
black src/                   # Format code
ruff check src/              # Lint code
mypy src/                    # Type checking
```

## 🎯 Use Cases

### Use Case 1: Microsoft Teams ChatOps (Primary)
```
Deploy: API mode via Docker or K8s
Integration: Power Automate + Teams webhook endpoint
Result: DevOps team asks questions directly in Teams channels via @mention
Who: Engineers needing on-demand cluster insights without leaving Teams
Features: Autonomous session management, conversation memory, Adaptive Cards
```

### Use Case 2: Incident Analysis (Monitoring Integration)
```
Deploy: /incident endpoint
Integration: Kubernetes event watchers, alert managers
Result: Automated incident triage and remediation suggestions
Who: Monitoring systems generating K8s alerts
```

### Use Case 3: Direct API Integration
```
Deploy: Full REST API
Integration: Custom dashboards, scripts, other automation tools
Result: Natural language cluster troubleshooting interface
Who: Internal tools needing LLM-powered analysis
```

## 🔍 Analysis Engine

### Two-Turn Investigation Pattern

The agent uses a sophisticated two-turn investigation methodology:

**Turn 1: Initial Assessment**
```
Input: Incident details (pod, namespace, error, restart count)
Process:
  - Assess severity (critical/high/medium/low)
  - Create investigation plan
  - Determine what data to collect
Output: Investigation plan with priority areas
```

**Turn 2: Refined Analysis**
```
Input:
  - Turn 1 investigation plan
  - Collected data (logs, events, metrics, deployments)
Process:
  - Correlate data points
  - Identify root cause
  - Analyze deployment timing
  - Check resource constraints
Output: Root cause analysis with specific remediation steps
```

### Severity Classification

Severity levels:
- **Critical**: Service outage, OOMKilled with 10+ restarts, immediate action
- **High**: CrashLoopBackOff, 3+ restarts, automated remediation recommended
- **Medium**: Warning signs, 1-2 restarts, queue for review
- **Low**: Informational, document and learn

## 📞 Support & Troubleshooting

### Common Issues

**"Module not found" errors:**
```bash
pip install -r requirements.txt
```

**"Permission denied" for cluster:**
```bash
# Verify K8S_CONTEXT=dev-eks in .env
kubectl config current-context
```

**"ANTHROPIC_API_KEY not found" or "ANTHROPIC_API_KEY environment variable is required":**

This is a **hard requirement** - the incident triage engine will not start without a valid API key. There is no rule-based fallback.

```bash
# Ensure .env file exists with valid key
cat .env | grep ANTHROPIC_API_KEY
# Verify it's exported
echo $ANTHROPIC_API_KEY
```

**Docker container can't access EKS:**
```bash
# Set AWS credentials in .env
# Generate container kubeconfig
./scripts/generate_container_kubeconfig.sh

# Verify kubeconfig mounted
docker compose exec oncall-agent-api ls -la /root/.kube/config
```

**API not responding:**
```bash
# Check server is running
curl http://localhost:8000/health

# Check logs
docker compose logs oncall-agent-api
# OR
tail -f logs/api.log
```

**API returns 500 errors:**
```bash
# Check logs for details
docker compose logs -f oncall-agent-api

# Verify environment variables
docker compose exec oncall-agent-api env | grep ANTHROPIC

# Test K8s connectivity
kubectl cluster-info
```

**API documentation not loading:**
```bash
# Ensure server is running
curl http://localhost:8000/health

# Access docs
open http://localhost:8000/docs
```

**Datadog queries failing:**
```bash
# Verify credentials set
echo $DATADOG_API_KEY
echo $DATADOG_APP_KEY

# Test Datadog API access
curl -X GET "https://api.datadoghq.com/api/v1/validate" \
  -H "DD-API-KEY: ${DATADOG_API_KEY}" \
  -H "DD-APPLICATION-KEY: ${DATADOG_APP_KEY}"
```

**NAT Gateway analysis not working:**
```bash
# Verify AWS credentials
aws sts get-caller-identity

# Test CloudWatch access
aws cloudwatch list-metrics --namespace AWS/NATGateway --region us-east-1
```

### Getting Help

**For deployment:** Read `k8s/README.md` or the Kubernetes section above

**For Teams integration:** Read `docs/teams-power-automate-setup.md`

**For API details:** Visit `http://localhost:8000/docs` when running

## 🚦 Current Status

### ✅ Production Ready

**API Mode:**
- ✅ FastAPI HTTP server operational
- ✅ 8 endpoints implemented (query, incident, session CRUD, health, root, stats)
- ✅ Session management with TTL and automatic cleanup
- ✅ Rate limiting and API key authentication
- ✅ OpenAPI/Swagger documentation
- ✅ CORS configuration
- ✅ Comprehensive error handling

**Infrastructure:**
- ✅ Docker API-only configuration
- ✅ Kubernetes manifests for API deployment
- ✅ Build and deployment automation scripts
- ✅ Health checks and readiness probes

**Integrations:**
- ✅ Claude LLM integration via Anthropic API
- ✅ Microsoft Teams via Power Automate (NEW!)
- ✅ Kubernetes analysis tools
- ✅ GitHub deployment correlation
- ✅ AWS resource verification (Secrets Manager, ECR)
- ✅ AWS Cost Explorer with EC2 tag analysis
- ✅ Datadog metrics integration
- ✅ NAT Gateway analysis via CloudWatch
- ✅ Zeus job correlation
- ✅ Incident Memory with sqlite-vec (NEW! 🧠)

### 🎓 Learning Focus

This project demonstrates:
- **Autonomous conversation handling** with session memory
- **Microsoft Teams integration** via Power Automate webhooks
- **Direct Anthropic API usage** (no Agent SDK overhead)
- **Stateless HTTP API** design patterns
- **FastAPI** best practices for LLM integration
- **Session management** for multi-turn conversations
- **Rate limiting** and authentication for production APIs

Compare with `eks-monitoring-agent/` to understand tradeoffs between Agent SDK and direct API approaches.

## 🏃 Next Steps

### Immediate Use

1. **For local testing:**
   ```bash
   ./run_api_server.sh
   open http://localhost:8000/docs
   ```

2. **For Teams integration:**
   - Set `TEAMS_API_KEY` in your environment
   - Configure Power Automate flow to POST to `/teams/webhook`
   - Start @mentioning the bot in your Teams channel!

3. **For Docker deployment:**
   ```bash
   docker compose build  # Rebuild with latest
   docker compose up -d  # Start API
   ```

4. **For K8s deployment:**
   - Deploy API: `kubectl apply -f k8s/`
   - See `k8s/README.md` for details

## 📝 Development Workflow

### Making Changes

1. **Start with hot reload:**
   ```bash
   uvicorn src.api.api_server:app --reload --host 0.0.0.0 --port 8000
   ```

2. **Make changes** in `src/api/` or `src/tools/`

3. **Test immediately:**
   - Use Swagger UI: `http://localhost:8000/docs`
   - Or use cURL commands
   - Changes apply automatically (no restart)

4. **Add tests** in `tests/api/`

5. **Format and lint:**
   ```bash
   black src/
   ruff check src/
   ```

### Adding New API Endpoints

1. **Define Pydantic models** in `src/api/models.py`
2. **Add endpoint handler** in `src/api/api_server.py`
3. **Implement business logic** in `src/tools/` if needed
4. **Add rate limiting** decorator
5. **Test in Swagger UI**
6. **Write tests** in `tests/api/`

### Extending Analysis Capabilities

1. **Add new tool** in `src/tools/new_analyzer.py`
2. **Register in agent client** (`src/api/agent_client.py`)
3. **Update agent prompt** to use new tool
4. **Test via `/query` endpoint**

## 🔐 Security Considerations

### API Security
- Set `API_KEYS` environment variable for production
- Use specific `CORS_ORIGINS` (not `*`)
- Enable rate limiting (configured by default)
- Monitor API access logs

### Cluster Safety
- Only `dev-eks` allowed for operations
- `prod-eks` and `staging-eks` protected
- Read-only operations only (no cluster modifications)
- GitOps workflow for any changes

### Secrets Management
- Never commit `.env` with real credentials
- Use Kubernetes Secrets for production deployment
- Rotate API keys regularly
- Restrict GitHub token permissions (minimum: `repo`, `read:org`)

## 📈 Performance Metrics

- **Response time**: ~2-15 seconds for queries
- **Session TTL**: 30 minutes with auto-cleanup
- **Max sessions per user**: 5 concurrent
- **Rate limits**: 60/30/10 requests per minute by endpoint
- **Token usage**: ~8K tokens per incident analysis

## 📝 License

Internal ArtemisHealth project - All rights reserved

## 👥 Contributing

1. Create feature branch from `main`
2. Make changes with tests
3. Update relevant documentation
4. Format code: `black src/`
5. Submit PR with detailed description

For questions, contact the DevOps team.

## 🔗 References

- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [Anthropic API Documentation](https://docs.anthropic.com/)
- [Kubernetes Python Client](https://github.com/kubernetes-client/python)
- [PyGithub](https://pygithub.readthedocs.io/)
- [Datadog API](https://docs.datadoghq.com/api/)
- [Main Repository](../README.md) - Learning lab overview and SDK comparison

---

**Status:** Production Ready - API mode with Teams integration and Incident Memory fully operational
**Last Updated:** February 2026
