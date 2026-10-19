"""Front matter parsing, with the shapes real docs in arigsela/kubernetes use."""

import pytest

from docs_checker.frontmatter import FrontMatterError, parse_front_matter

PLAIN = """---
type: "Kubernetes App Runbook"
title: "PostgreSQL — Runbook"
last_reviewed: 2026-10-11
status: stable
tags: [database, stateful]
sources:
  - base-apps/postgresql/deployments.yaml
  - base-apps/postgresql/pvc.yaml
  - scripts/provision-kagent-1-0-vault.sh
---
# Body
"""

MIXED = """---
title: "kagent"
last_reviewed: 2026-10-11
sources:
  - base-apps/kagent.yaml
  - id: build-orchestrator
    resource: base-apps/kagent/agent-templates/build-orchestrator.yaml
    title: build-orchestrator AgentTemplate (sub-agent hand-off)
  - base-apps/kagent/agent-templates/
  - id: upstream
    resource: https://github.com/kagent-dev/substrate/blob/v0.5.0-alpha2/docs/postgres.md
    title: upstream doc
  - https://example.com/page
---
body
"""


def test_four_source_forms():
    meta = parse_front_matter("base-apps/kagent/docs.md", MIXED)
    assert [(s.kind, s.value) for s in meta.sources] == [
        ("path", "base-apps/kagent.yaml"),
        ("map", "base-apps/kagent/agent-templates/build-orchestrator.yaml"),
        ("dir", "base-apps/kagent/agent-templates/"),
        ("url", "https://github.com/kagent-dev/substrate/blob/v0.5.0-alpha2/docs/postgres.md"),
        ("url", "https://example.com/page"),
    ]
    assert meta.last_reviewed == "2026-10-11"
    assert meta.body_start == 15


def test_source_lines_point_at_the_front_matter_line():
    meta = parse_front_matter("base-apps/postgresql/runbook.md", PLAIN)
    lines = PLAIN.splitlines()
    for source in meta.sources:
        assert lines[source.line - 1].strip() == f"- {source.value}"
    assert lines[meta.body_start - 1] == "# Body"
    mixed = parse_front_matter("x.md", MIXED)
    assert MIXED.splitlines()[mixed.sources[1].line - 1].strip().startswith("- id: build-orch")


def test_no_sources_is_an_empty_list():
    assert parse_front_matter("x.md", "---\ntitle: t\n---\nbody\n").sources == []


@pytest.mark.parametrize(
    "text, reason",
    [
        ("# just a body\n", "does not start with ---"),
        ("---\nsources: [a\n", "not closed"),
        ("---\nsources: [a\n---\n", "not valid YAML"),
        ("---\n- a\n- b\n---\n", "not a mapping"),
        ("---\nsources: nope\n---\n", "sources is not a list"),
        ("---\nsources:\n  - 3\n  - [a]\n---\n", "line 4"),
        ("---\nsources:\n  - {id: x}\n---\n", "no resource"),
        ("---\n" + "# " + "x" * 70000 + "\n---\n", "over 65536 bytes"),
    ],
)
def test_malformed_front_matter_raises_with_reason(text, reason):
    with pytest.raises(FrontMatterError) as err:
        parse_front_matter("x.md", text)
    assert reason in err.value.reason


def test_lines_are_counted_by_newline_only():
    # The checker numbers a doc's lines with text.split("\n") everywhere; a NEL, a
    # form feed or U+2028 inside a line (which str.splitlines, and YAML for the
    # first and last, break at) must not shift body_start or a source's line.
    text = '---\ntitle: "a\x85b"\nsources:\n  - a.yaml\n---\nbody   \x0c here\nlast\n'
    meta = parse_front_matter("x.md", text)
    lines = text.split("\n")
    assert meta.body_start == 6 and lines[meta.body_start - 1] == "body   \x0c here"
    assert meta.sources[0].line == 4 and lines[meta.sources[0].line - 1] == "  - a.yaml"
    assert len(text.splitlines()) != len(lines)  # the two countings really differ here
