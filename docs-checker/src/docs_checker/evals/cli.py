"""The eval set's curation CLI: ``python -m docs_checker.evals.curate <command>``.

``build`` and ``packets`` come from ``curate.py``; ``merge``, ``adjudicate`` and
``validate`` from ``labels.py``. Exit codes: 0 done, 1 an error or a failed validation,
2 a usage error.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from docs_checker.evals import labels
from docs_checker.evals.curate import DEFAULT_CLONE, Repo, build, write_json, write_packets
from docs_checker.evals.harness import EVALS_DIR, load_instances
from docs_checker.evals.score import LabelledLine


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m docs_checker.evals.curate")
    commands = parser.add_subparsers(dest="command", required=True)

    def with_repo(name: str, summary: str) -> argparse.ArgumentParser:
        command = commands.add_parser(name, help=summary)
        command.add_argument("--evals-dir", type=Path, default=EVALS_DIR)
        command.add_argument("--clone", type=Path, default=DEFAULT_CLONE)
        return command

    with_repo("build", "write instances.json from curate.json, planted/ and canary/")
    with_repo("packets", "write the labelling packets").add_argument(
        "--out", type=Path, required=True
    )
    merge = with_repo("merge", "join two labellers' rows over the served docs")
    merge.add_argument("--a", type=Path, action="append", required=True)
    merge.add_argument("--b", type=Path, action="append", required=True)
    merge.add_argument("--out", type=Path, required=True)
    merge.add_argument("--disagreements", type=Path, required=True)
    adjudicate = commands.add_parser(
        "adjudicate", help="apply decisions to disagreements, and audited overrides"
    )
    adjudicate.add_argument("--labels", type=Path, required=True)
    adjudicate.add_argument("--decisions", type=Path, help="with --disagreements")
    adjudicate.add_argument("--disagreements", type=Path, help="with --decisions")
    adjudicate.add_argument("--overrides", type=Path, help="audited changes and additions")
    with_repo("validate", "check the labels against the served docs")
    return parser


def _merge(args: argparse.Namespace) -> None:
    docs = labels.served_lines(args.evals_dir, args.clone)
    merged = labels.merge(labels.read_rows(args.a), labels.read_rows(args.b), docs)
    write_json(args.out, [label.model_dump() for label in merged.labels])
    write_json(args.disagreements, [d.model_dump() for d in merged.disagreements])
    agreed = len(merged.labels) - len(merged.disagreements)
    blank = sum(d.blank_line for d in merged.disagreements)
    print(
        f"{agreed} agreed lines, {len(merged.disagreements)} disagreements ({blank} of them a "
        f"claim label on a blank line or past the end; in {args.out} as rows awaiting "
        f"adjudication), {len(merged.dropped)} not-a-claim rows on blank lines or past the "
        "end dropped"
    )
    for row in merged.dropped:
        print(f"  dropped: labeller {row['labeller']}, {row['instance']} line {row['line']}")


def _adjudicate(args: argparse.Namespace) -> None:
    decisions = labels.load_rows(args.decisions, labels.Decision) if args.decisions else []
    sides = labels.load_rows(args.disagreements, labels.Disagreement) if args.decisions else []
    overrides = labels.load_rows(args.overrides, labels.Override) if args.overrides else []
    done = labels.adjudicate(
        labels.load_rows(args.labels, LabelledLine), decisions, sides, overrides
    )
    write_json(args.labels, [label.model_dump() for label in done])
    dropped = [f"{d.instance} line {d.line}" for d in decisions if d.drop]
    print(
        f"{args.labels}: {len(done)} lines; {len(decisions) - len(dropped)} decided, "
        f"{len(dropped)} dropped, {len(overrides)} overridden"
    )
    for where in dropped:
        print(f"  dropped: {where}")


def _run(args: argparse.Namespace) -> int:
    if args.command == "build":
        data = build(args.evals_dir, args.clone)
        print(f"wrote {args.evals_dir / 'instances.json'}: {len(data['instances'])} instances")
    elif args.command == "packets":
        instances, _ = load_instances(args.evals_dir)
        entries = write_packets(instances.values(), Repo(args.clone), args.out)
        print(f"wrote {len(entries)} packets and manifest.json to {args.out}")
    elif args.command == "merge":
        _merge(args)
    elif args.command == "adjudicate":
        _adjudicate(args)
    else:
        problems = labels.validate(args.evals_dir, args.clone)
        for problem in problems:
            print(problem)
        if problems:
            return 1
        print("labels valid")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command == "adjudicate":
        if (args.decisions is None) != (args.disagreements is None):
            parser.error("--decisions and --disagreements go together")
        if args.decisions is None and args.overrides is None:
            parser.error("give --decisions with --disagreements, --overrides, or both")
    try:
        return _run(args)
    except (ValueError, FileNotFoundError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
