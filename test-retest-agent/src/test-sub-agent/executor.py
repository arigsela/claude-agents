# ==============================================================================
# A2A Executor — Bridge Between A2A Protocol and CrewAI Agent
# ==============================================================================
#
# WHAT IS AN EXECUTOR?
# The A2A SDK uses an "executor" pattern. When the orchestrator sends a
# JSON-RPC "message/send" request, the A2A server calls the executor's
# execute() method. The executor bridges the A2A protocol with CrewAI:
#
#   A2A JSON-RPC request → Executor.execute() → agent.invoke(query) → A2A response
#
# EVENT SEQUENCE:
# The executor emits A2A events during processing:
# 1. TaskState.working   — "I'm processing your request"
# 2. ArtifactUpdate      — "Here's the result"
# 3. TaskState.completed  — "I'm done"
#
# These events are streamed back to the orchestrator in real-time,
# enabling progress tracking for long-running agent tasks.
# ==============================================================================

from a2a.server.agent_execution import AgentExecutor
from a2a.server.events import EventQueue
from a2a.types import (
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
    TaskArtifactUpdateEvent,
    Artifact,
    Part,
    TextPart,
)

from shared.logging_config import setup_logging

logger = setup_logging("test-sub-agent.executor")


def extract_user_input(message, default: str = "") -> str:
    """
    Extract the text content from an A2A message.

    A2A messages can wrap text in different ways depending on the SDK version.
    This helper handles both formats:
    - Direct TextPart: message.parts[0].text
    - Wrapped Part: message.parts[0].root.text

    Args:
        message: The A2A message object from the JSON-RPC request.
        default: Fallback text if extraction fails.

    Returns:
        The extracted text string.
    """
    if not message or not message.parts:
        return default

    part = message.parts[0]
    # Try direct TextPart access first
    if hasattr(part, "text"):
        return part.text
    # Try wrapped Part(root=TextPart(...)) format
    if hasattr(part, "root") and hasattr(part.root, "text"):
        return part.root.text
    return default


class SubAgentExecutor(AgentExecutor):
    """
    Bridges A2A protocol messages to the CrewAI agent.

    When the orchestrator sends a query via A2A, this executor:
    1. Extracts the query text from the A2A message
    2. Emits a "working" status event
    3. Runs the CrewAI agent via invoke()
    4. Emits the result as an artifact
    5. Emits a "completed" status event
    """

    async def execute(self, context, event_queue: EventQueue):
        """
        Process an incoming A2A request.

        Args:
            context: A2A execution context with the incoming message and task info.
            event_queue: Queue to emit A2A events (status updates, artifacts).
        """
        # Extract the query text from the A2A message
        query = extract_user_input(
            context.get_user_message(),
            default="No query provided"
        )
        logger.info(f"Received A2A request: {query[:100]}")

        # Emit "working" status — tells the orchestrator we're processing
        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                status=TaskStatus(state=TaskState.working),
            )
        )

        try:
            # Import and run the CrewAI agent
            from test-sub-agent.agent import invoke
            result = invoke(query)

            # Emit the result as an A2A artifact
            await event_queue.enqueue_event(
                TaskArtifactUpdateEvent(
                    artifact=Artifact(
                        parts=[Part(root=TextPart(text=result))],
                    ),
                )
            )

            # Emit "completed" status — tells the orchestrator we're done
            await event_queue.enqueue_event(
                TaskStatusUpdateEvent(
                    status=TaskStatus(state=TaskState.completed),
                )
            )

        except Exception as e:
            logger.error(f"Agent execution failed: {e}")
            # Emit "failed" status with error message
            await event_queue.enqueue_event(
                TaskStatusUpdateEvent(
                    status=TaskStatus(
                        state=TaskState.failed,
                        message=str(e),
                    ),
                )
            )

