"""blog-diagrams: the skill doc points at files that exist, and every example passes the layout check."""
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ROOT / "skills" / "blog-diagrams"
BASE = PLUGIN / "skills" / "blog-diagrams"
SKILL = BASE / "SKILL.md"
CHROMES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
]


def frontmatter(text):
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    return dict(re.findall(r"^(\w+): (.*)$", m.group(1), re.M)) if m else {}


class SkillDocTest(unittest.TestCase):
    def test_frontmatter_matches_plugin(self):
        fm = frontmatter(SKILL.read_text())
        plugin = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text())
        self.assertEqual(fm["name"], "blog-diagrams")
        self.assertEqual(fm["version"], plugin["version"])
        self.assertTrue(fm["description"].startswith("Use when"))

    def test_named_paths_exist(self):
        text = SKILL.read_text() + (BASE / "references" / "spec.md").read_text()
        paths = set(re.findall(r"<base>/([\w./-]+)", text))
        paths |= {f"examples/{n}" for n in re.findall(r"`([\w-]+\.json)`", SKILL.read_text())}
        self.assertIn("scripts/render.mjs", paths)
        for p in paths:
            self.assertTrue((BASE / p.rstrip("/")).exists(), p)

    def test_marketplace_entry(self):
        market = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text())
        sources = {p["name"]: p["source"] for p in market["plugins"]}
        self.assertEqual(sources.get("blog-diagrams"), "./skills/blog-diagrams")

    def test_engine_keeps_its_spec_placeholder(self):
        self.assertIn("/*__SPEC__*/{}", (BASE / "engine" / "engine.html").read_text())


@unittest.skipUnless(shutil.which("node") and any(Path(c).exists() for c in CHROMES), "needs node and Chrome")
class ExamplesRenderTest(unittest.TestCase):
    def test_every_example_has_no_layout_problems(self):
        with tempfile.TemporaryDirectory() as tmp:
            for spec in sorted((BASE / "examples").glob("*.json")):
                with self.subTest(example=spec.name):
                    copy = Path(tmp) / spec.name
                    shutil.copy(spec, copy)
                    r = subprocess.run(["node", str(BASE / "scripts" / "render.mjs"), str(copy), "--still"],
                                       capture_output=True, text=True, timeout=120)
                    self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                    self.assertIn("  0 problems", r.stdout)


if __name__ == "__main__":
    unittest.main()
