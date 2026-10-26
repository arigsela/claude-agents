"""readiness_model: constants, fact records and the Facts accessor."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills/readiness/scripts"))

import readiness_model as m  # noqa: E402


def doc():
    return {
        "facts": [
            m.fact("deploy.container.api", "deploy", {"image": "x"}, "app.yaml:3"),
            m.fact("deploy.workload.api", "deploy", {"replicas": 2}, "app.yaml:1"),
            m.fact("deploy.container.sidecar", "deploy", {"image": "y"}, "app.yaml:9"),
            m.fact("app.file.readme", "app", True, "README.md"),
        ],
        "sources": {"deploy": "ok", "cluster": "skipped: --no-live", "app": "ok"},
    }


class ModelTest(unittest.TestCase):
    def test_constants(self):
        self.assertEqual(m.PILLARS, ("Operational excellence", "Security", "Reliability",
                                     "Performance efficiency", "Cost optimization", "Sustainability"))
        self.assertEqual(m.STATUSES, ("pass", "partial", "fail", "unknown", "n/a"))
        self.assertEqual(m.SOURCES, ("app", "deploy", "backstage", "scorecard", "cluster", "github"))
        self.assertEqual(m.KINDS, ("rule", "judgment", "person"))

    def test_fact_shape(self):
        self.assertEqual(m.fact("a.b", "app", 1, "ev"),
                         {"id": "a.b", "source": "app", "value": 1, "evidence": "ev"})

    def test_get_value_prefix(self):
        f = m.Facts(doc())
        self.assertEqual(f.get("app.file.readme")["value"], True)
        self.assertIsNone(f.get("nope"))
        self.assertEqual(f.value("nope", 7), 7)
        self.assertEqual(f.value("deploy.workload.api"), {"replicas": 2})
        self.assertEqual([x["id"] for x in f.prefix("deploy.container.")],
                         ["deploy.container.api", "deploy.container.sidecar"])

    def test_match_returns_container_ids_in_fact_order(self):
        f = m.Facts(doc())
        self.assertEqual(f.match(["deploy.container.*"]),
                         ["deploy.container.api", "deploy.container.sidecar"])
        self.assertEqual(f.match(["deploy.container.*", "app.*"]),
                         ["deploy.container.api", "deploy.container.sidecar", "app.file.readme"])

    def test_status_and_ok(self):
        f = m.Facts(doc())
        self.assertEqual(f.status("cluster"), "skipped: --no-live")
        self.assertFalse(f.ok("cluster"))
        self.assertTrue(f.ok("deploy"))
        self.assertEqual(f.status("github"), "absent")
        self.assertFalse(f.ok("github"))

    def test_json_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.json"
            m.write_json(p, {"a": [1, 2]})
            self.assertEqual(m.read_json(p), {"a": [1, 2]})


if __name__ == "__main__":
    unittest.main()
