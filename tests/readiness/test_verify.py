"""verify: a report is rejected unless cited, rule-respecting and free of secrets."""
from __future__ import annotations

import contextlib
import copy
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills/readiness/scripts"))

import evaluate as ev  # noqa: E402
import verify as vf  # noqa: E402
from readiness_model import PILLARS, load_checks, write_json  # noqa: E402
from tests.readiness.test_collect import happy_path_facts  # noqa: E402

JUDGMENTS = ("ops.ci", "ops.release", "ops.alerts", "ops.telemetry", "sec.exposure",
             "rel.replicas", "rel.state", "perf.scaling", "cost.registry")
CANARY = "s3cr3t-canary-value"


class VerifyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.facts = happy_path_facts()
        cls.results = ev.evaluate(cls.facts, load_checks())
        cls.fid = next(f["id"] for f in cls.facts["facts"] if f["value"])

    def good(self) -> dict:
        return {
            "judgments": {j: {"status": "pass", "reason": "ok", "facts": [self.fid]} for j in JUDGMENTS},
            "pillar_notes": {PILLARS[0]: "fine"},
            "fixes": [{"text": "Run as non-root", "checks": ["sec.nonroot"], "where": "Dockerfile"}],
        }

    def v(self, report, **kw):
        return vf.verify(self.facts, self.results, report, **kw)

    def has(self, report, text, **kw):
        out = self.v(report, **kw)
        self.assertTrue(any(text in x for x in out), out)

    def test_good(self):
        self.assertEqual(self.v(self.good()), [])

    def test_missing_judgment(self):
        r = self.good()
        del r["judgments"]["ops.alerts"]
        self.has(r, "judgments.ops.alerts: missing")

    def test_rule_or_person_id(self):
        for cid in ("sec.nonroot", "orr.slo"):
            r = self.good()
            r["judgments"][cid] = {"status": "pass", "reason": "x", "facts": [self.fid]}
            self.has(r, f"judgments.{cid}: ")

    def test_empty_or_unknown_facts(self):
        r = self.good()
        r["judgments"]["ops.ci"]["facts"] = []
        self.has(r, "judgments.ops.ci: cites no facts")
        r = self.good()
        r["judgments"]["ops.ci"]["facts"] = ["nope.x"]
        self.has(r, "judgments.ops.ci: cites unknown fact nope.x")

    def test_unknown_status_needs_no_facts(self):
        r = self.good()
        r["judgments"]["ops.ci"] = {"status": "unknown", "reason": "no data", "facts": []}
        self.assertEqual(self.v(r), [])

    def test_pass_on_empty_values(self):
        facts = copy.deepcopy(self.facts)
        facts["facts"].append({"id": "x.empty", "source": "app", "value": [], "evidence": ""})
        r = self.good()
        r["judgments"]["ops.ci"]["facts"] = ["x.empty"]
        out = vf.verify(facts, self.results, r)
        self.assertTrue(any("judgments.ops.ci: pass cites only empty facts" in x for x in out), out)

    def test_bad_status(self):
        r = self.good()
        r["judgments"]["ops.ci"]["status"] = "n/a"
        self.has(r, "judgments.ops.ci: status")

    def test_too_many_fixes(self):
        r = self.good()
        r["fixes"] = r["fixes"] * 6
        self.has(r, "fixes: more than 5")

    def test_fix_names_no_failing_check(self):
        r = self.good()
        r["fixes"].append({"text": "t", "checks": ["ops.catalog"], "where": "w"})
        self.has(r, "fixes[1]: names no failing or partial check")

    def test_fix_can_cite_failing_judgment(self):
        r = self.good()
        r["judgments"]["ops.ci"]["status"] = "fail"
        r["fixes"] = [{"text": "t", "checks": ["ops.ci"], "where": "w"}]
        self.assertEqual(self.v(r), [])

    def test_pillar_note_key(self):
        r = self.good()
        r["pillar_notes"]["Speed"] = "x"
        self.has(r, "pillar_notes.Speed")

    def test_secrets(self):
        with mock.patch.dict(os.environ, {"BACKSTAGE_TOKEN": "t0k"}):
            r = self.good()
            r["judgments"]["ops.ci"]["reason"] = "token t0k here"
            self.has(r, "judgments.ops.ci.reason: contains a secret")
            r = self.good()
            r["fixes"][0]["text"] = "t0k"
            self.has(r, "fixes[0].text: contains a secret")
        r = self.good()
        r["judgments"]["ops.ci"]["reason"] = f"pw {CANARY}"
        self.has(r, "judgments.ops.ci.reason: contains a secret", canaries=[CANARY])
        r = self.good()
        r["pillar_notes"][PILLARS[0]] = "ghp_" + "a" * 24
        self.has(r, "contains a secret")

    def test_cli(self):
        with tempfile.TemporaryDirectory() as d:
            write_json(Path(d) / "facts.json", self.facts)
            write_json(Path(d) / "results.json", self.results)
            write_json(Path(d) / "report.json", self.good())
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                self.assertEqual(vf.main(["--out", d]), 0)
            self.assertEqual(buf.getvalue().strip(), "ok")
            bad = self.good()
            del bad["judgments"]["ops.ci"]
            write_json(Path(d) / "report.json", bad)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                self.assertEqual(vf.main(["--out", d]), 1)
            self.assertIn("judgments.ops.ci: missing", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
