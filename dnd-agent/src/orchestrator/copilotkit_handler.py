# ==============================================================================
# AG-UI Streaming Handler (CopilotKit-Compatible)
# ==============================================================================
#
# WHAT THIS FILE DOES:
# Implements the AG-UI (Agent-User Interaction) SSE streaming endpoint that
# the CopilotKit frontend consumes. This enables real-time streaming chat.
#
# WHY ag-ui-protocol INSTEAD OF copilotkit SDK?
# The `copilotkit` Python SDK imports `crewai.utilities.events.flow_events`
# which only exists in newer CrewAI versions. We're pinned to crewai==1.6.1
# (AVX2/LanceDB incompatibility on older CPUs). The `ag-ui-protocol` package
# provides the same AG-UI event types and SSE encoder with zero CrewAI deps.
#
# AG-UI PROTOCOL:
# An open standard for frontend <-> agent communication over SSE. Events:
#   - RunStarted / RunFinished — lifecycle (mandatory bookends)
#   - TextMessageStart / TextMessageContent / TextMessageEnd — streaming text
#   - ToolCallStart / ToolCallEnd — when the agent invokes tools
#
# HOW IT WORKS:
# 1. CopilotKit frontend POSTs to /copilotkit with a RunAgentInput
# 2. We run the OrchestratorFlow in a thread (sync kickoff -> async bridge)
# 3. We emit AG-UI SSE events wrapping the result
# 4. CopilotKit renders the streaming response in real-time
#
# LIMITATION:
# Since OrchestratorFlow.kickoff() is a blocking call, we emit the full
# result as a single TextMessageContent chunk (no token-level streaming).
# For true token streaming, CrewAI would need async callback hooks.
# ==============================================================================

import asyncio
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

from ag_ui.core import (
    RunAgentInput,
    EventType,
    RunStartedEvent,
    RunFinishedEvent,
    TextMessageStartEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    RunErrorEvent,
)
from ag_ui.encoder import EventEncoder

from shared.config import PROJECT_NAME
from shared.logging_config import setup_logging

logger = setup_logging("orchestrator.copilotkit")


def _run_orchestrator_flow(query: str) -> tuple[str, str]:
    """
    Run the OrchestratorFlow synchronously and return (result, route).

    This is called from a thread pool via asyncio.to_thread() to avoid
    blocking the event loop (CrewAI's kickoff() calls asyncio.run() internally).
    """
    from orchestrator.flow import OrchestratorFlow

    flow = OrchestratorFlow()
    result = flow.kickoff(inputs={"query": query})
    return str(result), flow.state.route


def setup_copilotkit(app: FastAPI):
    """
    Mount the AG-UI streaming endpoint at POST /copilotkit on the FastAPI app.

    The CopilotKit frontend connects to this endpoint and subscribes to the
    SSE event stream for real-time chat rendering.
    """

    @app.post("/copilotkit")
    async def copilotkit_handler(input_data: RunAgentInput):
        """
        AG-UI streaming endpoint.

        Receives a RunAgentInput from the CopilotKit frontend, runs the
        OrchestratorFlow, and streams the result as AG-UI SSE events.
        """
        run_id = str(uuid.uuid4())
        message_id = str(uuid.uuid4())
        encoder = EventEncoder()

        async def event_generator():
            try:
                # 1. Signal run started (mandatory first event)
                yield encoder.encode(
                    RunStartedEvent(
                        type=EventType.RUN_STARTED,
                        thread_id=input_data.thread_id,
                        run_id=run_id,
                    )
                )

                # 2. Start a text message
                yield encoder.encode(
                    TextMessageStartEvent(
                        type=EventType.TEXT_MESSAGE_START,
                        message_id=message_id,
                        role="assistant",
                    )
                )

                # 3. Extract the query from the last user message
                query = ""
                if input_data.messages:
                    # Get the last user message content
                    for msg in reversed(input_data.messages):
                        if hasattr(msg, "role") and msg.role == "user":
                            query = msg.content if hasattr(msg, "content") else str(msg)
                            break

                if not query:
                    query = "Hello"

                # 4. Run the orchestrator flow in a thread pool
                # (OrchestratorFlow.kickoff() is sync and calls asyncio.run())
                logger.info(f"CopilotKit query: {query[:100]}")
                result, route = await asyncio.to_thread(_run_orchestrator_flow, query)
                logger.info(f"CopilotKit result via route '{route}': {result[:100]}")

                # 5. Stream the result as a text content chunk
                yield encoder.encode(
                    TextMessageContentEvent(
                        type=EventType.TEXT_MESSAGE_CONTENT,
                        message_id=message_id,
                        delta=result,
                    )
                )

                # 6. End the message
                yield encoder.encode(
                    TextMessageEndEvent(
                        type=EventType.TEXT_MESSAGE_END,
                        message_id=message_id,
                    )
                )

                # 7. Signal run finished (mandatory last event)
                yield encoder.encode(
                    RunFinishedEvent(
                        type=EventType.RUN_FINISHED,
                        thread_id=input_data.thread_id,
                        run_id=run_id,
                    )
                )

            except Exception as e:
                logger.error(f"CopilotKit streaming error: {e}")
                yield encoder.encode(
                    RunErrorEvent(
                        type=EventType.RUN_ERROR,
                        message=str(e),
                        code="ORCHESTRATOR_ERROR",
                    )
                )

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    logger.info("AG-UI streaming endpoint mounted at POST /copilotkit")

