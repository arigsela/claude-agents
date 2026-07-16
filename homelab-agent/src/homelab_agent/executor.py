"""A2A AgentExecutor: the bridge from the A2A protocol to the LangGraph graph.

The a2a-sdk server calls execute() per message/send request; we extract the
question, run the graph (thread_id = A2A context_id, so one A2A conversation
maps to one checkpointer thread), and stream working → artifact → completed
events back. Mirrors oncall-crewai's executor shape.
"""

import logging
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

from homelab_agent.checkpointer import get_checkpointer
from homelab_agent.graph import build_graph

logger = logging.getLogger(__name__)


def _status_event(task_id, context_id, state, text, final):
    return TaskStatusUpdateEvent(
        task_id=task_id,
        context_id=context_id,
        final=final,
        status=TaskStatus(
            state=state,
            message=Message(
                role=Role.agent,
                message_id=str(uuid.uuid4()),
                parts=[TextPart(text=text)],
            ),
        ),
    )


def _extract_user_input(message) -> str:
    if message and message.parts:
        texts = []
        for part in message.parts:
            if isinstance(part, TextPart):
                texts.append(part.text)
            elif hasattr(part, "root") and isinstance(part.root, TextPart):
                texts.append(part.root.text)
        if texts:
            return " ".join(texts)
    return "Give me an overview of this homelab cluster."


class HomelabAgentExecutor(AgentExecutor):
    def __init__(self):
        # Compile once; the checkpointer (if any) makes threads persistent.
        self._graph = build_graph(checkpointer=get_checkpointer())

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        task_id, context_id = context.task_id, context.context_id
        try:
            question = _extract_user_input(context.message)
            logger.info("homelab-agent question: %s", question[:120])

            await event_queue.enqueue_event(_status_event(
                task_id, context_id, TaskState.working,
                "Consulting agent-docs (and live state if needed)...", False,
            ))

            result = await self._graph.ainvoke(
                {"question": question},
                config={"configurable": {"thread_id": context_id or str(uuid.uuid4())}},
            )
            answer = result.get("answer") or "No answer produced."

            await event_queue.enqueue_event(TaskArtifactUpdateEvent(
                task_id=task_id,
                context_id=context_id,
                artifact=Artifact(
                    artifact_id=str(uuid.uuid4()),
                    parts=[Part(root=TextPart(text=answer))],
                ),
            ))
            await event_queue.enqueue_event(_status_event(
                task_id, context_id, TaskState.completed, answer, True,
            ))
        except Exception as exc:
            logger.error("executor error: %s", exc, exc_info=True)
            await event_queue.enqueue_event(_status_event(
                task_id, context_id, TaskState.failed,
                f"homelab-agent error: {exc}", True,
            ))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError("homelab-agent does not support cancellation")
