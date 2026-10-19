import datetime as dt

from docs_checker.dismissals import is_dismissed, parse_dismissals
from tests.test_state import finding

TODAY = dt.date(2026, 10, 19)


def test_a_valid_file_parses():
    text = """
version: 1
dismissed:
  - {doc: docs/a.md, claim: "Uses nginx 1.2", evidence_hash: h, reason: ok, date: 2026-10-01}
  - {doc: docs/a.md, claim: other, expires: "2027-01-01", reason: ok, date: "2026-10-01"}
"""
    items, errors = parse_dismissals(text)
    assert errors == [] and len(items) == 2
    assert items[0].date == "2026-10-01" and items[1].evidence_hash is None


def test_dismissal_without_hash_needs_expiry():
    text = "version: 1\ndismissed:\n  - {doc: d.md, claim: c, reason: r, date: 2026-10-01}\n"
    items, errors = parse_dismissals(text)
    assert items == [] and "needs 'expires'" in errors[0]


def test_invalid_dismissals_are_reported_not_applied():
    text = """
version: 1
dismissed:
  - not-a-mapping
  - {doc: docs/a.md, claim: x, evidence_hash: h, reason: r, date: nope}
  - {doc: docs/a.md, claim: "uses nginx 1.2", evidence_hash: h, reason: r, date: 2026-10-01}
"""
    items, errors = parse_dismissals(text)
    assert len(items) == 1 and len(errors) == 2
    bad_only = "version: 1\ndismissed:\n  - {doc: docs/a.md, claim: 'Uses nginx 1.2', reason: r, date: 2026-10-01}\n"
    items, _ = parse_dismissals(bad_only)
    assert not is_dismissed(finding(), items, TODAY)


def test_missing_and_malformed_files():
    assert parse_dismissals(None) == ([], [])
    items, errors = parse_dismissals("version: 1\ndismissed: [unclosed")
    assert items == [] and len(errors) == 1
    assert parse_dismissals("version: 2\n")[0] == []


def test_matching_rules():
    f = finding()  # claim "Uses  nginx 1.2", evidence_hash "h", doc docs/a.md

    def d(**kw):
        body = ", ".join(f"{k}: '{v}'" for k, v in kw.items())
        base = f"version: 1\ndismissed:\n  - {{{body}}}\n"
        return parse_dismissals(base)[0]

    common = {"doc": "docs/a.md", "claim": "USES NGINX   1.2", "reason": "r", "date": "2026-10-01"}
    assert is_dismissed(f, d(**common, evidence_hash="h"), TODAY)
    assert not is_dismissed(f, d(**common, evidence_hash="other"), TODAY)
    assert not is_dismissed(f, d(**{**common, "doc": "docs/b.md"}, evidence_hash="h"), TODAY)
    assert not is_dismissed(f, d(**{**common, "claim": "different"}, evidence_hash="h"), TODAY)
    assert is_dismissed(f, d(**common, expires="2026-10-19"), TODAY)
    assert not is_dismissed(f, d(**common, expires="2026-10-18"), TODAY)
