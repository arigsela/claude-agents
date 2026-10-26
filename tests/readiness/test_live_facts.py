import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "readiness" / "scripts"))

import live_facts as lf  # noqa: E402

DATA = Path(__file__).resolve().parent / "data"
GET_OUT = (DATA / "kubectl_get.json").read_text()
TOP_OUT = (DATA / "kubectl_top.txt").read_text()
GET_CMD = "kubectl get deploy,statefulset,pods -n demo -o json --request-timeout=5s"
TOP_CMD = "kubectl top pods -n demo --containers --no-headers --request-timeout=5s"


def fake(responses, calls):
    def run(argv):
        calls.append(argv)
        return responses.get(" ".join(argv), (1, "", "no response"))
    return run


def by_id(facts):
    return {f["id"]: f for f in facts}


class QuantityTests(unittest.TestCase):
    def test_cpu(self):
        self.assertEqual(lf.parse_quantity_cpu("12m"), 12)
        self.assertEqual(lf.parse_quantity_cpu("1"), 1000)
        self.assertEqual(lf.parse_quantity_cpu("0m"), 0)
        self.assertEqual(lf.parse_quantity_cpu("1500m"), 1500)

    def test_mem(self):
        self.assertEqual(lf.parse_quantity_mem("64Mi"), 64)
        self.assertEqual(lf.parse_quantity_mem("1Gi"), 1024)
        self.assertEqual(lf.parse_quantity_mem("512Ki"), 0)
        self.assertEqual(lf.parse_quantity_mem("1000000"), 0)
        self.assertEqual(lf.parse_quantity_mem("2G"), 1907)
        with self.assertRaises(ValueError):
            lf.parse_quantity_mem("5Xi")


class PodWorkloadTests(unittest.TestCase):
    def test_owners(self):
        p = {"metadata": {"labels": {"pod-template-hash": "abc"},
                          "ownerReferences": [{"kind": "ReplicaSet", "name": "web-abc"}]}}
        self.assertEqual(lf.pod_workload(p), "Deployment/web")
        s = {"metadata": {"ownerReferences": [{"kind": "StatefulSet", "name": "db"}]}}
        self.assertEqual(lf.pod_workload(s), "StatefulSet/db")
        j = {"metadata": {"ownerReferences": [{"kind": "Job", "name": "j"}]}}
        self.assertIsNone(lf.pod_workload(j))
        self.assertIsNone(lf.pod_workload({"metadata": {}}))


class ClusterTests(unittest.TestCase):
    def run_cluster(self, responses, workloads=("Deployment/demo", "Deployment/valkey")):
        calls = []
        out = lf.cluster_facts("demo", list(workloads), run=fake(responses, calls))
        return out, calls

    def test_happy(self):
        (facts, status), calls = self.run_cluster({GET_CMD: (0, GET_OUT, ""), TOP_CMD: (0, TOP_OUT, "")})
        self.assertEqual(status, "ok")
        self.assertEqual([" ".join(c) for c in calls], [GET_CMD, TOP_CMD])
        self.assertTrue(all(c[1] in {"get", "top"} for c in calls))
        f = by_id(facts)
        self.assertEqual(f["cluster.workload.Deployment/demo"]["value"], {"found": True, "ready": 2, "desired": 2})
        self.assertEqual(f["cluster.workload.Deployment/valkey"]["value"]["found"], False)
        self.assertEqual(f["cluster.pod.demo-7d9f8c6b5-aaaaa"]["value"],
                         {"workload": "Deployment/demo", "restarts": 3, "oom_killed": True, "phase": "Running"})
        self.assertFalse(f["cluster.pod.demo-7d9f8c6b5-bbbbb"]["value"]["oom_killed"])
        self.assertNotIn("cluster.pod.db-0", f)
        self.assertEqual(f["cluster.usage.Deployment/demo/app"]["value"], {"cpu_m": 12, "memory_mi": 180})
        self.assertEqual(f["cluster.workload.Deployment/demo"]["evidence"], GET_CMD)
        self.assertEqual(f["cluster.usage.Deployment/demo/app"]["evidence"], TOP_CMD)
        self.assertTrue(all(x["source"] == "cluster" for x in facts))

    def test_statefulset(self):
        (facts, _), _ = self.run_cluster({GET_CMD: (0, GET_OUT, ""), TOP_CMD: (0, TOP_OUT, "")},
                                         ["StatefulSet/db"])
        f = by_id(facts)
        self.assertEqual(f["cluster.workload.StatefulSet/db"]["value"], {"found": True, "ready": 0, "desired": 1})
        self.assertEqual(f["cluster.usage.StatefulSet/db/app"]["value"], {"cpu_m": 1000, "memory_mi": 1024})

    def test_only_kinds_the_read_looks_up_get_a_workload_fact(self):
        # arigsela/beacon, 2026-10-26: its CronJobs and smoke Job read as "not found live", so rel.restarts was
        # unknown although every Deployment was running. The get covers Deployments and StatefulSets only.
        (facts, _), _ = self.run_cluster({GET_CMD: (0, GET_OUT, ""), TOP_CMD: (0, TOP_OUT, "")},
                                         ["Deployment/demo", "CronJob/backup", "Job/smoke", "DaemonSet/agent"])
        self.assertEqual(sorted(i for i in by_id(facts) if i.startswith("cluster.workload.")),
                         ["cluster.workload.Deployment/demo"])

    def test_get_fails(self):
        (facts, status), _ = self.run_cluster({GET_CMD: (1, "", "Unable to connect")})
        self.assertEqual((facts, status), ([], "unavailable: Unable to connect"))

    def test_not_installed(self):
        (facts, status), _ = self.run_cluster({GET_CMD: (127, "", "not installed")})
        self.assertEqual((facts, status), ([], "unavailable: kubectl not installed"))

    def test_bad_json(self):
        (facts, status), _ = self.run_cluster({GET_CMD: (0, "not json", "")})
        self.assertEqual(facts, [])
        self.assertTrue(status.startswith("unavailable:"))

    def test_unknown_unit_line_skipped(self):
        top = "demo-7d9f8c6b5-aaaaa   app   12m   5Xi\ndemo-7d9f8c6b5-bbbbb   app   5m   150Mi\n"
        (facts, _), _ = self.run_cluster({GET_CMD: (0, GET_OUT, ""), TOP_CMD: (0, top, "")})
        self.assertEqual(by_id(facts)["cluster.usage.Deployment/demo/app"]["value"], {"cpu_m": 5, "memory_mi": 150})

    def test_top_fails_keeps_get(self):
        (facts, status), _ = self.run_cluster({GET_CMD: (0, GET_OUT, ""),
                                               TOP_CMD: (1, "", "Metrics API not available")})
        self.assertEqual(status, "ok")
        self.assertTrue(any(x["id"].startswith("cluster.workload.") for x in facts))
        self.assertFalse(any(x["id"].startswith("cluster.usage.") for x in facts))


class GithubTests(unittest.TestCase):
    def go(self, alerts, prot, branch="main", probe=(0, "HTTP/2.0 200 OK\r\n\r\n{}", "")):
        calls = []
        r = {"gh api -i repos/o/r": probe,
             "gh api -i repos/o/r/vulnerability-alerts": alerts,
             "gh api -i repos/o/r/branches/main/protection": prot}
        facts, status = lf.github_facts("o/r", branch, run=fake(r, calls))
        return by_id(facts), status, calls

    def test_codes(self):
        f, status, calls = self.go((0, "HTTP/2.0 204 No Content\r\n\r\n", ""),
                                   (0, "HTTP/2.0 200 OK\r\n\r\n{}", ""))
        self.assertEqual(status, "ok")
        self.assertEqual(f["github.dependabot_alerts"]["value"], {"enabled": True, "http": 204})
        self.assertEqual(f["github.branch_protection"]["value"], {"protected": True, "http": 200})
        self.assertEqual(f["github.dependabot_alerts"]["evidence"], "gh api -i repos/o/r/vulnerability-alerts")
        self.assertEqual(f["github.dependabot_alerts"]["source"], "github")
        self.assertTrue(all(c[:3] == ["gh", "api", "-i"] and len(c) == 4 for c in calls))

    def test_404(self):
        nf = (1, "HTTP/2.0 404 Not Found\r\n\r\n", "x")
        f, _, _ = self.go(nf, nf)
        self.assertIs(f["github.dependabot_alerts"]["value"]["enabled"], False)
        self.assertIs(f["github.branch_protection"]["value"]["protected"], False)

    def test_403(self):
        f, _, _ = self.go((1, "HTTP/2.0 403 Forbidden\r\n\r\n", ""),
                          (1, "HTTP/2.0 403 Forbidden\r\n\r\nUpgrade to GitHub Pro", ""))
        self.assertIsNone(f["github.dependabot_alerts"]["value"]["enabled"])
        self.assertIsNone(f["github.branch_protection"]["value"]["protected"])

    def test_no_branch(self):
        f, _, calls = self.go((0, "HTTP/2.0 204 No Content\r\n\r\n", ""), (0, "", ""), branch=None)
        self.assertEqual(len(calls), 2)
        self.assertEqual(f["github.branch_protection"]["value"], {"protected": None, "http": 0})

    def test_unreadable_repo_is_unknown(self):
        nf = (1, "HTTP/2.0 404 Not Found\r\n\r\n", "x")
        f, status, calls = self.go(nf, nf, probe=nf)
        self.assertIsNone(f["github.dependabot_alerts"]["value"]["enabled"])
        self.assertIsNone(f["github.branch_protection"]["value"]["protected"])
        self.assertEqual(f["github.dependabot_alerts"]["value"]["http"], 404)
        self.assertEqual(status, "unavailable: repo not readable (HTTP 404)")
        self.assertEqual(len(calls), 1)

    def test_readable_alerts_404_is_false(self):
        nf = (1, "HTTP/2.0 404 Not Found\r\n\r\n", "x")
        f, status, _ = self.go(nf, (0, "HTTP/2.0 200 OK\r\n\r\n{}", ""))
        self.assertIs(f["github.dependabot_alerts"]["value"]["enabled"], False)
        self.assertEqual(status, "ok")

    def test_readable_protection_404_is_false(self):
        nf = (1, "HTTP/2.0 404 Not Found\r\n\r\n", "x")
        f, _, _ = self.go((0, "HTTP/2.0 204 No Content\r\n\r\n", ""), nf)
        self.assertIs(f["github.branch_protection"]["value"]["protected"], False)

    def test_gh_missing(self):
        facts, status = lf.github_facts("o/r", "main", run=lambda a: (127, "", "not installed"))
        self.assertEqual(status, "unavailable: gh not installed")
        self.assertEqual(facts, [])


class SubprocessTests(unittest.TestCase):
    def test_missing(self):
        with mock.patch("subprocess.run", side_effect=FileNotFoundError):
            self.assertEqual(lf.subprocess_run(["kubectl"]), (127, "", "not installed"))

    def test_timeout(self):
        with mock.patch("subprocess.run", side_effect=subprocess.TimeoutExpired("k", 20)):
            rc, _, err = lf.subprocess_run(["kubectl"])
        self.assertNotEqual(rc, 0)
        self.assertIn("timed out", err)


if __name__ == "__main__":
    unittest.main()
