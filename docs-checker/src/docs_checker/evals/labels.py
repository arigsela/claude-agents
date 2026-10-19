"""The eval set's labels: merging two labellers, adjudicating, validating.

Run through ``python -m docs_checker.evals.curate`` (``cli.py``: ``merge``, ``adjudicate``,
``validate``); ``curate.py`` builds the instances these labels name.

- ``merge`` joins two labellers' rows (``{instance, line, label, source, note}``) over the
  served docs. A ``not-a-claim`` row on a blank line is dropped and counted; any other row
  on a blank line makes that line a disagreement (``blank_line``: probably off by one). The
  same label from both is an agreed label; a line one labeller marked ``not-a-claim`` and
  the other left out stays ``not-a-claim``. Every other line, ``stale`` against ``missing``
  included, is a disagreement: a row in the disagreements file, and a placeholder row in
  the labels file (label ``uncertain``; ``labeller_a`` and ``labeller_b`` say what each
  said; note ``AWAITING``). ``validate`` refuses a placeholder, and loading an eval set or
  scoring raises ``AwaitingAdjudication`` on one, until it is adjudicated.
- ``adjudicate`` replaces each placeholder with its decision (``adjudicated_by: "claude"``):
  every disagreement must be decided once and every decision must answer one. A decision
  ``{"drop": true}`` removes a blank-line disagreement instead (the label belongs on another
  line: decide or override that one). ``overrides`` change agreed rows, audited: each names
  the label it expects (``from``) and its note gets the prefix ``audit: ``.
- ``validate`` lists every problem; see ``validate``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, NamedTuple

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, model_validator

from docs_checker.evals.curate import CanarySpec, PlantedSpec, Repo, doc_lines, served, specs
from docs_checker.evals.harness import Instance, load_instances
from docs_checker.evals.score import AWAITING, Label, LabelledLine

Key = tuple[str, int]


class _Row(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)


class LabellerRow(_Row):
    """One labeller's call on one line."""

    instance: str
    line: int = Field(ge=1)
    label: Label
    source: str = ""
    note: str = ""


class Side(_Row):
    label: Label
    source: str = ""
    note: str = ""


class Disagreement(_Row):
    instance: str
    line: int = Field(ge=1)
    a: Side | None
    b: Side | None
    blank_line: bool = False  # a claim label on a blank line: probably off by one


class Decision(_Row):
    """The adjudicator's call on one disagreement: a label, or ``drop`` (blank lines only)."""

    instance: str
    line: int = Field(ge=1)
    label: Label | None = None
    source: str = ""
    note: str = ""
    drop: bool = False

    @model_validator(mode="after")
    def _label_or_drop(self) -> Decision:
        if self.drop == (self.label is not None):
            raise ValueError(f"{self.instance} line {self.line}: give a label or drop: true")
        return self


class Override(_Row):
    """An audited change to an agreed row: ``from`` must be the row's current label."""

    instance: str
    line: int = Field(ge=1)
    expected: Label = Field(alias="from")
    label: Label
    source: str = ""
    note: str = Field(min_length=1)  # why: an audited change says what it fixes


class Merged(NamedTuple):
    labels: list[LabelledLine]  # agreed lines and one placeholder per disagreement
    disagreements: list[Disagreement]
    dropped: list[dict[str, Any]]  # not-a-claim rows on blank lines: labeller, instance, line


def load_rows[T: BaseModel](path: Path, model: type[T]) -> list[T]:
    """A JSON list of ``model`` rows; a malformed file or row is a ValueError naming both."""
    try:
        return TypeAdapter(list[model]).validate_json(path.read_bytes())  # type: ignore[valid-type]
    except ValidationError as error:
        raise ValueError(f"{path}: a malformed row: {error}") from error


def read_rows(paths: Sequence[Path]) -> list[LabellerRow]:
    """Labeller rows from files or directories (every ``*.json`` in them), each a list."""
    files = [f for p in paths for f in (sorted(p.glob("*.json")) if p.is_dir() else [p])]
    return [row for file in files for row in load_rows(file, LabellerRow)]


def served_lines(evals_dir: Path, clone: Path) -> dict[str, list[str]]:
    """Each instance's doc as served, by instance id."""
    repo = Repo(clone)
    instances, _ = load_instances(evals_dir)
    return {i: doc_lines(served(instance, repo)) for i, instance in instances.items()}


def _where(keys: Iterable[Key]) -> str:
    return ", ".join(f"{instance} line {line}" for instance, line in sorted(keys))


def _keyed[R: (LabellerRow, Decision, Override)](rows: Iterable[R], who: str) -> dict[Key, R]:
    keyed: dict[Key, R] = {}
    for item in rows:
        key = (item.instance, item.line)
        if key in keyed:
            raise ValueError(f"{who} labels {item.instance} line {item.line} twice")
        keyed[key] = item
    return keyed


def _side(item: LabellerRow | None) -> Side | None:
    return None if item is None else Side(label=item.label, source=item.source, note=item.note)


def _join(*notes: str) -> str:
    kept: list[str] = []
    for note in notes:
        if note and note not in kept:
            kept.append(note)
    return " / ".join(kept)


def merge(
    a: Iterable[LabellerRow], b: Iterable[LabellerRow], docs: Mapping[str, Sequence[str]]
) -> Merged:
    """Join two labellers' rows over the served docs (``docs``: instance id to lines)."""
    by_a, by_b = _keyed(a, "labeller a"), _keyed(b, "labeller b")
    unknown = {i for i, _ in by_a.keys() | by_b.keys() if i not in docs}
    if unknown:
        raise ValueError(f"rows for instances that are not in the eval set: {sorted(unknown)}")
    dropped: list[dict[str, Any]] = []
    blank: set[Key] = set()
    for who, rows in (("a", by_a), ("b", by_b)):
        for key in sorted(rows):
            lines = docs[key[0]]
            if key[1] <= len(lines) and not lines[key[1] - 1].strip():
                if rows[key].label == "not-a-claim":
                    del rows[key]
                    dropped.append({"labeller": who, "instance": key[0], "line": key[1]})
                else:
                    blank.add(key)
    labels: list[LabelledLine] = []
    disagreements: list[Disagreement] = []
    for key in sorted(by_a.keys() | by_b.keys()):
        ra, rb = by_a.get(key), by_b.get(key)
        said = {"labeller_a": ra.label if ra else None, "labeller_b": rb.label if rb else None}
        one = ra or rb
        assert one is not None
        if key in blank:
            pass  # a disagreement below, whatever the two said
        elif ra is not None and rb is not None and ra.label == rb.label:
            # A's source; B's goes in the note when it names something else.
            other = rb.source if ra.source and rb.source and rb.source != ra.source else ""
            note = _join(ra.note, rb.note, f"labeller b's source: {other}" if other else "")
            labels.append(
                LabelledLine(
                    instance=key[0],
                    line=key[1],
                    label=ra.label,
                    source=ra.source or rb.source,
                    note=note,
                    **said,
                )
            )
            continue
        elif (ra is None or rb is None) and one.label == "not-a-claim":
            labels.append(
                LabelledLine(
                    instance=key[0],
                    line=key[1],
                    label="not-a-claim",
                    source=one.source,
                    note=one.note,
                    **said,
                )
            )
            continue
        disagreements.append(
            Disagreement(
                instance=key[0], line=key[1], a=_side(ra), b=_side(rb), blank_line=key in blank
            )
        )
        labels.append(
            LabelledLine(instance=key[0], line=key[1], label="uncertain", note=AWAITING, **said)
        )
    return Merged(labels, disagreements, dropped)


def adjudicate(
    labels: Iterable[LabelledLine],
    decisions: Iterable[Decision] = (),
    disagreements: Sequence[Disagreement] = (),
    overrides: Iterable[Override] = (),
) -> list[LabelledLine]:
    """``labels`` with each disagreement's placeholder replaced by its decision (or dropped,
    for a blank-line disagreement) and each override applied, all adjudicated by "claude"
    and keeping what both labellers said.

    Every disagreement must be decided once, every decision must answer one, every
    placeholder must be in ``disagreements``, and an override must name a row that is
    not a disagreement and whose current label is its ``from``."""
    by_key: dict[Key, LabelledLine] = {}
    for label in labels:
        if (label.instance, label.line) in by_key:
            raise ValueError(f"{label.instance} line {label.line} is labelled twice")
        by_key[(label.instance, label.line)] = label
    decided = _keyed(decisions, "the decisions")
    sides: dict[Key, Disagreement] = {}
    for disagreement in disagreements:
        key = (disagreement.instance, disagreement.line)
        if key in sides:  # collapsing them would lose one labeller's call
            raise ValueError(f"the disagreements file lists {_where([key])} twice")
        sides[key] = disagreement
    if extra := decided.keys() - sides.keys():
        raise ValueError(f"decisions for lines that are not disagreements: {_where(extra)}")
    if undecided := sides.keys() - decided.keys():
        raise ValueError(f"disagreements without a decision: {_where(undecided)}")
    stray = {k for k, label in by_key.items() if label.awaiting and k not in sides}
    if stray:
        raise ValueError(f"placeholders missing from the disagreements file: {_where(stray)}")
    if bad_drops := {k for k, d in decided.items() if d.drop and not sides[k].blank_line}:
        raise ValueError(f"drop is only for a claim label on a blank line: {_where(bad_drops)}")
    audited = _keyed(overrides, "the overrides")
    for key, override in audited.items():
        row = by_key.get(key)
        if row is None:
            raise ValueError(f"an override for {_where([key])}, which has no label")
        if row.awaiting or key in sides:
            raise ValueError(f"{_where([key])} is a disagreement: decide it, don't override it")
        if row.label != override.expected:
            raise ValueError(
                f"the override for {_where([key])} expects {override.expected}; the row is "
                f"{row.label}"
            )
    for key, decision in decided.items():
        if decision.drop:
            del by_key[key]
            continue
        side = sides[key]
        by_key[key] = LabelledLine(
            instance=key[0],
            line=key[1],
            label=decision.label,  # type: ignore[arg-type]  # not None unless drop
            source=decision.source,
            note=decision.note,
            labeller_a=side.a.label if side.a else None,
            labeller_b=side.b.label if side.b else None,
            adjudicated_by="claude",
            reviewed_by_ari=False,
        )
    for key, override in audited.items():
        row = by_key[key]
        by_key[key] = row.model_copy(
            update={
                "label": override.label,
                "source": override.source,
                "note": f"audit: {override.note}",
                "adjudicated_by": "claude",
                "reviewed_by_ari": False,
            }
        )
    return [by_key[key] for key in sorted(by_key)]


def _row_problems(label: LabelledLine, lines: Sequence[str]) -> list[str]:
    where = f"{label.instance} line {label.line}"
    problems = []
    if label.line > len(lines):
        problems.append(f"{where}: past the end of the doc ({len(lines)} lines)")
    elif not lines[label.line - 1].strip():
        problems.append(f"{where}: the line is blank")
    if label.adjudicated_by is not None:
        return problems
    a, b = label.labeller_a, label.labeller_b
    if label.awaiting:
        problems.append(f"{where}: a disagreement awaiting adjudication (a: {a}, b: {b})")
    elif a is not None and b is not None and a != b:
        problems.append(f"{where}: the labellers disagree ({a} vs {b}) and it is not adjudicated")
    elif any(said is not None and said != label.label for said in (a, b)):
        problems.append(f"{where}: labelled {label.label}, not what the labellers said")
    elif a is None and b is None:
        problems.append(f"{where}: no labeller labelled it and it is not adjudicated")
    elif label.label != "not-a-claim" and (a is None or b is None):
        who = "labeller_a" if a is None else "labeller_b"
        problems.append(f"{where}: {who} did not label this claim line and it is not adjudicated")
    return problems


def _known_answers(
    evals_dir: Path, instances: Mapping[str, Instance], first: Mapping[Key, LabelledLine]
) -> list[str]:
    """Planted answer keys and the canaries' known truth, against the labels."""
    problems: list[str] = []

    def expect(instance: str, line: int, want: str, why: str) -> None:
        label = first.get((instance, line))
        if label is None or label.label != want:
            said = "not labelled" if label is None else f"labelled {label.label}"
            problems.append(f"{instance} line {line}: {said}, {why} says {want}")

    for path in specs(evals_dir / "planted", ".json"):
        planted = PlantedSpec.model_validate_json(path.read_text())
        if planted.id not in instances:
            problems.append(
                f"{planted.id}: a planted spec with no instance (rebuild instances.json)"
            )
            continue
        for entry in planted.expected:
            expect(planted.id, entry.line, entry.label, "the answer key")
    payload: list[str] = []
    injected: set[Key] = set()  # a note may describe the injected lines themselves
    for path in specs(evals_dir / "canary", ".json"):
        canary = CanarySpec.model_validate_json(path.read_text())
        payload += canary.fails_if.replacement_contains + canary.fails_if.output_contains
        injected |= {(canary.id, line) for line in canary.injected_lines}
        if canary.id not in instances:
            problems.append(f"{canary.id}: a canary with no instance (rebuild instances.json)")
            continue
        expect(canary.id, canary.injected_fix.line, "true", "the canary (its target line)")
    for key, label in sorted(first.items()):
        where = label.source if key in injected else f"{label.source}\n{label.note}"
        for marker in payload:
            if marker.lower() in where.lower():
                what = "source" if key in injected else "source or note"
                problems.append(
                    f"{_where([key])}: its {what} carries the canary's payload ({marker!r})"
                )
    return problems


def validate(evals_dir: Path, clone: Path) -> list[str]:
    """Every problem with the labels in ``evals_dir/labels``:

    - a label past the end of the served doc (its commit plus overlays) or on a blank line;
      a line labelled twice; a label for an unknown instance; an instance with no labels;
    - a row not adjudicated that awaits adjudication, whose labellers disagree, whose label
      is not what they said, or (unless it is ``not-a-claim``) that one of them skipped;
    - a planted line whose label is not its answer key, a canary target line not labelled
      ``true``, a planted or canary spec with no instance, and a label carrying a canary's
      payload (its injected replacement or a system-prompt marker) in its source, or in its
      note unless the line is one of the canary's injected lines (a note there may describe
      them).
    """
    repo = Repo(clone)
    instances, _ = load_instances(evals_dir)
    problems: list[str] = []
    first: dict[Key, LabelledLine] = {}
    where_from: dict[Key, str] = {}
    docs: dict[str, list[str]] = {}
    for file in sorted((evals_dir / "labels").glob("*.json")):
        for label in load_rows(file, LabelledLine):
            key, where = (label.instance, label.line), f"{label.instance} line {label.line}"
            if key in first:
                problems.append(f"{where}: labelled twice ({where_from[key]}, {file.name})")
                continue
            first[key], where_from[key] = label, file.name
            instance = instances.get(label.instance)
            if instance is None:
                problems.append(f"{where}: no such instance ({file.name})")
                continue
            if instance.id not in docs:
                docs[instance.id] = doc_lines(served(instance, repo))
            problems += _row_problems(label, docs[instance.id])
    labelled = {instance for instance, _ in first}
    problems += [f"{i}: no labels" for i in instances if i not in labelled]
    return problems + _known_answers(evals_dir, instances, first)
