"""``python -m docs_checker.evals``: run eval arms, estimate their spend, settle by hand.

    run --instances <ids|set> --levers <spec> [--mode replay|record-missing]
        [--memory-in PATH] [--memory-out PATH] [--arm LABEL] [--dry-run]
        [--clone PATH] [--evals-dir PATH] [--run-budget-usd X] [--overloaded N]
    spend [--settle RUN_ID --cash USD]

``--mode`` defaults to ``replay`` (free: a miss stops the run). ``record-missing``
needs ``DOCS_CHECKER_EVAL_ANTHROPIC_API_KEY`` and runs under the $20 spend guard.
``--dry-run`` prints each instance's estimated cash for a priced run and makes no
call. ``spend`` prints the spend ledger; ``--settle`` closes a reservation a crashed
run left, at the cash the Anthropic console shows for it.

Exit codes: 0 done, 1 an error, 2 refused (no key, past the cap, another harness
running, or a replay miss).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from docs_checker.evals.harness import (
    EVALS_DIR,
    KEY_ENV,
    RUN_BUDGET_USD,
    HarnessConfig,
    levers_spec,
    load_eval_set,
    run_arm,
    spend_table,
)
from docs_checker.evals.replay import MODES, CassetteMiss
from docs_checker.evals.spend import HarnessBusy, SpendCapExceeded, SpendGuard
from docs_checker.levers import parse_levers

DEFAULT_CLONE = Path(os.environ.get("DOCS_CHECKER_EVAL_CLONE", "~/git/kubernetes")).expanduser()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m docs_checker.evals")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="run one arm over a set of instances")
    run.add_argument("--instances", required=True, help="ids joined by commas, or a set")
    run.add_argument("--levers", required=True, help="all, none, a,b or -a (leave-one-out)")
    run.add_argument("--mode", choices=MODES, default="replay")
    run.add_argument("--memory-in", type=Path)
    run.add_argument("--memory-out", type=Path)
    run.add_argument("--arm", help="the arm's name in the results (default: the levers)")
    run.add_argument("--dry-run", action="store_true", help="estimate spend; no call")
    run.add_argument("--clone", type=Path, default=DEFAULT_CLONE)
    run.add_argument("--evals-dir", type=Path, default=EVALS_DIR)
    run.add_argument("--run-budget-usd", type=float, default=RUN_BUDGET_USD)
    run.add_argument("--overloaded", type=int, default=0, help="synthetic 529s per request")
    spend = commands.add_parser("spend", help="show or settle the eval spend ledger")
    spend.add_argument("--evals-dir", type=Path, default=EVALS_DIR)
    spend.add_argument("--settle", metavar="RUN_ID")
    spend.add_argument("--cash", type=float)
    return parser


def _run(args: argparse.Namespace) -> int:
    eval_set = load_eval_set(args.evals_dir)
    instances = eval_set.select(args.instances)
    levers = parse_levers(args.levers)
    spec = levers_spec(levers)
    guard = SpendGuard(args.evals_dir / ".spend.json")
    if args.dry_run:
        table, _ = spend_table(guard, instances, spec)
        print(table)
        return 0
    key = os.environ.get(KEY_ENV) if args.mode == "record-missing" else None
    if args.mode == "record-missing" and not key:
        print(f"record-missing needs the eval workspace's key in {KEY_ENV}", file=sys.stderr)
        return 2
    if not args.clone.is_dir():
        print(f"no clone of the docs repository at {args.clone}", file=sys.stderr)
        return 2
    cfg = HarnessConfig(
        evals_dir=args.evals_dir,
        clone=args.clone,
        mode=args.mode,
        api_key=key,
        run_budget_usd=args.run_budget_usd,
        overloaded=args.overloaded,
    )

    async def arm():
        try:
            return await run_arm(
                cfg,
                instances,
                levers,
                eval_set.labels,
                arm=args.arm or spec,
                memory_in=args.memory_in,
                memory_out=args.memory_out,
            )
        finally:
            if cfg.live is not None:
                await cfg.live.aclose()

    runs = asyncio.run(arm())
    for run in runs:
        s = run.score
        print(
            f"{run.instance.id}: {run.status}, {run.summary.calls} calls, workload "
            f"${run.summary.workload_cost_usd:.4f}, cash ${run.cash_usd:.4f}, "
            f"TP {s.tp} FP {s.fp} FN {s.fn}, to adjudicate {len(s.to_adjudicate)}"
        )
    return 0


def _spend(args: argparse.Namespace) -> int:
    guard = SpendGuard(args.evals_dir / ".spend.json")
    if args.settle:
        if args.cash is None:
            print("--settle needs --cash", file=sys.stderr)
            return 1
        with guard.lock():
            guard.settle(args.settle, cash_usd=args.cash, mode="settled-by-hand")
    print(
        f"cap ${guard.cap_usd:.2f}: settled ${guard.settled_usd:.4f}, reserved "
        f"${guard.reserved_usd:.4f}, headroom ${guard.headroom_usd:.4f}"
    )
    for run_id, held in sorted(guard.open_reservations().items()):
        print(f"open: {run_id} ${held['amount_usd']:.4f} ({held['instance']}, {held['levers']})")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return _run(args) if args.command == "run" else _spend(args)
    except (SpendCapExceeded, HarnessBusy, CassetteMiss) as error:
        print(f"refused: {error}", file=sys.stderr)
        return 2
    except (FileNotFoundError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
