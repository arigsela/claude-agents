"""A2A AgentExecutor bridge for the K8s Diagnostics agent.

Bridges the a2a-sdk AgentExecutor interface to the CrewAI agent.
Extracts user input from A2A RequestContext, invokes CrewAI, and
returns the result via the EventQueue.
"""

import uuid

from a2a.server.agent_execution import AgentExecutor
from a2a.server.agent_execution.context import RequestContext
from a2a.server.events.event_queue import EventQueue
from a2a.types import (
    Artifact,
    Message,
    Part,
    Role,
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
    TextPart,
)

from k8s_agent.agent import invoke
from shared.a2a_utils import extract_user_input
from shared.logging_config import setup_logging

logger = setup_logging("k8s-executor")


class K8sAgentExecutor(AgentExecutor):
    """A2A executor that delegates to the CrewAI K8s agent."""

    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        """Execute a K8s investigation request.

        Extracts the user's query from the A2A request context,
        invokes the CrewAI agent, and pushes the result back
        through the event queue.
        """
        task_id = context.task_id
        context_id = context.context_id

        try:
            # Extract user input from the request
            user_input = self._extract_user_input(context)
            logger.info(
                f"Executing K8s investigation: task_id={task_id}, "
                f"query={user_input[:100]}..."
            )

            # Signal that we're working
            await event_queue.enqueue_event(
                TaskStatusUpdateEvent(
                    task_id=task_id,
                    context_id=context_id,
                    final=False,
                    status=TaskStatus(
                        state=TaskState.working,
                        message=Message(
                            role=Role.agent,
                            message_id=str(uuid.uuid4()),
                            parts=[TextPart(text="Investigating K8s cluster state...")],
                        ),
                    ),
                )
            )

            # Invoke CrewAI agent
            result = invoke(query=user_input, context_id=context_id or "")

            # Send result as artifact (CrewAI extracts from artifacts, not status.message)
            await event_queue.enqueue_event(
                TaskArtifactUpdateEvent(
                    task_id=task_id,
                    context_id=context_id,
                    artifact=Artifact(
                        artifact_id=str(uuid.uuid4()),
                        parts=[Part(root=TextPart(text=result))],
                    ),
                )
            )

            # Send completed status
            await event_queue.enqueue_event(
                TaskStatusUpdateEvent(
                    task_id=task_id,
                    context_id=context_id,
                    final=True,
                    status=TaskStatus(
                        state=TaskState.completed,
                        message=Message(
                            role=Role.agent,
                            message_id=str(uuid.uuid4()),
                            parts=[TextPart(text=result)],
                        ),
                    ),
                )
            )

        except Exception as e:
            logger.error(f"K8s executor error: {e}", exc_info=True)
            await event_queue.enqueue_event(
                TaskStatusUpdateEvent(
                    task_id=task_id,
                    context_id=context_id,
                    final=True,
                    status=TaskStatus(
                        state=TaskState.failed,
                        message=Message(
                            role=Role.agent,
                            message_id=str(uuid.uuid4()),
                            parts=[TextPart(text=f"K8s agent error: {e}")],
                        ),
                    ),
                )
            )

    async def cancel(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        """Cancel is not supported for this agent."""
        raise NotImplementedError("K8s agent does not support cancellation")

    def _extract_user_input(self, context: RequestContext) -> str:
        """Extract the user's text input from the A2A request context."""
        return extract_user_input(
            context.message,
            default="Perform a general cluster health check",
        )
