#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6", "pathspec>=0.12,<1"]
# ///
"""verify: reject a report.json that is uncited, overrides a rule check, or leaks a secret."""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from readiness_model import PILLARS, Facts, read_json  # noqa: E402

JUDGMENT_STATUSES = ("pass", "partial", "fail", "unknown")
MAX_FIXES = 5
SECRET_RE = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----|ghp_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|xox[bp]-")


def _empty(v) -> bool:
    return v is None or v == [] or v == {}


def _leaks(text, secrets: list[str]) -> bool:
    if not isinstance(text, str):
        return False
    return bool(SECRET_RE.search(text)) or any(s and s in text for s in secrets)


def verify(facts_doc: dict, results: dict, report: dict, canaries: list[str] = ()) -> list[str]:
    out: list[str] = []
    facts = Facts(facts_doc)
    checks = results.get("checks", [])
    judgment_ids = [c["id"] for c in checks if c.get("kind") == "judgment"]
    final = {c["id"]: c.get("status") for c in checks if c.get("kind") == "rule"}
    secrets = [s for s in (os.environ.get("BACKSTAGE_TOKEN"), *canaries) if s]

    judgments = report.get("judgments")
    if not isinstance(judgments, dict):
        judgments = {}
        out.append("judgments: missing or not an object")
    for jid in judgment_ids:
        if jid not in judgments:
            out.append(f"judgments.{jid}: missing")
    for jid, j in judgments.items():
        if jid not in judgment_ids:
            out.append(f"judgments.{jid}: not a judgment check (rule statuses come from evaluate.py)")
            continue
        if not isinstance(j, dict):
            out.append(f"judgments.{jid}: not an object")
            continue
        status = j.get("status")
        if status not in JUDGMENT_STATUSES:
            out.append(f"judgments.{jid}: status {status!r} is not one of {', '.join(JUDGMENT_STATUSES)}")
            continue
        final[jid] = status
        cited = j.get("facts") or []
        if status != "unknown":
            if not cited:
                out.append(f"judgments.{jid}: cites no facts")
            for fid in cited:
                if facts.get(fid) is None:
                    out.append(f"judgments.{jid}: cites unknown fact {fid}")
            if status == "pass" and cited and all(
                    facts.get(f) is None or _empty(facts.get(f)["value"]) for f in cited):
                out.append(f"judgments.{jid}: pass cites only empty facts")
        if _leaks(j.get("reason"), secrets):
            out.append(f"judgments.{jid}.reason: contains a secret")

    notes = report.get("pillar_notes") or {}
    for pillar, note in notes.items():
        if pillar not in PILLARS:
            out.append(f"pillar_notes.{pillar}: not a pillar")
        if _leaks(note, secrets):
            out.append(f"pillar_notes.{pillar}: contains a secret")

    fixes = report.get("fixes") or []
    if len(fixes) > MAX_FIXES:
        out.append(f"fixes: more than {MAX_FIXES} ({len(fixes)})")
    for i, fx in enumerate(fixes):
        if not isinstance(fx, dict):
            out.append(f"fixes[{i}]: not an object")
            continue
        if not any(final.get(c) in ("fail", "partial") for c in fx.get("checks") or []):
            out.append(f"fixes[{i}]: names no failing or partial check")
        for field in ("text", "where"):
            if _leaks(fx.get(field), secrets):
                out.append(f"fixes[{i}].{field}: contains a secret")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="verify.py", description="Verify report.json against facts and results")
    ap.add_argument("--out", required=True, help="directory with facts.json, results.json and report.json")
    args = ap.parse_args(argv)
    out = Path(args.out).expanduser()
    try:
        docs = [read_json(out / n) for n in ("facts.json", "results.json", "report.json")]
    except (OSError, ValueError) as err:
        print(f"verify: cannot read inputs in {out} ({type(err).__name__})")
        return 1
    problems = verify(*docs)
    print("\n".join(problems) if problems else "ok")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
