"""Scoring a run's findings against the labelled lines of its instances.

A label names one line of an instance's doc (at the instance's commit, overlays
applied): ``stale`` and ``missing`` are positives, ``true`` and ``not-a-claim``
negatives, and ``uncertain`` lines count for nothing.

- Matching is one-to-one and scoped by instance (C#31): a finding can match a
  positive label of its own instance whose line is inside the finding's line range
  and whose class is the finding's verdict (stale or missing). The matching is a
  maximum one, so each label is matched at most once and as many findings as
  possible are true positives.
- A finding left unmatched is a false positive when any line it covers has a
  decisive label: a negative, a positive of the other class, or a positive already
  matched (a duplicate). Otherwise, when its labelled lines are all ``uncertain``,
  it is excluded; when none of its lines is labelled, it goes to ``to_adjudicate``
  rather than straight to the false positives (C#32).
- A positive label no finding matched is a false negative.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from docs_checker.state import Finding

Label = Literal["stale", "missing", "true", "not-a-claim", "uncertain"]
POSITIVE: frozenset[str] = frozenset({"stale", "missing"})


class LabelledLine(BaseModel):
    """One labelled line of an instance's doc (Task 17 writes them)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    instance: str
    line: int = Field(ge=1)
    label: Label
    source: str = ""  # the file (and line) that decides it
    note: str = ""
    labeller_a: str | None = None
    labeller_b: str | None = None
    adjudicated_by: str | None = None
    reviewed_by_ari: bool = False


@dataclass(frozen=True)
class Score:
    tp: int
    fp: int
    fn: int
    to_adjudicate: list[dict] = field(default_factory=list)
    precision: float | None = None
    recall: float | None = None
    workload_usd: float = 0.0
    cash_usd: float = 0.0
    cost_per_verified: float | None = None  # workload cost per true positive
    excluded: int = 0  # findings on uncertain lines only

    def to_dict(self) -> dict:
        return {
            "tp": self.tp,
            "fp": self.fp,
            "fn": self.fn,
            "to_adjudicate": list(self.to_adjudicate),
            "excluded": self.excluded,
            "precision": self.precision,
            "recall": self.recall,
            "workload_usd": self.workload_usd,
            "cash_usd": self.cash_usd,
            "cost_per_verified": self.cost_per_verified,
        }


def _lines(finding: Finding) -> range:
    return range(finding.line_start, finding.line_end + 1)


def _maximum_matching(edges: list[list[int]]) -> dict[int, int]:
    """Kuhn's augmenting paths: finding index -> label index, as many as possible."""
    owner: dict[int, int] = {}  # label -> finding

    def augment(finding: int, seen: set[int]) -> bool:
        for label in edges[finding]:
            if label in seen:
                continue
            seen.add(label)
            if label not in owner or augment(owner[label], seen):
                owner[label] = finding
                return True
        return False

    for finding in range(len(edges)):
        augment(finding, set())
    return {finding: label for label, finding in owner.items()}


def _item(finding: Finding) -> dict:
    return {
        "instance": finding.instance,
        "doc": finding.doc,
        "line_start": finding.line_start,
        "line_end": finding.line_end,
        "verdict": finding.verdict,
        "confidence": finding.confidence,
        "claim": finding.claim.text,
    }


def score(
    findings: Iterable[Finding],
    labels: Sequence[LabelledLine],
    *,
    workload_usd: float = 0.0,
    cash_usd: float = 0.0,
) -> Score:
    by_line: dict[tuple[str, int], int] = {}
    for index, label in enumerate(labels):
        key = (label.instance, label.line)
        if key in by_line:
            raise ValueError(f"{label.instance} line {label.line} is labelled twice")
        by_line[key] = index
    ordered = sorted(
        findings, key=lambda f: (f.instance, f.line_start, f.line_end, -f.confidence, f.id)
    )
    edges = [
        [
            by_line[(f.instance, line)]
            for line in _lines(f)
            if (f.instance, line) in by_line
            and labels[by_line[(f.instance, line)]].label == f.verdict
        ]
        for f in ordered
    ]
    matched = _maximum_matching(edges)
    used = set(matched.values())
    tp = fp = excluded = 0
    to_adjudicate: list[dict] = []
    for index, finding in enumerate(ordered):
        if index in matched:
            tp += 1
            continue
        covered = [
            labels[by_line[(finding.instance, line)]]
            for line in _lines(finding)
            if (finding.instance, line) in by_line
        ]
        if not covered:
            to_adjudicate.append(_item(finding))
        elif all(label.label == "uncertain" for label in covered):
            excluded += 1
        else:
            fp += 1
    fn = sum(
        1 for index, label in enumerate(labels) if label.label in POSITIVE and index not in used
    )
    return Score(
        tp=tp,
        fp=fp,
        fn=fn,
        to_adjudicate=to_adjudicate,
        precision=tp / (tp + fp) if tp + fp else None,
        recall=tp / (tp + fn) if tp + fn else None,
        workload_usd=round(workload_usd, 8),
        cash_usd=round(cash_usd, 8),
        cost_per_verified=workload_usd / tp if tp else None,
        excluded=excluded,
    )
