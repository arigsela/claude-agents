"""Executor pieces that need no gRPC: the ledger's rate card and what gets published."""

import dataclasses

from google.protobuf.json_format import MessageToDict

from docs_checker import ledger as ledger_module
from docs_checker.executor import answer_parts
from docs_checker.gate import RecordingGate
from docs_checker.ledger import CostLedger
from docs_checker.server import build_executor
from tests.fake_graph import build_test_graph
from tests.fakes import FakeModels, fake_settings, fake_tools_by_server


async def _tools():
    return fake_tools_by_server()


def test_the_ledger_prices_with_the_configured_rate_card(monkeypatch):
    base = ledger_module.RATE_CARDS["anthropic-2026-10-18"]
    custom = dataclasses.replace(base, version="test-card")
    monkeypatch.setitem(ledger_module.RATE_CARDS, "test-card", custom)
    settings = fake_settings({"DOCS_CHECKER_RATE_CARD": "test-card"})
    executor = build_executor(
        settings, graph=build_test_graph(), models=FakeModels(), tools=_tools, gate=RecordingGate()
    )

    ledger = executor._new_ledger("task-1", "ctx-1")
    assert ledger.rate_card.version == "test-card"


async def test_a_resumed_runs_belt_continues_the_runs_search_count():
    settings = dataclasses.replace(fake_settings(), max_searches=1, search_interval_s=0.0)
    executor = build_executor(
        settings, graph=build_test_graph(), models=FakeModels(), tools=_tools, gate=RecordingGate()
    )
    ledger = executor._new_ledger("task-1", "ctx-1")
    replay: dict = {}  # the task's memo, kept across a pause

    first = (await executor._deps(ledger, replay)).belt
    used, _ = await first.call("search_code", {"query": "a"}, node="locate", intent="i")
    resumed = (await executor._deps(ledger, replay)).belt
    over, _ = await resumed.call("search_code", {"query": "b"}, node="locate", intent="i")

    assert used.status == "ok" and over.status == "denied"


def test_published_parts_are_redacted():
    summary = CostLedger("r", "c", emit=False).summary("verified")
    events = [
        {
            "name": "search_code",
            "args": {"query": "password: hunter2hunter2"},
            "decision": "allow",
            "result_chars": 10,
        }
    ]
    parts = answer_parts("The key is AKIAABCDEFGHIJKLMNOP.", events, summary)
    published = [MessageToDict(p) for p in parts]
    blob = str(published)
    assert "AKIAABCDEFGHIJKLMNOP" not in blob and "hunter2hunter2" not in blob
    assert "[REDACTED]" in published[0]["text"]


class _Interrupt:
    def __init__(self, id_: str, call_ids: list[str]):
        self.id = id_
        self.value = {"action_requests": [{"id": c, "name": "t", "args": {}} for c in call_ids]}


def test_one_approval_response_is_split_per_pending_interrupt():
    from docs_checker.executor import resume_map

    payload = {
        "type": "tool_approval_response",
        "approvals": [
            {"id": "call-a", "approved": True},
            {"id": "call-b", "approved": False},
        ],
    }
    resume = resume_map(payload, [_Interrupt("i1", ["call-a"]), _Interrupt("i2", ["call-b"])])
    assert resume == {
        "i1": {"type": "tool_approval_response", "approvals": [{"id": "call-a", "approved": True}]},
        "i2": {
            "type": "tool_approval_response",
            "approvals": [{"id": "call-b", "approved": False}],
        },
    }


def test_an_interrupt_without_a_matching_decision_gets_none():
    from docs_checker.executor import resume_map

    payload = {"type": "tool_approval_response", "approvals": [{"id": "call-a", "approved": True}]}
    resume = resume_map(payload, [_Interrupt("i1", ["call-a"]), _Interrupt("i2", ["call-z"])])
    assert resume["i2"]["approvals"] == []


class _Queue:
    def __init__(self):
        self.events: list = []

    async def enqueue_event(self, event):
        self.events.append(event)


def _context(task_id: str = "task-c", text: str = "Which chart version does vault run?"):
    from types import SimpleNamespace

    return SimpleNamespace(
        task_id=task_id,
        context_id="ctx-c",
        current_task=None,
        message=None,
        call_context=None,
        get_user_input=lambda: text,
    )


def _states(queue: _Queue) -> list[int]:
    out = []
    for event in queue.events:
        status = getattr(event, "status", None)
        if status is not None:
            out.append(status.state)
    return out


async def test_cancel_during_an_awaited_model_call_stops_the_run_and_publishes_nothing_after():
    import asyncio

    from a2a.types import a2a_pb2

    from tests.fakes import reply

    started, release = asyncio.Event(), asyncio.Event()
    calls: list = []

    class BlockingModel:
        def bind_tools(self, tools, **_):
            return self

        async def ainvoke(self, messages, *_, **__):
            calls.append(messages)
            started.set()
            await release.wait()  # never released: only cancellation ends it
            return reply("done")

    tool_log: list = []

    async def tools():
        return fake_tools_by_server(tool_log)

    models = FakeModels(worker=BlockingModel())
    executor = build_executor(
        fake_settings(), graph=build_test_graph(), models=models, tools=tools, gate=RecordingGate()
    )
    context, queue = _context(), _Queue()

    run = asyncio.create_task(executor.execute(context, queue))
    await asyncio.wait_for(started.wait(), 2)
    await executor.cancel(context, queue)
    # execute returns by itself instead of hanging (asyncio.wait never cancels it)
    done, _ = await asyncio.wait({run}, timeout=2)
    assert run in done
    run.result()

    states = _states(queue)
    assert states[-1] == a2a_pb2.TaskState.TASK_STATE_CANCELED
    assert a2a_pb2.TaskState.TASK_STATE_COMPLETED not in states
    assert a2a_pb2.TaskState.TASK_STATE_FAILED not in states
    assert len(calls) == 1 and tool_log == []  # no model or tool call after the cancel
    assert executor._running == {} and executor._cancelled == set()


async def test_cancel_of_an_idle_task_still_reports_canceled():
    from a2a.types import a2a_pb2

    executor = build_executor(
        fake_settings(),
        graph=build_test_graph(),
        models=FakeModels(),
        tools=_tools,
        gate=RecordingGate(),
    )
    queue = _Queue()
    await executor.cancel(_context("idle"), queue)
    assert _states(queue) == [a2a_pb2.TaskState.TASK_STATE_CANCELED]
    assert executor._cancelled == set()


async def test_the_recursion_limit_fails_the_task_instead_of_running_on():
    from a2a.types import a2a_pb2

    from tests.fakes import ScriptedModel, reply

    # The test graph needs a limit of 3 (its input, worker and finish steps); allow 2.
    settings = fake_settings({"DOCS_CHECKER_RECURSION_LIMIT": "2"})
    models = FakeModels(worker=ScriptedModel([reply("done")]))
    executor = build_executor(
        settings, graph=build_test_graph(), models=models, tools=_tools, gate=RecordingGate()
    )
    queue = _Queue()
    await executor.execute(_context("loop"), queue)

    assert _states(queue)[-1] == a2a_pb2.TaskState.TASK_STATE_FAILED
    assert "recursion limit hit" in queue.events[-1].status.message.parts[0].text


async def test_cancel_during_tool_discovery_stops_the_task_and_publishes_nothing_after():
    import asyncio

    from a2a.types import a2a_pb2

    discovering = asyncio.Event()

    async def tools():
        discovering.set()
        await asyncio.Event().wait()  # discovery never finishes: only cancellation ends it

    executor = build_executor(
        fake_settings(), graph=build_test_graph(), models=FakeModels(), tools=tools
    )
    context, queue = _context("discovery"), _Queue()

    run = asyncio.create_task(executor.execute(context, queue))
    await asyncio.wait_for(discovering.wait(), 2)
    await executor.cancel(context, queue)
    done, _ = await asyncio.wait({run}, timeout=2)
    assert run in done  # execute returned by itself, not by a timeout's cancel
    run.result()

    states = _states(queue)
    assert states[-1] == a2a_pb2.TaskState.TASK_STATE_CANCELED
    assert a2a_pb2.TaskState.TASK_STATE_COMPLETED not in states
    assert a2a_pb2.TaskState.TASK_STATE_FAILED not in states
    assert executor._running == {} and executor._cancelled == set()
