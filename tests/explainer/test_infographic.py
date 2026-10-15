# Run: uv run --with pyyaml --with "pathspec<1" python -m unittest discover -s tests/explainer
"""infographic.py: the brief Codex sees, skipping without Codex, and slides on the page."""
from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills/explainer/scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import infographic  # noqa: E402
import render  # noqa: E402
from test_plan_mode import GOOD_PLAN, PLAN_FACTS  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 32

# Stands in for `codex exec`: writes slide-01.png into the -C directory, never touches the network.
FAKE_CODEX = """#!/bin/sh
while [ "$1" != "-C" ]; do shift; done
printf '\\211PNG\\r\\n\\032\\n' > "$2/slide-01.png"
echo saved
"""


class BriefTest(unittest.TestCase):
    def test_brief_holds_verified_text_only(self):
        text = infographic.brief(PLAN_FACTS, GOOD_PLAN, 3)
        self.assertIn("# EDP SageMaker MVP (plan, in o/edp-terraform)", text)
        self.assertIn("- [would_change] Give SageMaker its own deploy role", text)
        self.assertIn("Who approves prod applies?", text)
        self.assertIn("At most 3 landscape 16:9 slides", text)
        self.assertNotIn("terraform/cicd/iam.tf", text)  # refs and facts stay out

    def test_brief_masks_secret_looking_values(self):
        expl = {**GOOD_PLAN, "tldr": "password: hunter2hunter2"}
        self.assertNotIn("hunter2hunter2", infographic.brief(PLAN_FACTS, expl, 3))


class RunTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        (self.tmp / "facts.json").write_text(json.dumps(PLAN_FACTS))
        (self.tmp / "explainer.json").write_text(json.dumps(GOOD_PLAN))

    def run_main(self, facts=None) -> int:
        if facts is not None:
            (self.tmp / "facts.json").write_text(json.dumps(facts))
        argv = ["infographic.py", "--facts", str(self.tmp / "facts.json"), "--explainer", str(self.tmp / "explainer.json"),
                "--out-dir", str(self.tmp / "out"), "--timeout", "30"]
        with mock.patch.object(sys, "argv", argv):
            return infographic.main()

    def test_skips_without_codex(self):
        with mock.patch.object(infographic.shutil, "which", return_value=None):
            self.assertEqual(self.run_main(), 2)
        self.assertFalse((self.tmp / "out").exists())

    def test_skips_without_the_skill(self):
        with mock.patch.object(infographic.shutil, "which", return_value="/bin/codex"), \
             mock.patch.object(infographic, "find_skill", return_value=None):
            self.assertEqual(self.run_main(), 2)

    def test_skips_pr_pages(self):
        self.assertEqual(self.run_main({**PLAN_FACTS, "mode": "pr"}), 2)

    def test_fake_codex_writes_a_slide(self):
        codex = self.tmp / "codex"
        codex.write_text(FAKE_CODEX)
        codex.chmod(codex.stat().st_mode | stat.S_IEXEC)
        with mock.patch.object(infographic.shutil, "which", return_value=str(codex)), \
             mock.patch.object(infographic, "find_skill", return_value=self.tmp):
            self.assertEqual(self.run_main(), 0)
        manifest = json.loads((self.tmp / "out/manifest.json").read_text())
        self.assertEqual([Path(p).name for p in manifest["slides"]], ["slide-01.png"])
        self.assertEqual(manifest["codex"], "exit 0")
        self.assertTrue((self.tmp / "out/brief.md").is_file())

    def test_no_slide_is_exit_1(self):
        codex = self.tmp / "codex"
        codex.write_text("#!/bin/sh\nexit 3\n")
        codex.chmod(codex.stat().st_mode | stat.S_IEXEC)
        with mock.patch.object(infographic.shutil, "which", return_value=str(codex)), \
             mock.patch.object(infographic, "find_skill", return_value=self.tmp):
            self.assertEqual(self.run_main(), 1)
        self.assertEqual(json.loads((self.tmp / "out/manifest.json").read_text())["codex"], "exit 3")


class PageTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.png = Path(self._tmp.name) / "slide-01.png"
        self.png.write_bytes(PNG)

    def test_slides_are_inlined_after_tldr(self):
        page = render.render(PLAN_FACTS, GOOD_PLAN, [], infographic=[str(self.png)])
        self.assertIn('src="data:image/png;base64,', page)
        self.assertIn("They are not a fact source", page)
        self.assertLess(page.index("At a glance"), page.index("Background"))

    def test_non_png_missing_and_oversize_files_are_left_out(self):
        bad = Path(self._tmp.name) / "x.png"
        bad.write_bytes(b"not a png")
        with mock.patch.object(render, "MAX_INFOGRAPHIC_BYTES", len(PNG) - 1):
            page = render.render(PLAN_FACTS, GOOD_PLAN, [], infographic=[str(bad), "/nope.png", str(self.png)])
        self.assertNotIn("At a glance", page)

    def test_pr_pages_never_show_slides(self):
        self.assertEqual(render.infographic_html([]), "")


if __name__ == "__main__":
    unittest.main()
