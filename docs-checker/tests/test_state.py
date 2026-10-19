import pytest
from pydantic import ValidationError

from docs_checker.state import (
    Claim,
    DocOutcome,
    Finding,
    Window,
    evidence_hash,
    merge_outcomes,
)  # fmt: skip


def claim(**kw):
    base = {
        "doc": "docs/a.md", "line_start": 3, "line_end": 4, "text": "Uses  nginx 1.2",
        "kind": "version", "keys": ["nginx"], "values": ["1.2"],
    }  # fmt: skip
    return Claim(**{**base, **kw})


def finding(**kw):
    base = {
        "id": "f", "instance": "i", "commit": "c1", "doc": "docs/a.md",
        "line_start": 3, "line_end": 4, "claim": claim(), "verdict": "stale",
        "evidence_hash": "h", "confidence": 0.9, "old_text": "1.2", "replacement": "1.3",
    }  # fmt: skip
    return Finding(**{**base, **kw})


def outcome(doc, status="checked", **kw):
    return DocOutcome(doc=doc, commit="c1", status=status, **kw)


def test_claim_id_and_semantic_key():
    c = claim()
    assert len(c.id) == 16
    assert c.id == claim().id
    assert c.id != claim(line_start=9).id
    # whitespace and case do not change the key; checker version and evidence do
    assert c.semantic_key("v1", "e") == claim(text="uses nginx 1.2").semantic_key("v1", "e")
    assert c.semantic_key("v1", "e") != c.semantic_key("v2", "e")
    assert c.semantic_key("v1", "e") != c.semantic_key("v1", "other")
    assert c.semantic_key("v1", "e") != claim(values=["1.3"]).semantic_key("v1", "e")
    assert c.semantic_key("v1", "e") != claim(kind="image").semantic_key("v1", "e")
    # location is not part of the semantic key
    assert c.semantic_key("v1", "e") == claim(line_start=9, doc="x.md").semantic_key("v1", "e")


def test_evidence_hash_depends_on_every_window_field_and_order():
    a, b = Window(source="s", start=1, end=2, text="t"), Window(
        source="s2", start=1, end=2, text="t"
    )
    assert evidence_hash([a, b]) != evidence_hash([b, a])
    assert evidence_hash([a]) != evidence_hash([a.model_copy(update={"end": 3})])
    assert evidence_hash([a]) != evidence_hash([a.model_copy(update={"text": "u"})])
    assert evidence_hash([a]) == evidence_hash([a.model_copy()])


def test_action_digest_changes_with_replacement_or_commit():
    f = finding()
    assert len(f.action_digest) == 24
    assert f.action_digest == finding().action_digest
    assert f.action_digest != finding(replacement="1.4").action_digest
    assert f.action_digest != finding(commit="c2").action_digest
    assert f.action_digest != finding(evidence_hash="h2").action_digest
    assert f.model_dump()["action_digest"] == f.action_digest


def test_merge_outcomes_replaces_by_doc():
    old = {"a": outcome("a", "failed"), "b": outcome("b")}
    new = {"a": outcome("a", "checked")}
    merged = merge_outcomes(old, new)
    assert merged["a"].status == "checked" and merged["b"].status == "checked"
    assert old["a"].status == "failed" and set(old) == {"a", "b"} and set(new) == {"a"}
    assert merge_outcomes(None, new) == new


def test_claim_requires_a_value():
    with pytest.raises(ValidationError):
        claim(values=[])
    with pytest.raises(ValidationError):
        claim(values=list("abcdef"))
    with pytest.raises(ValidationError):
        claim(keys=list("abcdef"))
    with pytest.raises(ValidationError):
        claim(text="x" * 401)


def test_tool_events_are_truncated_not_rejected():
    ev = {"name": "n", "server": "", "args": {}, "decision": "allow", "action": "a",
          "result_chars": 0, "status": "ok", "ok": True, "evidence": []}  # fmt: skip
    events = [{**ev, "name": str(i)} for i in range(60)]
    out = outcome("a", tool_events=events)
    assert [e["name"] for e in out.tool_events] == [str(i) for i in range(50)]
