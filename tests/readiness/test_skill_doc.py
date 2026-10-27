import json
import re
import sys
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ROOT / "skills" / "readiness"
SKILL = PLUGIN / "skills" / "production-readiness" / "SKILL.md"
sys.path.insert(0, str(PLUGIN / "scripts"))

import verify  # noqa: E402


def frontmatter(text):
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    return yaml.safe_load(m.group(1)) if m else None


class SkillDocTest(unittest.TestCase):
    def test_frontmatter(self):
        fm = frontmatter(SKILL.read_text())
        self.assertEqual(fm["name"], "production-readiness")
        self.assertEqual(fm["version"], "0.3.0")
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

    def test_alerts_bar_names_the_alert_source(self):  # final review I6
        bar = re.search(r"- `ops.alerts` \(blocker\):.*?(?=\n   - `)", SKILL.read_text(), re.S).group(0)
        for needle in ("deploy.alert_source", "exists: false", "parsed: false", "unknown"):
            self.assertIn(needle, bar, needle)
        checks = {c["id"]: c for c in yaml.safe_load((PLUGIN / "checks.yaml").read_text())["checks"]}
        self.assertIn("deploy.alert_source", checks["ops.alerts"]["facts"])

    def test_bars_match_the_collected_facts(self):  # final review M3
        text = SKILL.read_text()
        bar = re.search(r"- `ops.telemetry`:.*?(?=\n   - `)", text, re.S).group(0)
        self.assertNotIn("metrics port", bar)  # container ports are not collected
        self.assertIn("annotation", bar)
        checks = {c["id"]: c for c in yaml.safe_load((PLUGIN / "checks.yaml").read_text())["checks"]}
        self.assertIn("cluster.usage.*", checks["perf.scaling"]["facts"])  # the bar accepts "justified by usage"
        self.assertIn("cluster", checks["perf.scaling"]["sources"])

    def test_collect_timeout_and_fresh_run_folder(self):  # final review M6
        text = SKILL.read_text()
        collect = re.search(r"1\. \*\*Collect\*\*.*?(?=\n2\. )", text, re.S).group(0)
        self.assertIn("600000", collect)
        self.assertIn("<W>/run-<n>", text)
        self.assertIn("never reuse an earlier run", text.lower())
        for script in ("collect.py", "evaluate.py", "verify.py", "render.py"):
            line = next(l for l in text.splitlines() if f"scripts/{script}" in l)
            self.assertIn("--out <R>", line, script)

    def test_html_publish_step(self):
        text = SKILL.read_text()
        render = re.search(r"5\. \*\*Render\*\*.*?(?=\n6\. )", text, re.S).group(0)
        self.assertIn("[--unverified] [--html]", render)
        publish = re.search(r"6\. \*\*Publish\*\* \(only with `--html`\).*?(?=\n7\. )", text, re.S).group(0)
        for needle in ("artifact-design", "<R>/report.html", '"composer_only": true', "Never edit"):
            self.assertIn(needle, publish, needle)
        fallback = next(l for l in publish.splitlines() if "--standalone" in l)
        self.assertIn("[--unverified]", fallback)  # the local page keeps the UNVERIFIED banner verify asked for
        self.assertIn("exactly when step 5 used it", publish)

    def test_readme_read_only_guarantees(self):  # final review M2
        readme = (PLUGIN / "README.md").read_text()
        section = readme.split("## Read-only guarantees", 1)[1].split("\n## ", 1)[0]
        for needle in ("POST /api/cve/report", "kubectl kustomize", "helm template", "helm dependency build",
                       "temp clone"):
            self.assertIn(needle, section, needle)
        sources = readme.split("## Sources", 1)[1].split("\n## ", 1)[0]
        self.assertIn("POST /api/cve/report", sources)

    def test_repo_readmes_list_the_plugin(self):  # final review M9
        for path in (ROOT / "README.md", ROOT / "skills" / "README.md"):
            rows = [l for l in path.read_text().splitlines() if l.startswith("|") and "readiness" in l]
            self.assertTrue(rows, path)
            self.assertIn("production-readiness", rows[0], path)

    def test_judgment_statuses_match_verify(self):  # final review M4, M5
        para = re.search(r"- `judgments`:.*?(?=\n   - `pillar_notes`)", SKILL.read_text(), re.S).group(0)
        for status in verify.JUDGMENT_STATUSES:
            self.assertIn(f"`{status}`", para, status)
        self.assertIn("candidate list", para)

    def test_marketplace_and_catalog(self):
        market = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text())
        entry = [p for p in market["plugins"] if p["name"] == "readiness"]
        self.assertEqual(len(entry), 1)
        self.assertEqual(entry[0]["source"], "./skills/readiness")
        cat = json.loads((ROOT / "skills" / "skills-catalog.json").read_text())
        self.assertEqual(cat["skills"]["readiness"]["version"], "0.3.0")
        plugin = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text())
        self.assertEqual(plugin["name"], "readiness")


if __name__ == "__main__":
    unittest.main()
