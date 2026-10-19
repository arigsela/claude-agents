"""The executor: what an A2A task carries in and out, and the plumbing around a run.

The A2A input and output tests drive the real audit graph over a temp git repository
served by the local fake of the agent-docs server, with scripted models (no network,
no key). The pure-plumbing tests (cancel, recursion limit, the belt across a pause)
keep the small test graph in ``tests/fake_graph.py``.
"""

import asyncio
import dataclasses
import json
import time
import uuid
from types import SimpleNamespace

import pytest
from a2a.helpers.proto_helpers import get_message_text
from a2a.types import a2a_pb2
from google.protobuf import struct_pb2
from google.protobuf.json_format import MessageToDict, ParseDict
from langgraph.checkpoint.memory import InMemorySaver

from docs_checker import ledger as ledger_module
from docs_checker.evals.localrepo import local_repo_tools
from docs_checker.executor import (
    FINDINGS_KEY,
    LEDGER_KEY,
    MEMORY_KEY,
    PART_TYPE_KEY,
    REPORT_KEY,
    SLACK_KEY,
    USAGE_KEY,
    completed_parts,
)
from docs_checker.gate import RecordingGate
from docs_checker.graph import budget_limit, build_graph, checkpoint_serde
from docs_checker.ledger import CostLedger
from docs_checker.report import Report
from docs_checker.request import RunRequest
from docs_checker.server import build_executor
from docs_checker.state import Claim, DocOutcome, Finding
from tests.fake_graph import build_test_graph
from tests.fakes import FakeModels, fake_settings, fake_tools_by_server
from tests.test_graph import (
    CLAIMS,
    FILES,
    FIXES,
    NAMES,
    REDIS_DOC,
    RUNBOOK,
    VAULT_DOC,
    VAULT_FIXED,
    VERDICTS,
    extract_model,
    fix_model,
    intake_model,
    judge_model,
    spy_on_tools,
)
from tests.test_scope import make_tree

HITL = "https://kagent.dev/extensions/hitl/v1"


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


def _finding(text: str) -> Finding:
    claim = Claim(doc="d.md", line_start=3, line_end=3, text=text, kind="config", values=["x"])
    return Finding(
        id=claim.id,
        instance="r",
        commit="c" * 40,
        doc="d.md",
        line_start=3,
        line_end=3,
        claim=claim,
        verdict="stale",
        evidence_hash="h",
        confidence=0.9,
        old_text=text,
        replacement="fixed",
    )


def test_published_parts_are_redacted():
    summary = CostLedger("r", "c", emit=False).summary("verified")
    finding = _finding("The admin password: hunter2hunter2 is set")
    event = {
        "name": "search_code",
        "server": "s",
        "args": {"query": "password: hunter2hunter2"},
        "decision": "allow",
        "action": "search",
        "result_chars": 10,
        "status": "ok",
        "ok": True,
        "evidence": [],
    }
    outcome = DocOutcome(
        doc="d.md", commit="c" * 40, status="checked", findings=[finding], tool_events=[event]
    )
    report = Report(run_id="r", commit="c" * 40, findings=[finding], counts={"findings": 1})
    memory = {"docs": {"d.md": {"open_findings": [finding.model_dump(mode="json")]}}}
    parts = completed_parts(
        "The key is AKIAABCDEFGHIJKLMNOP.",
        report_data=report,
        outcomes={"d.md": outcome},
        memory=memory,
        summary=summary,
    )
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


# --- A2A input and output on the docs-checker graph -------------------------------------


def a2a_message(
    text: str = "", data: object = None, *, task_id: str = "", context_id: str = ""
) -> a2a_pb2.Message:
    parts = [a2a_pb2.Part(text=text)] if text else []
    if data is not None:
        parts.append(a2a_pb2.Part(data=ParseDict(data, struct_pb2.Value())))
    return a2a_pb2.Message(
        message_id=str(uuid.uuid4()),
        role=a2a_pb2.Role.ROLE_USER,
        parts=parts,
        task_id=task_id,
        context_id=context_id,
    )


def hitl_decision(task_id: str, approvals: list[dict]) -> a2a_pb2.Message:
    message = a2a_message("decision", task_id=task_id, context_id="ctx-1")
    message.extensions.append(HITL)
    message.metadata.CopyFrom(
        ParseDict(
            {HITL: {"type": "tool_approval_response", "approvals": approvals}},
            struct_pb2.Struct(),
        )
    )
    return message


def request_context(message: a2a_pb2.Message, task_id: str, *, resumed: bool = False):
    """What the request handler builds for one turn; the client opted in to HITL."""
    return SimpleNamespace(
        task_id=task_id,
        context_id="ctx-1",
        current_task=object() if resumed else None,
        message=message,
        call_context=SimpleNamespace(state={"headers": {"a2a-extensions": HITL}}),
        get_user_input=lambda: get_message_text(message),
    )


class Queue:
    def __init__(self):
        self.events: list = []

    async def enqueue_event(self, event):
        self.events.append(event)

    def states(self) -> list[int]:
        return [e.status.state for e in self.events if getattr(e, "status", None) is not None]

    def last_status(self):
        return [e for e in self.events if getattr(e, "status", None) is not None][-1].status

    def artifact(self) -> a2a_pb2.Artifact:
        (artifact,) = [
            e.artifact for e in self.events if isinstance(e, a2a_pb2.TaskArtifactUpdateEvent)
        ]
        return artifact


async def send(executor, message, task_id: str = "task-1", *, resumed: bool = False) -> Queue:
    queue = Queue()
    await executor.execute(request_context(message, task_id, resumed=resumed), queue)
    return queue


def data_parts(artifact: a2a_pb2.Artifact) -> list[tuple[dict, object]]:
    """(part metadata, data) of every data part, in order."""
    return [
        (MessageToDict(p.metadata) if p.HasField("metadata") else {}, MessageToDict(p.data))
        for p in artifact.parts
        if p.HasField("data")
    ]


def keyed(artifact: a2a_pb2.Artifact, key: str):
    (value,) = [d[key] for _, d in data_parts(artifact) if isinstance(d, dict) and key in d]
    return value


def failed_reason(queue: Queue) -> str:
    assert queue.states()[-1] == a2a_pb2.TaskState.TASK_STATE_FAILED
    return queue.last_status().message.parts[0].text


def docs_models(**overrides) -> FakeModels:
    models = {
        "extract": extract_model(CLAIMS),
        "judge": judge_model(VERDICTS),
        "fix": fix_model(FIXES),
        **overrides,
    }
    return FakeModels(names=NAMES, **models)


def docs_executor(repo, commit, *, settings=None, models=None, graph=None, fix_gate=None):
    """The executor production builds, around the docs-checker graph and the local repo."""

    async def tools():
        return local_repo_tools(repo, commit)

    return build_executor(
        settings or fake_settings(),
        graph=graph or build_graph(checkpointer=InMemorySaver(serde=checkpoint_serde())),
        models=models or docs_models(),
        tools=tools,
        gate=RecordingGate(),
        fix_gate=fix_gate,
    )


@pytest.fixture(scope="module")
def docs_repo(tmp_path_factory):
    return make_tree(tmp_path_factory.mktemp("a2a"), FILES)


def extracted_docs(models: FakeModels) -> list[str]:
    import re

    return sorted(
        re.search(r"^path: (\S+)$", c[1].content, re.MULTILINE).group(1)
        for c in models.get("extract").calls
    )


async def test_data_part_request_over_text(docs_repo):
    repo, commit = docs_repo
    models = docs_models()
    executor = docs_executor(repo, commit, models=models)
    message = a2a_message("check all", {"scope": [REDIS_DOC], "mode": "interactive"})

    queue = await send(executor, message)

    assert queue.states()[-1] == a2a_pb2.TaskState.TASK_STATE_COMPLETED
    assert extracted_docs(models) == [REDIS_DOC]  # the data part's scope, not "all"
    report = keyed(queue.artifact(), REPORT_KEY)
    assert report["counts"]["docs"] == 1 and report["commit"] == commit

    # Without a data part, the text is the request.
    models = docs_models()
    queue = await send(docs_executor(repo, commit, models=models), a2a_message("check all"))
    assert queue.states()[-1] == a2a_pb2.TaskState.TASK_STATE_COMPLETED
    assert extracted_docs(models) == sorted([REDIS_DOC, VAULT_DOC, RUNBOOK])


@pytest.mark.parametrize(
    "data, says",
    [
        ({"scope": ["../secrets.md"]}, "not a normalized repo-relative path"),
        ({"scope": ["base-apps/vault/values.yaml"]}, "out of scope"),
        (["check", "all"], "request data must be an object"),
        ({"scope": "all", "ref": "main;rm"}, "not a branch name"),
    ],
)
async def test_an_unreadable_request_fails_the_task_without_a_call(
    docs_repo, monkeypatch, data, says
):
    repo, commit = docs_repo
    calls = spy_on_tools(monkeypatch)
    models = docs_models()
    queue = await send(docs_executor(repo, commit, models=models), a2a_message("", data))

    reason = failed_reason(queue)
    assert reason.startswith("docs-checker failed: the request could not be read")
    assert says in reason
    assert calls == [] and models.get("extract").calls == []
    assert a2a_pb2.TaskState.TASK_STATE_COMPLETED not in queue.states()


class LimitSpy:
    """The graph, recording the run budget's limit when a run starts and ends."""

    def __init__(self, graph):
        self.graph = graph
        self.limits: list[tuple[float | None, float | None]] = []

    async def aget_state(self, config):
        return await self.graph.aget_state(config)

    async def ainvoke(self, graph_input, config, *, context):
        start = context.ledger.budget.limit_usd
        try:
            return await self.graph.ainvoke(graph_input, config, context=context)
        finally:
            self.limits.append((start, context.ledger.budget.limit_usd))


def test_budget_limit_is_the_all_budget_or_per_doc():
    settings = dataclasses.replace(fake_settings(), run_budget_all_usd=1.5, run_budget_doc_usd=0.2)
    assert budget_limit(RunRequest(scope="all"), settings) == 1.5
    assert budget_limit(RunRequest(scope=[VAULT_DOC, REDIS_DOC]), settings) == pytest.approx(0.4)


async def test_budget_limit_follows_scope(docs_repo):
    repo, commit = docs_repo
    settings = fake_settings()  # $1.00 for all, $0.10 per doc
    cases = [
        (a2a_message("", {"scope": "all"}), (1.00, 1.00)),
        (a2a_message("", {"scope": [VAULT_DOC, REDIS_DOC]}), (0.20, 0.20)),
        (a2a_message(f"check {VAULT_DOC}"), (0.10, 0.10)),
        # Free text: the intake call runs under one doc's budget, then the scope's.
        (a2a_message("please look over every doc"), (0.10, 1.00)),
    ]
    for message, (start, end) in cases:
        spy = LimitSpy(build_graph(checkpointer=InMemorySaver(serde=checkpoint_serde())))
        models = docs_models(intake=intake_model(all_docs=True))
        executor = docs_executor(repo, commit, settings=settings, models=models, graph=spy)
        queue = await send(executor, message)
        assert queue.states()[-1] == a2a_pb2.TaskState.TASK_STATE_COMPLETED
        ((first, last),) = spy.limits
        assert (first, last) == (pytest.approx(start), pytest.approx(end))


async def test_completed_task_parts(docs_repo):
    repo, commit = docs_repo
    message = a2a_message("", {"scope": "all", "mode": "scheduled", "memory": None})
    queue = await send(docs_executor(repo, commit), message)

    assert queue.states()[-1] == a2a_pb2.TaskState.TASK_STATE_COMPLETED
    artifact = queue.artifact()
    texts = [p.text for p in artifact.parts if p.HasField("text")]
    assert len(texts) == 1 and texts[0].startswith("# Weekly docs check")
    assert VAULT_FIXED in texts[0]
    assert queue.last_status().message.parts[0].text == texts[0]

    plain = [d for meta, d in data_parts(artifact) if PART_TYPE_KEY not in meta]
    keys = [next(iter(d)) for d in plain]
    assert keys == [FINDINGS_KEY, MEMORY_KEY, SLACK_KEY, REPORT_KEY, LEDGER_KEY]

    findings = keyed(artifact, FINDINGS_KEY)
    assert sorted((f["doc"], f["verdict"]) for f in findings) == [
        (VAULT_DOC, "stale"),
        (RUNBOOK, "missing"),
        (RUNBOOK, "stale"),
    ]
    assert all(f["commit"] == commit and f["action_digest"] for f in findings)

    memory = keyed(artifact, MEMORY_KEY)
    assert memory["version"] == 1 and memory["run"] == 1
    assert set(memory["docs"]) == {VAULT_DOC, REDIS_DOC, RUNBOOK}
    assert {e["status"] for e in memory["docs"].values()} == {"checked"}

    slack = keyed(artifact, SLACK_KEY)
    assert slack.startswith("Weekly docs check at ") and len(slack) <= 3000

    report = keyed(artifact, REPORT_KEY)
    assert report["commit"] == commit and report["counts"]["findings"] == 3

    ledger = keyed(artifact, LEDGER_KEY)
    assert ledger["outcome"] == "verified" and ledger["calls"] > 0 and ledger["complete"]
    usage = MessageToDict(artifact.metadata)[USAGE_KEY]
    assert usage["totalTokenCount"] == usage["promptTokenCount"] + usage["candidatesTokenCount"]
    assert usage["totalTokenCount"] > 0


UNCHANGED_FILES = {k: v for k, v in FILES.items() if k != RUNBOOK}


async def test_an_all_unchanged_run_still_returns_the_full_memory(tmp_path):
    # The memory comes back through A2A, where every number is a double: the
    # snapshot the trigger saved from run 1 must still load in run 2.
    repo, commit = make_tree(tmp_path, UNCHANGED_FILES)
    first = await send(
        docs_executor(repo, commit),
        a2a_message("", {"scope": "all", "mode": "scheduled", "memory": None}),
    )
    saved = keyed(first.artifact(), MEMORY_KEY)
    assert saved["run"] == 1.0 and set(saved["docs"]) == {VAULT_DOC, REDIS_DOC}

    models = docs_models()
    second = await send(
        docs_executor(repo, commit, models=models),
        a2a_message("", {"scope": "all", "mode": "scheduled", "memory": saved}),
        task_id="task-2",
    )
    assert second.states()[-1] == a2a_pb2.TaskState.TASK_STATE_COMPLETED
    assert models.get("extract").calls == [] and models.get("judge").calls == []
    report = keyed(second.artifact(), REPORT_KEY)
    assert report["counts"]["docs_unchanged"] == 2 and report["counts"]["carried"] == 1
    memory = keyed(second.artifact(), MEMORY_KEY)
    assert memory["run"] == 2 and set(memory["docs"]) == {VAULT_DOC, REDIS_DOC}
    assert memory["docs"] == saved["docs"]  # every doc unchanged: the same entries, in full


async def test_function_call_parts_for_tool_events(docs_repo):
    repo, commit = docs_repo
    queue = await send(docs_executor(repo, commit), a2a_message("", {"scope": [VAULT_DOC]}))
    tagged = [(meta[PART_TYPE_KEY], d) for meta, d in data_parts(queue.artifact()) if meta]

    calls = [d for kind, d in tagged if kind == "function_call"]
    responses = [d for kind, d in tagged if kind == "function_response"]
    assert len(calls) == len(responses) >= 3
    # each call is followed by its response
    assert [kind for kind, _ in tagged] == ["function_call", "function_response"] * len(calls)
    assert [c["name"] for c in calls] == [r["name"] for r in responses]
    reads = {c["args"]["path"] for c in calls if c["name"] == "get_file_contents"}
    assert reads >= {VAULT_DOC, "base-apps/vault/values.yaml", "base-apps/vault/service.yaml"}
    assert all(c["args"]["sha"] == commit for c in calls if c["name"] == "get_file_contents")
    assert all(r["response"]["decision"] == "allow" for r in responses)


async def test_run_timeout_fails_cleanly(docs_repo):
    repo, commit = docs_repo
    settings = dataclasses.replace(fake_settings(), run_timeout_s=2.0)
    models = docs_models(extract=extract_model(CLAIMS, delay=60))
    executor = docs_executor(repo, commit, settings=settings, models=models)

    started = time.monotonic()
    queue = await send(executor, a2a_message("", {"scope": [VAULT_DOC]}))

    assert time.monotonic() - started < 10
    assert failed_reason(queue) == "docs-checker failed: timeout"
    assert a2a_pb2.TaskState.TASK_STATE_COMPLETED not in queue.states()
    assert queue.states().count(a2a_pb2.TaskState.TASK_STATE_FAILED) == 1
    # The partial cost stays in the ledger: the call in flight is unknown, its
    # reservation unsettled.
    ledger = MessageToDict(queue.events[-1].metadata)[LEDGER_KEY]
    assert ledger["outcome"] == "failed" and ledger["calls"] == 1 and ledger["unknown_calls"] == 1
    assert ledger["reserved_unsettled_usd"] > 0 and ledger["complete"] is False
    assert executor._running == {}
    await asyncio.sleep(0.05)
    assert models.get("extract").active == 0  # the model call was cancelled, not left running


async def test_a_failed_run_fails_the_task_with_its_reason(docs_repo):
    repo, commit = docs_repo
    queue = await send(docs_executor(repo, commit), a2a_message("check all at no-such-branch"))
    reason = failed_reason(queue)
    assert reason.startswith("docs-checker failed: ") and "no-such-branch" in reason
    assert not [e for e in queue.events if isinstance(e, a2a_pb2.TaskArtifactUpdateEvent)]


async def test_an_off_topic_request_completes_with_the_refusal(docs_repo):
    repo, commit = docs_repo
    models = docs_models(intake=intake_model("off_topic"))
    queue = await send(docs_executor(repo, commit, models=models), a2a_message("delete vault"))
    assert queue.states()[-1] == a2a_pb2.TaskState.TASK_STATE_COMPLETED
    artifact = queue.artifact()
    assert "read-only" in artifact.parts[0].text
    assert keyed(artifact, FINDINGS_KEY) == []
    assert keyed(artifact, LEDGER_KEY)["outcome"] == "refused"
    assert keyed(artifact, MEMORY_KEY)["docs"] == {}  # the memory part is always there


def test_request_json_numbers_come_back_as_ints():
    from docs_checker.executor import request_data

    message = a2a_message("", {"scope": "all", "memory": {"run": 3, "x": [1, 2.5]}})
    assert request_data(message) == {"scope": "all", "memory": {"run": 3, "x": [1, 2.5]}}
    assert isinstance(request_data(message)["memory"]["run"], int)
    assert request_data(a2a_message("check all")) is None
    assert json.dumps(request_data(message))  # plain JSON
