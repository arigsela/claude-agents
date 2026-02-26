"""A2A AgentExecutor bridge for the GitHub/GitOps agent.

Bridges the a2a-sdk AgentExecutor interface to the CrewAI agent.
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

from github_agent.agent import invoke
from shared.a2a_utils import extract_user_input
from shared.logging_config import setup_logging

logger = setup_logging("github-executor")


class GitHubAgentExecutor(AgentExecutor):
    """A2A executor that delegates to the CrewAI GitHub agent."""

    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        """Execute a GitOps request."""
        task_id = context.task_id
        context_id = context.context_id

        try:
            user_input = self._extract_user_input(context)
            logger.info(
                f"Executing GitOps request: task_id={task_id}, "
                f"query={user_input[:100]}..."
            )

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
                            parts=[TextPart(text="Inspecting GitOps repository...")],
                        ),
                    ),
                )
            )

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
            logger.error(f"GitHub executor error: {e}", exc_info=True)
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
                            parts=[TextPart(text=f"GitHub agent error: {e}")],
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
        raise NotImplementedError("GitHub agent does not support cancellation")

    def _extract_user_input(self, context: RequestContext) -> str:
        """Extract the user's text input from the A2A request context."""
        return extract_user_input(
            context.message,
            default="List the contents of the GitOps base-apps directory",
        )
