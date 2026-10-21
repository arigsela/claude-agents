"""AG-UI SSE endpoint for CopilotKit integration.

Provides a /copilotkit POST endpoint that accepts AG-UI RunAgentInput,
routes queries through the same classify/delegate pipeline as /query,
and streams back AG-UI events for CopilotKit to consume.

Uses ag-ui-protocol directly (no ag-ui-crewai dependency).
"""

import asyncio
import re
import uuid

from ag_ui.core import (
    EventType,
    RunAgentInput,
    RunFinishedEvent,
    RunStartedEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
)
from ag_ui.encoder import EventEncoder
from fastapi import Request
from fastapi.responses import StreamingResponse

from orchestrator.auth import AuthInfo, verify_jwt
from orchestrator.flow import OncallFlow, classify_query
from shared.logging_config import setup_logging

logger = setup_logging("copilotkit-endpoint")

encoder = EventEncoder()

# Pattern to strip raw CrewAI/Anthropic XML tool call blocks from agent output
_TOOL_CALL_XML_RE = re.compile(
    r"<function_calls>.*?</function_calls>",
    re.DOTALL,
)


def _clean_agent_response(text: str) -> str:
    """Strip raw XML tool-call blocks that CrewAI may include in output."""
    cleaned = _TOOL_CALL_XML_RE.sub("", text)
    # Collapse excessive whitespace left behind
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _extract_latest_user_message(input_data: RunAgentInput) -> str:
    """Extract the latest user message from AG-UI RunAgentInput."""
    if input_data.messages:
        # Walk backwards to find the last user message
        for msg in reversed(input_data.messages):
            if hasattr(msg, "role") and str(msg.role) == "user":
                if hasattr(msg, "content"):
                    content = msg.content
                    # content can be a string or a list of content parts
                    if isinstance(content, str):
                        return content
                    elif isinstance(content, list):
                        text_parts = []
                        for part in content:
                            if isinstance(part, str):
                                text_parts.append(part)
                            elif hasattr(part, "text"):
                                text_parts.append(part.text)
                        if text_parts:
                            return " ".join(text_parts)
    return "Perform a general cluster health check"


def _build_conversation_context(session_mgr, thread_id: str, max_turns: int = 5) -> str:
    """Build conversation context from recent session history.

    Returns a formatted string of recent exchanges, or empty string if none.
    """
    try:
        session = session_mgr.get_session(thread_id)
        if not session or not session.messages:
            return ""

        # Take last N exchanges (each exchange = user + assistant = 2 messages)
        recent = session.messages[-(max_turns * 2):]
        if not recent:
            return ""

        lines = []
        for msg in recent:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            # Truncate long assistant responses to keep context manageable
            if role == "assistant" and len(content) > 500:
                content = content[:500] + "... [truncated]"
            lines.append(f"{role.upper()}: {content}")

        return (
            "=== CONVERSATION HISTORY ===\n"
            + "\n\n".join(lines)
            + "\n=== END HISTORY ===\n\n"
        )
    except Exception as e:
        logger.warning(f"Failed to load conversation context: {e}")
        return ""


async def copilotkit_handler(request: Request, auth: AuthInfo | None = None):
    """Handle AG-UI requests from CopilotKit frontend.

    Accepts RunAgentInput JSON, routes through OncallFlow,
    and streams back AG-UI events as SSE.
    """
    body = await request.json()
    input_data = RunAgentInput(**body)

    thread_id = input_data.thread_id or str(uuid.uuid4())
    run_id = input_data.run_id or str(uuid.uuid4())
    message_id = str(uuid.uuid4())

    user_message = _extract_latest_user_message(input_data)

    # Resolve user_id: prefer auth info, fall back to X-User-JWT header
    user_id = auth.user_id if auth and auth.user_id else ""
    if not user_id:
        user_jwt = request.headers.get("X-User-JWT", "")
        if user_jwt.startswith("Bearer "):
            try:
                payload = verify_jwt(user_jwt[7:])
                user_id = payload.get("sub", "")
            except Exception:
                pass

    logger.info(f"CopilotKit request: thread={thread_id}, user={user_id or 'anon'}, query={user_message[:80]}...")

    async def event_stream():
        # 1. Run started
        yield encoder.encode(
            RunStartedEvent(
                type=EventType.RUN_STARTED,
                thread_id=thread_id,
                run_id=run_id,
            )
        )

        # 2. Text message start
        yield encoder.encode(
            TextMessageStartEvent(
                type=EventType.TEXT_MESSAGE_START,
                message_id=message_id,
                role="assistant",
            )
        )

        # 3. Send a "thinking" indicator while the flow runs
        # Classify on raw user message only (not context-prefixed)
        route = classify_query(user_message)
        thinking_text = {
            "k8s": "Investigating Kubernetes cluster...\n\n",
            "github": "Analyzing GitOps repository...\n\n",
            "combined": "Investigating K8s cluster and GitOps repository...\n\n",
        }.get(route, "Processing query...\n\n")

        yield encoder.encode(
            TextMessageContentEvent(
                type=EventType.TEXT_MESSAGE_CONTENT,
                message_id=message_id,
                delta=thinking_text,
            )
        )

        # 4. Run the OncallFlow in a thread (it uses sync CrewAI internally)
        try:
            # Build context from previous conversation turns
            session_mgr = request.app.state.session_manager
            context = _build_conversation_context(session_mgr, thread_id)
            query_with_context = context + user_message if context else user_message

            flow = OncallFlow()
            flow.state.query = query_with_context
            result = await asyncio.to_thread(flow.kickoff)
            result_text = _clean_agent_response(str(result))
        except Exception as e:
            logger.error(f"CopilotKit flow error: {e}", exc_info=True)
            result_text = f"Error processing query: {e}"

        # 5. Persist the exchange to the session
        try:
            session_mgr = request.app.state.session_manager
            session_mgr.append_messages(
                session_id=thread_id,
                user_msg=user_message,
                assistant_msg=result_text,
                user_id=user_id or "",
            )
        except Exception as e:
            logger.warning(f"Failed to persist session {thread_id}: {e}")

        # 6. Stream the result content
        yield encoder.encode(
            TextMessageContentEvent(
                type=EventType.TEXT_MESSAGE_CONTENT,
                message_id=message_id,
                delta=result_text,
            )
        )

        # 7. End the text message
        yield encoder.encode(
            TextMessageEndEvent(
                type=EventType.TEXT_MESSAGE_END,
                message_id=message_id,
            )
        )

        # 8. Run finished
        yield encoder.encode(
            RunFinishedEvent(
                type=EventType.RUN_FINISHED,
                thread_id=thread_id,
                run_id=run_id,
            )
        )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
