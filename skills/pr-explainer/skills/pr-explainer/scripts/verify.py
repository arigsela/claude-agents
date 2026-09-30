#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///
"""pr-explainer: check explainer.json against facts.json (spec §6.4). Exit 1 + errors JSON on failure."""
from __future__ import annotations

import argparse
import json
import re
import sys

SECRET_VALUE_RE = re.compile(
    r"(?i)((?:password|passwd|token|secret|api[_-]?key|private[_-]?key)\s*[:=]\s*)(\S{8,})")


def strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from strings(v)


def verify(facts: dict, expl: dict) -> list[str]:
    ids = {x["id"] for key in ("resources", "non_manifest_changes", "terraform") for x in facts[key]}
    errors = []
    if not str(expl.get("tldr", "")).strip():
        errors.append("tldr is empty")
    for section in ("behavior_changes", "callouts"):
        for i, item in enumerate(expl.get(section, [])):
            for ref in item.get("refs", []):
                if ref not in ids:
                    errors.append(f"{section}[{i}] references unknown id {ref!r}")
    must = set()
    for i, item in enumerate(expl.get("must_read", [])):
        if item.get("ref") not in ids:
            errors.append(f"must_read[{i}] references unknown id {item.get('ref')!r}")
        must.add(item.get("ref"))
    for ref in expl.get("reading_order", []):
        if ref not in ids:
            errors.append(f"reading_order references unknown id {ref!r}")
    for hit in facts["policy_hits"]:
        if hit["ref"] not in must:
            errors.append(f"policy hit {hit['ref']} ({hit['rule']}) is missing from must_read")
    covered = " ".join(expl.get("not_covered", [])).lower()
    for app in facts["apps"]:
        if app["render"] != "rendered" and app["app"].lower() not in covered:
            errors.append(f"app {app['app']} was not rendered but is missing from not_covered")
    for note in facts.get("notes", []):
        if note["key"].lower() not in covered:
            errors.append(f"note {note['key']!r} is missing from not_covered")
    if any(SECRET_VALUE_RE.search(s) for s in strings(expl)):
        errors.append("explainer text contains a secret-looking value")
    return errors


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--facts", required=True)
    ap.add_argument("--explainer", required=True)
    ap.add_argument("--errors-out", required=True)
    args = ap.parse_args()
    with open(args.facts) as fh:
        facts = json.load(fh)
    try:
        with open(args.explainer) as fh:
            expl = json.load(fh)
    except json.JSONDecodeError as err:
        errors = [f"explainer.json is not valid JSON: {err}"]
    else:
        errors = verify(facts, expl)
    with open(args.errors_out, "w") as fh:
        json.dump(errors, fh, indent=2)
    print("verify: OK" if not errors else "verify: FAILED\n" + "\n".join(f"- {e}" for e in errors))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
