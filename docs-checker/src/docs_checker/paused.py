"""Paused tasks: the cost ledger and replay memo a resume continues (ruling A1).

A paused task's graph state is in the checkpoint (``AsyncSqliteSaver`` at
``settings.checkpoint_db``). What the executor carries across the pause beside it,
the task's ``CostLedger`` and its replay memo, is kept here: in memory, for a
resume in the same process, and in a table of the same sqlite db, for a resume
after a restart (kagent alpha14 snapshots persist /data only, never process
memory). Without a db (tests, local runs) it is memory only.

The memo's values are encoded kind by kind, as the graph and the tool belt put
them in it, and the whole record then goes through the checkpointer's allowlisted
serializer (``graph.checkpoint_serde``), so only plain data is stored or loaded:

- ``tool:<call id>``: a ``(ToolResult, ToolEvent)`` pair;
- ``search:count`` and ``search:last_start``: the belt's int and float counters;
- ``extract:``, ``decision:`` and ``fix:``: model replies the graph already reduced
  to plain data (claim dicts, a decision dict, a replacement string).

Each entry is checked against what its key says it holds, both when it is written
and when it is read back (``_decode``). A value of any other shape is not kept, and is
named in a warning: a resume after a restart redoes that work and pays for it in its
own ledger. A record that is missing, not the serializer's msgpack, or malformed in
any part (a memo entry, a ledger entry, the budget) is a lost pause: the executor
resumes with a new ledger and the report says that the cost after the restart is a
lower bound (C#25).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict
from collections.abc import Callable
from typing import Any, get_args

from docs_checker.graph import checkpoint_serde
from docs_checker.ledger import CostLedger
from docs_checker.state import Claim, Decision
from docs_checker.tools import _SEARCH_COUNT, _SEARCH_LAST_START, ToolResult, ToolStatus

logger = logging.getLogger(__name__)

TABLE = "docs_checker_paused"
# Bounded, so abandoned pauses cannot pile up (in memory or on disk).
MAX_PAUSED = 64
RECORD_VERSION = 1

Held = tuple[CostLedger, dict[str, Any]]

_SCALARS = (str, int, float, bool, type(None))


def _plain(value: Any) -> bool:
    """JSON-shaped data: what the serializer stores without naming a class."""
    if isinstance(value, _SCALARS):
        return True
    if isinstance(value, list):
        return all(_plain(v) for v in value)
    if isinstance(value, dict):
        return all(isinstance(k, str) and _plain(v) for k, v in value.items())
    return False


# A ToolEvent's fields and their types (tools.ToolEvent).
_EVENT_FIELDS: dict[str, type | tuple[type, ...]] = {
    "name": str,
    "server": str,
    "args": dict,
    "decision": str,
    "action": str,
    "result_chars": int,
    "status": str,
    "ok": bool,
    "evidence": list,
}
_TOOL_STATUSES = frozenset(get_args(ToolStatus))


def _expect(ok: bool, what: str) -> None:
    if not ok:
        raise ValueError(f"malformed memo entry: {what}")


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _tool_pair(entry: dict) -> tuple[ToolResult, dict]:
    result, event = entry.get("result"), entry.get("event")
    _expect(isinstance(result, dict) and set(result) == {"text", "status", "raw_chars"}, "result")
    _expect(isinstance(result["text"], str), "result text")
    _expect(result["status"] in _TOOL_STATUSES, "result status")
    _expect(_is_int(result["raw_chars"]), "result size")
    _expect(isinstance(event, dict) and set(event) == set(_EVENT_FIELDS), "event fields")
    for name, kind in _EVENT_FIELDS.items():
        _expect(isinstance(event[name], kind), f"event {name}")
    _expect(_is_int(event["result_chars"]) and _plain(event["args"]), "event args")
    _expect(all(isinstance(e, str) for e in event["evidence"]), "event evidence")
    return ToolResult(**result), dict(event)


def _decode(key: str, entry: Any) -> Any:
    """The memo value an encoded entry holds, checked against what its key says it is
    (raises ``ValueError`` or ``TypeError`` on anything else)."""
    _expect(isinstance(entry, dict), "not an object")
    kind, value = entry.get("kind"), entry.get("value")
    if key.startswith("tool:"):
        _expect(kind == "tool", "a tool key without a tool result")
        return _tool_pair(entry)
    if key == _SEARCH_COUNT:
        _expect(kind == "number" and _is_int(value), "search count")
        return value
    if key == _SEARCH_LAST_START:
        _expect(kind == "number" and (_is_int(value) or isinstance(value, float)), "search start")
        return value
    _expect(kind == "data" and _plain(value), "not plain data")
    if key.startswith("extract:"):
        _expect(isinstance(value, list) and all(isinstance(c, dict) for c in value), "claims")
        for claim in value:
            Claim.model_validate(claim)  # what extract replays must validate there too
        return value
    if key.startswith("decision:"):
        _expect(isinstance(value, dict), "decision")
        Decision.model_validate(value)
        return value
    if key.startswith("fix:"):
        _expect(isinstance(value, str), "replacement")
        return value
    raise ValueError(f"no memo kind for key prefix {key.split(':', 1)[0]!r}")


def _encode(key: str, value: Any) -> dict:
    if key.startswith("tool:"):
        result, event = value
        if not isinstance(result, ToolResult):
            raise TypeError("not a (ToolResult, ToolEvent) pair")
        entry = {
            "kind": "tool",
            "result": {"text": result.text, "status": result.status, "raw_chars": result.raw_chars},
            "event": dict(event),
        }
    elif key.startswith("search:"):
        entry = {"kind": "number", "value": value}
    else:
        entry = {"kind": "data", "value": value}
    _decode(key, entry)  # nothing is written that could not be read back
    return entry


def encode_replay(replay: dict[str, Any]) -> tuple[dict[str, dict], list[str]]:
    """The memo's encodable entries, and the keys that could not be encoded."""
    encoded, dropped = {}, []
    for key, value in replay.items():
        try:
            encoded[key] = _encode(key, value)
        except (TypeError, ValueError, KeyError):
            dropped.append(key)
    return encoded, dropped


def decode_replay(encoded: Any) -> dict[str, Any]:
    if not isinstance(encoded, dict):
        raise TypeError("the memo is not an object")
    return {key: _decode(key, entry) for key, entry in encoded.items()}


class PausedTasks:
    """Where a paused task's ledger and memo wait for its resume.

    ``conn`` is an open aiosqlite connection (production: the checkpointer's, with
    its ``lock``, so writes never interleave with the checkpointer's own). ``put``
    keeps the pair in memory and, with a db, writes the record; ``take`` hands it
    back once, from memory when this process paused it, else from the db.
    """

    def __init__(self, conn: Any = None, *, lock: asyncio.Lock | None = None):
        self._conn = conn
        self._lock = lock or asyncio.Lock()
        self._memory: OrderedDict[str, Held] = OrderedDict()
        self._serde = checkpoint_serde()

    @property
    def durable(self) -> bool:
        """True when a pause survives a restart (kept in the checkpoint db)."""
        return self._conn is not None

    async def setup(self) -> None:
        if self._conn is None:
            return
        async with self._lock:
            await self._conn.execute(
                f"CREATE TABLE IF NOT EXISTS {TABLE} ("
                "task_id TEXT PRIMARY KEY, type TEXT NOT NULL, record BLOB NOT NULL, "
                "saved_at REAL NOT NULL)"
            )
            await self._conn.commit()

    async def put(self, task_id: str, ledger: CostLedger, replay: dict[str, Any]) -> None:
        self._memory[task_id] = (ledger, replay)
        self._memory.move_to_end(task_id)
        while len(self._memory) > MAX_PAUSED:
            self._memory.popitem(last=False)
        if self._conn is None:
            return
        encoded, dropped = encode_replay(replay)
        if dropped:
            logger.warning(
                "paused task %s: %d memo entries cannot be kept on disk (%s); a resume "
                "after a restart redoes them",
                task_id,
                len(dropped),
                ", ".join(sorted({key.split(":", 1)[0] + ":" for key in dropped})),
            )
        record = {"version": RECORD_VERSION, "ledger": ledger.dump_state(), "replay": encoded}
        try:
            kind, blob = self._serde.dumps_typed(record)
            async with self._lock:
                await self._conn.execute(
                    f"INSERT OR REPLACE INTO {TABLE} (task_id, type, record, saved_at) "
                    "VALUES (?, ?, ?, ?)",
                    (task_id, kind, blob, time.time()),
                )
                await self._conn.execute(
                    f"DELETE FROM {TABLE} WHERE task_id NOT IN "
                    f"(SELECT task_id FROM {TABLE} ORDER BY saved_at DESC LIMIT ?)",
                    (MAX_PAUSED,),
                )
                await self._conn.commit()
        except Exception as error:  # noqa: BLE001 - kept in memory; a restart loses it
            logger.warning(
                "paused task %s is kept in memory only (%s): after a restart its cost "
                "is a lower bound",
                task_id,
                type(error).__name__,
            )

    async def take(self, task_id: str, new_ledger: Callable[[], CostLedger]) -> Held | None:
        """The paused task's ledger and memo, once; None when none was kept (or the
        record cannot be read). ``new_ledger`` makes the ledger a db record fills."""
        held = self._memory.pop(task_id, None)
        if self._conn is None:
            return held
        row = await self._pop_row(task_id)
        if held is not None or row is None:
            return held
        try:
            if row[0] != "msgpack":  # what checkpoint_serde writes for a plain record
                raise ValueError(f"record type {row[0]!r}")
            record = self._serde.loads_typed(row)
            if record.get("version") != RECORD_VERSION:
                raise ValueError(f"record version {record.get('version')!r}")
            ledger = new_ledger()
            ledger.load_state(record["ledger"])
            return ledger, decode_replay(record["replay"])
        except Exception as error:  # noqa: BLE001 - a record we cannot read is a lost pause
            logger.warning(
                "paused task %s: its record cannot be read (%s)", task_id, type(error).__name__
            )
            return None

    async def drop(self, task_id: str) -> None:
        self._memory.pop(task_id, None)
        if self._conn is not None:
            await self._pop_row(task_id)

    async def _pop_row(self, task_id: str) -> tuple[str, bytes] | None:
        try:
            async with self._lock:
                async with self._conn.execute(
                    f"SELECT type, record FROM {TABLE} WHERE task_id = ?", (task_id,)
                ) as cursor:
                    row = await cursor.fetchone()
                if row is not None:
                    await self._conn.execute(f"DELETE FROM {TABLE} WHERE task_id = ?", (task_id,))
                    await self._conn.commit()
        except Exception as error:  # noqa: BLE001 - the db is a convenience over memory
            logger.warning("paused tasks db unavailable (%s)", type(error).__name__)
            return None
        return None if row is None else (row[0], bytes(row[1]))
