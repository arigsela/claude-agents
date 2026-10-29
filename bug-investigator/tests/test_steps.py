"""The UI step format: validation, one-line descriptions, repro files."""

import json

import pytest

from bug_investigator import steps

CLICK = {
    "do": "click",
    "target": {"role": "button", "name": "Done", "within": {"css": ".card", "text": "Update the cookie banner copy"}},
}


def test_valid_click_with_within():
    assert steps.validate([CLICK]) == []
    assert steps.validate([CLICK], fails_at=1) == []


def test_target_needs_exactly_one_locator():
    probs = steps.validate([{"do": "click", "target": {"role": "button", "label": "x"}}])
    assert probs == ["step 1: target needs exactly one of role, label, placeholder, text"]
    assert steps.validate([{"do": "click", "target": {}}])
    assert steps.validate([{"do": "click"}])
    assert steps.validate([{"do": "click", "target": {"text": "x", "name": "y"}}])  # name only with role


def test_goto_rejects_other_origins():
    for bad in ("//evil.example", "https://x", "evil"):
        assert steps.validate([{"do": "goto", "value": bad}]), bad
    assert steps.validate([{"do": "goto", "value": "/"}]) == []
    assert steps.validate([{"do": "goto", "value": "/", "target": {"text": "x"}}])


def test_goto_rejects_backslash_and_control_characters():
    # A browser normalises "/\evil.example" and "/<tab>/evil.example" to //evil.example.
    for bad in ("/\\evil.example", "/\t/evil.example", "/a\nb", "/\x00", "/\x1f", "/\x7f"):
        assert steps.validate([{"do": "goto", "value": bad}]) == [
            "step 1: goto value must not contain a backslash or control characters"
        ], repr(bad)
    assert steps.validate([{"do": "goto", "value": "/tasks?q=a%5Cb&x=é"}]) == []


def test_value_rules():
    assert steps.validate([{"do": "fill", "target": {"label": "Title"}}])  # value missing
    assert steps.validate([{"do": "click", "target": {"text": "x"}, "value": "v"}])  # value forbidden
    assert steps.validate([{"do": "expect_text", "target": {"text": "x"}, "value": "ok"}]) == []


def test_limits():
    ok = {"do": "click", "target": {"text": "x"}}
    assert any("15" in p for p in steps.validate([ok] * 16))
    assert steps.validate([ok] * 15) == []
    long = {"do": "fill", "target": {"label": "t"}, "value": "a" * 201}
    assert steps.validate([long])
    assert steps.validate([dict(ok, note="n" * 201)])
    assert steps.validate([]) == ["steps must be a non-empty list"]


def test_fails_at_range():
    s = [CLICK, CLICK]
    assert steps.validate(s, fails_at=None) == []
    for bad in (0, 3, "2", True):
        assert steps.validate(s, fails_at=bad), bad


def test_unknown_keys_rejected():
    assert steps.validate([dict(CLICK, extra=1)])
    assert steps.validate([{"do": "click", "target": {"text": "x", "css": "a"}}])
    assert steps.validate([{"do": "click", "target": {"text": "x", "within": {"css": "a", "text": "b", "x": 1}}}])
    assert steps.validate([{"do": "click", "target": {"text": "x", "within": {"css": "a"}}}])
    assert steps.validate([{"do": "dance", "target": {"text": "x"}}])
    assert steps.validate(["click"])


def test_describe_sentences():
    t = {"role": "button", "name": "Done"}
    cases = [
        (CLICK, 'click button "Done" in .card "Update the cookie banner copy"'),
        ({"do": "click", "target": {"role": "link"}}, "click link"),
        ({"do": "fill", "target": {"label": "Title"}, "value": "Hi"}, 'fill the field labelled "Title" with "Hi"'),
        ({"do": "select", "target": {"placeholder": "Status"}, "value": "Done"},
         'select "Done" in the field with placeholder "Status"'),
        ({"do": "press", "target": {"text": "Add"}, "value": "Enter"}, 'press Enter in the text "Add"'),
        ({"do": "goto", "value": "/board"}, "open /board"),
        ({"do": "expect_visible", "target": t}, 'expect button "Done" to be visible'),
        ({"do": "expect_absent", "target": t}, 'expect no button "Done"'),
        ({"do": "expect_text", "target": {"text": "a"}, "value": "b"}, 'expect the text "a" to contain "b"'),
    ]
    for step, want in cases:
        assert steps.describe(step) == want


def _write(tmp_path, obj):
    p = tmp_path / "r.json"
    p.write_text(json.dumps(obj))
    return str(p)


def test_load_repro_requires_title_and_steps(tmp_path):
    good = {"title": "Done works", "issue": 7, "steps": [CLICK]}
    assert steps.load_repro(_write(tmp_path, good)) == good
    assert steps.load_repro(_write(tmp_path, {"title": "t", "steps": [CLICK]}))["title"] == "t"
    for bad in ({"steps": [CLICK]}, {"title": "", "steps": [CLICK]}, {"title": "t"},
                {"title": "t", "steps": []}, {"title": "t", "issue": "7", "steps": [CLICK]}):
        with pytest.raises(ValueError, match="r.json: "):
            steps.load_repro(_write(tmp_path, bad))
