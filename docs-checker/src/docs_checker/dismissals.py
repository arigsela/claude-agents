"""Findings Ari rejected, kept in a git file (``docs/docs-checker-dismissed.yaml``).

Format::

    version: 1
    dismissed:
      - {doc, claim, evidence_hash?, expires?, reason, date}

A dismissal without ``evidence_hash`` must carry ``expires`` (C#44), so it cannot
silence a claim forever. An invalid entry is returned as an error and never applied.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

import yaml

from docs_checker.state import Finding


@dataclass(frozen=True)
class Dismissal:
    doc: str
    claim: str
    evidence_hash: str | None
    expires: str | None
    reason: str
    date: str


def _norm(text: str) -> str:
    return " ".join(text.split()).lower()


def _iso(value: Any) -> str | None:
    """An ISO date string (YAML may hand back a date object), else None."""
    if isinstance(value, dt.datetime):
        return None
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, str):
        try:
            return dt.date.fromisoformat(value.strip()).isoformat()
        except ValueError:
            return None
    return None


def _entry(raw: Any, n: int) -> Dismissal | str:
    where = f"dismissed[{n}]"
    if not isinstance(raw, dict):
        return f"{where}: not a mapping"
    for key in ("doc", "claim", "reason"):
        if not isinstance(raw.get(key), str) or not raw[key].strip():
            return f"{where}: '{key}' must be a non-empty string"
    date = _iso(raw.get("date"))
    if date is None:
        return f"{where}: 'date' must be an ISO date"
    expires = None
    if raw.get("expires") is not None:
        expires = _iso(raw["expires"])
        if expires is None:
            return f"{where}: 'expires' must be an ISO date"
    ev = raw.get("evidence_hash")
    if ev is not None and (not isinstance(ev, str) or not ev.strip()):
        return f"{where}: 'evidence_hash' must be a non-empty string"
    if ev is None and expires is None:
        return f"{where}: a dismissal without 'evidence_hash' needs 'expires'"
    return Dismissal(raw["doc"].strip(), raw["claim"], ev, expires, raw["reason"], date)


def parse_dismissals(text: str | None) -> tuple[list[Dismissal], list[str]]:
    """The valid dismissals and the errors. None (no file) is no dismissals, no errors."""
    if text is None:
        return [], []
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        return [], [f"dismissals file is not valid YAML: {type(exc).__name__}"]
    if data is None:
        return [], []
    if not isinstance(data, dict) or data.get("version") != 1:
        return [], ["dismissals file: expected a mapping with 'version: 1'"]
    items = data.get("dismissed")
    if items is None:
        return [], []
    if not isinstance(items, list):
        return [], ["dismissals file: 'dismissed' must be a list"]
    good: list[Dismissal] = []
    errors: list[str] = []
    for n, raw in enumerate(items):
        parsed = _entry(raw, n)
        if isinstance(parsed, str):
            errors.append(parsed)
        else:
            good.append(parsed)
    return good, errors


def is_dismissed(finding: Finding, dismissals: list[Dismissal], today: dt.date) -> bool:
    """Same doc and normalized claim text, and the same evidence or an unexpired entry."""
    claim = _norm(finding.claim.text)
    for d in dismissals:
        if d.doc != finding.doc or _norm(d.claim) != claim:
            continue
        if d.evidence_hash is not None:
            if d.evidence_hash == finding.evidence_hash:
                return True
        elif d.expires is not None and today.isoformat() <= d.expires:
            return True
    return False
