#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6", "pathspec>=0.12,<1"]
# ///
"""readiness: shared constants, fact records, the Facts accessor and the check catalog loader."""
from __future__ import annotations

import fnmatch
import json
from pathlib import Path

import yaml

PILLARS = ("Operational excellence", "Security", "Reliability",
           "Performance efficiency", "Cost optimization", "Sustainability")
STATUSES = ("pass", "partial", "fail", "unknown", "n/a")
SOURCES = ("app", "deploy", "backstage", "scorecard", "cluster", "github")
KINDS = ("rule", "judgment", "person")

PLUGIN_DIR = Path(__file__).resolve().parents[1]


def fact(id: str, source: str, value, evidence: str) -> dict:
    return {"id": id, "source": source, "value": value, "evidence": evidence}


class Facts:
    """Read access to a facts document (collect.py's facts.json): {"meta": {"sources": {source: status}, ...},
    "facts": [fact, ...]}."""

    def __init__(self, doc: dict):
        self.doc = doc
        self._facts = list(doc.get("facts", []))
        self._by_id = {f["id"]: f for f in self._facts}

    def get(self, id: str) -> dict | None:
        return self._by_id.get(id)

    def value(self, id: str, default=None):
        f = self._by_id.get(id)
        return default if f is None else f["value"]

    def prefix(self, p: str) -> list[dict]:
        return [f for f in self._facts if f["id"].startswith(p)]

    def match(self, globs: list[str]) -> list[str]:
        """Fact ids matching any glob, in fact order."""
        return [f["id"] for f in self._facts if any(fnmatch.fnmatchcase(f["id"], g) for g in globs)]

    def status(self, source: str) -> str:
        meta = self.doc.get("meta")
        sources = meta.get("sources") if isinstance(meta, dict) else None
        return sources.get(source, "absent") if isinstance(sources, dict) else "absent"

    def ok(self, source: str) -> bool:
        return self.status(source) == "ok"


def load_checks(path: Path | None = None) -> list[dict]:
    path = path or PLUGIN_DIR / "checks.yaml"
    data = yaml.safe_load(Path(path).read_text())
    return data["checks"] if isinstance(data, dict) else data


def read_json(path) -> dict:
    return json.loads(Path(path).read_text())


def _plain(v):
    """String dict keys all the way down: YAML keys can be dates or a mix of ints and strings, which json.dumps
    cannot write (non-str key types) or sort (sort_keys compares them)."""
    if isinstance(v, dict):
        return {k if isinstance(k, str) else str(k): _plain(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_plain(x) for x in v]
    return v


def write_json(path, obj) -> None:
    """default=str: a YAML-typed value (an unquoted date or timestamp) that reaches a fact is written as text."""
    Path(path).write_text(json.dumps(_plain(obj), indent=2, sort_keys=True, default=str) + "\n")
