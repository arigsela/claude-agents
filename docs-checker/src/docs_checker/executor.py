"""A2A executor: one A2A task = one graph run = one cost ledger.

The executor speaks A2A v1 protobuf types (a2a-sdk 1.x, ``lf.a2a.v1``).

In: the request is the message's data part ``{"scope", "ref", "mode", "memory"}``
when it has one, else its text (``request.parse_request``); text that is not a
``check ...`` request goes to the graph's intake model. A request that cannot be
read fails the task before any call. The run budget follows the scope
(``graph.budget_limit``), and ``memory`` is loaded into the run's store (honoured
in scheduled mode only). A HITL reply resumes the paused task instead.

Out, for a completed task, every part redacted on its way out:

- the report Markdown as a text part (and as the status message);
- data parts ``docs-checker/findings``, ``docs-checker/memory`` (the FULL updated
  snapshot, every run: the trigger always writes it back), and, when the run got
  as far as a report, ``docs-checker/slack`` and ``docs-checker/report``;
- each tool call as a data part tagged ``kagent.dev/a2a/part-type: function_call``
  followed by its ``function_response`` (the eval gate's ``expect_tools`` and
  ``forbid_tools`` read these), at most ``MAX_TOOL_EVENT_PARTS`` pairs in doc order
  (a doc keeps up to 50 events; a whole-repo run would otherwise publish thousands,
  M10), then ``docs-checker/tool-events`` with every doc's count and how many pairs
  were published;
- the run's ledger summary as data ``docs-checker/cost-run``, and token usage under
  the artifact metadata key ``kagent.dev/a2a/usage`` (the audit export reads
  ``totalTokenCount`` there).

A run the graph could not do (its ref, its scope) fails the task with the reason,
and so does a turn longer than ``run_timeout_s`` ("timeout"); the ledger summary
travels with the failure, partial cost included. Before that, at
``SOFT_DEADLINE_FRACTION`` of the timeout, the graph stops starting model calls
and docs (``RunDeps.soft_deadline``), so a long run completes with the docs it
checked, the rest ``skipped-budget`` with a time reason, instead of failing with
nothing (review I3). A paused run (an "ask") is
``input-required`` carrying a kagent HITL ``tool_approval_request``; its ledger and
replay memo wait in ``PausedTasks`` (the checkpoint db in production), so the
resume continues them, in this process or after a restart.
"""

from __future__ import annotations

import asyncio
import logging
import time
import traceback
import uuid
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.types import a2a_pb2
from google.protobuf import struct_pb2
from google.protobuf.json_format import MessageToDict, ParseDict
from google.protobuf.timestamp_pb2 import Timestamp
from langgraph.errors import GraphRecursionError
from langgraph.types import Command

from docs_checker.config import Settings
from docs_checker.gate import FixGate, ToolGate
from docs_checker.graph import RunDeps, budget_limit, run_config
from docs_checker.ledger import RATE_CARDS, CostLedger, RunSummary
from docs_checker.memory import SnapshotStore
from docs_checker.models import ModelSet
from docs_checker.paused import PausedTasks
from docs_checker.redact import redact, redact_obj
from docs_checker.report import Report, slack_text
from docs_checker.request import RunRequest, parse_request
from docs_checker.state import DocOutcome
from docs_checker.tools import ToolBelt, ToolEvent

logger = logging.getLogger(__name__)

PART_TYPE_KEY = "kagent.dev/a2a/part-type"
USAGE_KEY = "kagent.dev/a2a/usage"
LEDGER_KEY = "docs-checker/cost-run"
FINDINGS_KEY = "docs-checker/findings"
MEMORY_KEY = "docs-checker/memory"
SLACK_KEY = "docs-checker/slack"
REPORT_KEY = "docs-checker/report"
TOOL_EVENTS_KEY = "docs-checker/tool-events"
# Tool-event part pairs per completed artifact, in doc order (M10).
MAX_TOOL_EVENT_PARTS = 200

# The report's note when a resume lost the paused run's ledger (C#25).
RESTART_NOTE = "cost after restart is a lower bound"
# The graph's soft deadline, as a fraction of run_timeout_s: what is left must hold the
# branches in flight (a few model calls each) plus collect and report.
SOFT_DEADLINE_FRACTION = 0.75

# Tools grouped by the MCP server that advertised them (server name -> tools).
ToolsProvider = Callable[[], Awaitable[Mapping[str, list[Any]]]]


class UnreadableRequest(Exception):
    """The request is not one docs-checker can run (``parse_request`` refused it)."""


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


def _whole_numbers(value: Any) -> Any:
    """protobuf's ``Value`` carries every number as a double: a whole one is an int
    again, as the JSON the caller sent had it (the memory's counters must be ints)."""
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, dict):
        return {k: _whole_numbers(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_whole_numbers(v) for v in value]
    return value


def request_data(message: a2a_pb2.Message | None) -> Any:
    """The first data part's value, or None when the message has no data part."""
    if message is None:
        return None
    for part in message.parts:
        if part.HasField("data"):
            return _whole_numbers(MessageToDict(part.data))
    return None


def _tool_parts(event: ToolEvent) -> list[a2a_pb2.Part]:
    return [
        _data_part({"name": event["name"], "args": redact_obj(event["args"])}, "function_call"),
        _data_part(
            {
                "name": event["name"],
                "response": {"decision": event["decision"], "result_chars": event["result_chars"]},
            },
            "function_response",
        ),
    ]


def completed_parts(
    report: str,
    *,
    report_data: Report | None,
    outcomes: Mapping[str, DocOutcome],
    memory: dict,
    summary: RunSummary,
) -> list[a2a_pb2.Part]:
    """The completed task's parts. Everything that came from a repo file or a model
    is redacted here again, as the last step before it leaves the agent."""
    findings = []
    if report_data is not None:
        found = report_data.findings + report_data.needs_look + report_data.carried
        findings = [f.model_dump(mode="json") for f in found]
    parts = [
        a2a_pb2.Part(text=redact(report)),
        _data_part({FINDINGS_KEY: redact_obj(findings)}),
        _data_part({MEMORY_KEY: redact_obj(memory)}),
    ]
    if report_data is not None:
        parts.append(_data_part({SLACK_KEY: redact(slack_text(report_data))}))
        parts.append(_data_part({REPORT_KEY: redact_obj(report_data.model_dump(mode="json"))}))
    per_doc = {doc: len(outcomes[doc].tool_events) for doc in sorted(outcomes)}
    published = 0
    for doc in sorted(outcomes):
        for event in outcomes[doc].tool_events[: MAX_TOOL_EVENT_PARTS - published]:
            parts.extend(_tool_parts(event))
            published += 1
    counts = {"total": sum(per_doc.values()), "published": published, "per_doc": per_doc}
    parts.append(_data_part({TOOL_EVENTS_KEY: counts}))
    parts.append(_data_part({LEDGER_KEY: summary.to_dict()}))
    return parts


def memory_snapshot(store: SnapshotStore | None, result: Mapping[str, Any]) -> dict:
    """The full updated snapshot (C#21). Docs leave it only when a whole-repo run saw
    every doc in scope; any other run keeps the entries of docs it did not look at."""
    if store is None:
        store = SnapshotStore.from_snapshot(None, mode="interactive")
    in_scope = set(result.get("outcomes") or {})
    request = result.get("request")
    if not isinstance(request, RunRequest) or request.scope != "all" or result.get("truncated"):
        in_scope |= store.doc_paths()
    return store.snapshot(in_scope)


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


def _failure(report: str | None) -> str:
    """The reason a failed run gives, without the report's own prefix."""
    text = (report or "").strip().removeprefix("docs-checker failed:").strip()
    return text or "the run failed"


class DocsCheckerExecutor(AgentExecutor):
    """Runs the injected graph, which takes ``{"text"}`` or ``{"text", "request"}``
    with a ``RunDeps`` runtime context, and returns ``report`` (Markdown),
    ``report_data`` (``Report``), ``outcomes`` (doc -> ``DocOutcome``, with their tool
    events), ``request`` and ``outcome``, or pauses with ``interrupt()``.

    ``gate`` checks every tool call (through the tool belt); ``fix_gate`` every
    proposed fix (the graph reaches it as ``RunDeps.fix_gate``). ``paused`` keeps a
    paused task's ledger and replay memo until its resume."""

    def __init__(
        self,
        *,
        graph: Any,
        settings: Settings,
        models: ModelSet,
        tools: ToolsProvider,
        gate: ToolGate,
        fix_gate: FixGate,
        paused: PausedTasks | None = None,
    ):
        self._graph = graph
        self._settings = settings
        self._models = models
        self._tools = tools
        self._gate = gate
        self._fix_gate = fix_gate
        self._paused = paused if paused is not None else PausedTasks()
        # Each server's binding stays its own: a tool name bound on one server
        # must not authorize a same-named tool on another (no union).
        self._bindings: dict[str, tuple[str, ...]] = {}
        for server in settings.mcp_servers:
            self._bindings[server.name] = tuple(
                sorted(set(self._bindings.get(server.name, ())) | set(server.tools))
            )
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

    async def _deps(
        self,
        ledger: CostLedger,
        replay: dict[str, Any],
        store: SnapshotStore | None = None,
        *,
        soft_deadline: float | None = None,
    ) -> RunDeps:
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
            store=store,
            soft_deadline=soft_deadline,
        )

    def _request(self, context: RequestContext, ledger: CostLedger) -> tuple[dict, SnapshotStore]:
        """A new request: the graph's input, with the run's budget and memory set."""
        settings = self._settings
        text = context.get_user_input()
        try:
            request = parse_request(
                text, request_data(context.message), max_paths=settings.max_docs
            )
        except ValueError as error:
            raise UnreadableRequest(str(error)) from error
        if request is None:
            # Free text: the intake call runs on one doc's budget, and intake sets the
            # budget of the scope it reads (interactive, so no memory).
            ledger.budget.limit_usd = settings.run_budget_doc_usd
            return {"text": text}, SnapshotStore.from_snapshot(None, mode="interactive")
        ledger.budget.limit_usd = budget_limit(request, settings)
        store = SnapshotStore.from_snapshot(request.memory, mode=request.mode)
        return {"text": text, "request": request}, store

    async def _graph_input(
        self, context: RequestContext, config: dict, ledger: CostLedger, *, held: bool
    ) -> tuple[Any, SnapshotStore | None]:
        kagent_a2a = _hitl()
        payload = kagent_a2a.get_hitl_payload(context.message) if kagent_a2a else None
        if payload is None:
            return self._request(context, ledger)
        # Parallel branches can each be paused. Every pending pause gets only the
        # decisions for its own calls, keyed by its interrupt id; a pause with no
        # matching decision gets none, which the tool belt treats as a rejection.
        state = await self._graph.aget_state(config)
        pending = list(getattr(state, "interrupts", ()) or ())
        if not pending:
            return Command(resume=payload), None
        if not held:
            self._restarted(context.task_id, ledger, getattr(state, "values", None) or {})
        return Command(resume=resume_map(payload, pending)), None

    def _restarted(self, task_id: str, ledger: CostLedger, values: Mapping[str, Any]) -> None:
        """A paused task resumes without its ledger and memo (a restart that lost
        them): the cost counts from here on, and the run keeps the budget its request
        set, so the pause's approval still matches."""
        logger.warning("task %s resumes without its paused ledger: %s", task_id, RESTART_NOTE)
        ledger.lower_bound.append(RESTART_NOTE)
        request = values.get("request")
        if isinstance(request, RunRequest):
            ledger.budget.limit_usd = budget_limit(request, self._settings)

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
            # cancel() stopped the operation and already published CANCELED. Only now,
            # with the graph stopped, can nothing write to the task's thread again.
            await self._end(task_id)
        finally:
            self._running.pop(task_id, None)
            self._cancelled.discard(task_id)

    async def _execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        task_id, context_id = context.task_id, context.context_id
        # A new task starts here only off kagent (DefaultRequestHandlerV2). Under kagent,
        # kagent-core's settling executor has already enqueued and persisted the initial
        # Task before calling this one (current_task is still None), and a second one
        # would be logged at ERROR and dropped by a2a.
        if context.current_task is None and not self._settings.under_kagent:
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
        held = await self._paused.take(task_id, lambda: self._new_ledger(task_id, context_id))
        ledger, replay = held if held is not None else (self._new_ledger(task_id, context_id), {})
        try:
            await self._run(context, event_queue, ledger, replay, held=held is not None)
        except asyncio.CancelledError:
            if self._was_cancelled(task_id):
                logger.info("task %s cancelled; %d model calls ran", task_id, len(ledger.entries))
            raise

    def _was_cancelled(self, task_id: str) -> bool:
        return task_id in self._cancelled

    async def _run(
        self, context: RequestContext, event_queue: EventQueue, ledger, replay, *, held: bool
    ) -> None:
        task_id, context_id = context.task_id, context.context_id
        timeout = self._settings.run_timeout_s
        deadline = asyncio.timeout(timeout)
        soft_deadline = time.monotonic() + SOFT_DEADLINE_FRACTION * timeout
        deps: RunDeps | None = None
        try:
            async with deadline:
                config = run_config(task_id, self._settings, self._settings.levers)
                graph_input, store = await self._graph_input(context, config, ledger, held=held)
                deps = await self._deps(ledger, replay, store, soft_deadline=soft_deadline)
                if self._was_cancelled(task_id):
                    return
                result = await self._graph.ainvoke(graph_input, config, context=deps)
        except UnreadableRequest as error:
            await self._fail(
                event_queue,
                task_id,
                context_id,
                ledger,
                f"the request could not be read: {error}",
            )
            return
        except GraphRecursionError as error:
            await self._fail(
                event_queue, task_id, context_id, ledger, f"recursion limit hit: {error}"
            )
            return
        except Exception as error:  # noqa: BLE001 - logged below; the ledger keeps its cost
            if isinstance(error, TimeoutError) and deadline.expired():
                logger.warning("task %s timed out after %g s", task_id, timeout)
                await self._fail(event_queue, task_id, context_id, ledger, "timeout")
                return
            # Upstream errors can echo request or response content, so the
            # traceback is redacted like everything else that leaves the agent.
            trace = "".join(traceback.format_exception(error))
            logger.error("run failed: %s", redact(trace))
            await self._fail(event_queue, task_id, context_id, ledger, f"{type(error).__name__}")
            return

        if self._was_cancelled(task_id):
            return  # cancel() arrived after the run finished: publish nothing more
        if result.get("__interrupt__"):
            await self._paused.put(task_id, ledger, replay)
            await self._pause(event_queue, context, ledger, result["__interrupt__"])
            return
        if result.get("outcome") == "failed":
            await self._fail(
                event_queue, task_id, context_id, ledger, _failure(result.get("report"))
            )
            return

        summary = ledger.summary(result.get("outcome") or "unverified")
        logger.info("%s", summary.to_dict())
        report = redact(result.get("report") or "No report produced.")
        parts = completed_parts(
            report,
            report_data=result.get("report_data"),
            outcomes=result.get("outcomes") or {},
            memory=memory_snapshot(deps.store, result),
            summary=summary,
        )
        artifact = a2a_pb2.Artifact(artifact_id=str(uuid.uuid4()), name="report", parts=parts)
        artifact.metadata.CopyFrom(_struct({USAGE_KEY: usage_metadata(summary)}))
        await self._forget_thread(task_id)
        await event_queue.enqueue_event(
            a2a_pb2.TaskArtifactUpdateEvent(
                task_id=task_id, context_id=context_id, artifact=artifact, last_chunk=True
            )
        )
        await event_queue.enqueue_event(
            _status(task_id, context_id, a2a_pb2.TaskState.TASK_STATE_COMPLETED, report)
        )

    async def _forget_thread(self, task_id: str) -> None:
        """A task that ended (completed, failed, timed out or cancelled) is never
        resumed: delete its checkpoint thread (every namespace, subgraphs included), so
        the db under the snapshotted /data does not grow with every run. Paused tasks
        keep theirs. Done before the final status, while the task is still ours."""
        delete = getattr(getattr(self._graph, "checkpointer", None), "adelete_thread", None)
        if delete is None:
            return
        try:
            await delete(task_id)
        except Exception as error:  # noqa: BLE001 - the task's outcome stands without it
            logger.warning(
                "task %s: its checkpoint thread was not deleted (%s)", task_id, type(error).__name__
            )

    async def _end(self, task_id: str) -> None:
        """A cancelled task's leftovers: its paused record and its checkpoint thread."""
        await self._paused.drop(task_id)
        await self._forget_thread(task_id)

    async def _fail(self, event_queue, task_id, context_id, ledger, reason: str) -> None:
        summary = ledger.summary("failed")
        logger.info("%s", summary.to_dict())
        await self._forget_thread(task_id)
        await event_queue.enqueue_event(
            _status(
                task_id,
                context_id,
                a2a_pb2.TaskState.TASK_STATE_FAILED,
                f"docs-checker failed: {redact(reason)}",
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
        # This runs only while this process holds the task (a2a's local cancel path).
        # After a restart a2a cancels a paused task through its remote path
        # (_cancel_remote: the TaskStore records CANCELED; executor.cancel is not
        # called), so that task's paused row is reclaimed by the 64-entry eviction
        # (paused.MAX_PAUSED), and its checkpoint thread is left in the db.
        operation = self._running.get(task_id)
        if operation is not None and not operation.done():
            self._cancelled.add(task_id)
            operation.cancel()  # execute() cleans up once the operation has stopped
        else:
            await self._end(task_id)  # paused or idle: nothing runs that could write
        await event_queue.enqueue_event(
            _status(context.task_id, context.context_id, a2a_pb2.TaskState.TASK_STATE_CANCELED)
        )
