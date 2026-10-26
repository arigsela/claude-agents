"""checks.yaml: ids, kinds, blockers, field shape and Well-Architected refs."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills/readiness/scripts"))

from readiness_model import PILLARS, SOURCES, load_checks  # noqa: E402

EXPECTED_IDS = {
    "ops.catalog", "ops.runbook", "ops.docs", "ops.ci", "ops.release", "ops.alerts", "ops.telemetry", "ops.open_prs",
    "sec.image_digest", "sec.base_digest", "sec.nonroot", "sec.hardening", "sec.netpol", "sec.secrets", "sec.cve",
    "sec.dependabot", "sec.dep_updates", "sec.actions_pinned", "sec.token_perms", "sec.exposure", "sec.sa_token",
    "sec.repo_hygiene",
    "rel.probes", "rel.resources", "rel.replicas", "rel.pdb", "rel.restarts", "rel.dependencies", "rel.state",
    "perf.scaling", "perf.rightsize", "cost.overprovision", "cost.registry", "sus.utilization",
    "orr.oncall", "orr.slo", "orr.rollback", "orr.load", "orr.dep_failure", "orr.incident"}
JUDGMENT = {"ops.ci", "ops.release", "ops.alerts", "ops.telemetry", "sec.exposure", "rel.replicas", "rel.state",
            "perf.scaling", "cost.registry"}
BLOCKERS = {"ops.catalog", "ops.runbook", "ops.ci", "ops.alerts", "sec.nonroot", "sec.secrets", "sec.cve",
            "sec.exposure", "rel.probes", "rel.resources"}


class CatalogTest(unittest.TestCase):
    def setUp(self):
        self.checks = load_checks()

    def test_ids_kinds_blockers(self):
        ids = [c["id"] for c in self.checks]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(set(ids), EXPECTED_IDS)
        self.assertEqual(len(self.checks), 40)
        self.assertEqual({c["id"] for c in self.checks if c["kind"] == "judgment"}, JUDGMENT)
        self.assertEqual({c["id"] for c in self.checks if c["kind"] == "person"},
                         {i for i in EXPECTED_IDS if i.startswith("orr.")})
        self.assertEqual({c["id"] for c in self.checks if c.get("blocker")}, BLOCKERS)

    def test_fields(self):
        for c in self.checks:
            self.assertIn(c["pillar"], PILLARS, c["id"])
            self.assertTrue(c["title"], c["id"])
            self.assertTrue(set(c["sources"]) <= set(SOURCES), c["id"])
            if c["kind"] == "person":
                self.assertTrue(c["hints"], c["id"])
                self.assertIs(c["orr"], True, c["id"])
                self.assertNotIn("blocker", c, c["id"])
                self.assertEqual(c["sources"], [], c["id"])
            else:
                self.assertTrue(c["sources"], c["id"])
            if c["kind"] == "judgment":
                self.assertTrue(c["facts"], c["id"])

    def test_wa_ref_format(self):
        for c in self.checks:
            self.assertRegex(c["wa_ref"], r"^(none|[A-Z]{3,4}\d{2}-BP\d{2})$", c["id"])
            if c["wa_ref"] == "none":
                self.assertNotIn("wa_url", c, c["id"])
            else:
                self.assertTrue(c.get("wa_url", "").startswith("https://docs.aws.amazon.com/wellarchitected/"), c["id"])


if __name__ == "__main__":
    unittest.main()
