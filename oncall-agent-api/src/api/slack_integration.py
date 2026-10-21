"""
Slack integration for OnCall Agent API.

Provides:
- /slack/command - Slash command handler (/oncall)
- /slack/health - Health check for Slack integration
- /slack/events - Events API handler (URL verification + future @mention support)
- Proactive incident alert posting to Slack channels
"""

import asyncio
import logging
import os
import time
from datetime import datetime

import aiohttp
from fastapi import APIRouter, HTTPException, Request, Response

from api.middleware import validate_slack_signature
from api.slack_models import (
    SlackSlashCommand,
    format_incident_alert,
    format_query_response,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/slack", tags=["Slack Integration"])

# Module-level references set during app startup
_agent = None
_session_manager = None

# Rate limiting: track per-user command timestamps
_user_command_timestamps: dict[str, list[float]] = {}
_RATE_LIMIT_PER_MINUTE = 30


def init_slack_integration(agent, session_manager):
    """Initialize module with references to agent and session manager.

    Called from api_server.py during lifespan startup.
    """
    global _agent, _session_manager
    _agent = agent
    _session_manager = session_manager
    logger.info("Slack integration initialized")


def _check_rate_limit(user_id: str) -> bool:
    """Check if user has exceeded rate limit.

    Returns True if request is allowed, False if rate limited.
    """
    now = time.time()
    window_start = now - 60

    if user_id not in _user_command_timestamps:
        _user_command_timestamps[user_id] = []

    # Clean old entries
    _user_command_timestamps[user_id] = [
        ts for ts in _user_command_timestamps[user_id] if ts > window_start
    ]

    if len(_user_command_timestamps[user_id]) >= _RATE_LIMIT_PER_MINUTE:
        return False

    _user_command_timestamps[user_id].append(now)
    return True


async def _process_slack_command(command: SlackSlashCommand):
    """Background task to process a slash command and post the deferred response.

    Args:
        command: Parsed slash command payload
    """
    start_time = time.time()

    try:
        # Get or create session for this Slack user
        session = None
        if _session_manager:
            # Find existing session by user_id
            existing_sessions = _session_manager.list_user_sessions(command.user_id)
            if existing_sessions:
                session = existing_sessions[-1]  # Use most recent session
                logger.info(f"Resuming Slack session for user {command.user_id}: {session.session_id}")
            else:
                session = _session_manager.create_session(
                    user_id=command.user_id,
                    metadata={
                        "source": "slack",
                        "channel_id": command.channel_id,
                        "team_id": command.team_id,
                    },
                )
                logger.info(f"Created Slack session for user {command.user_id}: {session.session_id}")

        # Query the agent
        query_text = command.text or "help"
        logger.info(f"Slack command from {command.user_name} ({command.user_id}): {query_text[:100]}")

        if _agent is None:
            raise RuntimeError("Agent not initialized")

        # Build full query with session history for multi-turn context
        full_query = query_text
        if session and session.conversation_history:
            history_lines = []
            recent_history = session.conversation_history[-5:]
            for entry in recent_history:
                query = entry.get("query", "")
                responses = entry.get("responses", [])
                response_text = responses[0].get("content", "") if responses else ""
                if len(response_text) > 2000:
                    response_text = response_text[:2000] + "..."
                history_lines.append(f"User: {query}")
                history_lines.append(f"Assistant: {response_text}")

            if history_lines:
                history_context = "\n".join(history_lines)
                full_query = (
                    f"[Previous Conversation]\n{history_context}\n\n[Current Query]\n{query_text}"
                )
            logger.info(f"Slack session history: {len(session.conversation_history)} messages")

        agent_result = await _agent.query(full_query)
        response_text = agent_result.get("response", "No response generated.")

        duration_ms = (time.time() - start_time) * 1000

        # Update session with conversation entry
        if session and _session_manager:
            conversation_entry = {
                "timestamp": datetime.now().isoformat(),
                "query": query_text,
                "responses": [{"type": "text", "content": response_text}],
                "duration_ms": duration_ms,
                "source": "slack",
            }
            _session_manager.update_session(
                session.session_id, conversation_entry=conversation_entry
            )

        # Format as Block Kit
        blocks = format_query_response(response_text, query_text, duration_ms)

        # Post deferred response to response_url
        payload = {
            "response_type": "in_channel",
            "blocks": blocks,
            "text": response_text,  # Fallback for notifications
        }

        async with aiohttp.ClientSession() as http_session:
            async with http_session.post(
                command.response_url,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.error(
                        f"Failed to post Slack response: {resp.status} - {body}"
                    )
                else:
                    logger.info(
                        f"Slack response posted for {command.user_name} in {duration_ms:.0f}ms"
                    )

    except Exception as e:
        logger.error(f"Error processing Slack command: {e}", exc_info=True)

        # Post error response
        error_payload = {
            "response_type": "ephemeral",
            "text": f"Sorry, I encountered an error processing your request: {str(e)[:200]}",
        }
        try:
            async with aiohttp.ClientSession() as http_session:
                await http_session.post(
                    command.response_url,
                    json=error_payload,
                    timeout=aiohttp.ClientTimeout(total=10),
                )
        except Exception as post_err:
            logger.error(f"Failed to post error response to Slack: {post_err}")


@router.post("/command")
async def handle_slash_command(request: Request):
    """Handle incoming Slack slash command (/oncall).

    Slack sends slash commands as application/x-www-form-urlencoded.
    We must respond within 3 seconds, so we acknowledge immediately
    and process the command in a background task.
    """
    # Read raw body for signature verification
    body = await request.body()

    # Verify Slack request signature
    signing_secret = os.getenv("SLACK_SIGNING_SECRET", "")
    timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
    signature = request.headers.get("X-Slack-Signature", "")

    if signing_secret and not validate_slack_signature(
        body, timestamp, signature, signing_secret
    ):
        raise HTTPException(status_code=401, detail="Invalid Slack request signature")

    if not signing_secret:
        logger.warning("SLACK_SIGNING_SECRET not configured - signature verification skipped")

    # Parse form data
    form_data = await request.form()
    command = SlackSlashCommand(**dict(form_data))

    # Check rate limit
    if not _check_rate_limit(command.user_id):
        return Response(
            content="You're sending commands too quickly. Please wait a moment.",
            media_type="text/plain",
            status_code=200,
        )

    # Check agent readiness
    if _agent is None:
        return Response(
            content="OnCall Agent is still initializing. Please try again in a moment.",
            media_type="text/plain",
            status_code=200,
        )

    # Launch background task for processing
    asyncio.create_task(_process_slack_command(command))

    # Immediate acknowledgement (must respond within 3 seconds)
    return Response(
        content="Thinking...",
        media_type="text/plain",
        status_code=200,
    )


@router.get("/health")
async def slack_health():
    """Health check for Slack integration.

    Returns configuration status, alert channel, and bot token presence.
    """
    slack_enabled = os.getenv("SLACK_ENABLED", "false").lower() == "true"
    bot_token = os.getenv("SLACK_BOT_TOKEN", "")
    signing_secret = os.getenv("SLACK_SIGNING_SECRET", "")
    alert_channel = os.getenv("SLACK_ALERT_CHANNEL", "")

    configured = bool(bot_token and signing_secret)

    return {
        "status": "configured" if configured else "not_configured",
        "enabled": slack_enabled,
        "signing_secret_set": bool(signing_secret),
        "bot_token_set": bool(bot_token),
        "alert_channel": alert_channel or "(not set)",
        "agent_ready": _agent is not None,
        "endpoint": "/slack/command",
    }


@router.post("/events")
async def handle_slack_events(request: Request):
    """Handle Slack Events API requests.

    Primarily handles URL verification challenge during app setup.
    Future: handle app_mention events for @oncall support.
    """
    # Read raw body for signature verification
    body = await request.body()

    # Verify Slack request signature
    signing_secret = os.getenv("SLACK_SIGNING_SECRET", "")
    timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
    signature = request.headers.get("X-Slack-Signature", "")

    if signing_secret and not validate_slack_signature(
        body, timestamp, signature, signing_secret
    ):
        raise HTTPException(status_code=401, detail="Invalid Slack request signature")

    payload = await request.json()

    # Handle URL verification challenge
    if payload.get("type") == "url_verification":
        return {"challenge": payload.get("challenge", "")}

    # Future: handle event callbacks (app_mention, etc.)
    event_type = payload.get("event", {}).get("type", "unknown")
    logger.info(f"Received Slack event: {event_type}")

    return {"ok": True}


async def post_incident_alert(alert: dict, analysis: list, severity: str):
    """Post a proactive incident alert to the configured Slack channel.

    Called from the /incident endpoint after analysis completes.
    Only posts if SLACK_ENABLED=true and SLACK_ALERT_CHANNEL is set.

    Args:
        alert: Alert dict with service, namespace, error, etc.
        analysis: List of ResponseMessage objects/dicts with analysis text
        severity: Severity level (critical, high, medium, low)
    """
    slack_enabled = os.getenv("SLACK_ENABLED", "false").lower() == "true"
    if not slack_enabled:
        return

    bot_token = os.getenv("SLACK_BOT_TOKEN", "")
    alert_channel = os.getenv("SLACK_ALERT_CHANNEL", "")

    if not bot_token or not alert_channel:
        logger.debug("Slack alert skipped: bot token or alert channel not configured")
        return

    # Check minimum severity threshold
    min_severity = os.getenv("SLACK_ALERT_MIN_SEVERITY", "high").lower()
    severity_levels = {"low": 0, "medium": 1, "high": 2, "critical": 3}
    if severity_levels.get(severity, 0) < severity_levels.get(min_severity, 2):
        logger.debug(f"Slack alert skipped: severity {severity} below threshold {min_severity}")
        return

    try:
        blocks = format_incident_alert(alert, analysis, severity)

        # Use slack_sdk WebClient for posting to channels
        from slack_sdk import WebClient
        from slack_sdk.errors import SlackApiError

        client = WebClient(token=bot_token)

        try:
            client.chat_postMessage(
                channel=alert_channel,
                blocks=blocks,
                text=f"Incident Alert: {alert.get('service', 'unknown')} - {severity.upper()}",
            )
            logger.info(
                f"Slack incident alert posted to {alert_channel} for {alert.get('service')}"
            )
        except SlackApiError as e:
            logger.error(f"Slack API error posting incident alert: {e.response['error']}")

    except Exception as e:
        logger.error(f"Failed to post Slack incident alert: {e}", exc_info=True)
