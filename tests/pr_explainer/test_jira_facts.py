# Run: uv run --with pyyaml --with "pathspec<1" python -m unittest discover -s tests/pr_explainer
"""Ticket key detection in pr-explainer's collect.py."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills/pr-explainer/skills/pr-explainer/scripts"))
import collect  # noqa: E402


def pr(branch: str = "main", title: str = "", body: str = "") -> dict:
    return {"head": {"ref": branch}, "title": title, "body": body}


class JiraKeyTest(unittest.TestCase):
    def key(self, p: dict) -> str | None:
        # Without acli the note names the key it found, so no Jira call is made.
        with mock.patch.object(collect.shutil, "which", return_value=None):
            jira, notes = collect.jira_facts(p)
        self.assertIsNone(jira)
        text = notes[0]["text"]
        return None if text.startswith("No ") else text.split(" ", 1)[0]

    def test_ifs_key_in_branch(self):
        self.assertEqual(self.key(pr(branch="feature/IFS-314-repoint")), "IFS-314")

    def test_dx_key_in_body(self):
        self.assertEqual(self.key(pr(title="fix: forward buildContext", body="Fixes DX-593.")), "DX-593")

    def test_lowercase_dx_key_is_upper_cased(self):
        self.assertEqual(self.key(pr(branch="bugfix/dx-593-build-context")), "DX-593")

    def test_branch_wins_over_body(self):
        self.assertEqual(self.key(pr(branch="feature/IFS-1-a", body="see DX-2")), "IFS-1")

    def test_other_projects_are_ignored(self):
        self.assertIsNone(self.key(pr(branch="feature/PLAT-8108-a", body="ADX-12 and DX-abc")))


if __name__ == "__main__":
    unittest.main()
