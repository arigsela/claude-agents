#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6", "pathspec>=0.12,<1"]
# ///
"""readiness: facts.json + checks.yaml -> results.json (spec §7.5).

Usage: evaluate.py --out DIR   (reads DIR/facts.json, writes DIR/results.json)

Rule checks are decided from facts by rules.py (RULES, re-exported here). Judgment checks get the candidate fact
ids their `facts` globs match, for the model to decide. Person (ORR) checks get up to three lines from the docs that mention a hint word.
`verdict()` applies the spec's verdict rule to the final statuses.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from readiness_model import Facts, load_checks, read_json, write_json  # noqa: E402
from rules import RULES, Outcome, worst  # noqa: E402

__all__ = ["RULES", "Outcome", "worst", "person_hints", "evaluate", "verdict", "main"]

HINTS_PER_CHECK = 3
HINT_TEXT_CAP = 160


def _d(v) -> dict:
    return v if isinstance(v, dict) else {}


def _l(v) -> list:
    return v if isinstance(v, list) else []


# --- Hints, evaluate, verdict -------------------------------------------------------------------------------

def person_hints(f: Facts, words: list[str]) -> tuple[list[dict], list[str]]:
    """Up to HINTS_PER_CHECK doc lines (from `<source>.text.<path>` facts) that contain a hint word."""
    low = [str(w).lower() for w in words]
    hints: list[dict] = []
    ids: list[str] = []
    for t in f.prefix(""):
        parts = t["id"].split(".", 2)
        if len(parts) < 3 or parts[1] != "text" or not isinstance(_d(t["value"]).get("text"), str):
            continue
        for n, line in enumerate(t["value"]["text"].splitlines(), 1):
            if any(w in line.lower() for w in low):
                hints.append({"evidence": f"{parts[2]}:{n}", "text": line.strip()[:HINT_TEXT_CAP]})
                ids += [] if t["id"] in ids else [t["id"]]
                if len(hints) == HINTS_PER_CHECK:
                    return hints, ids
    return hints, ids


def _run_rule(cid: str, f: Facts) -> Outcome:
    rule = RULES.get(cid)
    if rule is None:
        return "unknown", f"no rule implements {cid}", []
    try:
        return rule(f)
    except Exception as err:  # malformed facts must not stop the report; the check says what happened
        return "unknown", f"rule failed on these facts ({type(err).__name__})", []


def evaluate(facts_doc: dict, checks: list[dict]) -> dict:
    f = Facts(facts_doc)
    out = []
    for c in checks:
        kind, status, reason, ids, hints = c.get("kind"), None, None, [], []
        if kind == "rule":
            status, reason, ids = _run_rule(c["id"], f)
        elif kind == "judgment":
            ids = f.match(_l(c.get("facts")))
        elif kind == "person":
            hints, ids = person_hints(f, _l(c.get("hints")))
        out.append({"id": c["id"], "pillar": c.get("pillar"), "title": c.get("title"), "kind": kind,
                    "blocker": bool(c.get("blocker")), "status": status, "reason": reason, "facts": ids,
                    "hints": hints})
    return {"checks": out}


def verdict(checks: list[dict], statuses: dict[str, str]) -> str:
    """Not ready: a blocker fails. Ready with gaps: any fail or partial, or a blocker unknown (a missing status
    counts as unknown). Ready otherwise. Person checks never count."""
    counted = [(c, statuses.get(c["id"]) or "unknown") for c in checks if c.get("kind") != "person"]
    if any(c.get("blocker") and s == "fail" for c, s in counted):
        return "Not ready"
    if any(s in ("fail", "partial") or (c.get("blocker") and s == "unknown") for c, s in counted):
        return "Ready with gaps"
    return "Ready"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="evaluate.py", description="Decide the rule checks from facts.json")
    ap.add_argument("--out", required=True, help="directory with facts.json; results.json is written there")
    args = ap.parse_args(argv)
    out = Path(args.out).expanduser()
    try:
        facts_doc = read_json(out / "facts.json")
    except (OSError, ValueError) as err:
        print(f"evaluate: cannot read {out / 'facts.json'} ({type(err).__name__})", file=sys.stderr)
        return 1
    write_json(out / "results.json", evaluate(facts_doc, load_checks()))
    print(f"results: {out / 'results.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
