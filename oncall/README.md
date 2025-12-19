# OnCall Troubleshooting API

FastAPI server exposing Claude-powered Kubernetes troubleshooting via RESTful endpoints with service catalog awareness.

---

## Skills Demonstrated

| Skill | Implementation |
|-------|----------------|
| **FastAPI Development** | 8 RESTful endpoints with automatic OpenAPI/Swagger documentation |
| **Anthropic API Integration** | Direct tool calling without SDK overhead for performance |
| **Custom Tool Development** | 18 tools spanning Kubernetes, GitHub, AWS, Datadog |
| **API Security** | Key-based authentication, tiered rate limiting, CORS configuration |
| **Session Management** | Multi-turn conversations with 30-min TTL and automatic cleanup |
| **Service Catalog Design** | Priority classification (P0/P1/P2), dependency mapping, known issues |
| **Middleware Architecture** | Request validation, authentication, rate limiting pipeline |

---

## Architecture

```
src/api/
├── api_server.py      # FastAPI app with 8 endpoints
├── agent_client.py    # Anthropic API wrapper with tool calling
├── custom_tools.py    # 18 tool implementations (1,300+ lines)
├── session_manager.py # Conversation state with TTL expiration
└── middleware.py      # Auth & rate limiting middleware

config/
└── service_mapping.yaml  # Service catalog with priorities
```

---

## API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/query` | POST | Primary troubleshooting - send natural language queries |
| `/session` | POST | Create conversation session for multi-turn interactions |
| `/session/{id}` | GET | Retrieve session with full conversation history |
| `/session/{id}` | DELETE | Delete session and free resources |
| `/sessions/stats` | GET | Session statistics and metrics |
| `/health` | GET | Health check for load balancers |
| `/docs` | GET | Interactive Swagger UI |

---

## Custom Tools (18 Total)

**Kubernetes (6)**: `list_namespaces`, `list_pods`, `get_pod_logs`, `get_pod_events`, `get_deployment_status`, `list_services`

**GitHub (2)**: `search_recent_deployments`, `get_recent_commits`

**AWS (2)**: `check_secrets_manager`, `check_ecr_image`

**Datadog (3)**: `query_datadog_metrics`, `get_resource_usage_trends`, `check_network_traffic`

**Analysis (3)**: `analyze_service_health`, `correlate_deployment_with_incidents`, `check_nat_gateway_metrics`

**Correlation (2)**: `find_zeus_jobs_during_timeframe`, `correlate_nat_spike_with_zeus_jobs`

---

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Set: ANTHROPIC_API_KEY, GITHUB_TOKEN

# Run API server
./run_api_server.sh

# Open Swagger UI
open http://localhost:8000/docs
```

---

## Configuration

```bash
# Required
ANTHROPIC_API_KEY=sk-ant-...
GITHUB_TOKEN=ghp_...

# API Settings
API_PORT=8000
API_KEYS=your-secret-key  # Empty for dev mode
SESSION_TTL_MINUTES=30

# Rate Limits (requests/minute)
RATE_LIMIT_AUTHENTICATED=60
RATE_LIMIT_UNAUTHENTICATED=10
```

---

## Technologies

`FastAPI` `Anthropic API` `Pydantic` `Kubernetes Python Client` `PyGithub` `Boto3` `Datadog API` `Docker`

---

MIT License
