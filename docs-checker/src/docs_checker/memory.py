"""Memory without a database (cost lever 3).

The weekly trigger holds a JSON snapshot and passes it in with each run. The agent
loads it into this LangGraph store, skips unchanged docs and reuses past decisions,
then returns the FULL updated snapshot (C#21), never a delta.

Trust model: the trigger is the only caller that sends memory, and it is the one that
receives the report. Memory is honoured only in ``scheduled`` mode (C#22): in any other
mode ``from_snapshot`` returns an empty store.

Namespaces: ``("doc",)`` keyed by doc path, ``("decision",)`` keyed by
``Claim.semantic_key``. The run counter lives in ``("meta",)``.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from langgraph.store.memory import InMemoryStore

from docs_checker.frontmatter import DocMeta
from docs_checker.repo import RepoReader
from docs_checker.state import Decision, Finding

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1
MAX_SNAPSHOT_BYTES = 512 * 1024
KEEP_RUNS = 4
CHECKER_KEY = "__checker__"  # reserved fingerprint key; no repo path starts with it
UNKNOWN = "!unknown"  # a commit we could not resolve: never equal to anything

MAX_INPUT_BYTES = 2 * MAX_SNAPSHOT_BYTES
MAX_COUNTER = 10**6
STATUSES = frozenset({"checked", "unchanged", "incomplete", "skipped-budget", "failed"})

_DOC = ("doc",)
_DECISION = ("decision",)
_META = ("meta",)


class SnapshotStore(InMemoryStore):
    """An in-memory store that loads from and dumps to a JSON-able snapshot.

    ``run`` is this run's number: one more than the snapshot it was loaded from.
    """

    run: int = 1

    @classmethod
    def from_snapshot(cls, data: Any, *, mode: str) -> SnapshotStore:
        store = cls()
        if mode != "scheduled":
            return store  # interactive callers get no memory (C#22)
        if data is None:
            return store
        try:
            docs, decisions, run = cls._validate(data)
        except (KeyError, TypeError, ValueError, RecursionError) as exc:
            log.warning("ignoring memory snapshot: %s", exc)
            return store
        for path, entry in docs.items():
            store.put(_DOC, path, entry)
        for key, entry in decisions.items():
            store.put(_DECISION, key, entry)
        store.run = run + 1
        return store

    @staticmethod
    def _counter(value: Any, what: str) -> int:
        if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= MAX_COUNTER:
            raise ValueError(f"bad {what}")
        return value

    @classmethod
    def _validate(cls, data: Any) -> tuple[dict, dict, int]:
        """Raises on anything wrong: one bad entry drops the WHOLE snapshot (a partly
        trusted snapshot is not worth the risk). Oversize input is rejected first."""
        if len(json.dumps(data, separators=(",", ":")).encode()) > MAX_INPUT_BYTES:
            raise ValueError("snapshot too large")
        if not isinstance(data, dict) or data.get("version") != SCHEMA_VERSION:
            raise ValueError("unsupported snapshot version")
        run = cls._counter(data["run"], "run counter")
        docs, decisions = data["docs"], data["decisions"]
        if not isinstance(docs, dict) or not isinstance(decisions, dict):
            raise TypeError("docs and decisions must be mappings")
        for entry in docs.values():
            if not isinstance(entry, dict):
                raise TypeError("bad doc entry")
            fp = entry.get("fingerprint")
            if not isinstance(fp, dict) or not all(
                isinstance(k, str) and isinstance(v, str) for k, v in fp.items()
            ):
                raise TypeError("bad fingerprint")
            if entry.get("status") not in STATUSES:
                raise ValueError("bad doc status")
            if not isinstance(entry.get("checker"), str):
                raise TypeError("bad checker")
            cls._counter(entry.get("run"), "doc run")
            findings = entry.get("open_findings")
            if not isinstance(findings, list) or not all(isinstance(f, dict) for f in findings):
                raise TypeError("bad open_findings")
            for f in findings:
                Finding.model_validate(f)
        for entry in decisions.values():
            if not isinstance(entry, dict):
                raise TypeError("bad decision entry")
            cls._counter(entry.get("last_run"), "last_run")
            Decision.model_validate(entry["decision"])
        return docs, decisions, run

    # -- docs ---------------------------------------------------------------
    def doc_paths(self) -> set[str]:
        """Every doc the store holds an entry for."""
        return set(self._all(_DOC))

    def get_doc(self, path: str) -> dict | None:
        item = self.get(_DOC, path)
        return item.value if item else None

    def put_doc(
        self,
        path: str,
        *,
        status: str,
        fingerprint: dict[str, str],
        checker: str,
        open_findings: list[dict],
    ) -> None:
        self.put(
            _DOC,
            path,
            {
                "status": status,
                "fingerprint": fingerprint,
                "checker": checker,
                "open_findings": open_findings,
                "run": self.run,
            },
        )

    # -- decisions ----------------------------------------------------------
    def get_decision(self, key: str) -> Decision | None:
        """A past decision; reading it marks it used in this run."""
        item = self.get(_DECISION, key)
        if item is None:
            return None
        self.put(_DECISION, key, {**item.value, "last_run": self.run})
        return Decision.model_validate(item.value["decision"])

    def put_decision(self, key: str, decision: Decision) -> None:
        self.put(_DECISION, key, {"decision": decision.model_dump(), "last_run": self.run})

    # -- snapshot -----------------------------------------------------------
    def _all(self, ns: tuple[str, ...]) -> dict[str, dict]:
        return {i.key: i.value for i in self.search(ns, limit=1_000_000)}

    def snapshot(self, in_scope: set[str]) -> dict:
        """The FULL snapshot, pruned: out-of-scope docs go; decisions are pruned first
        (unused for ``KEEP_RUNS`` runs, then oldest first until the 512 KiB soft
        target); if still above ``MAX_INPUT_BYTES`` (1 MiB, the hard cap, which the
        read side also enforces) whole in-scope doc entries are dropped largest-first
        until it fits, and those docs are re-checked next run."""
        docs = {p: e for p, e in self._all(_DOC).items() if p in in_scope}
        decisions = {
            k: e for k, e in self._all(_DECISION).items() if e["last_run"] > self.run - KEEP_RUNS
        }
        snap = {
            "version": SCHEMA_VERSION,
            "run": self.run,
            "docs": docs,
            "decisions": decisions,
        }

        def size() -> int:
            return len(json.dumps(snap, separators=(",", ":")).encode())

        if size() > MAX_SNAPSHOT_BYTES:
            for key in sorted(decisions, key=lambda k: (decisions[k]["last_run"], k)):
                del decisions[key]
                if size() <= MAX_SNAPSHOT_BYTES:
                    break
        if size() > MAX_SNAPSHOT_BYTES:
            log.warning(
                "memory snapshot is %d bytes with no decisions left, above the soft target %d",
                size(),
                MAX_SNAPSHOT_BYTES,
            )
        # Hard cap: the read side rejects input over MAX_INPUT_BYTES, so never write more.
        # Drop whole doc entries, largest first; those docs are re-checked next run.
        dropped = 0
        while size() > MAX_INPUT_BYTES and docs:
            biggest = max(docs, key=lambda p: (len(json.dumps(docs[p])), p))
            del docs[biggest]
            dropped += 1
        if dropped:
            log.warning(
                "memory snapshot over the hard cap %d: dropped %d doc entries (re-checked next run)",
                MAX_INPUT_BYTES,
                dropped,
            )
        return snap


async def fingerprint(
    meta: DocMeta, reader: RepoReader, evidence_paths: list[str], checker_version: str
) -> dict[str, str]:
    """{path: latest commit} for the doc, every path/dir source and every evidence path
    used, plus the checker version. A path whose commit is unknown (None: no commit, or
    a transient failure) gets ``UNKNOWN``, so the doc is never skipped on it."""
    paths = [meta.path]
    paths += [s.value for s in meta.sources if s.kind in ("path", "dir")]
    paths += evidence_paths
    result: dict[str, str] = {}
    for path in dict.fromkeys(paths):
        result[path] = await reader.latest_commit(path) or UNKNOWN
    result[CHECKER_KEY] = checker_version
    return result


def skip_unchanged(meta: DocMeta, stored: dict | None, current: dict[str, str]) -> bool:
    """True only when the stored outcome was ``checked`` and every fingerprint entry,
    the checker version included, matches. Incomplete, failed and skipped-budget docs
    are always re-checked (C#20), as is any doc with an unresolved commit."""
    if not stored or stored.get("status") != "checked":
        return False
    old = stored.get("fingerprint")
    if not isinstance(old, dict) or old != current:
        return False
    if old.get(CHECKER_KEY) != stored.get("checker") or meta.path not in old:
        return False
    return UNKNOWN not in old.values()
