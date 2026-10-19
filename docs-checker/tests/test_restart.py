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
from docs_checker.ledger import Budget, CostLedger
from docs_checker.paused import TABLE, PausedTasks
from docs_checker.server import open_executor
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


async def test_a_lost_pause_record_makes_the_cost_a_lower_bound(tmp_path):
    repo, commit = make_tree(tmp_path, FILES)
    settings = dataclasses.replace(
        fake_settings(), checkpoint_db=str(tmp_path / "data" / "checkpoints.sqlite")
    )
    ask = await pause_on_a_fix(settings, repo, commit, "task-l")
    with sqlite3.connect(settings.checkpoint_db) as db:
        db.execute(f"DELETE FROM {TABLE}")

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
        "extract:c:doc.md": [{"doc": "doc.md", "text": "claim", "values": ["1"], "id": "abc"}],
        "decision:c:doc.md:abc:key": {"verdict": "stale", "confidence": 0.9, "reason": "r"},
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


async def test_a_corrupt_record_is_treated_as_lost(db):
    import asyncio

    paused = PausedTasks(db, lock=asyncio.Lock())
    await paused.setup()
    await db.execute(
        f"INSERT INTO {TABLE} (task_id, type, record, saved_at) VALUES (?, ?, ?, ?)",
        ("task-c", "msgpack", b"\xc1 not msgpack", 0.0),
    )
    await db.commit()
    assert await paused.take("task-c", lambda: CostLedger("task-c", emit=False)) is None
