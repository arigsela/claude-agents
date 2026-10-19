"""The eval harness: run the audit graph on labelled doc instances and record what it cost.

Each instance is one doc at one commit of a local clone of the docs repository,
with optional overlays (planted mutations, an extra doc), served by the local
fake of the agent-docs server (``localrepo.py``). A run is the production graph
(``build_graph``) on an ``InMemorySaver``, the production fix gate and the real
tool belt, in scheduled mode (so memory is honoured), with the instance's doc as
the scope; nothing goes through gRPC.

Model calls go through ``ReplayTransport``: in ``replay`` mode every response
comes from the cassettes (``evals/cassettes/``) and a miss stops the run; in
``record-missing`` mode a miss goes to the API with the key from
``DOCS_CHECKER_EVAL_ANTHROPIC_API_KEY`` (never ``ANTHROPIC_API_KEY``) and is
recorded. Priced runs go through ``SpendGuard``: each reserves its estimate first
and settles to its cash cost after; replay runs cost no cash.

Each run is scored against the instance's labels (``score.py``) and appended to
``evals/results.jsonl``; ``evals/results.md`` shows every record as a table
between its markers. With ``memory_out`` a run's memory snapshot is written per
instance, and ``memory_in`` reads it back, so the short-circuit lever's second
run skips what the first one checked (C#30).
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import uuid
from collections import Counter
from collections.abc import Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import httpx2
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import BaseModel, ConfigDict, Field

from docs_checker.config import load_settings
from docs_checker.evals.localrepo import SERVER, local_repo_tools
from docs_checker.evals.replay import CassetteMiss, Mode, Offline, ReplayTransport
from docs_checker.evals.score import LabelledLine, Score, score
from docs_checker.evals.spend import SpendGuard
from docs_checker.executor import memory_snapshot
from docs_checker.gate import AllowGate, build_fix_gate
from docs_checker.graph import RunDeps, build_graph, checkpoint_serde, run_config
from docs_checker.ledger import RATE_CARDS, Budget, CostLedger, Reservation, RunSummary
from docs_checker.levers import Levers
from docs_checker.llm import RESPONSE_RECORDER, request_id_hook
from docs_checker.memory import SnapshotStore
from docs_checker.models import AnthropicModels
from docs_checker.redact import redact_obj
from docs_checker.request import parse_request
from docs_checker.state import Finding
from docs_checker.tools import READ_ONLY_TOOLS, ToolBelt

KEY_ENV = "DOCS_CHECKER_EVAL_ANTHROPIC_API_KEY"
ANTHROPIC_URL = "https://api.anthropic.com"
# docs-checker/evals in a checkout (src/docs_checker/evals/harness.py -> docs-checker/).
EVALS_DIR = Path(__file__).resolve().parents[3] / "evals"
# Per doc instance, so a baseline run (every lever off) is never cut short (spec §6).
RUN_BUDGET_USD = 2.0
_NO_KEY = "replay-only-no-key"  # replay never sends a request, so it needs no key
_BEGIN = "<!-- results:begin (written by python -m docs_checker.evals; edit outside) -->"
_END = "<!-- results:end -->"


class Instance(BaseModel):
    """One doc at one commit, with overlays planted there (Task 17 curates them)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    doc: str
    commit: str
    head: bool = False
    overlays: dict[str, str | None] = Field(default_factory=dict)
    split: Literal["dev", "holdout"] = "dev"
    purpose: str = ""


@dataclass(frozen=True)
class EvalSet:
    instances: dict[str, Instance]
    sets: dict[str, list[str]]
    labels: list[LabelledLine]

    def select(self, spec: str) -> list[Instance]:
        """``all``, a split (``dev``, ``holdout``), a named set, or ids joined by commas."""
        spec = spec.strip()
        if spec == "all":
            return list(self.instances.values())
        if spec in ("dev", "holdout"):
            return [i for i in self.instances.values() if i.split == spec]
        ids = self.sets.get(spec) or [part.strip() for part in spec.split(",") if part.strip()]
        unknown = [i for i in ids if i not in self.instances]
        if unknown or not ids:
            raise ValueError(f"no such instance or set: {', '.join(unknown) or spec!r}")
        return [self.instances[i] for i in ids]


def load_eval_set(evals_dir: Path) -> EvalSet:
    """``instances.json`` ({"instances": [...], "sets": {name: [id, ...]}}) and every
    ``labels/*.json`` (each a list of labelled lines)."""
    path = evals_dir / "instances.json"
    if not path.exists():
        raise FileNotFoundError(f"no eval set at {path} (Task 17 curates it)")
    data = json.loads(path.read_text())
    instances: dict[str, Instance] = {}
    for item in data["instances"]:
        instance = Instance.model_validate(item)
        if instance.id in instances:
            raise ValueError(f"instance {instance.id} is defined twice")
        instances[instance.id] = instance
    labels = [
        LabelledLine.model_validate(item)
        for file in sorted((evals_dir / "labels").glob("*.json"))
        for item in json.loads(file.read_text())
    ]
    return EvalSet(instances, dict(data.get("sets") or {}), labels)


def levers_spec(levers: Levers) -> str:
    """One spelling per lever set: ``all``, ``none``, or the levers on, in order."""
    on = [name for name in Levers.names() if getattr(levers, name)]
    if len(on) == len(Levers.names()):
        return "all"
    return ",".join(on) or "none"


class MeteredBudget(Budget):
    """The run budget, which also adds up the reservations it kept for attempts with
    unknown cost that were not replayed: an upper bound on their cash, since a live
    call that failed in flight may still have been billed."""

    def __init__(self, limit_usd: float | None):
        super().__init__(limit_usd)
        self.unknown_live_usd = 0.0

    def settle(self, reservation: Reservation, actual_usd: float | None) -> None:
        super().settle(reservation, actual_usd)
        if actual_usd is None and not (RESPONSE_RECORDER.get() or {}).get("replayed"):
            self.unknown_live_usd += reservation.amount_usd


@dataclass
class HarnessConfig:
    evals_dir: Path
    clone: Path
    mode: Mode
    api_key: str | None = None  # the eval workspace's key; record-missing only
    live: httpx2.AsyncBaseTransport | None = None  # the API (record-missing); tests mock it
    run_budget_usd: float = RUN_BUDGET_USD
    overloaded: int = 0  # synthetic 529s before each key's attempts (the retry row)
    cassette_dir: Path | None = None

    def __post_init__(self) -> None:
        if self.mode == "record-missing":
            if not self.api_key:
                raise ValueError(f"record-missing needs the eval key in {KEY_ENV}")
            if self.live is None:
                self.live = httpx2.AsyncHTTPTransport()

    @property
    def cassettes(self) -> Path:
        return self.cassette_dir or self.evals_dir / "cassettes"


@dataclass
class InstanceRun:
    instance: Instance
    levers: str
    status: str  # the doc's: checked, unchanged, incomplete, skipped-budget or failed
    outcome: str  # the run's
    summary: RunSummary
    cash_usd: float  # the summary's cash plus what unknown live calls kept reserved
    calls_by_node: dict[str, int]
    live_calls: int
    findings: list[Finding]
    score: Score
    memory: dict = field(default_factory=dict)


async def _until_miss(run: Any, transport: ReplayTransport, timeout_s: float) -> dict:
    """The graph's result, or ``CassetteMiss`` as soon as replay misses (the SDK would
    otherwise retry the miss as a connection error, and the doc would just fail)."""
    task = asyncio.ensure_future(run)
    missed = asyncio.ensure_future(transport.missed.wait())
    try:
        async with asyncio.timeout(timeout_s):
            await asyncio.wait({task, missed}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        missed.cancel()
        if not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
    if transport.misses:
        first = transport.misses[0]
        raise CassetteMiss(first.key, first.attempt)
    return task.result()


def replay_transport(cfg: HarnessConfig) -> ReplayTransport:
    """One run's transport: the API behind it only in record-missing mode."""
    inner = cfg.live if cfg.mode == "record-missing" and cfg.live is not None else Offline()
    return ReplayTransport(inner, cfg.cassettes, cfg.mode, overloaded=cfg.overloaded)


async def run_instance(
    cfg: HarnessConfig,
    instance: Instance,
    levers: Levers,
    labels: Sequence[LabelledLine],
    *,
    memory: dict | None = None,
    budget_usd: float | None = None,
    transport: ReplayTransport | None = None,
) -> InstanceRun:
    """One run of the graph on ``instance``, scored against its labels."""
    spec = levers_spec(levers)
    settings = load_settings({"DOCS_CHECKER_LEVERS": spec})
    transport = transport or replay_transport(cfg)
    models = AnthropicModels(
        settings.node_models,
        levers,
        http_timeout_s=settings.http_timeout_s,
        transport=transport,
        on_response=request_id_hook,
        api_key=cfg.api_key or _NO_KEY,
        base_url=ANTHROPIC_URL,
    )
    budget = MeteredBudget(cfg.run_budget_usd if budget_usd is None else budget_usd)
    ledger = CostLedger(
        instance.id,  # every finding carries it as its instance (C#31)
        "eval",
        rate_card=RATE_CARDS[settings.rate_card_version],
        default_ttl=settings.cache_ttl,
        emit=False,
        budget=budget,
    )
    replay: dict[str, Any] = {}
    belt = ToolBelt(
        local_repo_tools(cfg.clone, instance.commit, overlays=instance.overlays),
        AllowGate(),
        bindings={SERVER: sorted(READ_ONLY_TOOLS)},
        settings=settings,
        run_state=replay,
    )
    request = parse_request(
        None, {"scope": [instance.doc], "mode": "scheduled", "memory": memory}, max_paths=1
    )
    deps = RunDeps(
        models=models,
        belt=belt,
        ledger=ledger,
        settings=settings,
        replay=replay,
        fix_gate=build_fix_gate(settings),
        store=SnapshotStore.from_snapshot(memory, mode="scheduled"),
    )
    graph = build_graph(checkpointer=InMemorySaver(serde=checkpoint_serde()))
    config = run_config(f"eval-{instance.id}", settings, levers)
    result = await _until_miss(
        graph.ainvoke({"text": f"check {instance.doc}", "request": request}, config, context=deps),
        transport,
        settings.run_timeout_s,
    )
    outcomes = result.get("outcomes") or {}
    doc = outcomes.get(instance.doc)
    summary = ledger.summary(result.get("outcome") or "unverified")
    cash = summary.cash_cost_usd + budget.unknown_live_usd + summary.reserved_unsettled_usd
    findings = [f for outcome in outcomes.values() for f in outcome.findings]
    mine = [label for label in labels if label.instance == instance.id]
    return InstanceRun(
        instance=instance,
        levers=spec,
        status=doc.status if doc is not None else str(result.get("outcome") or "failed"),
        outcome=str(result.get("outcome") or "unverified"),
        summary=summary,
        cash_usd=round(cash, 8),
        calls_by_node=dict(Counter(entry.node for entry in ledger.entries)),
        live_calls=transport.live,
        findings=findings,
        score=score(
            findings, mine, workload_usd=summary.workload_cost_usd, cash_usd=round(cash, 8)
        ),
        memory=memory_snapshot(deps.store, result),
    )


# --- arms: several instances, the spend guard, memory files and results -------------------


def _read_memory(path: Path | None) -> dict[str, dict]:
    if path is None:
        return {}
    data = json.loads(path.read_text())
    return dict(data.get("instances") or {})


def _write_memory(path: Path, memories: dict[str, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": 1, "instances": memories}, indent=1, sort_keys=True))


def _now() -> str:
    return dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _compact(finding: Finding) -> dict:
    return {
        "doc": finding.doc,
        "line_start": finding.line_start,
        "line_end": finding.line_end,
        "verdict": finding.verdict,
        "confidence": finding.confidence,
        "needs_look": finding.needs_look,
        "carried": finding.carried,
        "claim": finding.claim.text,
        "replacement": finding.replacement,
    }


def _tokens(summary: RunSummary) -> dict[str, int]:
    return {
        "uncached_input": summary.uncached_input,
        "cache_write": summary.cache_write,
        "cache_read": summary.cache_read,
        "output": summary.output,
    }


def instance_record(run: InstanceRun, *, arm: str, mode: str, memory_in: bool, ts: str) -> dict:
    instance = run.instance
    return {
        "kind": "instance",
        "ts": ts,
        "arm": arm,
        "instance": instance.id,
        "split": instance.split,
        "doc": instance.doc,
        "commit": instance.commit,
        "levers": run.levers,
        "mode": mode,
        "memory_in": memory_in,
        "status": run.status,
        "outcome": run.outcome,
        "calls": run.summary.calls,
        "calls_by_node": run.calls_by_node,
        "live_calls": run.live_calls,
        **_tokens(run.summary),
        "workload_usd": run.summary.workload_cost_usd,
        "cash_usd": run.cash_usd,
        "complete": run.summary.complete,
        "score": run.score.to_dict(),
        "findings": [_compact(f) for f in run.findings],
    }


def arm_record(
    runs: Sequence[InstanceRun],
    labels: Sequence[LabelledLine],
    *,
    arm: str,
    mode: str,
    memory_in: bool,
    ts: str,
) -> dict:
    """The arm over all its instances: summed costs, one score (scoped by instance)."""
    ids = {run.instance.id for run in runs}
    workload = sum(run.summary.workload_cost_usd for run in runs)
    cash = sum(run.cash_usd for run in runs)
    total = score(
        [f for run in runs for f in run.findings],
        [label for label in labels if label.instance in ids],
        workload_usd=workload,
        cash_usd=cash,
    )
    calls: Counter[str] = Counter()
    for run in runs:
        calls.update(run.calls_by_node)
    return {
        "kind": "arm",
        "ts": ts,
        "arm": arm,
        "instances": [run.instance.id for run in runs],
        "levers": runs[0].levers if runs else "",
        "mode": mode,
        "memory_in": memory_in,
        "calls": sum(run.summary.calls for run in runs),
        "calls_by_node": dict(calls),
        "live_calls": sum(run.live_calls for run in runs),
        **{k: sum(_tokens(run.summary)[k] for run in runs) for k in _tokens(runs[0].summary)},
        "workload_usd": round(workload, 8),
        "cash_usd": round(cash, 8),
        "score": total.to_dict(),
    }


def _money(value: float | None) -> str:
    return "–" if value is None else f"{value:.4f}"


def _ratio(value: float | None) -> str:
    return "–" if value is None else f"{value:.2f}"


def _cell(text: object) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def _row(record: dict) -> str:
    s = record["score"]
    where = (
        f"**all ({len(record['instances'])})**" if record["kind"] == "arm" else record["instance"]
    )
    cells = [
        record["ts"],
        record["arm"],
        where,
        record["levers"],
        record["mode"],
        "in" if record["memory_in"] else "–",
        record.get("status", ""),
        record["calls"],
        f"{record['cache_read']}/{record['cache_write']}",
        _money(record["workload_usd"]),
        _money(record["cash_usd"]),
        s["tp"],
        s["fp"],
        s["fn"],
        len(s["to_adjudicate"]),
        _ratio(s["precision"]),
        _ratio(s["recall"]),
        _money(s["cost_per_verified"]),
    ]
    return "| " + " | ".join(_cell(c) for c in cells) + " |"


_HEADER = (
    "| When (UTC) | Arm | Instance | Levers | Mode | Memory | Status | Calls "
    "| Cache read/write tokens | Workload $ | Cash $ | TP | FP | FN | To adjudicate "
    "| Precision | Recall | Workload $ per TP |\n"
    "|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"
)


def append_results(evals_dir: Path, records: Sequence[dict]) -> None:
    """Append to ``results.jsonl`` and redraw the table in ``results.md`` from it,
    leaving anything outside the table's markers as it is."""
    evals_dir.mkdir(parents=True, exist_ok=True)
    jsonl = evals_dir / "results.jsonl"
    with jsonl.open("a") as out:
        for record in records:
            out.write(json.dumps(redact_obj(record), sort_keys=True, ensure_ascii=False) + "\n")
    rows = [_row(json.loads(line)) for line in jsonl.read_text().splitlines() if line.strip()]
    block = f"{_BEGIN}\n{_HEADER}\n" + "\n".join(rows) + f"\n{_END}"
    md = evals_dir / "results.md"
    text = md.read_text() if md.exists() else "# docs-checker eval results\n\n"
    if _BEGIN in text and _END in text:
        head, _, rest = text.partition(_BEGIN)
        _, _, tail = rest.partition(_END)
        text = head + block + tail
    else:
        text = text.rstrip("\n") + "\n\n" + block + "\n"
    md.write_text(text)


async def run_arm(
    cfg: HarnessConfig,
    instances: Sequence[Instance],
    levers: Levers,
    labels: Sequence[LabelledLine],
    *,
    arm: str,
    memory_in: Path | None = None,
    memory_out: Path | None = None,
) -> list[InstanceRun]:
    """Run ``instances`` one after another under the harness lock. A priced run first
    reserves all it may spend (its run budget, or the cap's headroom when smaller,
    which then is its budget; refused when the headroom is below its estimate) and
    settles to its cash after. A crash leaves the whole reservation, unless the run
    sent no request at all: then it settles to $0."""
    spec = levers_spec(levers)
    memories = _read_memory(memory_in)
    guard = SpendGuard()  # per user, not per checkout or evals dir (ruling E2)
    guard.ensure_writable()  # before any call: an unaccountable run never starts
    runs: list[InstanceRun] = []
    used_memory = False
    with guard.lock():
        for instance in instances:
            memory = memories.get(instance.id)
            used_memory = used_memory or memory is not None
            budget = cfg.run_budget_usd
            reservation = None
            transport = replay_transport(cfg)
            if cfg.mode == "record-missing":
                estimate, _ = guard.estimate(instance.id, spec)
                reservation = guard.reserve_run(
                    f"{arm}:{instance.id}:{uuid.uuid4().hex[:8]}",
                    estimate_usd=estimate,
                    budget_usd=budget,
                    instance=instance.id,
                    levers=spec,
                )
                budget = reservation.amount_usd
            try:
                run = await run_instance(
                    cfg,
                    instance,
                    levers,
                    labels,
                    memory=memory,
                    budget_usd=budget,
                    transport=transport,
                )
            except BaseException:
                if reservation is not None and transport.sent == 0:
                    # nothing reached the API, so nothing can have been billed
                    guard.settle(
                        reservation, cash_usd=0.0, mode=cfg.mode, memory_in=memory is not None
                    )
                raise
            workload = run.summary.workload_cost_usd
            if reservation is not None:
                guard.settle(
                    reservation,
                    cash_usd=run.cash_usd,
                    workload_usd=workload,
                    mode=cfg.mode,
                    memory_in=memory is not None,
                )
            else:
                guard.record(
                    instance=instance.id,
                    levers=spec,
                    workload_usd=workload,
                    mode=cfg.mode,
                    memory_in=memory is not None,
                )
            runs.append(run)
            record = instance_record(
                run, arm=arm, mode=cfg.mode, memory_in=memory is not None, ts=_now()
            )
            append_results(cfg.evals_dir, [record])
        if runs:
            summary = arm_record(
                runs, labels, arm=arm, mode=cfg.mode, memory_in=used_memory, ts=_now()
            )
            append_results(cfg.evals_dir, [summary])
    if memory_out is not None:
        _write_memory(memory_out, {**memories, **{run.instance.id: run.memory for run in runs}})
    return runs


def spend_table(guard: SpendGuard, instances: Sequence[Instance], levers: str) -> tuple[str, bool]:
    """The dry run: each instance's estimated cash for a priced run, from earlier runs'
    workload cost or the defaults, against the cap. No call, no lock, no write."""
    lines = [f"Spend estimate for a priced run (no API call): levers {levers}", ""]
    lines.append(f"{'instance':<32} {'split':<8} {'estimate_usd':>12}  source")
    total = 0.0
    for instance in instances:
        estimate, source = guard.estimate(instance.id, levers)
        total += estimate
        lines.append(f"{instance.id:<32} {instance.split:<8} {estimate:>12.4f}  {source}")
    lines.append(f"{'total':<32} {'':<8} {total:>12.4f}")
    headroom = guard.headroom_usd
    fits = total <= headroom + 1e-9
    lines += [
        "",
        f"eval cap ${guard.cap_usd:.2f}: settled ${guard.settled_usd:.4f}, reserved "
        f"${guard.reserved_usd:.4f}, headroom ${headroom:.4f} -> "
        + ("fits" if fits else "does NOT fit"),
    ]
    return "\n".join(lines), fits
