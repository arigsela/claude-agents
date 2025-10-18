"""
FastAPI Server for OnCall Troubleshooting Agent
Provides HTTP API wrapper for n8n integration
"""

from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import logging
import os
import sys
import time
from pathlib import Path
from typing import Optional
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from datetime import datetime

# Add src directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from api.agent_client import OnCallAgentClient
from api.models import (
    QueryRequest,
    QueryResponse,
    IncidentRequest,
    IncidentResponse,
    ErrorResponse,
    ResponseMessage,
    SessionRequest,
    SessionResponse
)
from api.session_manager import SessionManager
from api.middleware import (
    limiter_with_key,
    verify_api_key,
    rate_limit_exceeded_handler
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)

# Global instances
agent: Optional[OnCallAgentClient] = None
session_manager: Optional[SessionManager] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manage agent lifecycle during FastAPI startup and shutdown.

    On startup: Initialize the OnCallTroubleshootingAgent and SessionManager
    On shutdown: Cleanup resources
    """
    global agent, session_manager

    logger.info("="*60)
    logger.info("Starting OnCall Agent API Server")
    logger.info("="*60)

    try:
        # Initialize session manager
        ttl_minutes = int(os.getenv("SESSION_TTL_MINUTES", "30"))
        max_sessions = int(os.getenv("MAX_SESSIONS_PER_USER", "5"))

        logger.info("Initializing SessionManager...")
        session_manager = SessionManager(
            ttl_minutes=ttl_minutes,
            max_sessions_per_user=max_sessions,
            cleanup_interval_minutes=5
        )
        session_manager.start_cleanup_task()
        logger.info("✅ SessionManager initialized")

        # Initialize agent (using Anthropic SDK directly)
        logger.info("Initializing OnCall Agent with Anthropic SDK...")
        agent = OnCallAgentClient()
        logger.info("✅ Agent initialized successfully")
        logger.info(f"   - Model: {agent.model}")
        logger.info(f"   - Tools: {len(agent.tools)}")
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
    lifespan=lifespan
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
        return {
            "status": "unhealthy",
            "agent": agent_status,
            "message": "Agent not initialized"
        }

    return {
        "status": "healthy",
        "agent": agent_status,
        "version": "1.0.0"
    }


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
            "incident": "/incident (POST)"
        }
    }


@app.post("/query", response_model=QueryResponse)
@limiter_with_key.limit("60/minute")  # Authenticated users
async def query_agent(
    query_request: QueryRequest,
    request: Request,
    api_key: str = Depends(verify_api_key)
):
    """
    Send a query to the OnCall Agent.

    This endpoint allows you to ask questions or send instructions to the agent.
    The agent will analyze your query using its available tools (Kubernetes,
    GitHub, AWS, NAT Gateway analysis, Zeus job correlation) and provide an
    intelligent response.

    **Capabilities**:
    - Kubernetes pod/deployment analysis
    - GitHub deployment correlation
    - AWS resource verification (Secrets Manager, ECR)
    - **NAT gateway traffic analysis** (NEW)
    - **Zeus refresh job correlation** (NEW)

    **Example NAT Gateway Queries**:
    - "What caused the NAT gateway spike at 2am?"
    - "Show me NAT traffic for the last 24 hours"
    - "Are any Zeus refresh jobs uploading data right now?"
    - "Which client refresh is using the most bandwidth?"
    - "Correlate NAT traffic with Zeus jobs yesterday"

    **Example Kubernetes Queries**:
    - "Check the health of artemis-auth service"
    - "Why is proteus pod restarting?"
    - "Show me recent deployments for hermes"

    **AWS Credentials Required**:
    For NAT gateway analysis, the API server needs AWS credentials with:
    - CloudWatch:GetMetricStatistics (read NAT metrics)
    - EC2:DescribeNatGateways (get NAT gateway info)
    - EC2:DescribeVpcs (verify VPC association)

    Args:
        request: QueryRequest with prompt, optional namespace, and context

    Returns:
        QueryResponse with agent's analysis and responses

    Raises:
        HTTPException: 503 if agent not initialized, 500 for processing errors
    """
    if agent is None:
        raise HTTPException(
            status_code=503,
            detail="Agent not initialized"
        )

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
            history_summary = f"Previous conversation ({len(session.conversation_history)} messages)"
            full_query = f"[Session Context: {history_summary}]\n{full_query}"

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
        agent_result = await agent.query(full_query)

        # Format response
        formatted_responses = [
            ResponseMessage(
                type="text",
                content=agent_result.get("response", "No response generated")
            )
        ]

        duration_ms = (time.time() - start_time) * 1000

        # Update session with conversation entry if session exists
        if session and session_manager:
            conversation_entry = {
                "timestamp": datetime.now().isoformat(),
                "query": query_request.prompt,
                "responses": [r.dict() for r in formatted_responses],
                "duration_ms": duration_ms
            }
            session_manager.update_session(
                session.session_id,
                conversation_entry=conversation_entry
            )
            logger.debug(f"Session updated with conversation entry")

        logger.info(f"Query completed in {duration_ms:.2f}ms")

        return QueryResponse(
            status="success",
            session_id=query_request.session_id,
            responses=formatted_responses,
            query=query_request.prompt,
            duration_ms=duration_ms
        )

    except Exception as e:
        logger.error(f"Query processing error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Query processing failed: {str(e)}"
        )


@app.post("/incident", response_model=IncidentResponse)
@limiter_with_key.limit("30/minute")  # Higher limit for incident reporting
async def handle_incident(
    incident_request: IncidentRequest,
    request: Request,
    api_key: str = Depends(verify_api_key)
):
    """
    Handle a Kubernetes incident alert.

    This endpoint processes incident alerts from Kubernetes monitoring systems.
    The agent will analyze the incident, check recent events, correlate with
    deployments, and provide actionable remediation recommendations.

    Args:
        request: IncidentRequest with service, error, pod info, etc.

    Returns:
        IncidentResponse with agent's analysis and severity assessment

    Raises:
        HTTPException: 503 if agent not initialized, 500 for processing errors
    """
    if agent is None:
        raise HTTPException(
            status_code=503,
            detail="Agent not initialized"
        )

    start_time = time.time()

    try:
        # Build alert dictionary
        alert = {
            "service": incident_request.service,
            "namespace": incident_request.namespace,
            "error": incident_request.error,
            "pod": incident_request.pod,
            "restart_count": incident_request.restart_count,
            "cluster": incident_request.cluster
        }

        logger.info(f"Incident received: {incident_request.service} in {incident_request.namespace}")
        logger.info(f"Error: {incident_request.error}, Restarts: {incident_request.restart_count}")

        # Process incident through agent
        result = await agent.handle_incident(alert)

        # Format analysis responses
        formatted_analysis = []
        for response in result.get('agent_response', []):
            response_type = type(response).__name__

            if response_type == "AssistantMessage" and hasattr(response, 'content'):
                for block in response.content:
                    block_type = type(block).__name__

                    if block_type == "TextBlock" and hasattr(block, 'text'):
                        formatted_analysis.append(
                            ResponseMessage(
                                type="text",
                                content=block.text
                            )
                        )

        # If no analysis, create fallback
        if not formatted_analysis:
            formatted_analysis.append(
                ResponseMessage(
                    type="text",
                    content="Incident processed but no detailed analysis available."
                )
            )

        # Determine severity based on restart count and error type
        severity = "medium"
        if incident_request.restart_count >= 10 or "OOMKilled" in incident_request.error:
            severity = "critical"
        elif incident_request.restart_count >= 3 or "CrashLoopBackOff" in incident_request.error:
            severity = "high"
        elif incident_request.restart_count >= 1:
            severity = "medium"
        else:
            severity = "low"

        duration_ms = (time.time() - start_time) * 1000

        logger.info(f"Incident analysis completed in {duration_ms:.2f}ms")
        logger.info(f"Severity: {severity}")

        return IncidentResponse(
            status="analyzed",
            alert=alert,
            analysis=formatted_analysis,
            severity=severity,
            duration_ms=duration_ms
        )

    except Exception as e:
        logger.error(f"Incident processing error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Incident processing failed: {str(e)}"
        )


@app.post("/session", response_model=SessionResponse)
@limiter_with_key.limit("10/minute")  # Limited session creation
async def create_session(
    session_request: SessionRequest,
    request: Request,
    api_key: str = Depends(verify_api_key)
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
        raise HTTPException(
            status_code=503,
            detail="Session manager not initialized"
        )

    try:
        session = session_manager.create_session(
            user_id=session_request.user_id,
            metadata=session_request.metadata
        )

        logger.info(f"Session created: {session.session_id} for {session_request.user_id}")

        return SessionResponse(
            status="created",
            session_id=session.session_id,
            user_id=session.user_id,
            created_at=session.created_at,
            last_accessed=session.last_accessed,
            conversation_history=session.conversation_history
        )

    except Exception as e:
        logger.error(f"Session creation error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Session creation failed: {str(e)}"
        )


@app.get("/session/{session_id}", response_model=SessionResponse)
async def get_session(session_id: str):
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
        raise HTTPException(
            status_code=503,
            detail="Session manager not initialized"
        )

    session = session_manager.get_session(session_id)

    if session is None:
        raise HTTPException(
            status_code=404,
            detail=f"Session not found or expired: {session_id}"
        )

    return SessionResponse(
        status="success",
        session_id=session.session_id,
        user_id=session.user_id,
        created_at=session.created_at,
        last_accessed=session.last_accessed,
        conversation_history=session.conversation_history
    )


@app.delete("/session/{session_id}")
async def delete_session(session_id: str):
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
        raise HTTPException(
            status_code=503,
            detail="Session manager not initialized"
        )

    deleted = session_manager.delete_session(session_id)

    if not deleted:
        raise HTTPException(
            status_code=404,
            detail=f"Session not found: {session_id}"
        )

    logger.info(f"Session deleted: {session_id}")
    return {"status": "deleted", "session_id": session_id}


@app.get("/sessions/stats")
async def get_session_stats():
    """
    Get session manager statistics.

    Returns:
        Statistics about active sessions, users, etc.

    Raises:
        HTTPException: 503 if session manager not initialized
    """
    if session_manager is None:
        raise HTTPException(
            status_code=503,
            detail="Session manager not initialized"
        )

    stats = session_manager.get_stats()
    return {"status": "success", "stats": stats}


# Custom exception handler for validation errors
@app.exception_handler(422)
async def validation_exception_handler(request: Request, exc):
    """Custom handler for Pydantic validation errors"""
    logger.error(f"Validation error: {exc}")
    return ErrorResponse(
        error="ValidationError",
        message="Request validation failed",
        detail=str(exc)
    )


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("API_PORT", "8000"))
    host = os.getenv("API_HOST", "0.0.0.0")

    logger.info(f"Starting API server on {host}:{port}")
    uvicorn.run(
        "api_server:app",
        host=host,
        port=port,
        reload=True,
        log_level="info"
    )
