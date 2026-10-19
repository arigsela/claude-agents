"""The render check on its own (ruling G5), before any per-line rule: a fix may change
plain text and code, never a doc's structure."""

import sys

import pytest

from docs_checker.gate import apply_fix
from docs_checker.render import (
    MAX_RENDER_LINE_CHARS,
    structure,
    structure_refusal,
    views,
)
from tests.markdown_cases import (
    BLIND_SPOTS,
    CONTROL,
    CONTROL_LINES,
    FLIP_IDS,
    FLIPS,
    FRONT_MATTER,
    HIDDEN,
    OPEN_TAG_QUOTE,
    REPRO_COMMENT_NESTING,
    REPRO_TOGGLE,
    flip_case,
)


def refusal(case) -> str | None:
    lines, start, end, new = case
    return structure_refusal(lines, apply_fix(lines, start, end, new))


@pytest.mark.parametrize(("name", "old", "new"), FLIPS, ids=FLIP_IDS)
def test_every_ruled_block_kind_flip_changes_the_structure(name, old, new):
    assert refusal(flip_case(old, new)) == "the fix changes the doc's structure, not only its text"


def test_both_review_repros_change_the_structure():
    assert refusal(REPRO_COMMENT_NESTING) is not None
    for case in REPRO_TOGGLE.values():
        assert refusal(case) is not None


@pytest.mark.parametrize("name", list(BLIND_SPOTS))
def test_each_parser_blind_spot_is_refused(name):
    assert refusal(BLIND_SPOTS[name]) is not None


def test_raw_html_left_open_is_refused_even_when_only_text_changes():
    lines, start, end, new = OPEN_TAG_QUOTE
    patched = apply_fix(lines, start, end, new)
    assert structure("\n".join(lines)).digest == structure("\n".join(patched)).digest
    assert structure_refusal(lines, patched) == "the doc's raw HTML leaves a tag or comment open"
    closed = [line.replace(' title="', ">") for line in lines]  # the same doc, tag closed
    assert structure_refusal(closed, apply_fix(closed, start, end, new)) is None


@pytest.mark.parametrize(
    ("left_open", "closed"),
    [
        ('<div><a href="https://evil.example/u"', '<div><a href="https://evil.example/u">'),
        ('<div><img src=x alt="a', '<div><img src=x alt="a">'),  # an attribute value
        ("<div>\n<!-- note", "<div>\n<!-- note -->"),
        ("<div>\n<![CDATA[ x", "<div>\n<![CDATA[ x ]]>"),
        ("<div>\n</di", "<div>\n</div>"),
        ("Text <span\n\nmore", "Text <span>\n\nmore"),  # inline: not HTML until closed
    ],
)
def test_open_raw_html_is_noticed(left_open, closed):
    assert structure(left_open).open_html is not left_open.startswith("Text")
    assert not structure(closed).open_html


@pytest.mark.parametrize("line", CONTROL_LINES)
def test_a_version_fix_in_ordinary_markdown_keeps_the_structure(line):
    old = CONTROL[line - 1]
    assert (
        structure_refusal(CONTROL, apply_fix(CONTROL, line, line, old.replace("0.30.1", "0.31.0")))
        is None
    )


def test_a_fix_inside_raw_html_is_refused():
    lines = FRONT_MATTER + ["", "<div>Vault 0.30.1</div>", "", "End."]
    patched = apply_fix(lines, 6, 6, "<div>Vault 0.31.0</div>")
    assert structure_refusal(lines, patched) is not None


@pytest.mark.parametrize(
    ("before", "after", "same"),
    [
        # GitHub-style linkify: a link target is structure, a bare domain is text
        ("see https://a.example/x now", "see https://a.example/y now", False),
        ("see www.a.example/x now", "see www.a.example/y now", False),
        ("see xhttps://a.example/x now", "see x https://a.example/x now", False),
        ("pulls ghcr.io/a/b:1.2 now", "pulls ghcr.io/a/b:1.3 now", True),
        ("at grafana.example.com now", "at grafana2.example.com now", True),
        # code and plain text are free; a fence's info string is not
        ("```yaml\nv: 1\n```", "```yaml\nv: 2\n```", True),
        ("```yaml\nv: 1\n```", "```yml\nv: 1\n```", False),
        ("`v1` here", "`v2` here", True),
        ("    v1", "    v2", True),
        ("![Vault 0.30.1](p.png)", "![Vault 0.31.0](p.png)", False),  # alt text: not free
        ("a [x](https://a.example/x) b", "a [x](https://a.example/y) b", False),
        # a scheme markdown-it would refuse to link is still a link's target
        ("a [x](javascript:a) b", "a [x](javascript:b) b", False),
    ],
)
def test_what_counts_as_structure(before, after, same):
    assert (structure(before).digest == structure(after).digest) is same


def test_reaching_the_nesting_limit_is_noticed_and_refused():
    assert structure(">" * 21 + " x", max_nesting=20).nesting_limit  # a block level
    assert not structure(">" * 19 + " x", max_nesting=20).nesting_limit
    assert structure("[" * 25 + "x", max_nesting=20).nesting_limit  # skipping a label
    assert structure("[a](u)", max_nesting=1).nesting_limit  # parsing a link's text
    assert not structure("plain", max_nesting=1).nesting_limit
    lines = FRONT_MATTER + ["", ">" * 25 + " Install it"]
    assert structure_refusal(lines, lines, max_nesting=20) == (
        "the doc nests deeper than the render check reads"
    )
    # The deployed limit reads it, so the same doc passes.
    assert structure_refusal(lines, lines) is None


@pytest.fixture(params=[1000, 2500], ids=["python-default", "kagent-core"])
def recursion_limit(request):
    """Python's default recursion limit, and the one kagent.core sets when the image
    imports it: what a very deep doc does depends on it, and both must fail closed."""
    before = sys.getrecursionlimit()
    sys.setrecursionlimit(request.param)
    yield request.param
    sys.setrecursionlimit(before)


def test_very_deep_nesting_raises_or_reaches_the_limit(recursion_limit):
    with pytest.raises(RecursionError):
        structure(">" * 1200 + " x")
    lists = FRONT_MATTER + ["", "- " * 600 + "x"]  # two levels per list
    if recursion_limit == 1000:
        with pytest.raises(RecursionError):
            structure_refusal(lists, lists)
    else:
        assert structure("\n".join(lists)).nesting_limit
        assert structure_refusal(lists, lists) == "the doc nests deeper than the render check reads"


@pytest.mark.parametrize("opening", ["---", "\ufeff---"])
def test_front_matter_cannot_hide_the_body_from_the_render_check(opening):
    # As plain CommonMark the indented fence inside the front matter swallows the whole
    # body into one fence (free content), so that view sees no change; GitHub renders
    # the body after the front matter, which the second view checks.
    lines = [opening, "sources:", "  - base-apps/vault/values.yaml", "notes: |", "  ```", "---"]
    lines += HIDDEN + ["", "~~~", "~~~ a", "[docs] pins chart 0.30.1."]
    patched = apply_fix(lines, 10, 12, "~~~\n~~~ \n[docs] pins chart 0.31.0.")
    whole, body = views(lines)
    patched_whole, patched_body = views(patched)
    assert structure(whole).digest == structure(patched_whole).digest
    assert structure(body).digest != structure(patched_body).digest
    assert structure_refusal(lines, patched) is not None


def test_a_doc_with_a_line_too_long_to_render_check_is_refused():
    lines = FRONT_MATTER + ["", "x" * (MAX_RENDER_LINE_CHARS + 1)]
    assert structure_refusal(lines, lines) == "the doc is too long to render-check"
    lines = FRONT_MATTER + ["", "x" * MAX_RENDER_LINE_CHARS]
    assert structure_refusal(lines, lines) is None
