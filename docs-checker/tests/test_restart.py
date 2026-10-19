"""A paused task survives the process: a new executor on the same checkpoint db resumes it.

kagent alpha14 snapshots persist /data only, never process memory (ruling A1). The
checkpoint (AsyncSqliteSaver at ``settings.checkpoint_db``) holds the graph's pause;
the paused task's cost ledger and replay memo sit next to it in the same sqlite db,
so a resume in a new process keeps the whole cost and does not pay again for work
done before the pause. Strict approval holds across the restart.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import sqlite3

import pytest
from a2a.types import a2a_pb2
from google.protobuf.json_format import MessageToDict
from langchain_core.messages import AIMessage

from docs_checker.evals.localrepo import local_repo_tools
from docs_checker.executor import LEDGER_KEY, REPORT_KEY
from docs_checker.gate import RecordingGate
from docs_checker.graph import checkpoint_serde
from docs_checker.ledger import Budget, CostLedger
from docs_checker.paused import TABLE, PausedTasks
from docs_checker.server import open_executor
from docs_checker.state import Claim, Decision
from docs_checker.tools import ToolResult
from tests.fakes import FakeModels, RoutedModel, fake_settings, reply
from tests.test_executor import (
    HITL,
    a2a_message,
    hitl_decision,
    keyed,
    send,
)
from tests.test_graph import (
    CLAIMS,
    FILES,
    NAMES,
    TWO_CLAIM_DOC,
    TWO_CLAIM_FILES,
    TWO_CLAIMS,
    TWO_FIXES,
    VAULT_DOC,
    VAULT_FIXED,
    VERDICTS,
    asking_gate,
    extract_model,
    fix_model,
    judge_model,
    spy_on_tools,
)
from tests.test_scope import make_tree


def never(node: str) -> RoutedModel:
    def answer(user: str) -> AIMessage:
        raise AssertionError(f"{node} was called again after the restart")

    return RoutedModel(answer)


def settings_on(db) -> object:
    # $2.005 for one doc: the first judgement ($2.00) leaves no room for the second.
    return dataclasses.replace(fake_settings(), checkpoint_db=str(db), run_budget_doc_usd=2.005)


def executor_on(settings, repo, commit, models, *, fix_gate=None):
    async def tools():
        return local_repo_tools(repo, commit)

    return open_executor(
        settings, models=models, tools=tools, gate=RecordingGate(), fix_gate=fix_gate
    )


def pending_request(queue) -> dict:
    status = queue.last_status()
    assert status.state == a2a_pb2.TaskState.TASK_STATE_INPUT_REQUIRED
    assert HITL in status.message.extensions
    (tool,) = MessageToDict(status.message.metadata)[HITL]["tools"]
    return tool


def ledger_of(queue) -> dict:
    return keyed(queue.artifact(), LEDGER_KEY)


def expensive_judge() -> RoutedModel:
    def answer(user: str) -> AIMessage:
        body = {"verdict": "stale", "confidence": 0.9, "reason": "r", "window_index": 0}
        if json.dumps("The service is named vault") in user:
            return reply(json.dumps({**body, "verdict": "supported"}))
        return reply(json.dumps(body), uncached=4_000_000, output=50)  # $2.00 on Haiku

    return RoutedModel(answer)


def second_claim_judge() -> RoutedModel:
    def answer(user: str) -> AIMessage:
        if json.dumps("The service is named vault") in user:
            body = {"verdict": "supported", "confidence": 0.9, "reason": "r", "window_index": 0}
            return reply(json.dumps(body))
        raise AssertionError("the first claim was judged again after the restart")

    return RoutedModel(answer)


async def test_resume_after_executor_restart_on_the_same_db(tmp_path, monkeypatch):
    repo, commit = make_tree(tmp_path, TWO_CLAIM_FILES)
    settings = settings_on(tmp_path / "data" / "checkpoints.sqlite")
    request = a2a_message("", {"scope": [TWO_CLAIM_DOC], "mode": "interactive"})

    before = FakeModels(
        names=NAMES,
        extract=extract_model(TWO_CLAIMS),
        judge=expensive_judge(),
        fix=fix_model(TWO_FIXES),
    )
    async with executor_on(settings, repo, commit, before) as executor:
        paused = await send(executor, request, "task-r")
    ask = pending_request(paused)
    assert ask["name"] == "raise_budget" and ask["args"]["limit_usd"] == 2.005
    spent = MessageToDict(paused.events[-1].metadata)[LEDGER_KEY]
    assert spent["calls"] == 2 and spent["cost_usd_known"] >= 2.0

    # A new process: new executor, graph, checkpointer connection and models. The
    # extraction and the first judgement must come from the persisted memo.
    calls = spy_on_tools(monkeypatch)
    after = FakeModels(
        names=NAMES,
        extract=never("extract"),
        judge=second_claim_judge(),
        fix=fix_model(TWO_FIXES),
    )
    async with executor_on(settings, repo, commit, after) as executor:
        done = await send(
            executor,
            hitl_decision("task-r", [{"id": ask["id"], "approved": True}]),
            "task-r",
            resumed=True,
        )

    assert done.last_status().state == a2a_pb2.TaskState.TASK_STATE_COMPLETED
    report = keyed(done.artifact(), REPORT_KEY)
    # Checked, not skipped: the approval matched the pause, so the restored limit was
    # the one the pause offered to raise.
    assert report["counts"]["docs_checked"] == 1 and report["complete_cost"] is True
    assert [f["replacement"] for f in report["findings"]] == ["The chart is vault version 0.31.0."]
    assert len(after.get("judge").calls) == 1 and len(after.get("fix").calls) == 1
    # Tool results replayed too: the doc and its source were not read again.
    reads = {a.get("path") for name, a in calls if name == "get_file_contents"}
    assert TWO_CLAIM_DOC not in reads and "base-apps/vault/values.yaml" not in reads

    ledger = ledger_of(done)
    assert ledger["calls"] == 4  # 2 before the pause, 2 after the restart
    assert ledger["cost_usd_known"] >= 2.0 and ledger["complete"] is True
    assert set(ledger["by_node"]) == {"extract", "judge", "fix"}
    assert "lower bound" not in done.artifact().parts[0].text

    # The record is gone once the task resumed.
    with sqlite3.connect(settings.checkpoint_db) as db:
        assert db.execute(f"SELECT count(*) FROM {TABLE}").fetchone() == (0,)


async def pause_on_a_fix(settings, repo, commit, task_id: str) -> dict:
    models = FakeModels(
        names=NAMES,
        extract=extract_model(CLAIMS),
        judge=judge_model(VERDICTS),
        fix=fix_model({"Vault runs chart vault version 0.30.1.": VAULT_FIXED}),
    )
    request = a2a_message("", {"scope": [VAULT_DOC], "mode": "interactive"})
    async with executor_on(settings, repo, commit, models, fix_gate=asking_gate()) as executor:
        paused = await send(executor, request, task_id)
    ask = pending_request(paused)
    assert ask["name"] == "propose_fix" and ask["args"]["replacement"] == VAULT_FIXED
    return ask


def models_after_restart() -> FakeModels:
    return FakeModels(names=NAMES, extract=never("extract"), judge=never("judge"), fix=never("fix"))


async def test_strict_approval_holds_after_a_restart(tmp_path):
    repo, commit = make_tree(tmp_path, FILES)
    settings = dataclasses.replace(
        fake_settings(), checkpoint_db=str(tmp_path / "data" / "checkpoints.sqlite")
    )
    wrong = await pause_on_a_fix(settings, repo, commit, "task-a")
    right = await pause_on_a_fix(settings, repo, commit, "task-b")

    async with executor_on(
        settings, repo, commit, models_after_restart(), fix_gate=asking_gate()
    ) as executor:
        rejected = await send(
            executor,
            hitl_decision("task-a", [{"id": "some-other-fix", "approved": True}]),
            "task-a",
            resumed=True,
        )
        approved = await send(
            executor,
            hitl_decision("task-b", [{"id": right["id"], "approved": True}]),
            "task-b",
            resumed=True,
        )
    assert wrong["id"] == right["id"]  # same fix, same digest: only the reply differs

    (finding,) = keyed(rejected.artifact(), REPORT_KEY)["findings"]
    assert finding["replacement"] == "" and "rejected" in finding["fix_withheld"]
    (finding,) = keyed(approved.artifact(), REPORT_KEY)["findings"]
    assert finding["replacement"] == VAULT_FIXED and finding["fix_withheld"] is None
    assert ledger_of(approved)["calls"] == 3  # extract, judge, fix: before the pause only


def corrupt_the_record(path: str, task_id: str) -> None:
    """Decodable, but a memo entry is not what its key says (a tool result that is not
    a (ToolResult, ToolEvent) pair) and a ledger entry's cost is not a number."""
    serde = checkpoint_serde()
    with sqlite3.connect(path) as db:
        kind, blob = db.execute(
            f"SELECT type, record FROM {TABLE} WHERE task_id = ?", (task_id,)
        ).fetchone()
        record = serde.loads_typed((kind, blob))
        record["replay"]["tool:x"] = {"kind": "data", "value": "not a pair"}
        record["ledger"]["entries"][0]["cost_usd"] = "not a number"
        db.execute(
            f"UPDATE {TABLE} SET record = ? WHERE task_id = ?",
            (serde.dumps_typed(record)[1], task_id),
        )


@pytest.mark.parametrize("loss", ["deleted", "corrupt"])
async def test_a_lost_pause_record_makes_the_cost_a_lower_bound(tmp_path, loss):
    repo, commit = make_tree(tmp_path, FILES)
    settings = dataclasses.replace(
        fake_settings(), checkpoint_db=str(tmp_path / "data" / "checkpoints.sqlite")
    )
    ask = await pause_on_a_fix(settings, repo, commit, "task-l")
    if loss == "deleted":
        with sqlite3.connect(settings.checkpoint_db) as db:
            db.execute(f"DELETE FROM {TABLE}")
    else:
        corrupt_the_record(settings.checkpoint_db, "task-l")

    async with executor_on(
        settings, repo, commit, models_after_restart(), fix_gate=asking_gate()
    ) as executor:
        done = await send(
            executor,
            hitl_decision("task-l", [{"id": ask["id"], "approved": True}]),
            "task-l",
            resumed=True,
        )

    assert done.last_status().state == a2a_pb2.TaskState.TASK_STATE_COMPLETED
    report = keyed(done.artifact(), REPORT_KEY)
    (finding,) = report["findings"]
    assert finding["replacement"] == VAULT_FIXED  # the approval still applies
    assert report["complete_cost"] is False
    assert report["notes"] == ["cost after restart is a lower bound"]
    assert "cost after restart is a lower bound" in done.artifact().parts[0].text
    ledger = ledger_of(done)
    assert ledger["calls"] == 0 and ledger["complete"] is False


# --- the record itself ---------------------------------------------------------------


@pytest.fixture
async def db(tmp_path):
    import aiosqlite

    async with aiosqlite.connect(tmp_path / "paused.sqlite") as conn:
        yield conn


def ledger_with_spend() -> CostLedger:
    ledger = CostLedger("task-x", "ctx-x", emit=False, budget=Budget(0.5))
    ledger.record_message(
        node="judge", model="claude-haiku-5-5", attempt=1, message=reply("ok", uncached=1000)
    )
    ledger.record_error(node="fix", model="claude-haiku-5-5", attempt=1, error=RuntimeError("x"))
    return ledger


async def test_every_replay_kind_round_trips_and_the_ledger_with_it(db, caplog):
    import asyncio

    ledger = ledger_with_spend()
    reservation = await ledger.budget.reserve(0.01)
    ledger.budget.settle(reservation, 0.002)
    await ledger.budget.reserve(0.03)  # an attempt cancelled in flight: never settled
    event = {
        "name": "get_file_contents",
        "server": "agent-docs-mcp",
        "args": {"path": "a.yaml", "sha": "c" * 40},
        "decision": "allow",
        "action": "read a.yaml",
        "result_chars": 3,
        "status": "ok",
        "ok": True,
        "evidence": ["a.yaml"],
    }
    replay = {
        "tool:1": (ToolResult(text="a: 1", status="ok", raw_chars=4), event),
        "search:count": 2,
        "search:last_start": 12.5,
        # as graph_doc stores them: model dumps of a Claim and a Decision
        "extract:c:doc.md": [
            Claim(
                doc="doc.md", line_start=1, line_end=1, text="claim", kind="config", values=["1"]
            ).model_dump()
        ],
        "decision:c:doc.md:abc:key": Decision(
            verdict="stale", confidence=0.9, reason="r", judged_by="model"
        ).model_dump(),
        "fix:c:doc.md:abc:h": "the fixed line",
        "model:worker:x:0": AIMessage(content="not a docs-checker memo value"),
    }

    writer = PausedTasks(db, lock=asyncio.Lock())
    await writer.setup()
    with caplog.at_level(logging.WARNING):
        await writer.put("task-x", ledger, dict(replay))
    assert "model:" in caplog.text  # what could not be kept is named

    reader = PausedTasks(db, lock=asyncio.Lock())  # a new process: nothing in memory
    fresh = CostLedger("task-x", "ctx-x", emit=False)
    taken = await reader.take("task-x", lambda: fresh)
    assert taken is not None
    restored, memo = taken
    assert restored is fresh
    assert restored.entries == ledger.entries
    assert restored.budget.limit_usd == 0.5
    assert restored.budget.spent_usd == pytest.approx(ledger.budget.spent_usd)
    assert restored.budget.reserved_usd == pytest.approx(0.03)
    assert restored.summary("verified") == ledger.summary("verified")
    expected = {k: v for k, v in replay.items() if not k.startswith("model:")}
    assert memo == expected
    assert isinstance(memo["tool:1"], tuple) and isinstance(memo["tool:1"][0], ToolResult)
    assert type(memo["search:count"]) is int and type(memo["search:last_start"]) is float

    assert await reader.take("task-x", lambda: fresh) is None  # taken once


def corrupted(change) -> tuple[str, bytes]:
    """A well-formed record (a ledger and every memo kind), then ``change`` applied."""
    ledger = ledger_with_spend()
    event = {
        "name": "get_file_contents",
        "server": "agent-docs-mcp",
        "args": {"path": "a.yaml"},
        "decision": "allow",
        "action": "read a.yaml",
        "result_chars": 4,
        "status": "ok",
        "ok": True,
        "evidence": ["a.yaml"],
    }
    claim = {
        "doc": "d.md",
        "line_start": 3,
        "line_end": 3,
        "text": "claim",
        "kind": "config",
        "keys": [],
        "values": ["1"],
        "source_hint": "",
        "id": "abc",
    }
    decision = {"verdict": "stale", "confidence": 0.9, "reason": "r", "judged_by": "model"}
    replay = {
        "tool:1": {"kind": "tool", "result": {"text": "a: 1", "status": "ok", "raw_chars": 4},
                   "event": event},
        "search:count": {"kind": "number", "value": 2},
        "search:last_start": {"kind": "number", "value": 1.5},
        "extract:c:d.md": {"kind": "data", "value": [claim]},
        "decision:c:d.md:abc:k": {"kind": "data", "value": decision},
        "fix:c:d.md:abc:h": {"kind": "data", "value": "fixed"},
    }  # fmt: skip
    record = {"version": 1, "ledger": ledger.dump_state(), "replay": replay}
    kind = change(record)
    _, blob = checkpoint_serde().dumps_typed(record)
    return kind or "msgpack", blob


def _set(path: str, value):
    def change(record):
        *keys, last = path.split("/")
        target = record
        for key in keys:
            target = target[int(key)] if isinstance(target, list) else target[key]
        if isinstance(target, list):
            target[int(last)] = value
        else:
            target[last] = value

    return change


def _drop(path: str):
    def change(record):
        *keys, last = path.split("/")
        target = record
        for key in keys:
            target = target[int(key)] if isinstance(target, list) else target[key]
        del target[last]

    return change


CORRUPTIONS = {
    "a well-formed record": (lambda record: None, True),
    "not the serializer's type": (lambda record: "json", False),
    "a cost that is not a number": (_set("ledger/entries/0/cost_usd", "x"), False),
    "a usage count that is not an int": (_set("ledger/entries/0/usage/output", "50"), False),
    "an unknown entry status": (_set("ledger/entries/0/status", "maybe"), False),
    "a missing entry field": (_drop("ledger/entries/0/ts"), False),
    "a negative spend": (_set("ledger/budget/spent_usd", -1.0), False),
    "a tool result that is not a pair": (
        _set("replay/tool:x", {"kind": "data", "value": "not a pair"}), False),
    "a tool status that is not a status": (_set("replay/tool:1/result/status", "fine"), False),
    "a tool event without its fields": (_set("replay/tool:1/event", {"name": "x"}), False),
    "an extraction that is a number": (
        _set("replay/extract:c:d.md", {"kind": "number", "value": 3}), False),
    "a claim that is not a claim": (
        _set("replay/extract:c:d.md", {"kind": "data", "value": [{"doc": "d.md"}]}), False),
    "a decision that is not a decision": (
        _set("replay/decision:c:d.md:abc:k", {"kind": "data", "value": {"verdict": "maybe"}}),
        False),
    "a fix that is not text": (_set("replay/fix:c:d.md:abc:h", {"kind": "data", "value": 3}),
                               False),
    "a search counter that is text": (
        _set("replay/search:count", {"kind": "number", "value": "2"}), False),
    "a key of no known kind": (_set("replay/model:x", {"kind": "data", "value": "x"}), False),
}  # fmt: skip


@pytest.mark.parametrize("case", list(CORRUPTIONS))
async def test_a_corrupt_record_is_treated_as_lost(db, case):
    import asyncio

    change, kept = CORRUPTIONS[case]
    paused = PausedTasks(db, lock=asyncio.Lock())
    await paused.setup()
    kind, blob = corrupted(change)
    await db.execute(
        f"INSERT INTO {TABLE} (task_id, type, record, saved_at) VALUES (?, ?, ?, ?)",
        ("task-c", kind, blob, 0.0),
    )
    await db.commit()
    held = await paused.take("task-c", lambda: CostLedger("task-c", emit=False))
    if kept:
        ledger, memo = held
        ledger.summary("verified")
        assert set(memo) == {
            "tool:1", "search:count", "search:last_start", "extract:c:d.md",
            "decision:c:d.md:abc:k", "fix:c:d.md:abc:h",
        }  # fmt: skip
    else:
        assert held is None


async def test_undecodable_bytes_are_treated_as_lost(db):
    import asyncio

    paused = PausedTasks(db, lock=asyncio.Lock())
    await paused.setup()
    await db.execute(
        f"INSERT INTO {TABLE} (task_id, type, record, saved_at) VALUES (?, ?, ?, ?)",
        ("task-c", "msgpack", b"\xc1 not msgpack", 0.0),
    )
    await db.commit()
    assert await paused.take("task-c", lambda: CostLedger("task-c", emit=False)) is None


# --- checkpoint threads end with their task --------------------------------------------


def thread_rows(path: str, task_id: str) -> int:
    with sqlite3.connect(path) as db:
        return sum(
            db.execute(f"SELECT count(*) FROM {table} WHERE thread_id = ?", (task_id,)).fetchone()[
                0
            ]
            for table in ("checkpoints", "writes")
        )


def paused_rows(path: str, task_id: str) -> int:
    with sqlite3.connect(path) as db:
        return db.execute(f"SELECT count(*) FROM {TABLE} WHERE task_id = ?", (task_id,)).fetchone()[
            0
        ]


def vault_models(**overrides) -> FakeModels:
    models = {
        "extract": extract_model(CLAIMS),
        "judge": judge_model(VERDICTS),
        "fix": fix_model({"Vault runs chart vault version 0.30.1.": VAULT_FIXED}),
        **overrides,
    }
    return FakeModels(names=NAMES, **models)


@pytest.mark.parametrize("end", ["completed", "failed", "timeout"])
async def test_a_finished_task_leaves_no_checkpoint_thread(tmp_path, end):
    repo, commit = make_tree(tmp_path, FILES)
    settings = dataclasses.replace(
        fake_settings(),
        checkpoint_db=str(tmp_path / "data" / "checkpoints.sqlite"),
        run_timeout_s=2.0,
    )
    models = vault_models()
    message = a2a_message("", {"scope": [VAULT_DOC]})
    if end == "failed":
        message = a2a_message("check all at no-such-branch")
    elif end == "timeout":
        models = vault_models(extract=extract_model(CLAIMS, delay=60))
    async with executor_on(settings, repo, commit, models) as executor:
        queue = await send(executor, message, "task-t")
    state = {
        "completed": a2a_pb2.TaskState.TASK_STATE_COMPLETED,
        "failed": a2a_pb2.TaskState.TASK_STATE_FAILED,
        "timeout": a2a_pb2.TaskState.TASK_STATE_FAILED,
    }[end]
    assert queue.last_status().state == state
    assert thread_rows(settings.checkpoint_db, "task-t") == 0


async def test_a_paused_task_keeps_its_thread_and_a_cancel_removes_both(tmp_path):
    from tests.test_executor import Queue, request_context

    repo, commit = make_tree(tmp_path, FILES)
    db = str(tmp_path / "data" / "checkpoints.sqlite")
    settings = dataclasses.replace(fake_settings(), checkpoint_db=db)
    message = a2a_message("", {"scope": [VAULT_DOC], "mode": "interactive"})
    async with executor_on(
        settings, repo, commit, vault_models(), fix_gate=asking_gate()
    ) as executor:
        paused = await send(executor, message, "task-p")
        pending_request(paused)
        assert thread_rows(db, "task-p") > 0 and paused_rows(db, "task-p") == 1

        queue = Queue()
        await executor.cancel(request_context(message, "task-p", resumed=True), queue)

        assert queue.states() == [a2a_pb2.TaskState.TASK_STATE_CANCELED]
        assert paused_rows(db, "task-p") == 0  # the durable record, not only memory
        assert thread_rows(db, "task-p") == 0


async def test_a_cancelled_running_task_leaves_no_checkpoint_thread(tmp_path):
    import asyncio

    from tests.test_executor import Queue, request_context

    repo, commit = make_tree(tmp_path, FILES)
    db = str(tmp_path / "data" / "checkpoints.sqlite")
    settings = dataclasses.replace(fake_settings(), checkpoint_db=db)
    extract = extract_model(CLAIMS, delay=60)
    message = a2a_message("", {"scope": [VAULT_DOC]})
    async with executor_on(settings, repo, commit, vault_models(extract=extract)) as executor:
        context, queue = request_context(message, "task-k"), Queue()
        run = asyncio.create_task(executor.execute(context, queue))
        for _ in range(500):
            if extract.active:
                break
            await asyncio.sleep(0.01)
        assert extract.active == 1 and thread_rows(db, "task-k") > 0
        await executor.cancel(context, queue)
        await asyncio.wait_for(run, 5)

    assert queue.states()[-1] == a2a_pb2.TaskState.TASK_STATE_CANCELED
    assert thread_rows(db, "task-k") == 0


async def test_nolock_checkpointer_pragmas(tmp_path):
    from docs_checker.graph import open_checkpointer

    async with open_checkpointer(str(tmp_path / "c.sqlite"), nolock=True) as saver:
        async with saver.conn.execute("PRAGMA journal_mode") as cursor:
            assert (await cursor.fetchone())[0] == "memory"
        async with saver.conn.execute("PRAGMA synchronous") as cursor:
            assert (await cursor.fetchone())[0] == 0


async def test_nolock_checkpoint_survives_reopen(tmp_path):
    from langgraph.checkpoint.base import empty_checkpoint

    from docs_checker.graph import open_checkpointer

    path = str(tmp_path / "nested" / "c.sqlite")
    config = {"configurable": {"thread_id": "t1", "checkpoint_ns": ""}}
    async with open_checkpointer(path, nolock=True) as saver:
        await saver.setup()
        checkpoint = empty_checkpoint()
        await saver.aput(config, checkpoint, {"source": "input", "step": -1}, {})
    async with open_checkpointer(path, nolock=True) as saver:
        found = await saver.aget_tuple(config)
    assert found is not None and found.checkpoint["id"] == checkpoint["id"]
