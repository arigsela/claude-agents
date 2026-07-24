

"""AG-UI SSE endpoint for CopilotKit integration.

Provides a /copilotkit POST endpoint that accepts AG-UI RunAgentInput,
routes queries through the classify/delegate pipeline,
and streams back AG-UI events for CopilotKit to consume.
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

from shared.logging_config import setup_logging

logger = setup_logging("copilotkit-endpoint")

encoder = EventEncoder()

_TOOL_CALL_XML_RE = re.compile(
    r"<function_calls>.*?</function_calls>",
    re.DOTALL,
)


def _clean_agent_response(text: str) -> str:
    """Strip raw XML tool-call blocks that CrewAI may include in output."""
    cleaned = _TOOL_CALL_XML_RE.sub("", text)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _extract_latest_user_message(input_data: RunAgentInput) -> str:
    """Extract the latest user message from AG-UI RunAgentInput."""
    if input_data.messages:
        for msg in reversed(input_data.messages):
            if hasattr(msg, "role") and str(msg.role) == "user":
                if hasattr(msg, "content"):
                    content = msg.content
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
    return "Hello"


async def copilotkit_handler(request: Request, auth=None):
    """Handle AG-UI requests from CopilotKit frontend."""
    body = await request.json()
    input_data = RunAgentInput(**body)

    thread_id = input_data.thread_id or str(uuid.uuid4())
    run_id = input_data.run_id or str(uuid.uuid4())
    message_id = str(uuid.uuid4())

    user_message = _extract_latest_user_message(input_data)

    user_id = auth.user_id if auth and hasattr(auth, "user_id") and auth.user_id else ""

    logger.info(f"CopilotKit request: thread={thread_id}, query={user_message[:80]}...")

    async def event_stream():
        yield encoder.encode(
            RunStartedEvent(
                type=EventType.RUN_STARTED,
                thread_id=thread_id,
                run_id=run_id,
            )
        )

        yield encoder.encode(
            TextMessageStartEvent(
                type=EventType.TEXT_MESSAGE_START,
                message_id=message_id,
                role="assistant",
            )
        )

        yield encoder.encode(
            TextMessageContentEvent(
                type=EventType.TEXT_MESSAGE_CONTENT,
                message_id=message_id,
                delta="Processing query...\n\n",
            )
        )

        try:
            from orchestrator.flow import OrchestratorFlow

            # Build context from previous conversation turns if session manager available
            query_with_context = user_message
            session_mgr = getattr(request.app.state, "session_manager", None)
            if session_mgr:
                context = session_mgr.build_conversation_context(thread_id)
                if context:
                    query_with_context = context + user_message

            flow = OrchestratorFlow()
            flow.state.query = query_with_context
            result = await asyncio.to_thread(flow.kickoff)
            result_text = _clean_agent_response(str(result))
        except Exception as e:
            logger.error(f"CopilotKit flow error: {e}", exc_info=True)
            result_text = f"Error processing query: {e}"

        # Persist the exchange if session manager available
        try:
            session_mgr = getattr(request.app.state, "session_manager", None)
            if session_mgr:
                session_mgr.append_messages(
                    session_id=thread_id,
                    user_msg=user_message,
                    assistant_msg=result_text,
                    user_id=user_id or "",
                )
        except Exception as e:
            logger.warning(f"Failed to persist session {thread_id}: {e}")

        yield encoder.encode(
            TextMessageContentEvent(
                type=EventType.TEXT_MESSAGE_CONTENT,
                message_id=message_id,
                delta=result_text,
            )
        )

        yield encoder.encode(
            TextMessageEndEvent(
                type=EventType.TEXT_MESSAGE_END,
                message_id=message_id,
            )
        )

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

