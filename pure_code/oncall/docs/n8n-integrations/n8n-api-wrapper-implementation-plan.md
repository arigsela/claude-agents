# n8n API Wrapper Implementation Plan: HTTP API for OnCall Agent

## Overview

This implementation adds a FastAPI HTTP wrapper around the existing OnCall Troubleshooting Agent to enable n8n integration. The API exposes endpoints for querying the agent, handling incidents, and managing sessions, while maintaining all existing functionality and safety guardrails.

**Key Goals:**
- Enable n8n AI Agent to use OnCall API as a Kubernetes troubleshooting tool ✅
- Preserve existing agent capabilities and safety mechanisms ✅
- Add session management for audit trail and rate limiting ✅
- Implement rate limiting and authentication ✅
- Maintain compatibility with existing daemon mode ✅

**Architectural Decision (Based on Testing):**
- Sessions store conversation history for audit/debugging
- Context passing is intentionally lightweight (summary only)
- n8n AI Agent maintains conversation intelligence
- Your OnCall API serves as a stateless, focused K8s expert tool

## Implementation Approach

**Architecture Pattern:** Thin API wrapper over existing agent
**Storage:** In-memory session management with optional Redis integration
**Integration Points:**
- FastAPI server wrapping `OnCallTroubleshootingAgent`
- Session management for stateful conversations
- Integration with existing orchestrator for incident handling
**Testing Strategy:** Unit tests for endpoints, integration tests for agent interactions, E2E tests with mock n8n requests

## Phase 1: Core API Server Implementation

Create the FastAPI server foundation with essential endpoints for agent interaction.

### Phase 1.1: API Server Setup ✅
File: `oncall-agent-poc/src/api/api_server.py`

**Implementation Tasks:**
- ✅ Create `src/api/` directory structure
- ✅ Create `api_server.py` with FastAPI app initialization
- ✅ Add lifespan event handlers (startup/shutdown) for agent initialization
- ✅ Implement health check endpoint (`GET /health`)
- ✅ Add CORS middleware for development
- ✅ Configure logging integration with existing agent logger

**Testing Tasks:**
File: `oncall-agent-poc/tests/api/test_api_server.py`

- ✅ Test health check endpoint returns correct status
- ✅ Test agent initialization on startup
- ✅ Test CORS headers are present
- ✅ Run tests: `pytest tests/api/test_api_server.py -v`

### Phase 1.2: Request/Response Models ✅
File: `oncall-agent-poc/src/api/models.py`

**Implementation Tasks:**
- ✅ Create Pydantic models for request validation
- ✅ Implement `QueryRequest` model (prompt, namespace, context)
- ✅ Implement `IncidentRequest` model (service, namespace, error, pod, restart_count, cluster)
- ✅ Implement `SessionRequest` model (session_id, user_id)
- ✅ Create response models (`QueryResponse`, `IncidentResponse`, `ErrorResponse`)
- ✅ Add input validation (max length, required fields, regex patterns)

**Testing Tasks:**
File: `oncall-agent-poc/tests/api/test_models.py`

- ✅ Test request model validation (valid inputs)
- ✅ Test request model validation (invalid inputs raise errors)
- ✅ Test response model serialization
- ✅ Run tests: `pytest tests/api/test_models.py -v`

### Phase 1.3: Query Endpoint Implementation ✅
File: `oncall-agent-poc/src/api/api_server.py`

**Implementation Tasks:**
- ✅ Implement `POST /query` endpoint
- ✅ Extract prompt and context from request
- ✅ Format query with namespace context if provided
- ✅ Call `agent.query()` and await responses
- ✅ Format responses for JSON serialization
- ✅ Add error handling with appropriate HTTP status codes (400, 500, 503)
- ✅ Add request logging with duration tracking

**Testing Tasks:**
File: `oncall-agent-poc/tests/api/test_query_endpoint.py`

- ✅ Test successful query with valid input
- ✅ Test query with namespace context
- ✅ Test error handling for invalid queries
- ✅ Test response format matches schema
- ✅ Run tests: `pytest tests/api/test_query_endpoint.py -v`

### Phase 1.4: Incident Endpoint Implementation ✅
File: `oncall-agent-poc/src/api/api_server.py`

**Implementation Tasks:**
- ✅ Implement `POST /incident` endpoint
- ✅ Extract incident details from request
- ✅ Build alert dictionary compatible with `agent.handle_incident()`
- ✅ Call incident handler and format response
- ✅ Add cluster validation (dev-eks only)
- ✅ Implement severity determination based on restart count and error type
- ✅ Add error handling for agent failures

**Testing Tasks:**
File: `oncall-agent-poc/tests/api/test_incident_endpoint.py`

- ✅ Test successful incident handling
- ✅ Test cluster validation (reject prod-eks)
- ✅ Test severity classification (critical/high/medium/low)
- ✅ Test error response for invalid input
- ✅ Run tests: `pytest tests/api/test_incident_endpoint.py -v`

## Phase 2: Session Management & Advanced Features

Add stateful session management for multi-turn conversations and memory integration.

### Phase 2.1: Session Manager Implementation ✅
File: `oncall-agent-poc/src/api/session_manager.py`

**Implementation Tasks:**
- ✅ Create `SessionManager` class with in-memory storage
- ✅ Implement session creation with TTL (default 30 minutes)
- ✅ Add session retrieval and update methods
- ✅ Implement session cleanup (background task)
- ✅ Add session metadata (user_id, created_at, last_accessed, conversation_history)
- ✅ Implement max sessions per user limit (default 5)

**Testing Tasks:**
File: `oncall-agent-poc/tests/api/test_session_manager.py`

- ✅ Test session creation and retrieval
- ✅ Test session expiration (TTL)
- ✅ Test session cleanup task
- ✅ Test max sessions per user enforcement
- ✅ Run tests: `pytest tests/api/test_session_manager.py -v`

### Phase 2.2: Session Endpoints ✅
File: `oncall-agent-poc/src/api/api_server.py`

**Implementation Tasks:**
- ✅ Implement `POST /session` endpoint (create session)
- ✅ Implement `GET /session/{session_id}` endpoint (get session info)
- ✅ Implement `DELETE /session/{session_id}` endpoint (delete session)
- ✅ Add session_id parameter to `/query` endpoint
- ✅ Implement conversation history tracking per session
- ✅ Add `GET /sessions/stats` endpoint for monitoring

**Testing Tasks:**
File: `oncall-agent-poc/tests/api/test_session_endpoints.py`

- ✅ Test session creation returns valid session_id
- ✅ Test session retrieval with history
- ✅ Test session deletion
- ✅ Test query with session context
- ✅ Run tests: `pytest tests/api/test_session_endpoints.py -v`

### Phase 2.3: Rate Limiting & Authentication ✅
File: `oncall-agent-poc/src/api/middleware.py`

**Implementation Tasks:**
- ✅ Install slowapi for rate limiting
- ✅ Implement rate limiter with custom key function
- ✅ Add rate limit decorators to endpoints (60/min query, 30/min incident, 10/min session)
- ✅ Create API key authentication middleware
- ✅ Add `X-API-KEY` header validation
- ✅ Implement custom rate limit exceeded handler

**Testing Tasks:**
File: `oncall-agent-poc/tests/api/test_middleware.py`

- ✅ Test rate limiting enforcement
- ✅ Test API key validation (valid/invalid)
- ✅ Test different rate limits per endpoint
- ✅ Test authentication disabled in dev mode (no API_KEYS set)
- ✅ Run tests: `pytest tests/api/test_middleware.py -v`

## Phase 3: Infrastructure & Deployment

Update deployment configurations to support the API server alongside existing daemon mode.

### Phase 3.1: Docker Configuration ✅
File: `oncall-agent-poc/Dockerfile`

**Implementation Tasks:**
- ✅ Add FastAPI and uvicorn to `requirements.txt`
- ✅ Add slowapi for rate limiting to `requirements.txt`
- ✅ Add python-multipart for form data to `requirements.txt`
- ✅ Create `docker-entrypoint.sh` script to support multiple run modes
- ✅ Add environment variable `RUN_MODE` (daemon/api/both)
- ✅ Update Dockerfile to use entrypoint script with mode detection
- ✅ Add mode-specific health checks (curl for API, python for daemon)

**Testing Tasks:**
File: `test_docker_api.sh`

- ✅ Build script created: `build_api.sh`
- ✅ Test script created: `test_docker_api.sh`
- ✅ Entrypoint supports all three modes (daemon/api/both)
- ✅ Health checks configured per mode

### Phase 3.2: Docker Compose Configuration ✅
File: `oncall-agent-poc/docker-compose.yml`

**Implementation Tasks:**
- ✅ Split into two services: `oncall-agent-daemon` and `oncall-agent-api`
- ✅ Add port mapping 8000:8000 for API access
- ✅ Add all API environment variables (API_KEYS, SESSION_TTL, RATE_LIMITS, CORS)
- ✅ Configure volume mounts for configs and kubeconfig
- ✅ Add healthcheck for API service (curl-based)
- ✅ Support running daemon only, API only, or both

**Testing Tasks:**
File: `test_docker_api.sh`

- ✅ Test script validates build and container startup
- ✅ Tests health endpoint, session creation, query endpoint
- ✅ Supports selective service startup (daemon/api/both)

### Phase 3.3: Kubernetes Manifests ✅
File: `oncall-agent-poc/k8s/api-deployment.yaml`

**Implementation Tasks:**
- ✅ Create complete `api-deployment.yaml` with all K8s resources
- ✅ Configure deployment with 2 replicas for HA
- ✅ Create dedicated ServiceAccount `oncall-agent-api-sa`
- ✅ Create ClusterRole with read-only K8s permissions
- ✅ Configure resource limits (512Mi/1Gi memory, 500m/1000m CPU)
- ✅ Add Secret resource for credentials (Anthropic, GitHub, API keys)
- ✅ Create Service resource (ClusterIP, port 80 → 8000)
- ✅ Add liveness and readiness probes (HTTP /health endpoint)
- ✅ Include optional Ingress configuration (commented out)

**Testing Tasks:**
File: `k8s/deployment-guide.md`, `docs/deployment-guide.md`

- ✅ Deployment guide created with step-by-step instructions
- ✅ Includes dry-run validation commands
- ✅ Includes troubleshooting section
- ✅ Ready for deployment to dev-eks cluster

## Phase 4: Integration, Documentation & n8n Workflow

Create comprehensive documentation and example n8n workflows for integration.

### Phase 4.1: API Documentation ⬜
File: `oncall-agent-poc/docs/api-documentation.md`

**Implementation Tasks:**
- ⬜ Create API documentation with endpoint specifications
- ⬜ Add OpenAPI/Swagger integration to FastAPI
- ⬜ Document authentication requirements
- ⬜ Add example requests/responses for each endpoint
- ⬜ Document rate limiting rules
- ⬜ Add error response reference table

**Testing Tasks:**
File: Manual validation

- ⬜ Verify OpenAPI docs accessible at http://localhost:8000/docs
- ⬜ Test example requests from documentation
- ⬜ Validate error responses match documentation

### Phase 4.2: n8n Workflow Examples ⬜
File: `oncall-agent-poc/docs/n8n-integration-guide.md`

**Implementation Tasks:**
- ⬜ Create n8n integration guide
- ⬜ Provide example workflow JSON for chat interface
- ⬜ Document Code Node for query formatting
- ⬜ Document HTTP Request Node configuration
- ⬜ Add workflow for incident alerts from Kubernetes
- ⬜ Add workflow for memory integration (Zeus nodes)

**Testing Tasks:**
File: Manual n8n testing

- ⬜ Import example workflow to n8n
- ⬜ Test chat interface workflow
- ⬜ Test incident alert workflow
- ⬜ Verify response formatting

### Phase 4.3: Integration Tests ⬜
File: `oncall-agent-poc/tests/integration/test_api_integration.py`

**Implementation Tasks:**
- ⬜ Create end-to-end integration test suite
- ⬜ Test full query flow (request → agent → response)
- ⬜ Test incident handling with Teams notification
- ⬜ Test session-based conversation flow
- ⬜ Test rate limiting behavior
- ⬜ Mock external dependencies (K8s, GitHub, Anthropic API)

**Testing Tasks:**
File: `oncall-agent-poc/tests/integration/test_api_integration.py`

- ⬜ Run integration tests: `pytest tests/integration/ -v`
- ⬜ Verify all endpoints work together
- ⬜ Test error propagation
- ⬜ Test concurrent requests

## Technical Notes

### FastAPI Application Structure

```python
from fastapi import FastAPI, HTTPException, Depends, Header
from contextlib import asynccontextmanager
import logging

# Global agent instance
agent = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage agent lifecycle"""
    global agent
    logger.info("Initializing OnCall Agent...")
    agent = OnCallTroubleshootingAgent()
    yield
    logger.info("Shutting down OnCall Agent...")

app = FastAPI(
    title="OnCall Troubleshooting Agent API",
    version="1.0.0",
    lifespan=lifespan
)
```

### Request/Response Models

```python
from pydantic import BaseModel, Field, validator
from typing import Optional, Dict, Any, List

class QueryRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=10000)
    namespace: Optional[str] = Field(default="default", max_length=253)
    context: Optional[Dict[str, Any]] = Field(default_factory=dict)
    session_id: Optional[str] = None

class IncidentRequest(BaseModel):
    service: str = Field(..., min_length=1)
    namespace: str = Field(default="default")
    error: str = Field(..., min_length=1)
    pod: Optional[str] = None
    restart_count: int = Field(default=0, ge=0)
    cluster: str = Field(default="dev-eks")

    @validator('cluster')
    def validate_cluster(cls, v):
        if v not in ['dev-eks']:
            raise ValueError('Only dev-eks cluster is allowed')
        return v

class QueryResponse(BaseModel):
    status: str
    session_id: Optional[str] = None
    responses: List[Dict[str, str]]
    query: str
    duration_ms: Optional[float] = None
```

### Session Management

```python
from datetime import datetime, timedelta
import uuid
from typing import Dict, Optional

class SessionManager:
    def __init__(self, ttl_minutes: int = 30, max_per_user: int = 5):
        self.sessions: Dict[str, Dict] = {}
        self.ttl = timedelta(minutes=ttl_minutes)
        self.max_per_user = max_per_user

    def create_session(self, user_id: str) -> str:
        session_id = str(uuid.uuid4())
        self.sessions[session_id] = {
            'user_id': user_id,
            'created_at': datetime.now(),
            'last_accessed': datetime.now(),
            'history': []
        }
        self._cleanup_old_sessions(user_id)
        return session_id

    def get_session(self, session_id: str) -> Optional[Dict]:
        session = self.sessions.get(session_id)
        if session and self._is_expired(session):
            del self.sessions[session_id]
            return None
        if session:
            session['last_accessed'] = datetime.now()
        return session
```

### Rate Limiting Configuration

```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

@app.post("/query")
@limiter.limit("10/minute")
async def query_agent(
    request: QueryRequest,
    x_api_key: str = Header(None)
):
    # Validate API key
    if not validate_api_key(x_api_key):
        raise HTTPException(status_code=401, detail="Invalid API key")

    # Process query...
```

## Validation Rules

1. **Cluster Validation**: Only `dev-eks` is allowed; reject any request for prod-eks or staging-eks
2. **Input Sanitization**: All text inputs sanitized to prevent injection attacks
3. **Rate Limits**:
   - Default: 10 requests/minute per IP
   - Authenticated: 60 requests/minute per API key
4. **Session Limits**:
   - Max 5 sessions per user
   - 30-minute TTL on inactive sessions
5. **Request Size**:
   - Query prompt: max 10,000 characters
   - Incident description: max 5,000 characters

## Error Handling

- `400 Bad Request`: Invalid input (validation errors, malformed JSON)
- `401 Unauthorized`: Missing or invalid API key
- `404 Not Found`: Session not found or expired
- `429 Too Many Requests`: Rate limit exceeded
- `500 Internal Server Error`: Agent processing error
- `503 Service Unavailable`: Agent not initialized or unavailable

## Environment Variables

New variables required for API mode:

```bash
# API Configuration
API_HOST=0.0.0.0
API_PORT=8000
API_KEY=your-secret-api-key-here

# Session Management
SESSION_TTL_MINUTES=30
MAX_SESSIONS_PER_USER=5

# Rate Limiting
RATE_LIMIT_PER_MINUTE=10
RATE_LIMIT_AUTHENTICATED=60

# Redis (optional, for distributed sessions)
REDIS_URL=redis://localhost:6379/0
```

## Testing Commands Quick Reference

```bash
# Run all API tests
pytest tests/api/ -v

# Run specific test file
pytest tests/api/test_api_server.py -v

# Run specific test
pytest tests/api/test_query_endpoint.py::test_successful_query -v

# Run with coverage
pytest tests/api/ --cov=src/api --cov-report=html

# Run integration tests
pytest tests/integration/ -v

# Run all tests for API wrapper
pytest -k "api" -v

# Test with verbose output
pytest tests/api/ -vv --log-cli-level=DEBUG
```

## Progress Tracking

**Total Phases:** 4
**Total Tasks:** 74 (implementation + testing)
**Completed:** 56 (24/24 Phase 1, 18/18 Phase 2, 14/14 Phase 3, 0/24 Phase 4)
**Percentage:** 76%
**Last Updated:** 2025-10-07

### Completed Phases:
- ✅ Phase 1: Core API Server Implementation (24/24 tasks) - **COMPLETE**
- ✅ Phase 2: Session Management & Advanced Features (18/18 tasks) - **COMPLETE**
- ✅ Phase 3: Infrastructure & Deployment (14/14 tasks) - **COMPLETE**
- ⬜ Phase 4: Integration, Documentation & n8n Workflow (0/24 tasks) - **OPTIONAL**

### Current Status:
✅ Phase 3 COMPLETE! Docker verified - both daemon and API modes running simultaneously.

**Verification Completed:**
- ✅ Both services start and run healthy
- ✅ Daemon actively monitoring dev-eks cluster (checked events every 5 min)
- ✅ API HTTP server running on port 8000
- ✅ Health checks passing for both modes
- ⚠️ API query endpoint needs `claude` CLI (added to Dockerfile, requires rebuild)

### Next Steps:
1. **Rebuild for full API functionality:** `docker compose build && docker compose up -d`
2. **OR use as-is:** Daemon works 100%, API health endpoint works
3. **OR deploy to K8s:** Follow `docs/deployment-guide.md`
4. Phase 4 is optional - core functionality complete!

### Phase Summaries:

#### Phase 1 Summary: ✅ COMPLETE
**Completed:** 2025-10-06

Successfully implemented the core FastAPI server foundation for n8n integration:

**What was built:**
- **API Server** (`src/api/api_server.py`): FastAPI app with lifespan management, CORS middleware, health endpoint
- **Data Models** (`src/api/models.py`): Complete Pydantic models for request/response validation
- **Query Endpoint** (`POST /query`): Accepts natural language queries, integrates with OnCallTroubleshootingAgent
- **Incident Endpoint** (`POST /incident`): Handles K8s incident alerts with severity classification
- **Comprehensive Tests**: 4 test files covering all endpoints, models, and validation logic

**Key features:**
- Cluster protection enforced (dev-eks only)
- Severity auto-classification based on restart count and error type
- Response formatting for JSON serialization
- Error handling with appropriate HTTP status codes (400, 422, 500, 503)
- Duration tracking for performance monitoring
- OpenAPI/Swagger docs auto-generated at `/docs`

**Files created:**
- `src/api/__init__.py`
- `src/api/api_server.py` (355 lines)
- `src/api/models.py` (245 lines)
- `tests/api/test_api_server.py`
- `tests/api/test_models.py`
- `tests/api/test_query_endpoint.py`
- `tests/api/test_incident_endpoint.py`
- `validate_api.py` (quick validation script)

**Updated:**
- `requirements.txt` - Added fastapi, uvicorn, python-multipart

**Ready for:**
Phase 2 (Session Management) or immediate testing with:
```bash
pip install -r requirements.txt
uvicorn src.api.api_server:app --reload --port 8000
```

#### Phase 2 Summary: ✅ COMPLETE
**Completed:** 2025-10-06

Successfully implemented session management, rate limiting, and authentication:

**What was built:**
- **SessionManager** (`src/api/session_manager.py`): Full session lifecycle management with TTL, cleanup, and per-user limits
- **Session Endpoints**: CRUD operations for sessions (POST /session, GET /session/{id}, DELETE /session/{id})
- **Middleware** (`src/api/middleware.py`): Rate limiting with slowapi, API key validation, custom error handlers
- **Enhanced Query Endpoint**: Session-aware queries with conversation history tracking
- **Comprehensive Tests**: Session manager tests, middleware tests, session endpoint tests

**Key features:**
- Session TTL with automatic cleanup (default 30 minutes)
- Max 5 concurrent sessions per user (configurable)
- Rate limiting per endpoint: 60/min (query), 30/min (incident), 10/min (session)
- API key authentication via X-API-Key header
- Dev mode support (authentication disabled when API_KEYS not set)
- Per-API-key rate limiting (authenticated users get their own bucket)
- Conversation history tracking and retrieval
- Session statistics endpoint for monitoring

**Files created:**
- `src/api/session_manager.py` (280 lines)
- `src/api/middleware.py` (165 lines)
- `tests/api/test_session_manager.py` (comprehensive session tests)
- `tests/api/test_middleware.py` (auth and rate limiting tests)
- `tests/api/test_session_endpoints.py` (endpoint integration tests)

**Files updated:**
- `src/api/api_server.py` - Added session endpoints, integrated rate limiting and auth
- `requirements.txt` - Added slowapi>=0.1.9
- `.env.example` - Added API configuration variables

**Ready for:**
Multi-turn conversations with session context, production deployment with authentication and rate limiting.

**Key Design Decision:**
After testing, confirmed that sessions should store history for audit/debugging, but NOT automatically inject full conversation context into queries. This design is optimal for n8n AI Agent integration where:
- n8n AI Agent orchestrates conversation with user
- Your OnCall API serves as a focused, stateless K8s expert tool
- n8n AI Agent adds necessary context to its tool calls
- Avoids redundant context management between two LLMs

**Context Enhancement (Optional):**
See `docs/session-context-enhancement.md` for options to pass conversation history to the agent if needed for direct human → API interactions (without n8n AI Agent intermediary).

#### Phase 3 Summary: ✅ COMPLETE
**Completed:** 2025-10-07

Successfully implemented Docker and Kubernetes deployment configurations:

**What was built:**
- **Docker Entrypoint** (`docker-entrypoint.sh`): Multi-mode support (daemon/api/both)
- **Updated Dockerfile**: Mode-specific health checks, entrypoint integration
- **Docker Compose**: Separate services for daemon and API with full configuration
- **Kubernetes Manifests** (`k8s/api-deployment.yaml`): Complete deployment with RBAC, secrets, service
- **Build Scripts**: `build_api.sh` for image building
- **Test Scripts**: `test_docker_api.sh` for automated Docker testing
- **Deployment Guides**: Comprehensive guides for all deployment methods

**Key features:**
- Multi-mode Docker support (daemon/api/both via RUN_MODE env var)
- High availability with 2 replicas in K8s
- Proper RBAC with read-only ClusterRole
- Health checks for both Docker and K8s
- Resource limits configured (512Mi-1Gi memory, 500m-1000m CPU)
- Service discovery via ClusterIP
- Optional Ingress configuration included
- Secrets management via K8s Secrets

**Files created:**
- `docker-entrypoint.sh` (70 lines) - Smart mode detection
- `k8s/api-deployment.yaml` (230 lines) - Complete K8s deployment
- `k8s/deployment-guide.md` - Quick deployment reference
- `build_api.sh` - Docker build script
- `test_docker_api.sh` - Automated Docker testing
- `docs/deployment-guide.md` - Comprehensive deployment guide
- `docs/deployment-modes-explained.md` - Mode comparison guide
- `docs/daemon-and-api-together.md` - How both modes work together
- `docs/rebuild-for-phase3.md` - Rebuild instructions
- `docs/PHASE-3-VERIFICATION.md` - Verification test results

**Files updated:**
- `Dockerfile` - Added RUN_MODE support, entrypoint script, claude CLI, health checks
- `docker-compose.yml` - Split into daemon and API services with full config

**Deployment options ready:**
1. Local: `./run_api_server.sh` (verified working ✅)
2. Docker: `docker compose up` (verified - both modes running ✅)
3. Kubernetes: `kubectl apply -f k8s/api-deployment.yaml` (manifests ready)

**Verification completed:**
- ✅ Both containers start and run healthy
- ✅ Daemon mode: Monitoring cluster every 5 minutes
- ✅ API mode: HTTP server on port 8000, health checks passing
- ⚠️ API query endpoint: Needs rebuild with claude CLI (Dockerfile updated)

**Ready for:**
Production deployment to dev-eks cluster, n8n integration in Kubernetes environment.

#### Phase 4 Summary:
_To be added when phase is complete_

---

## Quick Start Commands

### Phase 1 & 2 Complete - Ready to Use!

```bash
# Install dependencies
pip install -r requirements.txt

# Run API server locally
./run_api_server.sh

# Test API health
curl http://localhost:8000/health

# Create a session
curl -X POST http://localhost:8000/session \
  -H "Content-Type: application/json" \
  -d '{"user_id": "your-email@example.com"}'

# Send a query
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"prompt": "What services are you monitoring?", "namespace": "default"}'

# View interactive docs
open http://localhost:8000/docs
```

### n8n Integration

```bash
# Import workflow to n8n
# File: docs/n8n-workflow-example.json

# Follow guide
# File: docs/n8n-integration-complete-guide.md
```

### Coming in Phase 3

```bash
# Run with Docker
docker compose up api

# Deploy to Kubernetes
kubectl apply -f k8s/api-deployment.yaml
```

## References

**Implementation Documentation:**
- `docs/n8n-integration-complete-guide.md` - Complete n8n setup guide
- `docs/n8n-workflow-example.json` - Ready-to-import n8n workflow
- `docs/n8n-ai-agent-integration.md` - Architecture and patterns
- `docs/sessions-explained.md` - How sessions work
- `docs/session-context-enhancement.md` - Optional context passing enhancement
- `docs/phase-2-test-results.md` - Test results and validation
- `docs/phase-2-testing-guide.md` - Manual testing guide
- `docs/api-quick-start.md` - API usage quick start

**External Documentation:**
- FastAPI Documentation: https://fastapi.tiangolo.com/
- Slowapi (Rate Limiting): https://github.com/laurents/slowapi
- n8n Documentation: https://docs.n8n.io/
- n8n AI Agent: https://docs.n8n.io/integrations/builtin/cluster-nodes/root-nodes/n8n-nodes-langchain.agent/
- Claude Agent SDK: https://github.com/anthropics/anthropic-agent-sdk
