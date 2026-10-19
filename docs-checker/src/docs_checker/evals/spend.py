"""The eval budget: $20 of cash, across every eval run ever made (spec §8).

``SpendGuard`` keeps its ledger at one fixed per-user path,
``~/.cache/docs-checker/spend.json`` (ruling E2), whatever checkout or ``--evals-dir``
a harness runs from, so a fresh clone or worktree does not start again at $0. The
env value ``DOCS_CHECKER_SPEND_LEDGER`` moves it; it exists for tests. The eval
workspace's own Anthropic spend limit ($25) stays the hard backstop.

- ``reserve_run`` holds what a run *can* spend before it starts: its run budget, or
  the cap's headroom when that is smaller, which then is the run's budget. A run is
  refused only when the headroom is below its estimate (C#1);
- ``settle`` swaps the reservation for the run's actual **cash** cost (what reached
  the API; a replayed call costs nothing);
- a run that crashes never settles, so its whole reservation stays and keeps
  counting: what it spent is unknown until a person checks the Anthropic console
  and settles it by hand (``python -m docs_checker.evals spend --settle``). The
  harness settles a crashed run to $0 itself only when it sent no request;
- ``record`` notes a run that cost no cash (replay), so its workload cost can
  estimate the next priced run of the same instance and levers.

Only one harness runs at a time: ``lock`` takes an exclusive ``flock`` on
``spend.lock`` next to the ledger (the OS drops it if the process dies), and
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
LEDGER_ENV = "DOCS_CHECKER_SPEND_LEDGER"
DEFAULT_LEDGER = "~/.cache/docs-checker/spend.json"
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


class SpendLedgerUnwritable(Exception):
    """The spend ledger cannot be written, so a run could not be accounted. Nothing ran."""


def ledger_path() -> Path:
    """The per-user spend ledger: ``DOCS_CHECKER_SPEND_LEDGER`` (tests), else
    ``~/.cache/docs-checker/spend.json``."""
    return Path(os.environ.get(LEDGER_ENV) or DEFAULT_LEDGER).expanduser()


@dataclass(frozen=True)
class SpendReservation:
    id: str
    amount_usd: float


def _empty() -> dict[str, Any]:
    return {"version": _VERSION, "open": {}, "runs": []}


def _committed(data: dict[str, Any]) -> float:
    """Settled cash plus open reservations, unrounded (the cap check and the headroom
    must agree to the last digit, or a reservation of exactly the headroom is refused)."""
    settled = sum(r["cash_usd"] for r in data["runs"])
    return settled + sum(r["amount_usd"] for r in data["open"].values())


class SpendGuard:
    def __init__(self, path: Path | str | None = None, cap_usd: float = CAP_USD):
        self.path = Path(path) if path is not None else ledger_path()
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

    def ensure_writable(self) -> None:
        """Raise ``SpendLedgerUnwritable`` unless the ledger and its lock can be written."""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise SpendLedgerUnwritable(f"the spend ledger {self.path}: {error}") from error
        targets = [self.path.parent, *(p for p in (self.path, self.lock_path) if p.exists())]
        unwritable = [str(p) for p in targets if not os.access(p, os.W_OK)]
        if unwritable:
            raise SpendLedgerUnwritable(
                f"the spend ledger {self.path} is not writable: {', '.join(unwritable)}"
            )

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
        return max(self.cap_usd - _committed(self._read()), 0.0)

    def open_reservations(self) -> dict[str, dict[str, Any]]:
        return dict(self._read()["open"])

    # --- runs -----------------------------------------------------------------------------

    def reserve_run(
        self, run_id: str, *, estimate_usd: float, budget_usd: float, instance: str, levers: str
    ) -> SpendReservation:
        """Reserve all a run may spend: ``budget_usd``, or the cap's headroom when that is
        smaller (the reservation's amount is then the run's budget). Refused when the
        headroom is below ``estimate_usd`` or nothing is left."""
        if not self._locked:
            raise RuntimeError("reserve only under the harness lock")
        headroom = self.headroom_usd
        if headroom + _EPSILON_USD < estimate_usd or headroom <= _EPSILON_USD:
            raise SpendCapExceeded(
                f"run {run_id} estimates ${estimate_usd:.4f} but only ${headroom:.4f} of the "
                f"${self.cap_usd:.2f} eval cap is left"
            )
        amount = min(budget_usd, headroom)
        return self.reserve(
            run_id, amount, instance=instance, levers=levers, estimate_usd=estimate_usd
        )

    def reserve(
        self,
        run_id: str,
        amount_usd: float,
        *,
        instance: str,
        levers: str,
        estimate_usd: float | None = None,
    ) -> SpendReservation:
        if not self._locked:
            raise RuntimeError("reserve only under the harness lock")
        if amount_usd < 0:
            raise ValueError(f"cannot reserve a negative amount: {amount_usd}")
        data = self._read()
        if run_id in data["open"]:
            raise ValueError(f"run {run_id} already holds a reservation")
        committed = _committed(data)
        if committed + amount_usd > self.cap_usd + _EPSILON_USD:
            raise SpendCapExceeded(
                f"run {run_id} estimates ${amount_usd:.4f} on top of ${committed:.4f} "
                f"settled or reserved: past the ${self.cap_usd:.2f} eval cap"
            )
        data["open"][run_id] = {
            "amount_usd": amount_usd,
            "estimate_usd": amount_usd if estimate_usd is None else estimate_usd,
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
                "estimate_usd": held.get("estimate_usd", held["amount_usd"]),
                "reserved_usd": held["amount_usd"],
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
                "reserved_usd": 0.0,
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
