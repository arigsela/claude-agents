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

    def test_garbled_shapes_never_raise(self):
        def mut(f):
            r = self.good()
            f(r)
            return r
        shapes = {
            "fixes int": mut(lambda r: r.update(fixes=5)),
            "pillar_notes list": mut(lambda r: r.update(pillar_notes=["a"])),
            "pillar_notes str": mut(lambda r: r.update(pillar_notes="a")),
            "facts int": mut(lambda r: r["judgments"]["ops.ci"].update(facts=3)),
            "facts nested": mut(lambda r: r["judgments"]["ops.ci"].update(facts=[[1]])),
            "checks nested": mut(lambda r: r["fixes"][0].update(checks=[["a"]])),
            "checks int": mut(lambda r: r["fixes"][0].update(checks=3)),
            "judgments list": mut(lambda r: r.update(judgments=[])),
            "judgment int": mut(lambda r: r["judgments"].update({"ops.ci": 3})),
            "status list": mut(lambda r: r["judgments"]["ops.ci"].update(status=[])),
        }
        for name, r in shapes.items():
            with self.subTest(name):
                out = self.v(r)
                self.assertTrue(out, name)
        for bad in ([], "x", 3, None):
            with self.subTest(report=bad):
                self.assertTrue(self.v(bad))

    def test_cli_non_dict_report_and_crash(self):
        with tempfile.TemporaryDirectory() as d:
            write_json(Path(d) / "facts.json", self.facts)
            write_json(Path(d) / "results.json", self.results)
            (Path(d) / "report.json").write_text("[1]")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                self.assertEqual(vf.main(["--out", d]), 1)
            self.assertTrue(buf.getvalue().strip())
            write_json(Path(d) / "report.json", self.good())
            buf = io.StringIO()
            with mock.patch.object(vf, "verify", side_effect=KeyError("t0k")), contextlib.redirect_stdout(buf):
                self.assertEqual(vf.main(["--out", d]), 1)
            self.assertIn("KeyError", buf.getvalue())
            self.assertNotIn("t0k", buf.getvalue())

    def test_non_string_fields_rejected_and_scanned(self):
        with mock.patch.dict(os.environ, {"BACKSTAGE_TOKEN": "t0k"}):
            r = self.good()
            r["judgments"]["ops.ci"]["reason"] = ["t0k"]
            out = self.v(r)
            self.assertTrue(any("judgments.ops.ci.reason: not a string" in x for x in out), out)
            self.assertTrue(any("judgments.ops.ci.reason: contains a secret" in x for x in out), out)
            r = self.good()
            r["fixes"][0]["where"] = {"a": "t0k"}
            out = self.v(r)
            self.assertTrue(any("fixes[0].where: not a string" in x for x in out), out)
            self.assertTrue(any("fixes[0].where: contains a secret" in x for x in out), out)
            r = self.good()
            r["pillar_notes"][PILLARS[0]] = ["t0k"]
            self.assertTrue(any("contains a secret" in x for x in self.v(r)))

    def test_leaking_identifiers_are_redacted(self):
        with mock.patch.dict(os.environ, {"BACKSTAGE_TOKEN": "t0k"}):
            r = self.good()
            r["judgments"]["t0k"] = {"status": "pass", "reason": "x", "facts": [self.fid]}
            r["judgments"]["ops.ci"]["facts"] = ["t0k"]
            r["pillar_notes"]["t0k"] = "x"
            r["fixes"][0]["checks"].append("t0k")
            out = self.v(r)
            self.assertTrue(any("judgments[<redacted>]: contains a secret" in x for x in out), out)
            self.assertTrue(any("contains a secret" in x and "pillar_notes" in x for x in out), out)
            self.assertTrue(any("fixes[0].checks" in x and "contains a secret" in x for x in out), out)
            self.assertFalse(any("t0k" in x for x in out), out)

    # --- results.json cannot carry a changed rule status (final review I1) ---------------------------------

    def tampered(self, f) -> dict:
        res = copy.deepcopy(self.results)
        f(res)
        return res

    @staticmethod
    def check(res: dict, cid: str) -> dict:
        return next(c for c in res["checks"] if c["id"] == cid)

    def test_changed_rule_status(self):
        res = self.tampered(lambda r: self.check(r, "sec.nonroot").update(status="pass"))
        self.assertIn("results.json: rule sec.nonroot status changed", vf.verify(self.facts, res, self.good()))

    def test_changed_rule_reason(self):
        res = self.tampered(lambda r: self.check(r, "ops.catalog").update(reason="all good"))
        self.assertIn("results.json: rule ops.catalog status changed", vf.verify(self.facts, res, self.good()))

    def test_deleted_judgment_check(self):
        res = self.tampered(lambda r: r.update(checks=[c for c in r["checks"] if c["id"] != "ops.alerts"]))
        r = self.good()
        del r["judgments"]["ops.alerts"]
        out = vf.verify(self.facts, res, r)
        self.assertIn("results.json: checks differ from checks.yaml", out)
        self.assertIn("judgments.ops.alerts: missing", out)  # judgment ids come from checks.yaml

    def test_extra_or_garbled_checks(self):
        for res in (self.tampered(lambda r: r["checks"].append({"id": "x.extra", "kind": "rule", "status": "pass"})),
                    {"checks": "x"}, [], None):
            with self.subTest(res=str(res)[:40]):
                self.assertIn("results.json: checks differ from checks.yaml", vf.verify(self.facts, res, self.good()))

    def test_every_rule_pass_and_no_judgments(self):
        """The reviewer's reproduction: every rule status set to pass and every judgment check deleted."""
        res = self.tampered(lambda r: r.update(checks=[dict(c, status="pass") for c in r["checks"]
                                                       if c["kind"] == "rule"]))
        out = vf.verify(self.facts, res, {"judgments": {}, "pillar_notes": {}, "fixes": []})
        self.assertIn("results.json: checks differ from checks.yaml", out)
        self.assertIn("results.json: rule sec.nonroot status changed", out)
        for j in JUDGMENTS:
            self.assertIn(f"judgments.{j}: missing", out)

    def test_fix_statuses_come_from_the_facts(self):
        # results.json says ops.catalog failed; on these facts it passes, so a fix naming only it is rejected.
        res = self.tampered(lambda r: self.check(r, "ops.catalog").update(status="fail"))
        r = self.good()
        r["fixes"] = [{"text": "t", "checks": ["ops.catalog"], "where": "w"}]
        self.assertIn("fixes[0]: names no failing or partial check", vf.verify(self.facts, res, r))

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
