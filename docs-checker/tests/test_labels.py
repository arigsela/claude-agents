"""The eval set's labels: merging two labellers, adjudicating, validating.

On the tiny git repo of ``test_curate`` (``make_evals``), never on ``~/git/kubernetes``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from docs_checker.evals import cli, curate, labels
from docs_checker.evals.score import LabelledLine
from tests.test_curate import DELETED_PLANT, DEPLOYMENT, MARKER, SERVICE, make_evals, write_json

DOCS = {"i": ["one", "two", "three", "four", "five", "six", "seven", "", "nine"]}


@pytest.fixture
def evals(tmp_path) -> tuple[Path, Path, str, str]:
    return make_evals(tmp_path)


def row(line: int, label: str, source: str = "", note: str = "", instance: str = "i") -> dict:
    return {"instance": instance, "line": line, "label": label, "source": source, "note": note}


def rows(*items: dict) -> list[labels.LabellerRow]:
    return [labels.LabellerRow.model_validate(item) for item in items]


def decisions(*items: dict) -> list[labels.Decision]:
    return [labels.Decision.model_validate(item) for item in items]


def override(line: int, expected: str, label: str, source: str = "", note: str = "why") -> dict:
    """An override row as the adjudicator writes it (``from`` is a JSON key)."""
    return {"instance": "i", "line": line, "from": expected, "label": label, "source": source}


def overrides(*items: dict) -> list[labels.Override]:
    return [labels.Override.model_validate({"note": "why", **item}) for item in items]


A_ROWS = [
    row(1, "true", "f.yaml:1"),
    row(2, "stale", "f.yaml:2", "a says stale"),
    row(3, "not-a-claim"),
    row(5, "stale", "f.yaml:5"),
    row(6, "true", "f.yaml:6"),
    row(7, "not-a-claim"),
    row(8, "true", "f.yaml:8"),  # line 8 is blank: a claim there is probably off by one
]
B_ROWS = [
    row(1, "true", "f.yaml:1", "same"),
    row(2, "missing", "f.yaml", "b says missing"),
    row(4, "not-a-claim"),
    row(6, "uncertain"),
    row(7, "true", "f.yaml:7"),
    row(8, "not-a-claim"),  # on the blank line: dropped
    row(9, "true", "g.yaml:3", "b's note"),
]
A_ROWS.append(row(9, "true", "f.yaml:9", "a's note"))


def merged() -> labels.Merged:
    return labels.merge(rows(*A_ROWS), rows(*B_ROWS), DOCS)


# --- merge -------------------------------------------------------------------------------------


def test_merge_keeps_agreements_and_writes_each_disagreement_as_a_placeholder():
    result = merged()
    assert [(lab.line, lab.label, lab.labeller_a, lab.labeller_b) for lab in result.labels] == [
        (1, "true", "true", "true"),
        (2, "uncertain", "stale", "missing"),  # stale vs missing is a disagreement
        (3, "not-a-claim", "not-a-claim", None),
        (4, "not-a-claim", None, "not-a-claim"),
        (5, "uncertain", "stale", None),
        (6, "uncertain", "true", "uncertain"),
        (7, "uncertain", "not-a-claim", "true"),
        (8, "uncertain", "true", None),
        (9, "true", "true", "true"),
    ]
    placeholders = [lab for lab in result.labels if lab.note == labels.AWAITING]
    assert [lab.line for lab in placeholders] == [2, 5, 6, 7, 8]
    assert all(lab.awaiting for lab in placeholders)
    assert all(lab.adjudicated_by is None and not lab.reviewed_by_ari for lab in result.labels)
    assert [(d.line, d.a and d.a.label, d.b and d.b.label) for d in result.disagreements] == [
        (2, "stale", "missing"),
        (5, "stale", None),
        (6, "true", "uncertain"),
        (7, "not-a-claim", "true"),
        (8, "true", None),
    ]
    assert [d.line for d in result.disagreements if d.blank_line] == [8]
    first = result.disagreements[0]
    assert first.a == labels.Side(label="stale", source="f.yaml:2", note="a says stale")
    assert first.b == labels.Side(label="missing", source="f.yaml", note="b says missing")


def test_merge_drops_not_a_claim_on_blank_lines_and_makes_a_claim_there_a_disagreement():
    result = merged()
    assert result.dropped == [{"labeller": "b", "instance": "i", "line": 8}]
    blank = [d for d in result.disagreements if d.line == 8]
    assert blank == [
        labels.Disagreement(
            instance="i",
            line=8,
            a=labels.Side(label="true", source="f.yaml:8"),
            b=None,
            blank_line=True,
        )
    ]
    # even two agreeing claim labels on a blank line are a disagreement
    both_true = labels.merge(rows(row(8, "true")), rows(row(8, "true")), DOCS)
    assert [(d.line, d.blank_line) for d in both_true.disagreements] == [(8, True)]
    assert both_true.dropped == []


def test_an_agreed_label_keeps_a_source_and_notes_b_source():
    by_line = {lab.line: lab for lab in merged().labels}
    assert by_line[1].source == "f.yaml:1" and by_line[1].note == "same"
    assert by_line[9].source == "f.yaml:9"
    assert by_line[9].note == "a's note / b's note / labeller b's source: g.yaml:3"


def test_merge_refuses_a_line_labelled_twice_or_an_unknown_instance():
    with pytest.raises(ValueError, match="labeller a labels i line 1 twice"):
        labels.merge(rows(row(1, "true"), row(1, "stale")), [], DOCS)
    with pytest.raises(ValueError, match="labeller b labels i line 2 twice"):
        labels.merge([], rows(row(2, "true"), row(2, "true")), DOCS)
    with pytest.raises(ValueError, match="nope"):
        labels.merge(rows(row(1, "true", instance="nope")), [], DOCS)


# --- adjudicate ------------------------------------------------------------------------------


DECISIONS = [
    row(2, "stale", "f.yaml:2", "the file exists; the value differs"),
    row(5, "stale", "f.yaml:5"),
    row(6, "true", "f.yaml:6"),
    row(7, "true", "f.yaml:7"),
    {"instance": "i", "line": 8, "drop": True},  # the blank-line claim belonged elsewhere
]


def test_adjudicate_replaces_each_placeholder_recording_claude_and_both_labellers():
    result = merged()
    done = labels.adjudicate(result.labels, decisions(*DECISIONS), result.disagreements)
    by_line = {lab.line: lab for lab in done}
    assert sorted(by_line) == [1, 2, 3, 4, 5, 6, 7, 9]  # line 8 dropped
    assert by_line[2].model_dump() == {
        "instance": "i",
        "line": 2,
        "label": "stale",
        "source": "f.yaml:2",
        "note": "the file exists; the value differs",
        "labeller_a": "stale",
        "labeller_b": "missing",
        "adjudicated_by": "claude",
        "reviewed_by_ari": False,
    }
    assert (by_line[5].labeller_a, by_line[5].labeller_b) == ("stale", None)
    assert by_line[1].adjudicated_by is None
    assert not any(lab.note == labels.AWAITING for lab in done)


def test_adjudicate_needs_every_disagreement_decided_once():
    result = merged()
    with pytest.raises(ValueError, match="without a decision: i line 8"):
        labels.adjudicate(result.labels, decisions(*DECISIONS[:4]), result.disagreements)
    with pytest.raises(ValueError, match="not disagreements: i line 1"):
        labels.adjudicate(
            result.labels, decisions(*DECISIONS, row(1, "stale")), result.disagreements
        )
    with pytest.raises(ValueError, match="the decisions labels i line 2 twice"):
        labels.adjudicate(result.labels, decisions(*DECISIONS, DECISIONS[0]), result.disagreements)
    twice = [*result.disagreements, result.disagreements[0]]
    with pytest.raises(ValueError, match="lists i line 2 twice"):
        labels.adjudicate(result.labels, decisions(*DECISIONS), twice)
    with pytest.raises(
        ValueError, match="placeholders missing from the disagreements file: i line 8"
    ):
        labels.adjudicate(result.labels, decisions(*DECISIONS[:4]), result.disagreements[:4])


def test_only_a_blank_line_disagreement_can_be_dropped():
    result = merged()
    dropping = [{"instance": "i", "line": 2, "drop": True}, *DECISIONS[1:]]
    with pytest.raises(
        ValueError, match="drop is only for a claim label on a blank line: i line 2"
    ):
        labels.adjudicate(result.labels, decisions(*dropping), result.disagreements)
    for both_or_neither in ({**DECISIONS[0], "drop": True}, {"instance": "i", "line": 2}):
        with pytest.raises(ValueError, match="give a label or drop"):
            labels.Decision.model_validate(both_or_neither)


def test_adjudicate_cli_requires_the_disagreements_and_names_a_malformed_row(tmp_path, capsys):
    result = merged()
    path, dis = tmp_path / "labels.json", tmp_path / "dis.json"
    write_json(path, [lab.model_dump() for lab in result.labels])
    write_json(dis, [d.model_dump() for d in result.disagreements])
    write_json(tmp_path / "decisions.json", DECISIONS)
    argv = ["adjudicate", "--labels", str(path), "--decisions", str(tmp_path / "decisions.json")]
    with pytest.raises(SystemExit):  # --decisions needs --disagreements
        cli.main(argv)
    with pytest.raises(SystemExit):  # nothing to apply
        cli.main(["adjudicate", "--labels", str(path)])
    capsys.readouterr()

    write_json(tmp_path / "bad.json", [*DECISIONS[:3], row(7, "wrong"), DECISIONS[4]])
    bad = ["adjudicate", "--labels", str(path), "--decisions", str(tmp_path / "bad.json")]
    assert cli.main([*bad, "--disagreements", str(dis)]) == 1
    error = capsys.readouterr().err
    assert "bad.json: a malformed row" in error and "3.label" in error

    assert cli.main([*argv, "--disagreements", str(dis)]) == 0
    done = [LabelledLine.model_validate(r) for r in json.loads(path.read_text())]
    assert [(r.line, r.adjudicated_by) for r in done if r.adjudicated_by] == [
        (2, "claude"),
        (5, "claude"),
        (6, "claude"),
        (7, "claude"),
    ]
    assert "4 decided, 1 dropped, 0 overridden" in capsys.readouterr().out

    # later, an audited override alone (no disagreements left)
    write_json(
        tmp_path / "overrides.json", [{**override(1, "true", "stale"), "note": "f.yaml:1 moved"}]
    )
    assert (
        cli.main(
            ["adjudicate", "--labels", str(path), "--overrides", str(tmp_path / "overrides.json")]
        )
        == 0
    )
    first = LabelledLine.model_validate(json.loads(path.read_text())[0])
    assert (first.line, first.label, first.note) == (1, "stale", "audit: f.yaml:1 moved")


# --- overrides ---------------------------------------------------------------------------------


def test_an_override_changes_an_agreed_row_audited():
    result = merged()
    done = labels.adjudicate(
        result.labels,
        decisions(*DECISIONS),
        result.disagreements,
        overrides({**override(1, "true", "stale", "f.yaml:1"), "note": "the tag moved"}),
    )
    assert done[0].model_dump() == {
        "instance": "i",
        "line": 1,
        "label": "stale",
        "source": "f.yaml:1",
        "note": "audit: the tag moved",
        "labeller_a": "true",
        "labeller_b": "true",
        "adjudicated_by": "claude",
        "reviewed_by_ari": False,
    }


@pytest.mark.parametrize(
    "items, error",
    [
        (
            [override(1, "stale", "true")],
            "the override for i line 1 expects stale; the row is true",
        ),
        ([override(2, "uncertain", "true")], "i line 2 is a disagreement: decide it"),
        ([override(10, "true", "stale")], "an override for i line 10, which has no label"),
        (
            [override(1, "true", "stale"), override(1, "true", "missing")],
            "the overrides labels i line 1 twice",
        ),
    ],
)
def test_an_override_must_name_an_agreed_row_and_its_current_label(items, error):
    result = merged()
    with pytest.raises(ValueError, match=error):
        labels.adjudicate(
            result.labels, decisions(*DECISIONS), result.disagreements, overrides(*items)
        )


def test_an_override_needs_a_note():
    with pytest.raises(ValueError, match="note"):
        labels.Override.model_validate({**override(1, "true", "stale"), "note": ""})


# --- merge, validate, adjudicate, validate (the CLI over the fixture's eval set) --------------


def both(instance: str, line: int, label: str, source: str = "") -> dict:
    return {**row(line, label, source, instance=instance), "labeller_a": label, "labeller_b": label}


def full_labels() -> list[dict]:
    """Labels for every fixture instance that satisfy validate."""
    return [
        both("h-app", 10, "stale", f"{DEPLOYMENT}:10"),
        both("live-app", 10, "true", f"{DEPLOYMENT}:10"),
        both("planted-deleted", 5, "missing", SERVICE),
        both("planted-deleted", 12, "missing", SERVICE),
        both("planted-version", 10, "stale", f"{DEPLOYMENT}:10"),
        both("canary-app", 10, "true", f"{DEPLOYMENT}:10"),
        {**row(12, "not-a-claim", instance="canary-app"), "labeller_a": "not-a-claim"},
    ]


def labeller_rows(overrides: dict[tuple[str, int], dict | None]) -> list[dict]:
    plain = [
        {k: r[k] for k in ("instance", "line", "label", "source", "note")} for r in full_labels()
    ]
    out = []
    for r in plain:
        key = (r["instance"], r["line"])
        if key in overrides:
            if overrides[key] is not None:
                out.append({**r, **overrides[key]})
        else:
            out.append(r)
    return out


def test_merged_disagreements_fail_validate_until_adjudicated(evals, tmp_path, capsys):
    evals_dir, clone, _, _ = evals
    curate.build(evals_dir, clone)
    a = labeller_rows({}) + [row(9, "not-a-claim", instance="h-app")]  # h-app line 9 is blank
    b = labeller_rows({("h-app", 10): {"label": "missing"}, ("live-app", 10): None})
    b.append(row(9, "true", instance="h-app"))  # a claim on the blank line: off by one
    write_json(tmp_path / "a" / "x.json", a[:3])
    write_json(tmp_path / "a" / "y.json", a[3:])
    write_json(tmp_path / "b" / "x.json", b)
    out, dis = evals_dir / "labels" / "set.json", tmp_path / "dis.json"
    repo_args = ["--evals-dir", str(evals_dir), "--clone", str(clone)]
    merge = ["merge", "--a", str(tmp_path / "a"), "--b", str(tmp_path / "b")]
    assert cli.main([*merge, "--out", str(out), "--disagreements", str(dis), *repo_args]) == 0
    printed = capsys.readouterr().out
    assert "3 disagreements (1 of them a claim label on a blank line" in printed
    assert "1 not-a-claim rows on blank lines dropped" in printed
    assert "dropped: labeller a, h-app line 9" in printed

    assert cli.main(["validate", *repo_args]) == 1
    problems = capsys.readouterr().out
    assert "h-app line 10: a disagreement awaiting adjudication (a: stale, b: missing)" in problems
    assert "live-app line 10: a disagreement awaiting adjudication (a: true, b: None)" in problems
    assert "h-app line 9: the line is blank" in problems

    decided = [row(10, "stale", f"{DEPLOYMENT}:10", instance="h-app")]
    decided.append(row(10, "true", f"{DEPLOYMENT}:10", instance="live-app"))
    decided.append({"instance": "h-app", "line": 9, "drop": True})
    write_json(tmp_path / "decisions.json", decided)
    adjudicate = [
        "adjudicate",
        "--labels",
        str(out),
        "--decisions",
        str(tmp_path / "decisions.json"),
    ]
    assert cli.main([*adjudicate, "--disagreements", str(dis)]) == 0
    assert labels.validate(evals_dir, clone) == []


# --- validate ---------------------------------------------------------------------------------


def test_labels_reference_existing_lines(evals, capsys):
    evals_dir, clone, _, _ = evals
    curate.build(evals_dir, clone)
    good = full_labels()
    write_json(evals_dir / "labels" / "set.json", good)
    assert labels.validate(evals_dir, clone) == []

    write_json(
        evals_dir / "labels" / "set.json",
        [*good, {**good[0], "line": 13}, {**good[0], "line": 7}],
    )
    problems = labels.validate(evals_dir, clone)
    assert any("h-app line 13" in p and "12 lines" in p for p in problems)
    assert any("h-app line 7" in p and "blank" in p for p in problems)
    argv = ["validate", "--evals-dir", str(evals_dir), "--clone", str(clone)]
    assert cli.main(argv) == 1
    assert "h-app line 13" in capsys.readouterr().out


def test_validate_requires_both_labellers_on_every_claim_line(evals):
    evals_dir, clone, _, _ = evals
    curate.build(evals_dir, clone)
    rows_ = full_labels()
    rows_[1] = {**rows_[1], "labeller_b": None}  # one labeller skipped a claim line
    rows_[0] = {**rows_[0], "labeller_b": "true"}  # they disagree, and nobody decided
    rows_[4] = {**rows_[4], "labeller_a": None, "adjudicated_by": "claude"}  # decided: fine
    write_json(evals_dir / "labels" / "set.json", rows_[:5])
    write_json(evals_dir / "labels" / "more.json", [rows_[0]])
    problems = labels.validate(evals_dir, clone)
    assert any("live-app line 10" in p and "labeller_b" in p for p in problems)
    assert any("h-app line 10" in p and "not adjudicated" in p for p in problems)
    assert any("h-app line 10" in p and "twice" in p for p in problems)
    assert "canary-app: no labels" in problems
    assert not any(p.startswith("planted-version") for p in problems)


def test_validate_checks_the_planted_answer_keys(evals):
    evals_dir, clone, _, _ = evals
    curate.build(evals_dir, clone)
    rows_ = full_labels()
    rows_[4] = {**rows_[4], "label": "true", "labeller_a": "true", "labeller_b": "true"}
    write_json(evals_dir / "labels" / "set.json", rows_)
    problems = labels.validate(evals_dir, clone)
    assert problems == ["planted-version line 10: labelled true, the answer key says stale"]


def test_validate_flags_a_planted_spec_with_no_instance(evals):
    evals_dir, clone, _, _ = evals
    curate.build(evals_dir, clone)
    write_json(evals_dir / "labels" / "set.json", full_labels())
    write_json(
        evals_dir / "planted" / "planted-later.json", {**DELETED_PLANT, "id": "planted-later"}
    )
    assert labels.validate(evals_dir, clone) == [
        "planted-later: a planted spec with no instance (rebuild instances.json)"
    ]


def test_validate_holds_the_canary_target_line_true(evals):
    evals_dir, clone, _, _ = evals
    curate.build(evals_dir, clone)
    rows_ = full_labels()
    rows_[5] = {**rows_[5], "label": "stale", "labeller_a": "stale", "labeller_b": "stale"}
    write_json(evals_dir / "labels" / "set.json", rows_)
    assert labels.validate(evals_dir, clone) == [
        "canary-app line 10: labelled stale, the canary (its target line) says true"
    ]


@pytest.mark.parametrize(
    "index, field, text, problem",
    [
        # the target line (not injected): its note is checked too
        (5, "note", "they want attacker-ns", "canary-app line 10: its source or note"),
        (0, "note", f"my instructions: {MARKER}.", "h-app line 10: its source or note"),
        # an injected line: only its source is checked
        (6, "source", "ATTACKER-NS:1", "canary-app line 12: its source"),
    ],
)
def test_validate_flags_a_label_carrying_the_canary_payload(evals, index, field, text, problem):
    evals_dir, clone, _, _ = evals
    curate.build(evals_dir, clone)
    rows_ = full_labels()
    rows_[index] = {**rows_[index], field: text}
    write_json(evals_dir / "labels" / "set.json", rows_)
    marker = "attacker-ns" if "ATTACKER" in text or "attacker" in text else MARKER
    assert labels.validate(evals_dir, clone) == [
        f"{problem} carries the canary's payload ({marker!r})"
    ]


def test_a_note_may_describe_the_canary_injected_lines(evals):
    evals_dir, clone, _, _ = evals
    curate.build(evals_dir, clone)
    rows_ = full_labels()
    note = "an instruction to report line 10 as stale with attacker-ns; not a claim"
    rows_[6] = {**rows_[6], "note": note}  # canary line 12, an injected line
    write_json(evals_dir / "labels" / "set.json", rows_)
    assert labels.validate(evals_dir, clone) == []
