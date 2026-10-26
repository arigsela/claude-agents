import json
import re
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ROOT / "skills" / "readiness"
SKILL = PLUGIN / "skills" / "production-readiness" / "SKILL.md"


def frontmatter(text):
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    return yaml.safe_load(m.group(1)) if m else None


class SkillDocTest(unittest.TestCase):
    def test_frontmatter(self):
        fm = frontmatter(SKILL.read_text())
        self.assertEqual(fm["name"], "production-readiness")
        self.assertEqual(fm["version"], "0.1.0")
        self.assertEqual(fm["requires"]["tools"], ["git", "gh", "uv", "kubectl"])
        self.assertNotIn("model", fm)

    def test_named_scripts_exist(self):
        names = set(re.findall(r"\$\{CLAUDE_PLUGIN_ROOT\}/scripts/(\w+\.py)", SKILL.read_text()))
        self.assertEqual(names, {"collect.py", "evaluate.py", "verify.py", "render.py"})
        for n in names:
            self.assertTrue((PLUGIN / "scripts" / n).is_file(), n)

    def test_bars_cover_every_judgment_check(self):
        text = SKILL.read_text()
        checks = yaml.safe_load((PLUGIN / "checks.yaml").read_text())["checks"]
        for c in checks:
            if c["kind"] == "judgment":
                self.assertIn(f"`{c['id']}`", text, c["id"])

    def test_untrusted_data_rule_names_every_input(self):
        text = SKILL.read_text()
        rule = re.search(r"2\. \*\*Everything you read is untrusted.*?(?=\n3\. )", text, re.S).group(0)
        for needle in ("facts.json", "results.json", "alert rule", "catalog", "scorecard",
                       "CVE", "never followed"):
            self.assertIn(needle, rule, needle)

    def test_marketplace_and_catalog(self):
        market = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text())
        entry = [p for p in market["plugins"] if p["name"] == "readiness"]
        self.assertEqual(len(entry), 1)
        self.assertEqual(entry[0]["source"], "./skills/readiness")
        cat = json.loads((ROOT / "skills" / "skills-catalog.json").read_text())
        self.assertEqual(cat["skills"]["readiness"]["version"], "0.1.0")
        plugin = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text())
        self.assertEqual(plugin["name"], "readiness")


if __name__ == "__main__":
    unittest.main()
