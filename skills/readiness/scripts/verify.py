#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6", "pathspec>=0.12,<1"]
# ///
"""verify: reject a report.json that is uncited, overrides a rule check, or leaks a secret."""
from __future__ import annotations

import argparse
import json
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


def _leaks(value, secrets: list[str]) -> bool:
    text = value if isinstance(value, str) else json.dumps(value, default=str, sort_keys=True)
    return bool(SECRET_RE.search(text)) or any(s in text for s in secrets)


def _name(value, secrets: list[str]) -> str:
    """An identifier safe to echo in a violation line."""
    return "<redacted>" if _leaks(value, secrets) else str(value)


def verify(facts_doc: dict, results: dict, report: dict, canaries: list[str] = ()) -> list[str]:
    out: list[str] = []
    secrets = [s for s in (os.environ.get("BACKSTAGE_TOKEN"), *canaries) if s]
    if not isinstance(report, dict):
        return ["report: not an object"]
    facts = Facts(facts_doc)
    checks = results.get("checks", [])
    judgment_ids = [c["id"] for c in checks if c.get("kind") == "judgment"]
    final = {c["id"]: c.get("status") for c in checks if c.get("kind") == "rule"}

    def text_field(path: str, value) -> None:
        if not isinstance(value, str):
            out.append(f"{path}: not a string")
        if _leaks(value, secrets):
            out.append(f"{path}: contains a secret")

    def ids(path: str, value) -> list[str]:
        """The string ids of a list field; report what is not a list or not a string id."""
        if not isinstance(value, list):
            out.append(f"{path}: not a list")
            return []
        good = [v for v in value if isinstance(v, str)]
        if len(good) != len(value):
            out.append(f"{path}: not a string id")
        return good

    judgments = report.get("judgments")
    if not isinstance(judgments, dict):
        judgments = {}
        out.append("judgments: missing or not an object")
    for jid in judgment_ids:
        if jid not in judgments:
            out.append(f"judgments.{jid}: missing")
    for jid, j in judgments.items():
        if _leaks(jid, secrets):
            out.append("judgments[<redacted>]: contains a secret")
            continue
        if jid not in judgment_ids:
            out.append(f"judgments.{jid}: not a judgment check (rule statuses come from evaluate.py)")
            continue
        if not isinstance(j, dict):
            out.append(f"judgments.{jid}: not an object")
            continue
        status = j.get("status")
        if status not in JUDGMENT_STATUSES:
            out.append(f"judgments.{jid}: status {_name(status, secrets)} is not one of "
                       f"{', '.join(JUDGMENT_STATUSES)}")
        else:
            final[jid] = status
        cited = ids(f"judgments.{jid}.facts", j.get("facts", []))
        if status in ("pass", "partial", "fail"):
            if not cited:
                out.append(f"judgments.{jid}: cites no facts")
            for fid in cited:
                if _leaks(fid, secrets):
                    out.append(f"judgments.{jid}.facts: contains a secret")
                elif facts.get(fid) is None:
                    out.append(f"judgments.{jid}: cites unknown fact {fid}")
            if status == "pass" and cited and all(
                    facts.get(f) is None or _empty(facts.get(f)["value"]) for f in cited):
                out.append(f"judgments.{jid}: pass cites only empty facts")
        text_field(f"judgments.{jid}.reason", j.get("reason"))

    notes = report.get("pillar_notes", {})
    if not isinstance(notes, dict):
        out.append("pillar_notes: not an object")
        notes = {}
    for pillar, note in notes.items():
        if _leaks(pillar, secrets):
            out.append("pillar_notes[<redacted>]: contains a secret")
            continue
        if pillar not in PILLARS:
            out.append(f"pillar_notes.{pillar}: not a pillar")
        text_field(f"pillar_notes.{pillar}", note)

    fixes = report.get("fixes", [])
    if not isinstance(fixes, list):
        out.append("fixes: not a list")
        fixes = []
    if len(fixes) > MAX_FIXES:
        out.append(f"fixes: more than {MAX_FIXES} ({len(fixes)})")
    for i, fx in enumerate(fixes):
        if not isinstance(fx, dict):
            out.append(f"fixes[{i}]: not an object")
            continue
        named = ids(f"fixes[{i}].checks", fx.get("checks", []))
        if any(_leaks(c, secrets) for c in named):
            out.append(f"fixes[{i}].checks: contains a secret")
        elif not any(final.get(c) in ("fail", "partial") for c in named):
            out.append(f"fixes[{i}]: names no failing or partial check")
        for field in ("text", "where"):
            text_field(f"fixes[{i}].{field}", fx.get(field))
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
    try:
        problems = verify(*docs)
    except Exception as err:  # a garbled report must fail the gate, never skip it
        problems = [f"report: could not be verified ({type(err).__name__})"]
    print("\n".join(problems) if problems else "ok")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
