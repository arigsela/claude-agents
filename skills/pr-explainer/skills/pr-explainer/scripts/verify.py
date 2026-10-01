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

import ref_groups

# The prose must come from one pinned model; managed settings can silently ignore a skill's
# model override, so the narrator states its model and a mismatch marks the page unverified.
NARRATOR_MODEL = "claude-opus-5-5"
# covered: the diff delivers it. respected: a scope limit or constraint the diff does not break.
# out_of_band: done outside this PR, cited from a ticket comment (j*). not_covered / unclear: neither.
TICKET_STATUSES = {"covered", "respected", "out_of_band", "not_covered", "unclear"}
# Refs that differ in one place render as one group; more groups than this per row means the
# narrator is listing evidence instead of pointing at it.
MAX_REF_GROUPS = 6
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
    index = {x["id"]: x for key in ("resources", "non_manifest_changes", "terraform") for x in facts[key]}
    ids = set(index)
    comments = {c["id"]: c for c in (facts.get("jira") or {}).get("comments") or [] if c.get("id")}
    errors = []

    def check_groups(where: str, refs: list[str]) -> None:
        n = len(ref_groups.group([ref_groups.entry(index.get(r) or comments.get(r), r) for r in refs]))
        if n > MAX_REF_GROUPS:
            errors.append(f"{where} cites {n} ref groups (max {MAX_REF_GROUPS}); cite one representative per pattern")

    if not str(expl.get("tldr", "")).strip():
        errors.append("tldr is empty")
    for section in ("behavior_changes", "callouts"):
        allowed = ids | set(comments) if section == "callouts" else ids
        for i, item in enumerate(expl.get(section, [])):
            for ref in item.get("refs", []):
                if ref not in allowed:
                    errors.append(f"{section}[{i}] references unknown id {ref!r}")
            check_groups(f"{section}[{i}]", item.get("refs", []))
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
    if expl.get("narrator_model") != NARRATOR_MODEL:
        errors.append(f"narrator_model is {expl.get('narrator_model')!r}; the explainer must be written by {NARRATOR_MODEL}")
    ticket = expl.get("ticket")
    if facts.get("jira") and not ticket:
        errors.append(f"facts.jira has {facts['jira']['key']} but the explainer has no ticket section")
    if ticket and not facts.get("jira"):
        errors.append("explainer has a ticket section but facts.jira is null")
    for i, item in enumerate((ticket or {}).get("criteria", [])):
        status, refs = item.get("status"), item.get("refs", [])
        if status not in TICKET_STATUSES:
            errors.append(f"ticket.criteria[{i}] status {status!r} is not one of {sorted(TICKET_STATUSES)}")
        for ref in refs:
            if ref not in ids and ref not in comments:
                errors.append(f"ticket.criteria[{i}] references unknown id {ref!r}")
        if status == "covered" and not any(r in ids for r in refs):
            errors.append(f"ticket.criteria[{i}] is covered but cites no change from the PR")
        if status == "out_of_band" and not any(r in comments for r in refs):
            errors.append(f"ticket.criteria[{i}] is out_of_band but cites no ticket comment (j*)")
        if status != "covered" and not str(item.get("reason", "")).strip():
            errors.append(f"ticket.criteria[{i}] is {status} but has no reason")
        check_groups(f"ticket.criteria[{i}]", refs)
    if any(SECRET_VALUE_RE.search(s) for s in strings(expl)):
        errors.append("explainer text contains a secret-looking value")
    return errors


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--facts", required=True)
    ap.add_argument("--explainer", required=True)
    ap.add_argument("--errors-out", required=True)
    args = ap.parse_args()
    try:
        with open(args.facts) as fh:
            facts = json.load(fh)
        try:
            with open(args.explainer) as fh:
                expl = json.load(fh)
        except json.JSONDecodeError as err:
            errors = [f"explainer.json is not valid JSON: {err}"]
        else:
            errors = verify(facts, expl)
    except Exception as err:  # never crash silently
        errors = [f"verify crashed: {type(err).__name__}: {err}"]
    with open(args.errors_out, "w") as fh:
        json.dump(errors, fh, indent=2)
    print("verify: OK" if not errors else "verify: FAILED\n" + "\n".join(f"- {e}" for e in errors))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
