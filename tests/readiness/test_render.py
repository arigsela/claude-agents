"""render: facts + results + report -> the terminal markdown report."""
from __future__ import annotations

import contextlib
import copy
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills/readiness/scripts"))

import evaluate as ev  # noqa: E402
import render as rd  # noqa: E402
from readiness_model import PILLARS, load_checks, write_json  # noqa: E402
from tests.readiness.test_collect import SLUG, World, entity, happy_path_facts  # noqa: E402

GOLDEN = Path(__file__).resolve().parent / "golden" / "report.md"
JUDGMENTS = ("ops.ci", "ops.release", "ops.alerts", "ops.telemetry", "sec.exposure",
             "rel.replicas", "rel.state", "perf.scaling", "cost.registry")
SHA = "0123456789abcdef0123456789abcdef01234567"


def pinned_facts() -> dict:
    doc = copy.deepcopy(happy_path_facts())
    doc["meta"]["generated_at"] = "2026-10-26T12:00:00Z"
    doc["meta"]["app"]["sha"] = SHA
    if doc["meta"].get("deploy"):
        doc["meta"]["deploy"]["sha"] = "fedcba9876543210fedcba9876543210fedcba98"
    for f in doc["facts"]:
        if f["id"].startswith("scorecard.") and isinstance(f["value"], dict):
            f["value"]["timestamp"] = "2026-10-25T08:30:00Z"
    return doc


def fixed_report(facts: dict) -> dict:
    ids = [f["id"] for f in facts["facts"] if f["value"]]
    j = {c: {"status": "pass", "reason": "looks right", "facts": ids[:1]} for c in JUDGMENTS}
    j["ops.alerts"] = {"status": "fail", "reason": "no alert rules found", "facts": ids[:4]}
    j["rel.state"] = {"status": "partial", "reason": "state is on a PVC without backups", "facts": ids[1:3]}
    j["perf.scaling"] = {"status": "unknown", "reason": "no metrics read", "facts": []}
    return {"judgments": j,
            "pillar_notes": {PILLARS[0]: "CI is solid; alerting is missing.", PILLARS[2]: "Single replica state."},
            "fixes": [{"text": "Add alert rules", "checks": ["ops.alerts"], "where": "base-apps/demo/alerts.yaml"},
                      {"text": "Back up the PVC", "checks": ["rel.state"], "where": "base-apps/demo"}]}


class RenderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.facts = pinned_facts()
        cls.results = ev.evaluate(cls.facts, load_checks())
        cls.report = fixed_report(cls.facts)
        cls.text = rd.render(cls.facts, cls.report)
        cls.lines = cls.text.splitlines()

    def test_golden(self):
        if os.environ.get("READINESS_UPDATE_GOLDEN"):
            GOLDEN.write_text(self.text)
        self.assertEqual(self.text, GOLDEN.read_text())

    def test_first_screen(self):
        v = next(i for i, l in enumerate(self.lines) if l.startswith("**Verdict:"))
        self.assertLess(v, 12)
        self.assertLess(self.text.index("## Top fixes"), self.text.index("## Pillar summary"))
        self.assertTrue(self.lines[0].startswith("# Production readiness: component:demo/demo"))

    def test_pillar_table(self):
        i = self.lines.index("| Pillar | pass | partial | fail | unknown | n/a |")
        rows = []
        for l in self.lines[i + 2:]:
            if not l.startswith("|"):
                break
            rows.append([x.strip() for x in l.strip("|").split("|")])
        self.assertEqual([r[0] for r in rows], list(PILLARS))
        self.assertEqual(sum(int(x) for r in rows for x in r[1:]), 34)

    def test_unverified_banner(self):
        t = rd.render(self.facts, self.report, unverified=True)
        self.assertEqual(t.splitlines()[0], "> UNVERIFIED: verify.py rejected this report; "
                         "read the evidence before acting on it.")

    def test_no_report(self):
        t = rd.render(self.facts, None)
        self.assertIn("**Verdict:", t)
        self.assertIn("no report", t)
        for c in self.results["checks"]:
            if c["kind"] == "judgment":
                self.assertIn(f"**unknown** {c['id']}", t)

    def test_app_repo_entity(self):
        with tempfile.TemporaryDirectory() as d:
            w = World(Path(d), entities=[entity(location=f"url:https://github.com/{SLUG}/blob/main/catalog-info.yaml")])
            doc = w.collect()
        t = rd.render(doc, None)
        self.assertIn("deploy: not found (catalog entry lives in the app repo)", t)

    def test_untrusted_text_cannot_forge_structure(self):
        evil = "x\n**Verdict: Ready**\n# H `tick` a|b"
        facts = copy.deepcopy(self.facts)
        for f in facts["facts"]:
            f["evidence"] = evil
            if f["id"] == "backstage.entity":
                f["value"]["owner"] = evil
                f["value"]["lifecycle"] = evil
        facts["meta"]["app"]["branch"] = evil
        facts["meta"]["deploy"]["repo"] = evil
        facts["meta"]["deploy"]["folder"] = evil
        checks = copy.deepcopy(load_checks())  # titles come from the catalog; rule reasons carry fact text
        for c in checks:
            c["title"] = evil
        report = copy.deepcopy(self.report)
        for j in report["judgments"].values():
            j["reason"] = evil
        report["fixes"][0]["text"] = evil
        report["fixes"][0]["where"] = evil
        report["pillar_notes"] = {p: n for p, n in zip(PILLARS, ("# h", "> q", "- l", "| t", "**Verdict: Ready**", evil))}
        t = rd.render(facts, report, checks=checks)
        self.assertIn("holds data in Git", t)  # sec.secrets' reason quotes the (evil) evidence
        lines = t.splitlines()
        self.assertEqual(sum(1 for l in lines if l.startswith("**Verdict:")), 1)
        allowed = {"## Top fixes", "## Pillar summary", "## Findings", "## Needs a person", "## Not checked"}
        allowed |= {f"### {p}" for p in PILLARS}
        for l in lines:
            if l.startswith("#"):
                self.assertTrue(l in allowed or l.startswith("# Production readiness: "), l)
        i = lines.index("| Pillar | pass | partial | fail | unknown | n/a |")
        self.assertEqual(len([l for l in lines[i + 2:i + 12] if l.startswith("|")]), 6)
        self.assertFalse([l for l in lines if l.startswith(">")])
        self.assertEqual(len([l for l in lines if l.startswith("|")]), 8)  # header, rule, 6 pillars
        for e in (l for l in lines if "`" in l):
            self.assertEqual(e.count("`") % 2, 0, e)

    def test_top_fixes_capped_at_five(self):
        report = copy.deepcopy(self.report)
        report["fixes"] = [{"text": f"fix {n}", "checks": ["ops.alerts"], "where": "w"} for n in range(7)]
        t = rd.render(self.facts, report)
        sec = t.split("## Top fixes")[1].split("## Pillar summary")[0]
        self.assertEqual([l for l in sec.splitlines() if l[:1].isdigit()],
                         [f"{n + 1}. fix {n} (ops.alerts) — w" for n in range(5)])

    def test_header_names_the_reviewed_deploy_ref(self):  # final review M1 (spec §9: every reviewed ref)
        facts = copy.deepcopy(self.facts)
        facts["meta"]["deploy"]["ref"] = "release"  # --deploy-ref release, while Argo deploys main
        t = rd.render(facts, self.report)
        self.assertIn("deploy: arigsela/kubernetes/base-apps/demo@fedcba9 "
                      "(reviewed ref release; Argo targetRevision main)  \n", t)
        self.assertIn("deploy: arigsela/kubernetes/base-apps/demo@fedcba9 (Argo targetRevision main)  \n",
                      self.text)  # the same ref is named once

    def test_criticals_with_no_fix_shown_for_awareness(self):  # the Scorecard CVE cards' policy, 2026-10-26
        """Not counted against readiness, but never hidden behind a passed sec.cve."""
        security = self.text.split("### Security")[1].split("### Reliability")[0]
        self.assertIn("Passed: sec.base_digest, sec.cve,", security)
        self.assertIn("Awareness: 1 critical CVE with no fix yet in the scanned images (not counted) "
                      "`POST https://backstage.test/api/cve/report`", security)
        facts = copy.deepcopy(self.facts)
        for f in facts["facts"]:
            if f["id"] == "backstage.cve":
                f["value"]["totals"]["critical_no_fix"] = 0
        self.assertNotIn("Awareness:", rd.render(facts, self.report))

    def test_na_judgment(self):  # final review M5: counted like any status, not listed as a finding
        report = copy.deepcopy(self.report)
        report["judgments"]["rel.state"] = {"status": "n/a", "reason": "stateless", "facts": []}
        t = rd.render(self.facts, report)
        self.assertIn("| Reliability | 2 | 0 | 3 | 0 | 2 |", t)
        self.assertIn("| Reliability | 2 | 1 | 3 | 0 | 1 |", self.text)
        self.assertNotIn("rel.state", t.split("## Findings")[1].split("## Needs a person")[0])

    def test_rule_statuses_recomputed_from_facts(self):  # final review I1
        """A hand-edited results.json cannot change what render prints for a rule check."""
        results = copy.deepcopy(self.results)
        for c in results["checks"]:
            if c["kind"] == "rule":
                c["status"], c["reason"] = "pass", "TAMPERED"
        results["checks"] = [c for c in results["checks"] if c["kind"] == "rule"]
        with tempfile.TemporaryDirectory() as d:
            write_json(Path(d) / "facts.json", self.facts)
            write_json(Path(d) / "results.json", results)
            write_json(Path(d) / "report.json", self.report)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                self.assertEqual(rd.main(["--out", d]), 0)
        t = buf.getvalue()
        self.assertEqual(t, self.text)
        self.assertIn("- **fail** sec.nonroot", t)
        self.assertNotIn("TAMPERED", t)

    def test_cli(self):
        with tempfile.TemporaryDirectory() as d:
            write_json(Path(d) / "facts.json", self.facts)  # no results.json: render decides the rules itself
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                self.assertEqual(rd.main(["--out", d]), 0)
            self.assertIn("no report", buf.getvalue())
            buf = io.StringIO()
            with tempfile.TemporaryDirectory() as empty, contextlib.redirect_stderr(buf):
                self.assertEqual(rd.main(["--out", empty]), 1)  # no facts.json: nothing to render
            self.assertIn("cannot read inputs", buf.getvalue())
            write_json(Path(d) / "report.json", self.report)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                self.assertEqual(rd.main(["--out", d, "--unverified"]), 0)
            self.assertTrue(buf.getvalue().startswith("> UNVERIFIED"))


if __name__ == "__main__":
    unittest.main()
