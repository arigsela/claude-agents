"""
FastAPI Server for OnCall Troubleshooting Agent
Provides HTTP API wrapper for n8n integration
"""

import logging
import os
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded

# Add src directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from api import images
from api.agent_client import OnCallAgentClient
from api.middleware import limiter_with_key, rate_limit_exceeded_handler, verify_api_key
from api.models import (
    ErrorResponse,
    QueryRequest,
    QueryResponse,
    ResponseMessage,
    SessionRequest,
    SessionResponse,
)
from api.session_manager import SessionManager
from api.slack_integration import init_slack_integration
from api.slack_integration import router as slack_router

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# Global instances
agent: OnCallAgentClient | None = None
session_manager: SessionManager | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manage agent lifecycle during FastAPI startup and shutdown.

    On startup: Initialize the OnCallAgentClient and SessionManager
    On shutdown: Cleanup resources
    """
    global agent, session_manager

    logger.info("=" * 60)
    logger.info("Starting OnCall Agent API Server")
    logger.info("=" * 60)

    try:
        # Initialize session manager
        ttl_minutes = int(os.getenv("SESSION_TTL_MINUTES", "30"))
        max_sessions = int(os.getenv("MAX_SESSIONS_PER_USER", "5"))
        session_persist_path = os.getenv("SESSION_PERSIST_PATH")

        logger.info("Initializing SessionManager...")
        session_manager = SessionManager(
            ttl_minutes=ttl_minutes,
            max_sessions_per_user=max_sessions,
            cleanup_interval_minutes=5,
            persist_directory=session_persist_path,
        )
        session_manager.start_cleanup_task()
        logger.info("✅ SessionManager initialized")

        # Initialize agent (using Anthropic SDK directly)
        logger.info("Initializing OnCall Agent with Anthropic SDK...")
        agent = OnCallAgentClient()
        logger.info("✅ Agent initialized successfully")
        logger.info(f"   - Model: {agent.model}")
        logger.info(f"   - Tools: {len(agent.tools)}")

        # Initialize Slack integration
        init_slack_integration(agent, session_manager)
        logger.info("✅ Slack integration initialized")
    except Exception as e:
        logger.error(f"❌ Failed to initialize: {e}")
        raise

    yield

    # Cleanup
    logger.info("Shutting down OnCall Agent API Server...")
    if session_manager:
        session_manager.stop_cleanup_task()


# Initialize FastAPI application
app = FastAPI(
    title="OnCall Troubleshooting Agent API",
    description="HTTP API for OnCall Agent - n8n Integration",
    version="1.0.0",
    lifespan=lifespan,
)

# Add rate limiter to app state
app.state.limiter = limiter_with_key

# Add custom rate limit exceeded handler
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

# Configure CORS for development
# In production, restrict origins appropriately
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(images.router)
app.include_router(slack_router)


@app.get("/health")
async def health_check():
    """
    Health check endpoint for load balancers and monitoring.

    Returns:
        dict: Health status and agent initialization state
    """
    agent_status = "initialized" if agent is not None else "not_initialized"

    # If agent is not initialized, return 503 Service Unavailable
    if agent is None:
        return {"status": "unhealthy", "agent": agent_status, "message": "Agent not initialized"}

    return {"status": "healthy", "agent": agent_status, "version": "1.0.0"}


@app.get("/")
async def root():
    """
    Root endpoint with API information.

    Returns:
        dict: API information and available endpoints
    """
    return {
        "service": "OnCall Troubleshooting Agent API",
        "version": "1.0.0",
        "endpoints": {
            "health": "/health",
            "docs": "/docs",
            "openapi": "/openapi.json",
            "query": "/query (POST)",
            "session": "/session (POST/GET/DELETE)",
            "sessions_stats": "/sessions/stats (GET)",
            "images": {
                "health": "/images/health (GET)",
                "tags": "/images/tags?service={service_name} (GET)",
            },
            "slack": {
                "command": "/slack/command (POST)",
                "health": "/slack/health (GET)",
                "events": "/slack/events (POST)",
            },
        },
    }


@app.post("/query", response_model=QueryResponse)
@limiter_with_key.limit("60/minute")  # Authenticated users
async def query_agent(
    query_request: QueryRequest, request: Request, api_key: str = Depends(verify_api_key)
):
    """
    Send a query to the OnCall Agent.

    This endpoint allows you to ask questions or send instructions to the agent.
    The agent will analyze your query using its available tools (Kubernetes,
    GitHub, AWS, incident memory) and provide an intelligent response.

    **Capabilities**:
    - Kubernetes pod/deployment analysis
    - GitHub deployment correlation
    - AWS resource verification (Secrets Manager, ECR)
    - Incident memory (search past incidents, store new ones)

    **Example Queries**:
    - "Check the health of chores-tracker-backend"
    - "Why is n8n pod restarting?"
    - "Show me recent deployments for chores-tracker"
    - "Have we seen this OOMKilled error before?"

    Args:
        request: QueryRequest with prompt, optional namespace, and context

    Returns:
        QueryResponse with agent's analysis and responses

    Raises:
        HTTPException: 503 if agent not initialized, 500 for processing errors
    """
    if agent is None:
        raise HTTPException(status_code=503, detail="Agent not initialized")

    start_time = time.time()

    try:
        # Get session if session_id provided
        session = None
        if query_request.session_id and session_manager:
            session = session_manager.get_session(query_request.session_id)
            if session:
                logger.info(f"Using session: {query_request.session_id}")
            else:
                logger.warning(f"Session not found or expired: {query_request.session_id}")

        # Format the query with context
        full_query = query_request.prompt

        # Add session context if available
        if session and session.conversation_history:
            # Build actual conversation history for context
            history_lines = []
            # Limit to last 5 exchanges to avoid context overflow
            recent_history = session.conversation_history[-5:]
            for entry in recent_history:
                query = entry.get("query", "")
                responses = entry.get("responses", [])
                response_text = responses[0].get("content", "") if responses else ""
                # Truncate long responses (2000 chars to preserve YAML diffs for PR workflows)
                if len(response_text) > 2000:
                    response_text = response_text[:2000] + "..."
                history_lines.append(f"User: {query}")
                history_lines.append(f"Assistant: {response_text}")

            if history_lines:
                history_context = "\n".join(history_lines)
                full_query = (
                    f"[Previous Conversation]\n{history_context}\n\n[Current Query]\n{full_query}"
                )

        if query_request.namespace and query_request.namespace != "default":
            full_query = f"[Context: namespace={query_request.namespace}]\n{full_query}"

        # Add any additional context
        if query_request.context:
            context_str = "\n".join([f"{k}: {v}" for k, v in query_request.context.items()])
            full_query = f"[Additional Context]\n{context_str}\n\n{full_query}"

        logger.info(f"Query received: {query_request.prompt[:100]}...")
        logger.info(f"Namespace: {query_request.namespace}")
        if session:
            logger.info(f"Session history: {len(session.conversation_history)} messages")

        # Query the agent (using Anthropic SDK)
        agent_result = await agent.query(
            full_query, context=query_request.context, system_prompt=query_request.system_prompt
        )

        # Format response
        formatted_responses = [
            ResponseMessage(
                type="text", content=agent_result.get("response", "No response generated")
            )
        ]

        duration_ms = (time.time() - start_time) * 1000

        # Update session with conversation entry if session exists
        if session and session_manager:
            conversation_entry = {
                "timestamp": datetime.now().isoformat(),
                "query": query_request.prompt,
                "responses": [r.dict() for r in formatted_responses],
                "duration_ms": duration_ms,
            }
            session_manager.update_session(
                session.session_id, conversation_entry=conversation_entry
            )
            logger.debug("Session updated with conversation entry")

        logger.info(f"Query completed in {duration_ms:.2f}ms")

        return QueryResponse(
            status="success",
            session_id=query_request.session_id,
            responses=formatted_responses,
            query=query_request.prompt,
            duration_ms=duration_ms,
        )

    except Exception as e:
        logger.error(f"Query processing error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Query processing failed: {str(e)}")


@app.post("/session", response_model=SessionResponse)
@limiter_with_key.limit("10/minute")  # Limited session creation
async def create_session(
    session_request: SessionRequest, request: Request, api_key: str = Depends(verify_api_key)
):
    """
    Create a new session for multi-turn conversations.

    Sessions maintain conversation history and context across multiple queries.
    Each session has a TTL (default 30 minutes) and is automatically cleaned up
    when expired.

    Args:
        request: SessionRequest with user_id and optional metadata

    Returns:
        SessionResponse with session_id and session details

    Raises:
        HTTPException: 503 if session manager not initialized
    """
    if session_manager is None:
        raise HTTPException(status_code=503, detail="Session manager not initialized")

    try:
        session = session_manager.create_session(
            user_id=session_request.user_id, metadata=session_request.metadata
        )

        logger.info(f"Session created: {session.session_id} for {session_request.user_id}")

        return SessionResponse(
            status="created",
            session_id=session.session_id,
            user_id=session.user_id,
            created_at=session.created_at,
            last_accessed=session.last_accessed,
            conversation_history=session.conversation_history,
        )

    except Exception as e:
        logger.error(f"Session creation error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Session creation failed: {str(e)}")


@app.get("/session/{session_id}", response_model=SessionResponse)
async def get_session(session_id: str, api_key: str = Depends(verify_api_key)):
    """
    Retrieve session information and conversation history.

    Args:
        session_id: Session identifier

    Returns:
        SessionResponse with session details and conversation history

    Raises:
        HTTPException: 404 if session not found or expired
    """
    if session_manager is None:
        raise HTTPException(status_code=503, detail="Session manager not initialized")

    session = session_manager.get_session(session_id)

    if session is None:
        raise HTTPException(status_code=404, detail=f"Session not found or expired: {session_id}")

    return SessionResponse(
        status="success",
        session_id=session.session_id,
        user_id=session.user_id,
        created_at=session.created_at,
        last_accessed=session.last_accessed,
        conversation_history=session.conversation_history,
    )


@app.delete("/session/{session_id}")
async def delete_session(session_id: str, api_key: str = Depends(verify_api_key)):
    """
    Delete a session.

    Args:
        session_id: Session identifier

    Returns:
        Success message

    Raises:
        HTTPException: 404 if session not found
    """
    if session_manager is None:
        raise HTTPException(status_code=503, detail="Session manager not initialized")

    deleted = session_manager.delete_session(session_id)

    if not deleted:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    logger.info(f"Session deleted: {session_id}")
    return {"status": "deleted", "session_id": session_id}


@app.get("/sessions/stats")
async def get_session_stats(api_key: str = Depends(verify_api_key)):
    """
    Get session manager statistics.

    Returns:
        Statistics about active sessions, users, etc.

    Raises:
        HTTPException: 503 if session manager not initialized
    """
    if session_manager is None:
        raise HTTPException(status_code=503, detail="Session manager not initialized")

    stats = session_manager.get_stats()
    return {"status": "success", "stats": stats}


# Custom exception handler for validation errors
@app.exception_handler(422)
async def validation_exception_handler(request: Request, exc):
    """Custom handler for Pydantic validation errors"""
    logger.error(f"Validation error: {exc}")
    return ErrorResponse(
        error="ValidationError", message="Request validation failed", detail=str(exc)
    )


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("API_PORT", "8000"))
    host = os.getenv("API_HOST", "0.0.0.0")

    logger.info(f"Starting API server on {host}:{port}")
    uvicorn.run("api_server:app", host=host, port=port, reload=True, log_level="info")
