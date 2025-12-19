# OnCall Agent - CLAUDE.md

FastAPI-based troubleshooting agent for Kubernetes clusters with n8n integration.

## Architecture

- **API Server**: FastAPI with 8 HTTP endpoints
- **LLM**: Direct Anthropic API (not Agent SDK)
- **Tools**: 18 custom tools for K8s/GitHub/AWS/Datadog
- **Sessions**: 30-minute TTL with conversation history

## Quick Start

```bash
# Setup
pip install -r requirements.txt
cp .env.example .env

# Run
./run_api_server.sh
open http://localhost:8000/docs
```

## Key Files

```
src/api/
├── api_server.py      # FastAPI endpoints
├── agent_client.py    # Anthropic SDK wrapper
├── custom_tools.py    # 18 K8s/GitHub/AWS tools
├── session_manager.py # Session handling
└── middleware.py      # Auth & rate limiting
```

## API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/query` | POST | Primary troubleshooting endpoint |
| `/session` | POST | Create conversation session |
| `/session/{id}` | GET | Get session history |
| `/health` | GET | Health check |
| `/docs` | GET | Swagger UI |

## Testing

```bash
pytest tests/api/ -v
./test_query.sh
```
