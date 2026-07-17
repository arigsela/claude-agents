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
from homelab_agent.memory import get_store

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


_PROGRESS = {
    "orient": "Orienting…",
    "recall": "Recalling related context…",
    "retrieve": "Retrieving docs…",
    "delegate_k8s": "Delegating to k8s-reader…",
    "drift_check": "Checking for drift…",
    "synthesize": "Synthesizing answer…",
    # remember: silent housekeeping, no progress event
}


def _chunk_text(message_chunk) -> str:
    """Extract text from a LangGraph 'messages'-mode chunk (str or block list)."""
    text = getattr(message_chunk, "text", None)
    if isinstance(text, str) and text:
        return text
    content = getattr(message_chunk, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(b.get("text", "") for b in content if isinstance(b, dict))
    return ""


class HomelabAgentExecutor(AgentExecutor):
    def __init__(self):
        # Compile once. Checkpointer = short-term thread state; store = long-term
        # semantic memory. Both are None when unconfigured (local dev).
        self._graph = build_graph(checkpointer=get_checkpointer(), store=get_store())

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        task_id = context.task_id
        # Resolved once: every event and the checkpointer thread_id below
        # must agree on the same id, or a missing A2A context_id would get
        # a fresh uuid per use and split one conversation across "threads".
        context_id = context.context_id or str(uuid.uuid4())
        try:
            question = _extract_user_input(context.message)
            logger.info("homelab-agent question: %s", question[:120])

            await event_queue.enqueue_event(
                _status_event(
                    task_id,
                    context_id,
                    TaskState.working,
                    "Working on it…",
                    False,
                )
            )

            answer_parts: list[str] = []
            final_answer: str | None = None
            async for mode, chunk in self._graph.astream(
                {"question": question},
                config={"configurable": {"thread_id": context_id}},
                stream_mode=["updates", "messages"],
            ):
                if mode == "updates":
                    for node_name, delta in chunk.items():
                        message = _PROGRESS.get(node_name)
                        if message:
                            await event_queue.enqueue_event(
                                _status_event(
                                    task_id,
                                    context_id,
                                    TaskState.working,
                                    message,
                                    False,
                                )
                            )
                        # The "updates" delta carries the synthesize node's
                        # authoritative answer straight from graph state — the
                        # source of truth. Streamed "messages" tokens are for
                        # live UX only; if they're ever absent (model doesn't
                        # emit token deltas), this keeps the real answer intact
                        # instead of silently falling back to "No answer
                        # produced."
                        if (
                            node_name == "synthesize"
                            and isinstance(delta, dict)
                            and delta.get("answer")
                        ):
                            final_answer = delta["answer"]
                elif mode == "messages":
                    message_chunk, metadata = chunk
                    if metadata.get("langgraph_node") == "synthesize":
                        token = _chunk_text(message_chunk)
                        if token:
                            answer_parts.append(token)
                            await event_queue.enqueue_event(
                                _status_event(
                                    task_id,
                                    context_id,
                                    TaskState.working,
                                    token,
                                    False,
                                )
                            )

            answer = final_answer or "".join(answer_parts) or "No answer produced."

            await event_queue.enqueue_event(
                TaskArtifactUpdateEvent(
                    task_id=task_id,
                    context_id=context_id,
                    artifact=Artifact(
                        artifact_id=str(uuid.uuid4()),
                        parts=[Part(root=TextPart(text=answer))],
                    ),
                )
            )
            await event_queue.enqueue_event(
                _status_event(
                    task_id,
                    context_id,
                    TaskState.completed,
                    answer,
                    True,
                )
            )
        except Exception as exc:
            logger.error("executor error: %s", exc, exc_info=True)
            await event_queue.enqueue_event(
                _status_event(
                    task_id,
                    context_id,
                    TaskState.failed,
                    f"homelab-agent error: {exc}",
                    True,
                )
            )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError("homelab-agent does not support cancellation")
