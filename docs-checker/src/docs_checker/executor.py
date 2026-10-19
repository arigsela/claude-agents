"""A2A executor: one A2A task = one graph run = one cost ledger.

The executor speaks A2A v1 protobuf types (a2a-sdk 1.x, ``lf.a2a.v1``). It
emits what kagent's tooling reads from a task:

- the answer as a text part, and the run's ledger summary as a data part;
- each tool call as a data part tagged ``kagent.dev/a2a/part-type:
  function_call`` (the eval gate's ``expect_tools``/``forbid_tools`` read these);
- token usage under the artifact metadata key ``kagent.dev/a2a/usage`` (the
  audit export reads ``totalTokenCount`` there);
- a paused run (the drift gate answered "ask") as ``input-required`` carrying a
  kagent HITL ``tool_approval_request``; the reply resumes the same task.
"""

from __future__ import annotations

import asyncio
import logging
import traceback
import uuid
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.types import a2a_pb2
from google.protobuf import struct_pb2
from google.protobuf.json_format import ParseDict
from google.protobuf.timestamp_pb2 import Timestamp
from langgraph.errors import GraphRecursionError
from langgraph.types import Command

from docs_checker.config import Settings
from docs_checker.gate import FixGate, ToolGate
from docs_checker.graph import RunDeps, run_config
from docs_checker.ledger import RATE_CARDS, CostLedger, RunSummary
from docs_checker.models import ModelSet
from docs_checker.redact import redact, redact_obj
from docs_checker.tools import ToolBelt

logger = logging.getLogger(__name__)

PART_TYPE_KEY = "kagent.dev/a2a/part-type"
USAGE_KEY = "kagent.dev/a2a/usage"
LEDGER_KEY = "docs-checker/cost-run"

# Tools grouped by the MCP server that advertised them (server name -> tools).
ToolsProvider = Callable[[], Awaitable[Mapping[str, list[Any]]]]

# Ledgers of paused tasks, kept so a resumed task reports its whole cost. Like
# the in-memory checkpointer, this relies on Substrate snapshotting the actor's
# process memory between turns. Bounded so abandoned pauses cannot pile up.
MAX_PAUSED_LEDGERS = 64


def _now() -> Timestamp:
    ts = Timestamp()
    ts.GetCurrentTime()
    return ts


def _struct(data: dict) -> struct_pb2.Struct:
    return ParseDict(data, struct_pb2.Struct())


def _data_part(data: dict, part_type: str | None = None) -> a2a_pb2.Part:
    part = a2a_pb2.Part(data=ParseDict(data, struct_pb2.Value()))
    if part_type:
        part.metadata.CopyFrom(_struct({PART_TYPE_KEY: part_type}))
    return part


def _agent_message(text: str, task_id: str, context_id: str) -> a2a_pb2.Message:
    return a2a_pb2.Message(
        message_id=str(uuid.uuid4()),
        role=a2a_pb2.Role.ROLE_AGENT,
        task_id=task_id,
        context_id=context_id,
        parts=[a2a_pb2.Part(text=text)],
    )


def _status(task_id, context_id, state, text: str | None = None, metadata=None):
    status = a2a_pb2.TaskStatus(state=state, timestamp=_now())
    if text is not None:
        status.message.CopyFrom(_agent_message(text, task_id, context_id))
    event = a2a_pb2.TaskStatusUpdateEvent(task_id=task_id, context_id=context_id, status=status)
    if metadata:
        event.metadata.CopyFrom(_struct(metadata))
    return event


def usage_metadata(summary: RunSummary) -> dict:
    """ADK-style usage counters, the shape kagent's audit export already reads."""
    prompt = summary.uncached_input + summary.cache_write + summary.cache_read
    return {
        "promptTokenCount": prompt,
        "candidatesTokenCount": summary.output,
        "cachedContentTokenCount": summary.cache_read,
        "totalTokenCount": prompt + summary.output,
    }


def answer_parts(answer: str, events: list, summary: RunSummary) -> list[a2a_pb2.Part]:
    """The completed task's parts. Everything model-written is redacted here too,
    as the last step before it leaves the agent."""
    parts = [a2a_pb2.Part(text=redact(answer))]
    for event in events:
        parts.append(
            _data_part({"name": event["name"], "args": redact_obj(event["args"])}, "function_call")
        )
        parts.append(
            _data_part(
                {
                    "name": event["name"],
                    "response": {
                        "decision": event["decision"],
                        "result_chars": event["result_chars"],
                    },
                },
                "function_response",
            )
        )
    parts.append(_data_part({LEDGER_KEY: summary.to_dict()}))
    return parts


def resume_map(payload: dict, interrupts) -> dict:
    """Split one tool_approval_response into a resume value per pending interrupt."""
    approvals = payload.get("approvals")
    approvals = [a for a in approvals if isinstance(a, dict)] if isinstance(approvals, list) else []
    resume = {}
    for interrupt in interrupts:
        value = getattr(interrupt, "value", None)
        requests = value.get("action_requests") or [] if isinstance(value, dict) else []
        ids = {r.get("id") for r in requests if isinstance(r, dict)}
        resume[interrupt.id] = {
            "type": payload.get("type"),
            "approvals": [a for a in approvals if a.get("id") in ids],
        }
    return resume


def _hitl():
    """kagent-core's HITL helpers when installed (in the image), else None."""
    try:
        from kagent.core import a2a as kagent_a2a
    except ImportError:
        return None
    return kagent_a2a


def _headers(context: RequestContext) -> dict:
    state = getattr(context.call_context, "state", None)
    headers = state.get("headers") if isinstance(state, dict) else None
    return headers if isinstance(headers, dict) else {}


class DocsCheckerExecutor(AgentExecutor):
    """Runs the injected graph, which takes ``{"question": <user text>}`` with a
    ``RunDeps`` runtime context, and returns ``answer``, ``events`` (ToolEvents) and
    ``outcome``, or pauses with ``interrupt()``.

    ``gate`` checks every tool call (through the tool belt); ``fix_gate`` every
    proposed fix (the graph reaches it as ``RunDeps.fix_gate``)."""

    def __init__(
        self,
        *,
        graph: Any,
        settings: Settings,
        models: ModelSet,
        tools: ToolsProvider,
        gate: ToolGate,
        fix_gate: FixGate,
    ):
        self._graph = graph
        self._settings = settings
        self._models = models
        self._tools = tools
        self._gate = gate
        self._fix_gate = fix_gate
        # Each server's binding stays its own: a tool name bound on one server
        # must not authorize a same-named tool on another (no union).
        self._bindings: dict[str, tuple[str, ...]] = {}
        for server in settings.mcp_servers:
            self._bindings[server.name] = tuple(
                sorted(set(self._bindings.get(server.name, ())) | set(server.tools))
            )
        self._paused_ledgers: OrderedDict[str, CostLedger] = OrderedDict()
        # Per paused task: the memo its resume replays (see RunDeps.replay).
        self._paused_replays: OrderedDict[str, dict[str, Any]] = OrderedDict()
        # Cancellation: each executing task's whole operation (tool discovery, the
        # resume lookup and the graph run), and the tasks a cancel() reached while
        # they were executing (they must publish nothing).
        self._running: dict[str, asyncio.Future] = {}
        self._cancelled: set[str] = set()

    def _new_ledger(self, task_id: str, context_id: str) -> CostLedger:
        return CostLedger(
            task_id,
            context_id,
            rate_card=RATE_CARDS[self._settings.rate_card_version],
            default_ttl=self._settings.cache_ttl,
        )

    async def _deps(self, ledger: CostLedger, replay: dict[str, Any]) -> RunDeps:
        # The replay memo is the run's state across pauses: the belt keeps the
        # run's search count and pacing in it, so a resume does not reset them.
        belt = ToolBelt(
            await self._tools(),
            self._gate,
            bindings=self._bindings,
            settings=self._settings,
            run_state=replay,
        )
        return RunDeps(
            models=self._models,
            belt=belt,
            ledger=ledger,
            settings=self._settings,
            replay=replay,
            fix_gate=self._fix_gate,
        )

    async def _graph_input(self, context: RequestContext, config: dict) -> Any:
        kagent_a2a = _hitl()
        payload = kagent_a2a.get_hitl_payload(context.message) if kagent_a2a else None
        if payload is None:
            return {"question": context.get_user_input()}
        # Parallel branches can each be paused. Every pending pause gets only the
        # decisions for its own calls, keyed by its interrupt id; a pause with no
        # matching decision gets none, which the tool belt treats as a rejection.
        state = await self._graph.aget_state(config)
        pending = list(getattr(state, "interrupts", ()) or ())
        if not pending:
            return Command(resume=payload)
        return Command(resume=resume_map(payload, pending))

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        task_id = context.task_id
        # Registered before the first await, so cancel() stops every step of the
        # task, not only the graph run.
        operation = asyncio.ensure_future(self._execute(context, event_queue))
        self._running[task_id] = operation
        try:
            await operation
        except asyncio.CancelledError:
            if not self._was_cancelled(task_id):
                raise
            # cancel() stopped the operation and already published CANCELED.
        finally:
            self._running.pop(task_id, None)
            self._cancelled.discard(task_id)

    async def _execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        task_id, context_id = context.task_id, context.context_id
        if context.current_task is None:
            await event_queue.enqueue_event(
                a2a_pb2.Task(
                    id=task_id,
                    context_id=context_id,
                    status=a2a_pb2.TaskStatus(
                        state=a2a_pb2.TaskState.TASK_STATE_SUBMITTED, timestamp=_now()
                    ),
                    history=[context.message] if context.message else [],
                )
            )
        await event_queue.enqueue_event(
            _status(task_id, context_id, a2a_pb2.TaskState.TASK_STATE_WORKING)
        )

        # A resume continues the paused task's ledger, so the completed task's
        # summary covers every call, including those made before the pause.
        ledger = self._paused_ledgers.pop(task_id, None) or self._new_ledger(task_id, context_id)
        replay = self._paused_replays.pop(task_id, None) or {}
        try:
            await self._run(context, event_queue, ledger, replay)
        except asyncio.CancelledError:
            if self._was_cancelled(task_id):
                logger.info("task %s cancelled; %d model calls ran", task_id, len(ledger.entries))
            raise

    def _was_cancelled(self, task_id: str) -> bool:
        return task_id in self._cancelled

    async def _run(self, context: RequestContext, event_queue: EventQueue, ledger, replay) -> None:
        task_id, context_id = context.task_id, context.context_id
        try:
            deps = await self._deps(ledger, replay)
            config = run_config(task_id, self._settings, self._settings.levers)
            graph_input = await self._graph_input(context, config)
            if self._was_cancelled(task_id):
                return
            result = await self._graph.ainvoke(graph_input, config, context=deps)
        except GraphRecursionError as error:
            await self._fail(
                event_queue, task_id, context_id, ledger, f"recursion limit hit: {error}"
            )
            return
        except Exception as error:  # noqa: BLE001 - logged below; the ledger keeps its cost
            # Upstream errors can echo request or response content, so the
            # traceback is redacted like everything else that leaves the agent.
            trace = "".join(traceback.format_exception(error))
            logger.error("run failed: %s", redact(trace))
            await self._fail(event_queue, task_id, context_id, ledger, f"{type(error).__name__}")
            return

        if self._was_cancelled(task_id):
            return  # cancel() arrived after the run finished: publish nothing more
        if result.get("__interrupt__"):
            self._paused_ledgers[task_id] = ledger
            self._paused_replays[task_id] = replay
            while len(self._paused_ledgers) > MAX_PAUSED_LEDGERS:
                self._paused_ledgers.popitem(last=False)
            while len(self._paused_replays) > MAX_PAUSED_LEDGERS:
                self._paused_replays.popitem(last=False)
            await self._pause(event_queue, context, ledger, result["__interrupt__"])
            return

        summary = ledger.summary(result.get("outcome", "unverified"))
        logger.info("%s", summary.to_dict())
        answer = redact(result.get("answer") or "No answer produced.")
        parts = answer_parts(answer, result.get("events") or [], summary)
        artifact = a2a_pb2.Artifact(artifact_id=str(uuid.uuid4()), name="answer", parts=parts)
        artifact.metadata.CopyFrom(_struct({USAGE_KEY: usage_metadata(summary)}))
        await event_queue.enqueue_event(
            a2a_pb2.TaskArtifactUpdateEvent(
                task_id=task_id, context_id=context_id, artifact=artifact, last_chunk=True
            )
        )
        await event_queue.enqueue_event(
            _status(task_id, context_id, a2a_pb2.TaskState.TASK_STATE_COMPLETED, answer)
        )

    async def _fail(self, event_queue, task_id, context_id, ledger, reason: str) -> None:
        summary = ledger.summary("failed")
        logger.info("%s", summary.to_dict())
        await event_queue.enqueue_event(
            _status(
                task_id,
                context_id,
                a2a_pb2.TaskState.TASK_STATE_FAILED,
                f"docs-checker failed: {reason}",
                metadata={LEDGER_KEY: summary.to_dict()},
            )
        )

    async def _pause(self, event_queue, context, ledger, interrupts) -> None:
        """Turn every pending interrupt into one input-required with a HITL approval
        request listing all of their calls (parallel branches can pause together)."""
        requests, hints = [], []
        for interrupt in interrupts:
            value = getattr(interrupt, "value", interrupt)
            if not isinstance(value, dict):
                continue
            for request in value.get("action_requests") or []:
                requests.append({**request, "args": redact_obj(request.get("args") or {})})
            if value.get("hint"):
                hints.append(redact(value["hint"]))
        hint = "; ".join(hints)
        text = f"Approval is required: {hint}" if hint else "Human input is required."
        message = _agent_message(text, context.task_id, context.context_id)
        kagent_a2a = _hitl()
        if kagent_a2a and requests and kagent_a2a.hitl_activated(_headers(context)):
            tools = [
                kagent_a2a.HitlTool(
                    id=r["id"], call_id=r.get("call_id", r["id"]), name=r["name"], args=r["args"]
                )
                for r in requests
            ]
            kagent_a2a.attach_hitl_extension(
                message, kagent_a2a.ToolApprovalRequest(hint=hint or None, tools=tools)
            )
        summary = ledger.summary("unverified")
        status = a2a_pb2.TaskStatus(
            state=a2a_pb2.TaskState.TASK_STATE_INPUT_REQUIRED, message=message, timestamp=_now()
        )
        event = a2a_pb2.TaskStatusUpdateEvent(
            task_id=context.task_id, context_id=context.context_id, status=status
        )
        event.metadata.CopyFrom(_struct({LEDGER_KEY: summary.to_dict()}))
        await event_queue.enqueue_event(event)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        """Stop the task's whole operation (tool discovery, model and tool calls
        included), then report CANCELED; execute() publishes nothing after this."""
        task_id = context.task_id
        self._paused_ledgers.pop(task_id, None)
        self._paused_replays.pop(task_id, None)
        operation = self._running.get(task_id)
        if operation is not None:
            self._cancelled.add(task_id)
            if not operation.done():
                operation.cancel()
        await event_queue.enqueue_event(
            _status(context.task_id, context.context_id, a2a_pb2.TaskState.TASK_STATE_CANCELED)
        )
