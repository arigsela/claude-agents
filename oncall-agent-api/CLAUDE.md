# CLAUDE.md

## Project Overview

**OnCall Agent API** — A FastAPI service wrapping an Anthropic SDK-powered agent for Kubernetes incident diagnosis and GitOps remediation.

**Architecture**: Direct Anthropic API tool calling (not Claude Agent SDK). The agent has ~26 tools for K8s, GitHub, AWS, Datadog, web search, and incident memory. All tools are plain async functions in `custom_tools.py` with schemas defined in `agent_client.py`.

**Key capabilities**:
- Kubernetes pod/deployment diagnosis via Python kubernetes client
- GitOps PR creation against `arigsela/kubernetes` (ArgoCD auto-sync)
- Slack `/oncall` slash commands with deferred response pattern
- Incident memory via sqlite-vec for semantic search of past incidents
- AWS cost analysis (Cost Explorer, Athena)
- Datadog metrics integration
- NAT gateway traffic analysis

## Quick Commands

```bash
# Start API server (local dev)
cd oncall-agent-api
source venv/bin/activate
uvicorn src.api.api_server:app --reload --host 0.0.0.0 --port 8000

# Run tests
PYTHONPATH=oncall-agent-api/src pytest oncall-agent-api/tests/ -v

# Run specific test file
PYTHONPATH=oncall-agent-api/src pytest oncall-agent-api/tests/api/test_gitops_tools.py -v

# Code quality
black oncall-agent-api/src/
ruff check oncall-agent-api/src/

# Docker
cd oncall-agent-api && docker compose up
```

## Directory Structure

```
oncall-agent-api/
├── src/
│   ├── api/
│   │   ├── api_server.py          # FastAPI app, lifespan, core endpoints
│   │   ├── agent_client.py        # OnCallAgentClient: Anthropic SDK, tool schemas, tool loop
│   │   ├── custom_tools.py        # All tool implementations (K8s, GitHub, GitOps, AWS, Datadog)
│   │   ├── middleware.py          # Rate limiting, API key auth, Slack signature validation
│   │   ├── models.py             # Pydantic request/response models
│   │   ├── session_manager.py    # Session TTL, conversation history
│   │   ├── slack_integration.py  # /slack router: commands, events, proactive alerts
│   │   ├── slack_models.py       # Block Kit formatters
│   │   ├── images.py             # /images router: ECR image tags
│   │   ├── memory.py             # /memory router (NOT registered in app)
│   │   ├── athena_costs.py       # /athena-costs router (NOT registered in app)
│   │   ├── cost_explorer.py      # /cost-explorer router (NOT registered in app)
│   │   └── hermes_chartdata.py   # /hermes-chartdata router (NOT registered in app)
│   ├── memory/
│   │   ├── embeddings.py         # Embedding model for incident similarity
│   │   ├── incident_store.py     # sqlite-vec vector storage
│   │   └── models.py             # Incident data models
│   └── tools/
│       ├── aws_athena_querier.py  # Athena SQL queries
│       ├── aws_cost_explorer.py   # AWS Cost Explorer API
│       ├── aws_integrator.py      # AWS Secrets Manager, ECR
│       ├── datadog_integrator.py  # Datadog metrics
│       ├── nat_gateway_analyzer.py # NAT gateway traffic
│       └── zeus_analyzer.py       # Zeus job analysis
├── tests/
│   ├── api/                       # 15+ test files
│   ├── memory/                    # Embedding and store tests
│   └── tools/                     # Tool integration tests
├── k8s/                           # Kubernetes deployment manifests
├── config/
│   ├── service_mapping.yaml       # Service-to-GitHub repo mapping
│   └── kubeconfig-container.yaml
└── .env.example                   # Required env vars template
```

## Key Architecture Details

### Registered Routers (active in api_server.py)
Only 2 routers are mounted:
- `images.router` → `/images/*`
- `slack_router` → `/slack/*`

4 routers exist but are **NOT registered**: memory, athena_costs, cost_explorer, hermes_chartdata.

### API Endpoints
| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/health` | None | Health check |
| GET | `/` | None | API info |
| POST | `/query` | API Key | Query the agent (60/min) |
| POST | `/session` | API Key | Create session (10/min) |
| GET | `/session/{id}` | API Key | Get session |
| DELETE | `/session/{id}` | API Key | Delete session |
| GET | `/sessions/stats` | API Key | Session stats |
| GET | `/images/tags` | API Key | ECR image tags |
| POST | `/slack/command` | Slack Sig | Slash command handler |
| POST | `/slack/events` | Slack Sig | Events API |
| GET | `/slack/health` | None | Slack config check |

### Agent Tool Registration Pattern
1. Implement async function in `custom_tools.py`
2. Add Anthropic tool schema in `agent_client.py` → `_define_tools()`
3. Add to tool map in `agent_client.py` → `_execute_tool()`
4. Reference in system prompt if needed

Tools without schemas in `_define_tools()` are invisible to the LLM.

### Session Management
- Sessions have a TTL (default 30 min, configurable via `SESSION_TTL_MINUTES`)
- Conversation history is truncated to last 5 exchanges, responses capped at 2000 chars
- Background cleanup task runs every 5 minutes
- Max sessions per user configurable via `MAX_SESSIONS_PER_USER`

### GitOps PR Workflow
The agent can create PRs in `arigsela/kubernetes` under `base-apps/`:
1. Path validation: all operations restricted to `GITOPS_BASE_PATH` (default: `base-apps/`)
2. No delete operations allowed (only `update` and `create`)
3. System prompt requires explicit user confirmation before PR creation
4. Branch naming: `oncall-agent/{service}-{action}-{timestamp}`

### Slack Integration
- Deferred response pattern: acknowledge within 3s, process in background, POST to `response_url`
- Multi-turn sessions: creates/resumes sessions per Slack user
- Rate limit: 30 commands/min per user
- Signature verification via HMAC-SHA256 (`SLACK_SIGNING_SECRET`)

## Required Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | Yes | Claude API key |
| `GITHUB_TOKEN` | Yes | GitHub PAT (repo + workflow scope) |
| `API_KEYS` | Yes | Comma-separated valid API keys for auth |
| `ANTHROPIC_MODEL` | No | Default: `claude-sonnet-4-5-20250929` |
| `K8S_CONTEXT` | No | Default: `dev-eks` |
| `SLACK_BOT_TOKEN` | No | Slack bot OAuth token (`xoxb-...`) |
| `SLACK_SIGNING_SECRET` | No | Slack app signing secret |
| `SLACK_ENABLED` | No | Enable Slack alerts (`true`/`false`) |
| `SLACK_ALERT_CHANNEL` | No | Channel for proactive alerts |
| `GITOPS_REPO` | No | Default: `arigsela/kubernetes` |
| `GITOPS_BASE_PATH` | No | Default: `base-apps/` |
| `GITOPS_BASE_BRANCH` | No | Default: `main` |
| `DATADOG_API_KEY` | No | For metrics queries |
| `DATADOG_APP_KEY` | No | For metrics queries |
| `BRAVE_API_KEY` | No | Brave Search API key (free tier: 2k queries/mo) |

## Testing

```bash
# All tests
PYTHONPATH=oncall-agent-api/src pytest oncall-agent-api/tests/ -v

# Specific areas
PYTHONPATH=oncall-agent-api/src pytest oncall-agent-api/tests/api/test_slack_integration.py -v
PYTHONPATH=oncall-agent-api/src pytest oncall-agent-api/tests/api/test_gitops_tools.py -v
PYTHONPATH=oncall-agent-api/src pytest oncall-agent-api/tests/memory/ -v
```

Tests mock external dependencies (`_get_github_client`, `_get_k8s_client`, Anthropic API).

## Important Notes

1. **Read-only by default**: All K8s operations are read-only. Cluster modifications only happen through GitOps PRs
2. **No auto-merge**: PRs created by the agent are never auto-merged
3. **PYTHONPATH**: Tests and imports require `src/` on the Python path
4. **Entry point**: `src/api/api_server.py` (not `src/api/server.py`)
5. **Incident memory**: Uses sqlite-vec (optional dependency, graceful fallback if not installed)
