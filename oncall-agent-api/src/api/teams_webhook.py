"""
Microsoft Teams Webhook Router.

Handles @mention interactions from Teams channels, processes queries
through the OnCall agent, and returns responses as Adaptive Cards.

Supports two authentication methods:
1. HMAC-SHA256 (native Teams Outgoing Webhook)
2. API Key (Power Automate / HTTP connector)
"""

import logging
import os
import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request

from api.middleware import validate_teams_hmac
from api.teams_models import (
    TeamsActivity,
    TeamsResponse,
    create_adaptive_card_response,
    create_error_card,
    create_welcome_card,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/teams", tags=["teams"])


def get_webhook_secret() -> str | None:
    """
    Get Teams webhook secret from environment.

    Returns:
        Base64-encoded HMAC secret from Teams webhook configuration, or None
    """
    return os.getenv("TEAMS_WEBHOOK_SECRET")


def get_teams_api_key() -> str | None:
    """
    Get Teams API key for Power Automate authentication.

    Returns:
        API key string, or None if not configured
    """
    return os.getenv("TEAMS_API_KEY")


async def validate_teams_request(request: Request) -> bytes:
    """
    FastAPI dependency to validate Teams webhook request.

    Supports two authentication methods:
    1. HMAC-SHA256 signature (native Teams Outgoing Webhook)
       - Authorization header: "HMAC {base64_signature}"
    2. API Key (Power Automate / HTTP connector)
       - X-API-Key header or Authorization: Bearer {key}

    Args:
        request: FastAPI request object

    Returns:
        Raw request body bytes for JSON parsing

    Raises:
        HTTPException: 401 if authentication fails, 503 if not configured
    """
    # Read raw body
    body = await request.body()
    auth_header = request.headers.get("Authorization", "")
    api_key_header = request.headers.get("X-API-Key", "")

    # Get configured secrets
    hmac_secret = get_webhook_secret()
    api_key = get_teams_api_key()

    # Check if any authentication method is configured
    if not hmac_secret and not api_key:
        logger.error(
            "Teams webhook not configured - neither TEAMS_WEBHOOK_SECRET nor TEAMS_API_KEY set"
        )
        raise HTTPException(
            status_code=503,
            detail="Teams webhook not configured (set TEAMS_WEBHOOK_SECRET or TEAMS_API_KEY)",
        )

    client_host = request.client.host if request.client else "unknown"

    # Method 1: HMAC authentication (native Teams Outgoing Webhook)
    if auth_header.startswith("HMAC ") and hmac_secret:
        if validate_teams_hmac(body, auth_header, hmac_secret):
            logger.info(f"Teams webhook authenticated via HMAC from {client_host}")
            return body
        else:
            logger.warning(f"Invalid Teams HMAC signature from {client_host}")
            raise HTTPException(status_code=401, detail="Invalid HMAC signature")

    # Method 2: API Key authentication (Power Automate)
    if api_key:
        # Check X-API-Key header
        if api_key_header and api_key_header == api_key:
            logger.info(f"Teams webhook authenticated via X-API-Key from {client_host}")
            return body

        # Check Authorization: Bearer {key}
        if auth_header.startswith("Bearer ") and auth_header[7:] == api_key:
            logger.info(f"Teams webhook authenticated via Bearer token from {client_host}")
            return body

    # No valid authentication found
    logger.warning(f"Teams webhook authentication failed from {client_host}")
    raise HTTPException(
        status_code=401, detail="Authentication required (HMAC signature or API key)"
    )


def strip_at_mention(text: str) -> str:
    """
    Remove @mention tags from Teams message text.

    Teams includes the @mention in the format <at>BotName</at>
    at the start of the message.

    Args:
        text: Message text from Teams activity

    Returns:
        Cleaned message text without @mention
    """
    # Remove <at>...</at> tags and any following whitespace
    cleaned = re.sub(r"<at>.*?</at>\s*", "", text).strip()
    return cleaned


@router.post("/webhook", response_model=TeamsResponse)
async def teams_webhook(
    activity: TeamsActivity, request: Request, body: bytes = Depends(validate_teams_request)
):
    """
    Handle Microsoft Teams Outgoing Webhook.

    Teams sends HTTP POST when bot is @mentioned in channel.
    Must respond within 5 seconds with Adaptive Card.

    Flow:
    1. Validate HMAC signature (done by dependency)
    2. Strip @mention from message
    3. Get or create session for conversation
    4. Query agent with user message
    5. Return Adaptive Card response

    Args:
        activity: Parsed Teams activity payload
        request: FastAPI request object
        body: Raw body from HMAC validation dependency

    Returns:
        TeamsResponse with Adaptive Card

    Raises:
        HTTPException: 503 if agent not initialized
    """
    # Import globals from api_server to avoid circular imports
    from api.api_server import agent, session_manager

    if agent is None:
        logger.error("Agent not initialized for Teams webhook")
        return create_error_card(
            "OnCall Agent is not available. Please try again later.", "Service Unavailable"
        )

    if session_manager is None:
        logger.error("SessionManager not initialized for Teams webhook")
        return create_error_card(
            "Session manager is not available. Please try again later.", "Service Unavailable"
        )

    # Log incoming request
    logger.info(
        f"Teams webhook from {activity.from_.name} "
        f"in conversation {activity.conversation.id[:50]}..."
    )

    # Strip @mention from text
    clean_text = strip_at_mention(activity.text)

    # Handle empty messages (just @mention with no query)
    if not clean_text:
        logger.info("Empty message received, returning welcome card")
        return create_welcome_card()

    # Create session ID from Teams conversation ID
    session_id = f"teams-{activity.conversation.id}"

    # Get or create session for this conversation
    session = session_manager.get_session(session_id)

    if session is None:
        # Create new session with Teams metadata
        session = session_manager.create_session(
            user_id=activity.from_.id,
            metadata={
                "platform": "teams",
                "conversation_id": activity.conversation.id,
                "user_name": activity.from_.name,
                "tenant_id": activity.conversation.tenantId,
                "channel_id": activity.channelId,
            },
        )
        # Override the auto-generated session ID with our teams-prefixed ID
        old_id = session.session_id
        session.session_id = session_id
        # Update the sessions dict with the new ID
        if old_id in session_manager.sessions:
            del session_manager.sessions[old_id]
        session_manager.sessions[session_id] = session
        logger.info(f"Created new Teams session: {session_id}")
    else:
        logger.info(f"Using existing Teams session: {session_id}")

    try:
        # Build query with conversation history for context
        full_query = clean_text

        if session.conversation_history:
            # Build actual conversation history for context
            history_lines = []
            # Limit to last 5 exchanges to avoid context overflow
            recent_history = session.conversation_history[-5:]
            for entry in recent_history:
                query = entry.get("query", "")
                response = entry.get("response", "")
                # Truncate long responses
                if len(response) > 500:
                    response = response[:500] + "..."
                history_lines.append(f"User: {query}")
                history_lines.append(f"Assistant: {response}")

            if history_lines:
                history_context = "\n".join(history_lines)
                full_query = (
                    f"[Previous Conversation]\n{history_context}\n\n[Current Query]\n{clean_text}"
                )

        # Query agent (using existing OnCallAgentClient)
        logger.info(f"Processing query: {clean_text[:100]}...")
        agent_result = await agent.query(full_query)

        # Extract response text
        response_text = agent_result.get("response", "No response generated")

        # Update session history
        conversation_entry = {
            "timestamp": datetime.now().isoformat(),
            "user": activity.from_.name,
            "query": clean_text,
            "response": response_text[:500],  # Truncate for history
        }
        session_manager.update_session(session_id, conversation_entry=conversation_entry)

        logger.info(f"Query processed successfully for {activity.from_.name}")

        # Return Adaptive Card response
        return create_adaptive_card_response(response_text)

    except Exception as e:
        logger.error(f"Agent query failed: {e}", exc_info=True)
        return create_error_card(
            f"Failed to process your request: {str(e)[:200]}", "Processing Error"
        )


@router.get("/health")
async def teams_health():
    """
    Health check endpoint for Teams integration.

    Returns configuration status and endpoint information.

    Returns:
        dict: Health status including authentication methods configured
    """
    hmac_configured = bool(os.getenv("TEAMS_WEBHOOK_SECRET"))
    api_key_configured = bool(os.getenv("TEAMS_API_KEY"))
    any_auth_configured = hmac_configured or api_key_configured

    # Import to check initialization
    from api.api_server import agent, session_manager

    return {
        "status": "healthy" if any_auth_configured else "not_configured",
        "authentication": {
            "hmac_configured": hmac_configured,
            "api_key_configured": api_key_configured,
            "any_configured": any_auth_configured,
        },
        "agent_initialized": agent is not None,
        "session_manager_initialized": session_manager is not None,
        "endpoint": "/teams/webhook",
        "supported_auth_methods": [
            "HMAC (Teams Outgoing Webhook)" if hmac_configured else None,
            "API Key (Power Automate)" if api_key_configured else None,
        ],
    }
