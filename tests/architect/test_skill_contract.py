"""Contract checks on the architect skill's text.

The skill's behaviour lives in SKILL.md prose, so these tests pin the rules that
past regressions broke: the Codex review step must not skip silently, must work
outside a git repository, and the plugin version must match everywhere it is
written. How agents follow the text is tested separately with agent runs.
"""

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SKILL = REPO / "skills/architect/skills/architect/SKILL.md"


def _version(text: str) -> str:
    match = re.search(r'^version: "([^"]+)"', text, re.MULTILINE)
    assert match, "no version in frontmatter"
    return match.group(1)


def _codex_step() -> str:
    text = SKILL.read_text()
    start = text.index("5. **Get an independent challenge")
    end = text.index("6. **Deliver**", start)
    return " ".join(text[start:end].split())


def test_versions_match_everywhere() -> None:
    version = _version(SKILL.read_text())
    assert _version((REPO / "skills/architect/SKILL.md").read_text()) == version
    plugin = json.loads(
        (REPO / "skills/architect/.claude-plugin/plugin.json").read_text()
    )
    assert plugin["version"] == version
    catalog = json.loads((REPO / "skills/skills-catalog.json").read_text())
    assert catalog["skills"]["architect"]["version"] == version
    assert (
        f"| [architect](./architect/) | {version} |"
        in (REPO / "skills/README.md").read_text()
    )


def test_codex_step_is_never_skipped_silently() -> None:
    step = _codex_step()
    assert "without comment" not in step
    assert "(optional)" not in step
    assert "Whenever you don't run it, say why in one line of your reply" in step


def test_codex_step_runs_outside_a_git_repository() -> None:
    step = _codex_step()
    assert "`git rev-parse --show-toplevel` fails" in step
    assert "`git init -q <dir>`" in step
    assert "save the draft there as `draft.md`" in step
    assert "starting each with `cd <dir> &&`" in step
    assert "Delete that directory afterwards." in step


def test_codex_step_eligibility_and_disclosure() -> None:
    step = _codex_step()
    assert "design, review or recommendation someone else will act on" in step
    assert "when the `codex` skill is in your list of available skills" in step
    assert "ask the user before sending it" in step
    assert "**Independent review** line" in step
