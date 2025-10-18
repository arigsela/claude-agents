# OnCall Agent HTTP API

FastAPI wrapper for the OnCall Troubleshooting Agent, enabling n8n integration and HTTP-based interactions.

## Quick Start

```bash
# From project root
./setup_api.sh          # Install dependencies and validate
./run_api_server.sh     # Start the API server

# Visit http://localhost:8000/docs for interactive API documentation
```

## API Endpoints

### `GET /health`
Health check endpoint for load balancers and monitoring.

**Response:**
```json
{
  "status": "healthy",
  "agent": "initialized",
  "version": "1.0.0"
}
```

### `POST /query`
Send a natural language query to the OnCall Agent.

**Request:**
```json
{
  "prompt": "What services are experiencing issues?",
  "namespace": "proteus-dev",
  "context": {
    "user": "devops-team",
    "source": "n8n"
  },
  "session_id": null
}
```

**Response:**
```json
{
  "status": "success",
  "session_id": null,
  "responses": [
    {
      "type": "text",
      "content": "Currently monitoring 5 services. No critical issues detected..."
    }
  ],
  "query": "What services are experiencing issues?",
  "duration_ms": 2345.67,
  "timestamp": "2025-10-06T12:00:00Z"
}
```

### `POST /incident`
Report a Kubernetes incident for analysis.

**Request:**
```json
{
  "service": "proteus",
  "namespace": "proteus-dev",
  "error": "CrashLoopBackOff",
  "pod": "proteus-api-7b9c8d6f4-xyz12",
  "restart_count": 5,
  "cluster": "dev-eks"
}
```

**Response:**
```json
{
  "status": "analyzed",
  "alert": { /* original alert data */ },
  "analysis": [
    {
      "type": "text",
      "content": "Root cause analysis and remediation steps..."
    }
  ],
  "severity": "high",
  "duration_ms": 3456.78,
  "timestamp": "2025-10-06T12:00:00Z"
}
```

## Severity Classification

Incidents are automatically classified based on error type and restart count:

| Severity | Conditions |
|----------|------------|
| **Critical** | OOMKilled OR restart_count >= 10 |
| **High** | CrashLoopBackOff OR restart_count >= 3 |
| **Medium** | restart_count >= 1 |
| **Low** | restart_count == 0 |

## Safety Features

- **Cluster Protection**: Only `dev-eks` is allowed; requests for prod-eks are rejected with 422 error
- **Input Validation**: All requests validated with Pydantic models
- **Error Handling**: Proper HTTP status codes (400, 422, 500, 503)
- **Logging**: All requests logged with duration tracking

## Architecture

```
FastAPI Server (lifespan managed)
    ↓
OnCallTroubleshootingAgent (initialized at startup)
    ↓
Claude Agent SDK + Direct K8s/GitHub APIs
    ↓
JSON Response
```

## Files

- `api_server.py` - FastAPI application and endpoints
- `models.py` - Pydantic request/response models
- `README.md` - This file

## Development

```bash
# Run with auto-reload
./run_api_server.sh

# Run tests
pytest tests/api/ -v

# Check code quality
black src/api/
ruff check src/api/
```

## Deployment

See parent documentation:
- `docs/n8n-api-wrapper-implementation-plan.md` - Full implementation plan
- `docs/api-quick-start.md` - Detailed quick start guide
- Phase 3 of implementation plan for Kubernetes deployment

## Next Phases

- **Phase 2**: Session management for multi-turn conversations
- **Phase 3**: Docker and Kubernetes deployment
- **Phase 4**: n8n workflow examples and documentation
