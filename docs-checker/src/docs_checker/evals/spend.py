"""The eval budget: $20 of cash, across every eval run ever made (spec §8).

``SpendGuard`` keeps its ledger in ``evals/.spend.json`` (git-ignored):

- ``reserve`` holds a run's estimate before the run starts and refuses one that
  would take settled spend plus open reservations past the cap (C#1);
- ``settle`` swaps the reservation for the run's actual **cash** cost (what reached
  the API; a replayed call costs nothing);
- a run that crashes never settles, so its reservation stays and keeps counting:
  whether it spent its estimate is unknown until a person checks the Anthropic
  console and settles it by hand (``python -m docs_checker.evals spend --settle``);
- ``record`` notes a run that cost no cash (replay), so its workload cost can
  estimate the next priced run of the same instance and levers.

Only one harness runs at a time: ``lock`` takes an exclusive ``flock`` on
``.spend.lock`` next to the ledger (the OS drops it if the process dies), and
every change to the ledger needs it.
"""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CAP_USD = 20.0
# Estimates before any ledger numbers (controller ruling): per doc, levers all off
# (and any mix, to be safe) or all on.
DEFAULT_BASELINE_USD = 0.60
DEFAULT_ALL_ON_USD = 0.05
_EPSILON_USD = 1e-9
_VERSION = 1


class SpendCapExceeded(Exception):
    """A run's estimate would take eval spend past the cap. Nothing was run."""


class HarnessBusy(Exception):
    """Another harness holds the lock."""


@dataclass(frozen=True)
class SpendReservation:
    id: str
    amount_usd: float


def _empty() -> dict[str, Any]:
    return {"version": _VERSION, "open": {}, "runs": []}


class SpendGuard:
    def __init__(self, path: Path | str, cap_usd: float = CAP_USD):
        self.path = Path(path)
        self.cap_usd = cap_usd
        self.lock_path = self.path.with_name(self.path.name.removesuffix(".json") + ".lock")
        self._locked = False

    # --- the ledger file ----------------------------------------------------------------

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return _empty()
        data = json.loads(self.path.read_text())
        if data.get("version") != _VERSION:
            raise ValueError(f"{self.path}: unsupported spend ledger version")
        return data

    def _write(self, data: dict[str, Any]) -> None:
        if not self._locked:
            raise RuntimeError("the spend ledger changes only under the harness lock")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
        with os.fdopen(fd, "w") as out:
            json.dump(data, out, indent=1, sort_keys=True)
            out.write("\n")
        os.replace(tmp, self.path)

    @contextmanager
    def lock(self) -> Iterator[SpendGuard]:
        """Hold the one-harness lock; ``HarnessBusy`` if another harness has it."""
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.lock_path, os.O_CREAT | os.O_RDWR, 0o644)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise HarnessBusy(f"another eval harness holds {self.lock_path}") from error
            self._locked = True
            try:
                yield self
            finally:
                self._locked = False
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)

    # --- totals ---------------------------------------------------------------------------

    @property
    def settled_usd(self) -> float:
        return round(sum(r["cash_usd"] for r in self._read()["runs"]), 8)

    @property
    def reserved_usd(self) -> float:
        return round(sum(r["amount_usd"] for r in self._read()["open"].values()), 8)

    @property
    def headroom_usd(self) -> float:
        return max(self.cap_usd - self.settled_usd - self.reserved_usd, 0.0)

    def open_reservations(self) -> dict[str, dict[str, Any]]:
        return dict(self._read()["open"])

    # --- runs -----------------------------------------------------------------------------

    def reserve(
        self, run_id: str, amount_usd: float, *, instance: str, levers: str
    ) -> SpendReservation:
        if not self._locked:
            raise RuntimeError("reserve only under the harness lock")
        if amount_usd < 0:
            raise ValueError(f"cannot reserve a negative amount: {amount_usd}")
        data = self._read()
        if run_id in data["open"]:
            raise ValueError(f"run {run_id} already holds a reservation")
        committed = sum(r["cash_usd"] for r in data["runs"]) + sum(
            r["amount_usd"] for r in data["open"].values()
        )
        if committed + amount_usd > self.cap_usd + _EPSILON_USD:
            raise SpendCapExceeded(
                f"run {run_id} estimates ${amount_usd:.4f} on top of ${committed:.4f} "
                f"settled or reserved: past the ${self.cap_usd:.2f} eval cap"
            )
        data["open"][run_id] = {
            "amount_usd": amount_usd,
            "instance": instance,
            "levers": levers,
            "ts": time.time(),
        }
        self._write(data)
        return SpendReservation(run_id, amount_usd)

    def settle(
        self,
        reservation: SpendReservation | str,
        *,
        cash_usd: float,
        workload_usd: float | None = None,
        mode: str = "record-missing",
        memory_in: bool = False,
    ) -> None:
        """Close the reservation with the run's cash cost (and its workload cost, which
        estimates the next run of the same instance and levers)."""
        run_id = reservation if isinstance(reservation, str) else reservation.id
        data = self._read()
        held = data["open"].pop(run_id, None)
        if held is None:
            raise ValueError(f"run {run_id} holds no open reservation")
        data["runs"].append(
            {
                "id": run_id,
                "instance": held["instance"],
                "levers": held["levers"],
                "mode": mode,
                "memory_in": memory_in,
                "estimate_usd": held["amount_usd"],
                "cash_usd": round(cash_usd, 8),
                "workload_usd": None if workload_usd is None else round(workload_usd, 8),
                "ts": time.time(),
            }
        )
        self._write(data)

    def record(
        self,
        *,
        instance: str,
        levers: str,
        workload_usd: float,
        mode: str = "replay",
        memory_in: bool = False,
    ) -> None:
        """A run that paid no cash (replay): its workload cost, for estimates."""
        data = self._read()
        data["runs"].append(
            {
                "id": f"{mode}:{instance}:{time.time():.6f}",
                "instance": instance,
                "levers": levers,
                "mode": mode,
                "memory_in": memory_in,
                "estimate_usd": 0.0,
                "cash_usd": 0.0,
                "workload_usd": round(workload_usd, 8),
                "ts": time.time(),
            }
        )
        self._write(data)

    def estimate(self, instance: str, levers: str) -> tuple[float, str]:
        """What a priced run of ``instance`` with ``levers`` may cost, and where the
        number came from: the largest workload cost of earlier runs without memory
        (``history``), else the per-doc default (``default``)."""
        past = [
            r["workload_usd"]
            for r in self._read()["runs"]
            if r["instance"] == instance
            and r["levers"] == levers
            and not r.get("memory_in")
            and r.get("workload_usd") is not None
        ]
        if past:
            return max(past), "history"
        return (DEFAULT_ALL_ON_USD if levers == "all" else DEFAULT_BASELINE_USD), "default"
