"""evaluate: rule checks decided from facts, judgment candidates, ORR hints and the verdict."""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills/readiness/scripts"))

import evaluate as ev  # noqa: E402
import rules  # noqa: E402
from readiness_model import SOURCES, STATUSES, Facts, fact, load_checks  # noqa: E402
from tests.readiness.test_collect import happy_path_facts  # noqa: E402

CHECKS = load_checks()
OK = {s: "ok" for s in SOURCES}
U = "unavailable: x"
DIGEST = "@sha256:" + "a" * 64
READ = {"contents": "read"}
SHA = "1" * 40


def doc(*facts, **sources) -> dict:
    """A minimal facts doc: every source ok unless a keyword overrides it (deploy="unavailable: x")."""
    return {"meta": {"sources": {**OK, **sources}}, "facts": list(facts)}


def F(id: str, value, evidence: str | None = None) -> dict:
    return fact(id, id.split(".", 1)[0], value, evidence or id)


def res(rcpu="200m", rmem="256Mi", lcpu="500m", lmem="512Mi") -> dict:
    return {"requests": {"cpu": rcpu, "memory": rmem}, "limits": {"cpu": lcpu, "memory": lmem}}


def ctr(ref="Deployment/api/api", init=False, sec=None, **kw) -> dict:
    value = {"workload": ref.rsplit("/", 1)[0], "init": init, "image": "reg/api" + DIGEST, "image_pinned": True,
             "probes": {"readiness": True, "liveness": True, "startup": False}, "resources": res(),
             "security": {"runAsNonRoot": True, "runAsUser": 1000, "readOnlyRootFilesystem": True,
                          "allowPrivilegeEscalation": False, "capabilities_drop": ["ALL"]}}
    value["security"].update(sec or {})
    value.update(kw)
    return F(f"deploy.container.{ref}", value, "base-apps/api/deployment.yaml:1-40")


def wl(ref="Deployment/api", **kw) -> dict:
    kind, name = ref.split("/")
    value = {"kind": kind, "name": name, "replicas": 2, "replicas_comment": None, "pod_labels": {"app": name},
             "pod_run_as_non_root": True, "pod_run_as_user": None, "automount_sa_token": False,
             "service_account": name,
             "pod_annotations": [], "volume_kinds": [], "volume_claim_templates": 0}
    value.update(kw)
    return F(f"deploy.workload.{ref}", value, "base-apps/api/deployment.yaml:1-40")


def obj(ref: str, **value) -> dict:
    return F(f"deploy.object.{ref}", value, "base-apps/api/objects.yaml:1-9")


def expr(key: str, operator: str, *values: str) -> dict:
    return {"key": key, "operator": operator, "values": list(values)}


def afile(key: str, exists: bool = True) -> dict:
    return F(f"app.file.{key}", {"exists": exists, "path": key if exists else None, "searched": [key]})


def docs_md(exists: bool) -> dict:
    return F("deploy.file.docs", {"exists": exists, "path": "base-apps/api/docs.md"})


def runbook(exists: bool) -> dict:
    return F("deploy.file.runbook", {"exists": exists, "path": "base-apps/api/runbook.md"})


def wf(stem="ci", uses=None, perms=READ, without=(), write_all=False) -> dict:
    uses = [{"ref": f"actions/checkout@{SHA}", "pinned": True, "line": 8}] if uses is None else uses
    return F(f"app.workflow.{stem}", {"file": f".github/workflows/{stem}.yml", "triggers": ["pull_request"],
                                      "permissions": perms, "jobs_without_permissions": list(without),
                                      "write_all": write_all, "run_steps": [], "uses": uses})


def metric(mid, evaluation="success", value=1, status="success", error=None) -> dict:
    return F(f"scorecard.{mid}", {"value": value, "evaluation": evaluation, "status": status, "error": error,
                                  "timestamp": "2026-10-25T09:00:00.000Z"})


def entity(**kw) -> dict:
    value = {"ref": "component:api/api", "owner": "group:default/platform", "lifecycle": "production",
             "system": "default/obs", "depends_on": [], "provides_apis": [], "annotations": {}}
    value.update(kw)
    return F("backstage.entity", value)


def dep(ref, lifecycle="production", error=None) -> dict:
    return F(f"backstage.dependency.{ref}", {"ref": ref, "lifecycle": lifecycle, "error": error})


def cve(critical=0, high=0, ok=True, unmatched=(), error=None, matched=("reg/api" + DIGEST,),
        kev=0, nofix=0) -> dict:
    findings = ([{"id": "CVE-1", "severity": "CRITICAL", "pkg": "openssl", "fixed": "3.0.15", "image": "img"}]
                * bool(critical)
                + [{"id": "CVE-2", "severity": "HIGH", "pkg": "zlib", "fixed": "1.2.13", "image": "img"}] * bool(high))
    totals = {"critical": critical, "high": high, "critical_no_fix": nofix, "kev_fixable": kev}
    return F("backstage.cve", {"ok": ok, "scanned_at": "2026-10-25", "matched": list(matched),
                               "unmatched": list(unmatched), "totals": totals,
                               "findings": findings, "error": error})


def cw(ref="Deployment/api", found=True) -> dict:
    return F(f"cluster.workload.{ref}", {"found": found, "ready": 2 * found, "desired": 2 * found})


def pod(name, workload="Deployment/api", restarts=0, oom=False) -> dict:
    return F(f"cluster.pod.{name}", {"workload": workload, "restarts": restarts, "oom_killed": oom,
                                     "phase": "Running"})


def use(ref="Deployment/api/api", cpu=60, mem=100) -> dict:
    return F(f"cluster.usage.{ref}", {"cpu_m": cpu, "memory_mi": mem})


def alerts(enabled=True, http=204) -> dict:
    return F("github.dependabot_alerts", {"enabled": enabled, "http": http})


def protection(protected=True, http=200) -> dict:
    return F("github.branch_protection", {"protected": protected, "http": http})


DEPLOY = (wl(), ctr())
NO_PROBES = {"readiness": False, "liveness": False, "startup": False}
CRONJOB = (wl("CronJob/backup", replicas=None), ctr("CronJob/backup/backup", probes=NO_PROBES))

CASES: dict[str, list[tuple[dict, str]]] = {
    "ops.catalog": [
        (doc(entity()), "pass"),
        (doc(entity(system=None)), "partial"),
        (doc(F("backstage.entity", None)), "fail"),
        (doc(entity(), backstage="unavailable: HTTP 500"), "unknown"),
    ],
    "ops.runbook": [
        (doc(runbook(True)), "pass"),
        (doc(runbook(False), metric("filecheck.runbook", "exist", True)), "fail"),  # the deploy folder wins
        (doc(metric("filecheck.runbook", "exist", True), deploy=U), "pass"),
        (doc(metric("filecheck.runbook", "missing", False), deploy=U), "fail"),
        (doc(metric("filecheck.runbook", None, None, "error", "boom"), deploy=U), "unknown"),
        (doc(deploy=U, scorecard="not installed (404)"), "unknown"),
    ],
    "ops.docs": [
        (doc(afile("readme"), docs_md(True)), "pass"),
        (doc(afile("readme"), docs_md(False)), "partial"),
        (doc(afile("readme", False), docs_md(True)), "partial"),
        (doc(afile("readme", False), docs_md(False)), "fail"),
        (doc(afile("readme"), deploy=U), "partial"),
        (doc(afile("readme", False), deploy=U), "fail"),
        (doc(app=U), "unknown"),
    ],
    "ops.open_prs": [
        (doc(metric("github.openPRs", "success", 3)), "pass"),
        (doc(metric("github.openPRs", "warning", 12)), "partial"),
        (doc(metric("github.openPRs", "error", 30)), "fail"),
        (doc(), "unknown"),
        (doc(metric("github.openPRs", None, None, "error", "rate limited")), "unknown"),
        (doc(metric("github.openPRs", "success", 3), scorecard="not installed (404)"), "unknown"),
    ],
    "sec.image_digest": [
        (doc(*DEPLOY), "pass"),
        (doc(*DEPLOY, ctr("Deployment/api/init", init=True, image="busybox:1.36", image_pinned=False)), "fail"),
        (doc(*DEPLOY, deploy=U), "unknown"),
        (doc(F("deploy.application", {"path": "base-apps/api", "render": "raw-fallback"})), "unknown"),
    ],
    "sec.base_digest": [
        (doc(F("app.dockerfile.from.1", {"image": "python:3.12" + DIGEST, "pinned": True}, "Dockerfile:1"),
             F("app.dockerfile.user", {"user": "10001"}, "Dockerfile")), "pass"),
        (doc(F("app.dockerfile.from.1", {"image": "python:3.12", "pinned": False}, "Dockerfile:1")), "fail"),
        (doc(afile("readme")), "n/a"),
        (doc(app=U), "unknown"),
    ],
    "sec.nonroot": [
        (doc(*DEPLOY), "pass"),
        (doc(wl(pod_run_as_non_root=True), ctr(sec={"runAsNonRoot": None, "runAsUser": None})), "pass"),
        (doc(wl(pod_run_as_non_root=None), ctr(sec={"runAsNonRoot": None, "runAsUser": 1000})), "pass"),
        (doc(wl(pod_run_as_non_root=True), ctr(sec={"runAsNonRoot": False, "runAsUser": None})), "fail"),
        (doc(wl(pod_run_as_non_root=None), ctr(sec={"runAsNonRoot": None, "runAsUser": 0})), "fail"),
        # final review I2: the pod's runAsUser counts when the container sets none (base-apps/n8n)
        (doc(wl(pod_run_as_non_root=None, pod_run_as_user=1000), ctr(sec={"runAsNonRoot": None, "runAsUser": None})),
         "pass"),
        (doc(wl(pod_run_as_non_root=None, pod_run_as_user=0), ctr(sec={"runAsNonRoot": None, "runAsUser": None})),
         "fail"),
        (doc(wl(pod_run_as_non_root=None, pod_run_as_user=1000), ctr(sec={"runAsNonRoot": None, "runAsUser": 0})),
         "fail"),  # the container's runAsUser overrides the pod's
    ],
    "sec.hardening": [
        (doc(*DEPLOY), "pass"),
        (doc(*DEPLOY, ctr("Deployment/api/proxy", sec={"readOnlyRootFilesystem": None})), "partial"),
        (doc(wl(), ctr(sec={"capabilities_drop": ["NET_RAW"]})), "fail"),
        (doc(wl(), ctr(sec={"allowPrivilegeEscalation": None})), "fail"),
    ],
    "sec.netpol": [
        (doc(*DEPLOY, obj("NetworkPolicy/deny", pod_selector={})), "pass"),
        (doc(*DEPLOY, obj("NetworkPolicy/api", pod_selector={"app": "api"})), "pass"),
        (doc(*DEPLOY, wl("Deployment/cache", pod_labels={}), obj("NetworkPolicy/api", pod_selector={"app": "api"})),
         "partial"),
        (doc(*DEPLOY, obj("NetworkPolicy/other", pod_selector={"app": "other"})), "fail"),
        (doc(*DEPLOY), "fail"),
        # final review I3: matchExpressions are evaluated, not read as "selects all"
        (doc(wl("Deployment/a"), ctr("Deployment/a/a"), obj("NetworkPolicy/b", pod_selector={},
                                                             match_expressions=[expr("app", "In", "b")])), "fail"),
        (doc(*DEPLOY, obj("NetworkPolicy/x", pod_selector={}, match_expressions=[expr("app", "Exists")])), "pass"),
        (doc(*DEPLOY, obj("NetworkPolicy/x", pod_selector={}, match_expressions=[expr("app", "NotIn", "api")])),
         "fail"),
        (doc(*DEPLOY, obj("NetworkPolicy/x", pod_selector={}, match_expressions=[expr("app", "NotIn", "web")])),
         "pass"),
        (doc(*DEPLOY, obj("NetworkPolicy/x", pod_selector={}, match_expressions=[expr("app", "DoesNotExist")])),
         "fail"),
        (doc(*DEPLOY, obj("NetworkPolicy/x", pod_selector={}, match_expressions=[expr("tier", "DoesNotExist")])),
         "pass"),
        (doc(*DEPLOY, obj("NetworkPolicy/x", pod_selector={"app": "api"},
                          match_expressions=[expr("tier", "In", "web")])), "fail"),  # a selector with both needs both
        (doc(*DEPLOY, obj("NetworkPolicy/x", pod_selector={}, match_expressions=[expr("app", "Matches", "api")])),
         "fail"),  # an operator Kubernetes does not have selects nothing
    ],
    "sec.secrets": [
        (doc(*DEPLOY, obj("Secret/api", keys=[], has_data=False), obj("ExternalSecret/api", target="api",
                                                                       keys=["token"])), "pass"),
        (doc(*DEPLOY, obj("Secret/api", keys=["password"], has_data=True)), "fail"),
        (doc(obj("Secret/api", keys=["password"], has_data=True)), "fail"),  # evidence beats an empty render
        (doc(), "unknown"),  # nothing rendered: no vacuous pass
        (doc(*DEPLOY, deploy=U), "unknown"),
    ],
    "sec.cve": [
        (doc(*DEPLOY, cve()), "pass"),
        (doc(*DEPLOY, cve(high=2)), "pass"),  # highs count only when actively exploited (KEV)
        (doc(*DEPLOY, cve(critical=1, high=2)), "fail"),
        (doc(*DEPLOY, cve(kev=1)), "fail"),  # actively exploited with a fix, at any severity
        (doc(*DEPLOY, cve(nofix=2)), "pass"),  # criticals with no fix: named, not counted
        (doc(*DEPLOY, cve(ok=False, critical=None, high=None, kev=None, nofix=None, error="HTTP 500")), "unknown"),
        (doc(*DEPLOY, cve(unmatched=["busybox:1.36"])), "partial"),  # some images not scanned yet
        (doc(*DEPLOY, cve(critical=1, unmatched=["busybox:1.36"])), "fail"),
        (doc(*DEPLOY, cve(high=1, unmatched=["busybox:1.36"])), "partial"),
        (doc(*DEPLOY), "unknown"),  # no report
        (doc(*DEPLOY, cve(), backstage="unavailable: timeout"), "unknown"),
        (doc(*DEPLOY, cve(matched=[])), "unknown"),  # an empty report scanned nothing: no pass
        (doc(*DEPLOY, cve(matched=[], unmatched=["reg/api:v2"])), "unknown"),  # nothing scanned yet
        (doc(*DEPLOY, cve(critical=1, matched=[])), "fail"),  # a critical in the totals still wins
        (doc(*DEPLOY, cve(kev=None, nofix=None)), "unknown"),  # a portal before v1.7.0: no KEV count
    ],
    "sec.dependabot": [
        (doc(alerts(), metric("dependabot.alertsCritical", "success", 0), metric("dependabot.alertsHigh", "success", 0)),
         "pass"),
        (doc(alerts(), metric("dependabot.alertsCritical", "success", 0), metric("dependabot.alertsHigh", "warning", 4)),
         "partial"),
        (doc(alerts(), metric("dependabot.alertsCritical", "error", 2), metric("dependabot.alertsHigh", "success", 0)),
         "fail"),
        (doc(alerts(False, 404)), "fail"),
        (doc(alerts()), "unknown"),  # on, but no scorecard metrics
        (doc(alerts(), metric("dependabot.alertsCritical", "success", 0),
             metric("dependabot.alertsHigh", None, None, "error", "403 Resource not accessible")), "unknown"),
        (doc(alerts(None, 403)), "unknown"),
        (doc(github="unavailable: gh not installed"), "unknown"),  # no github facts at all
    ],
    "sec.dep_updates": [
        (doc(afile("dependabot"), afile("renovate", False)), "pass"),
        (doc(afile("dependabot", False), afile("renovate")), "pass"),
        (doc(afile("dependabot", False), afile("renovate", False)), "fail"),
        (doc(app=U), "unknown"),
    ],
    "sec.actions_pinned": [
        (doc(wf()), "pass"),
        (doc(wf(uses=[{"ref": "actions/checkout@v4", "pinned": False, "line": 8}])), "fail"),
        (doc(afile("readme")), "n/a"),
    ],
    "sec.token_perms": [
        (doc(wf()), "pass"),
        (doc(wf(perms=None, without=[])), "pass"),  # every job sets its own
        (doc(wf(), wf("release", perms=None, without=["publish"])), "partial"),
        (doc(wf(perms=None, without=["build"])), "fail"),
        (doc(wf(), wf("release", perms="write-all", write_all=True)), "fail"),
        (doc(afile("readme")), "n/a"),
    ],
    "sec.sa_token": [
        (doc(wl(automount_sa_token=False, service_account=None), ctr()), "pass"),
        (doc(wl(automount_sa_token=None, service_account="api"), ctr()), "pass"),
        (doc(wl(automount_sa_token=None, service_account=None), ctr()), "partial"),
        (doc(wl(automount_sa_token=True, service_account="default"), ctr()), "partial"),
    ],
    "sec.repo_hygiene": [
        (doc(afile("codeowners"), afile("security"), protection()), "pass"),
        (doc(afile("codeowners"), afile("security", False), protection()), "partial"),
        (doc(afile("codeowners", False), afile("security", False), protection(False, 404)), "fail"),
        (doc(afile("codeowners"), afile("security"), protection(None, 403)), "pass"),  # unknown protection left out
        (doc(afile("codeowners", False), afile("security", False), github="unavailable: gh not installed"), "fail"),
    ],
    "rel.probes": [
        (doc(*DEPLOY, ctr("Deployment/api/init", init=True, probes=NO_PROBES)), "pass"),  # init needs none
        (doc(wl(), ctr(probes={"readiness": True, "liveness": False, "startup": False})), "fail"),
        (doc(wl(), ctr("Deployment/api/init", init=True)), "unknown"),  # no non-init container rendered
        (doc(wl(), ctr(probes=NO_PROBES), *CRONJOB), "fail"),  # only the Deployment's container counts
        (doc(*DEPLOY, *CRONJOB), "pass"),  # batch containers take no probes
        (doc(*CRONJOB), "n/a"),
        (doc(wl("Job/migrate", replicas=None), ctr("Job/migrate/migrate", probes=NO_PROBES)), "n/a"),
    ],
    "rel.resources": [
        (doc(*DEPLOY), "pass"),
        (doc(wl(), ctr(resources=res(lcpu=None))), "fail"),
        (doc(*DEPLOY, deploy="skipped: x"), "unknown"),
    ],
    "rel.pdb": [
        (doc(wl(replicas=2), ctr(), obj("PodDisruptionBudget/api", selector={"app": "api"})), "pass"),
        (doc(wl(replicas=2), ctr()), "fail"),
        (doc(wl(replicas=3), ctr(), obj("PodDisruptionBudget/x", selector={"app": "x"})), "fail"),
        (doc(wl(replicas=1), ctr()), "n/a"),
        (doc(wl(replicas=None), ctr()), "n/a"),
        (doc(wl(replicas=None), ctr(), obj("HorizontalPodAutoscaler/api", target="Deployment/api", min=2, max=5)),
         "fail"),  # the HPA keeps two or more running
        (doc(wl(replicas=2), ctr(), obj("PodDisruptionBudget/x", selector={},
                                        match_expressions=[expr("app", "In", "other")])), "fail"),  # final review I3
        (doc(wl(replicas=2), ctr(), obj("PodDisruptionBudget/x", selector={},
                                        match_expressions=[expr("app", "In", "api", "web")])), "pass"),
    ],
    "rel.restarts": [
        (doc(cw(), pod("api-1"), pod("api-2")), "pass"),
        (doc(cw(), pod("api-1", restarts=2), pod("api-2")), "partial"),
        (doc(cw(), pod("api-1", restarts=1, oom=True)), "fail"),
        (doc(cw(found=False)), "unknown"),
        (doc(cw()), "unknown"),  # found, but no pods
        (doc(cw(), pod("api-1", oom=True), cw("Deployment/cache", found=False)), "fail"),
        (doc(cw(), pod("api-1"), cluster="skipped: --no-live"), "unknown"),
    ],
    "rel.dependencies": [
        (doc(entity(), dep("component:dex/dex")), "pass"),
        (doc(entity(), dep("component:dex/dex"), dep("component:x/x", "experimental")), "partial"),
        (doc(entity(), dep("component:dex/dex"), dep("resource:vault/vault", None)), "pass"),  # null lifecycle: n/a
        (doc(entity(), dep("resource:vault/vault", None)), "n/a"),
        (doc(entity()), "n/a"),
        (doc(entity(), dep("component:x/x", None, "not found")), "unknown"),
        (doc(backstage=U), "unknown"),
    ],
    "perf.rightsize": [
        (doc(*DEPLOY, use(cpu=60, mem=100)), "pass"),
        (doc(*DEPLOY, use(cpu=250, mem=100)), "partial"),  # above the 200m request
        (doc(wl(), ctr(resources=res(rcpu="500m", lcpu="500m")), use(cpu=460, mem=100)), "partial"),  # 92% of limit
        (doc(*DEPLOY), "unknown"),
        (doc(*DEPLOY, use(), cluster="unavailable: no namespace"), "unknown"),
        (doc(wl(), ctr(resources=res(None, None, None, None)), use()), "unknown"),
    ],
    "cost.overprovision": [
        (doc(*DEPLOY, use(cpu=60, mem=100)), "pass"),
        (doc(wl(), ctr(resources=res(rcpu="1")), use(cpu=10, mem=200)), "partial"),  # 1000m requested, 10m used
        (doc(wl(), ctr(resources=res(rmem="2Gi")), use(cpu=100, mem=100)), "partial"),  # 2048Mi vs 100Mi
        (doc(wl(), ctr(resources=res(rcpu="100m", rmem="128Mi")), use(cpu=1, mem=1)), "pass"),  # at the floors
        (doc(*DEPLOY), "unknown"),
        (doc(wl(), ctr(resources=res(None, None, None, None)), use()), "unknown"),  # usage, but no requests
        (doc(*DEPLOY, use(), ctr("Deployment/api/proxy", resources=res(None, None, None, None)),
             use("Deployment/api/proxy", cpu=1, mem=1)), "pass"),  # the proxy without requests is skipped
    ],
    "sus.utilization": [
        (doc(*DEPLOY, use(cpu=60)), "pass"),
        (doc(*DEPLOY, use(cpu=5)), "partial"),  # 5m of 200m
        (doc(*DEPLOY), "unknown"),
        (doc(wl(), ctr(resources=res(rcpu=None)), use(cpu=5)), "unknown"),
    ],
}

# Rows of the plan's rule table with a partial or an n/a outcome: each needs a case.
PARTIAL = {"ops.catalog", "ops.docs", "ops.open_prs", "sec.hardening", "sec.netpol", "sec.cve", "sec.dependabot",
           "sec.token_perms", "sec.sa_token", "sec.repo_hygiene", "rel.restarts", "rel.dependencies",
           "perf.rightsize", "cost.overprovision", "sus.utilization"}
NA = {"sec.base_digest", "sec.actions_pinned", "sec.token_perms", "rel.pdb", "rel.dependencies", "rel.probes"}

# Task 7's happy path, decided by hand from its facts (test_collect.World).
HAPPY = {
    "ops.catalog": "pass", "ops.runbook": "pass", "ops.docs": "pass", "ops.open_prs": "pass",
    "sec.image_digest": "fail", "sec.base_digest": "pass", "sec.nonroot": "fail", "sec.hardening": "partial",
    "sec.netpol": "partial", "sec.secrets": "fail", "sec.cve": "pass", "sec.dependabot": "unknown",
    "sec.dep_updates": "fail", "sec.actions_pinned": "pass", "sec.token_perms": "pass", "sec.sa_token": "partial",
    "sec.repo_hygiene": "partial", "rel.probes": "fail", "rel.resources": "fail", "rel.pdb": "n/a",
    "rel.restarts": "fail", "rel.dependencies": "pass", "perf.rightsize": "partial", "cost.overprovision": "pass",
    "sus.utilization": "pass",
}


def run(rule_id: str, d: dict) -> tuple[str, str, list[str]]:
    return ev.RULES[rule_id](Facts(d))


class RuleTableTest(unittest.TestCase):
    def test_rules_cover_the_rule_checks(self):
        self.assertEqual(set(ev.RULES), {c["id"] for c in CHECKS if c["kind"] == "rule"})

    def test_every_rule_has_a_passing_and_a_non_passing_case(self):
        self.assertEqual(set(CASES), set(ev.RULES))
        for rid, cases in CASES.items():
            got = [want for _, want in cases]
            self.assertIn("pass", got, rid)
            self.assertTrue(any(w != "pass" for w in got), rid)
        for rid in PARTIAL:
            self.assertIn("partial", [w for _, w in CASES[rid]], rid)
        for rid in NA:
            self.assertIn("n/a", [w for _, w in CASES[rid]], rid)

    def test_cases(self):
        for rid, cases in CASES.items():
            for i, (d, want) in enumerate(cases):
                with self.subTest(rule=rid, case=i):
                    status, reason, ids = run(rid, d)
                    self.assertEqual(status, want, reason)
                    self.assertIsInstance(reason, str)
                    self.assertTrue(reason)
                    known = {f["id"] for f in d["facts"]}
                    self.assertTrue(set(ids) <= known, (rid, ids))

    def test_unavailable_sources_give_unknown_or_na(self):
        d = {"meta": {"sources": {s: U for s in SOURCES}}, "facts": []}
        for rid in ev.RULES:
            with self.subTest(rule=rid):
                status, reason, _ = run(rid, d)
                self.assertIn(status, ("unknown", "n/a"))
                if status == "unknown":
                    self.assertRegex(reason, r"^\w+ unavailable: x")

    def test_unavailable_reason_names_the_source_and_its_status(self):
        self.assertEqual(run("rel.restarts", doc(cluster="skipped: --no-live"))[:2],
                         ("unknown", "cluster unavailable: skipped: --no-live"))
        self.assertEqual(run("ops.open_prs", doc(scorecard="not installed (404)"))[1],
                         "scorecard unavailable: not installed (404)")
        self.assertEqual(run("rel.probes", doc(*DEPLOY, deploy="unavailable: no managed-by-location"))[1],
                         "deploy unavailable: no managed-by-location")

    def test_review_focus_1_no_dockerfile_no_workflows(self):
        d = doc(*(afile(k) for k in ("readme", "codeowners", "security", "dependabot", "renovate", "tests_dir")))
        for rid in ("sec.base_digest", "sec.actions_pinned", "sec.token_perms"):
            self.assertEqual(run(rid, d)[0], "n/a", rid)

    def test_review_focus_4_workload_not_running_live(self):
        status, reason, ids = run("rel.restarts", doc(cw("Deployment/valkey", found=False)))
        self.assertEqual(status, "unknown")
        self.assertIn("Deployment/valkey: not found live", reason)
        self.assertEqual(ids, ["cluster.workload.Deployment/valkey"])

    def test_reasons_name_the_offending_items(self):
        _, reason, ids = run("rel.probes", doc(wl("Deployment/valkey"), ctr(
            "Deployment/valkey/valkey", probes={"readiness": True, "liveness": False, "startup": False})))
        self.assertEqual(reason, "Deployment/valkey/valkey has no liveness probe")
        self.assertEqual(ids, ["deploy.container.Deployment/valkey/valkey"])
        _, reason, _ = run("sec.actions_pinned", doc(wf(uses=[{"ref": "actions/checkout@v4", "pinned": False,
                                                               "line": 8}])))
        self.assertEqual(reason, ".github/workflows/ci.yml:8 uses actions/checkout@v4")
        _, reason, _ = run("rel.resources", doc(wl(), ctr(resources=res(lcpu=None, lmem=None))))
        self.assertEqual(reason, "Deployment/api/api has no limits.cpu, limits.memory")
        root = doc(wl(pod_run_as_non_root=None), ctr(sec={"runAsNonRoot": None, "runAsUser": None}),
                   F("app.dockerfile.user", {"user": "10001"}, "Dockerfile"))
        root["meta"]["app"] = {"slug": "arigsela/api"}  # reg/api is built from this repo
        _, reason, ids = run("sec.nonroot", root)
        self.assertIn("Deployment/api/api", reason)
        self.assertIn("Dockerfile USER 10001", reason)
        self.assertIn("app.dockerfile.user", ids)
        _, reason, _ = run("sec.cve", doc(*DEPLOY, cve(critical=1, high=1, unmatched=["busybox:1.36"])))
        self.assertIn("1 fixable critical: CVE-1 in openssl (fixed 3.0.15)", reason)
        self.assertIn("not scanned: busybox:1.36", reason)
        self.assertNotIn("CVE-2", reason)  # a non-exploited high is not named
        _, reason, _ = run("perf.rightsize", doc(*DEPLOY, use(cpu=250, mem=100)))
        self.assertEqual(reason, "Deployment/api/api cpu 250m is above its 200m request")

    def test_nonroot_dockerfile_user_only_for_the_apps_own_image(self):  # final review I2
        d = doc(wl(pod_run_as_non_root=None), ctr(sec={"runAsNonRoot": None, "runAsUser": None}),
                wl("Deployment/valkey", pod_run_as_non_root=None),
                ctr("Deployment/valkey/valkey", image="valkey/valkey:8", sec={"runAsNonRoot": None, "runAsUser": None}),
                F("app.dockerfile.user", {"user": "10001"}, "Dockerfile"))
        d["meta"]["app"] = {"slug": "arigsela/api"}
        _, reason, ids = run("sec.nonroot", d)
        self.assertEqual(reason, "Deployment/api/api sets neither runAsNonRoot nor a non-zero runAsUser "
                                 "(Dockerfile USER 10001); Deployment/valkey/valkey sets neither runAsNonRoot nor a "
                                 "non-zero runAsUser")
        d["facts"] = [x for x in d["facts"] if not x["id"].startswith("deploy.container.Deployment/api/")]
        _, reason, ids = run("sec.nonroot", d)
        self.assertEqual(reason, "Deployment/valkey/valkey sets neither runAsNonRoot nor a non-zero runAsUser")
        self.assertNotIn("app.dockerfile.user", ids)

    def test_fix_round_1_reasons(self):
        _, reason, ids = run("rel.probes", doc(wl(), ctr(probes=NO_PROBES), *CRONJOB))
        self.assertEqual(reason, "Deployment/api/api has no readiness or liveness probe")
        self.assertEqual(ids, ["deploy.container.Deployment/api/api"])
        self.assertEqual(run("rel.probes", doc(*CRONJOB))[1], "only Job/CronJob containers, which take no probes")
        self.assertEqual(run("sec.cve", doc(*DEPLOY, cve(matched=[])))[1],
                         "the CVE report matched none of the rendered images")

    def test_cve_policy_reasons(self):  # the Scorecard CVE cards' policy, 2026-10-26
        self.assertEqual(run("sec.cve", doc(*DEPLOY, cve(high=3)))[1],
                         "no fixable critical or actively exploited CVEs in 1 scanned images")
        self.assertEqual(run("sec.cve", doc(*DEPLOY, cve(nofix=2)))[1],
                         "no fixable critical or actively exploited CVEs in 1 scanned images; "
                         "2 critical with no fix yet (awareness, not counted)")
        self.assertEqual(run("sec.cve", doc(*DEPLOY, cve(kev=2, nofix=1)))[1],
                         "2 actively exploited (CISA KEV) with a fix; "
                         "1 critical with no fix yet (awareness, not counted)")
        self.assertEqual(run("sec.cve", doc(*DEPLOY, cve(matched=[], unmatched=["reg/api:v2"])))[1],
                         "the CVE report matched none of the rendered images (not scanned: reg/api:v2)")
        self.assertEqual(run("sec.cve", doc(*DEPLOY, cve(kev=None)))[1],
                         "the CVE report gave no KEV count (portal older than v1.7.0)")
        self.assertEqual(run("cost.overprovision", doc(wl(), ctr(resources=res(None, None, None, None)), use()))[1],
                         "no CPU or memory requests to compare live usage with")
        self.assertEqual(run("cost.overprovision", doc(*DEPLOY, use(), ctr("Deployment/api/proxy",
                                                       resources=res(None, None, None, None)),
                                                       use("Deployment/api/proxy", cpu=1, mem=1)))[1],
                         "requests are within 4x of live usage (1 container)")

    def test_long_lists_are_capped(self):
        many = [ctr(f"Deployment/api/c{i}", image=f"img{i}:1", image_pinned=False) for i in range(8)]
        _, reason, ids = run("sec.image_digest", doc(wl(), *many))
        self.assertEqual(len(ids), 8)
        self.assertTrue(reason.endswith("; and 3 more"), reason)

    def test_worst(self):
        self.assertEqual(ev.worst([]), "n/a")
        self.assertEqual(ev.worst(["n/a", "n/a"]), "n/a")
        self.assertEqual(ev.worst(["pass", "n/a"]), "pass")
        self.assertEqual(ev.worst(["pass", "unknown"]), "unknown")
        self.assertEqual(ev.worst(["unknown", "partial", "pass"]), "partial")
        self.assertEqual(ev.worst(["partial", "fail", "n/a"]), "fail")

    def test_constants(self):
        self.assertEqual((rules.NEAR_LIMIT, rules.OVERPROVISION_RATIO, rules.OVERPROVISION_MIN_CPU_M,
                          rules.OVERPROVISION_MIN_MEM_MI, rules.IDLE_RATIO), (0.9, 4, 100, 128, 0.10))
        self.assertIs(ev.RULES, rules.RULES)  # evaluate re-exports the one RULES dict


class EvaluateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.happy = happy_path_facts()
        cls.results = ev.evaluate(cls.happy, CHECKS)
        cls.by_id = {c["id"]: c for c in cls.results["checks"]}

    def test_shape_and_order(self):
        self.assertEqual([c["id"] for c in self.results["checks"]], [c["id"] for c in CHECKS])
        for c, src in zip(self.results["checks"], CHECKS):
            self.assertEqual(set(c), {"id", "pillar", "title", "kind", "blocker", "status", "reason", "facts",
                                      "hints"})
            self.assertEqual((c["pillar"], c["title"], c["kind"], c["blocker"]),
                             (src["pillar"], src["title"], src["kind"], bool(src.get("blocker"))))

    def test_happy_path_rule_statuses(self):
        got = {c["id"]: c["status"] for c in self.results["checks"] if c["kind"] == "rule"}
        self.assertEqual(got, HAPPY)
        for c in self.results["checks"]:
            if c["kind"] == "rule":
                self.assertIn(c["status"], STATUSES)
                self.assertNotIn("rule failed", c["reason"])

    def test_happy_path_reasons(self):
        self.assertIn("Deployment/valkey/valkey has no readiness or liveness probe", self.by_id["rel.probes"]["reason"])
        self.assertIn("Deployment/valkey: not found live", self.by_id["rel.restarts"]["reason"])
        self.assertIn("demo-7d9f8c6b5-aaaaa", self.by_id["rel.restarts"]["reason"])
        self.assertIn("Secret/demo-secret", self.by_id["sec.secrets"]["reason"])
        self.assertIn("busybox:1.36", self.by_id["sec.image_digest"]["reason"])
        # valkey's image is not built from arigsela/demo, so the app's Dockerfile USER says nothing about it
        self.assertEqual(self.by_id["sec.nonroot"]["reason"],
                         "Deployment/valkey/valkey sets neither runAsNonRoot nor a non-zero runAsUser")

    def test_catalog_sources_name_what_each_rule_reads(self):
        # Knock out one source at a time: a rule that reports it unavailable must list it in checks.yaml.
        sources = {c["id"]: set(c["sources"]) for c in CHECKS}
        for s in SOURCES:
            d = json.loads(json.dumps(self.happy))
            d["meta"]["sources"][s] = U
            for rid in ev.RULES:
                with self.subTest(source=s, rule=rid):
                    _, reason, _ = run(rid, d)
                    if f"{s} unavailable" in reason:
                        self.assertIn(s, sources[rid])

    def test_judgment_stubs(self):
        alerts_check = self.by_id["ops.alerts"]
        self.assertIsNone(alerts_check["status"])
        self.assertEqual(alerts_check["facts"], ["deploy.alert_source", "deploy.alert_rule.demo-up",
                                                 "deploy.alert_rule.generic-mem"])
        facts = Facts(self.happy)
        for c in CHECKS:
            if c["kind"] == "judgment":
                got = self.by_id[c["id"]]
                self.assertIsNone(got["status"], c["id"])
                self.assertEqual(got["facts"], facts.match(c["facts"]), c["id"])
                self.assertEqual(got["hints"], [], c["id"])

    def test_person_checks_have_no_status(self):
        for c in self.results["checks"]:
            if c["kind"] == "person":
                self.assertIsNone(c["status"], c["id"])
                self.assertFalse(c["blocker"], c["id"])

    def test_a_rule_that_raises_gives_unknown(self):
        def boom(_f):
            raise KeyError("x")
        with mock.patch.dict(ev.RULES, {"ops.catalog": boom}):
            got = {c["id"]: c for c in ev.evaluate(doc(), CHECKS)["checks"]}
        self.assertEqual(got["ops.catalog"]["status"], "unknown")
        self.assertIn("KeyError", got["ops.catalog"]["reason"])


class HintsTest(unittest.TestCase):
    def hints(self, *facts) -> dict[str, list[dict]]:
        return {c["id"]: c["hints"] for c in ev.evaluate(doc(*facts), CHECKS)["checks"] if c["kind"] == "person"}

    def test_runbook_rollback_line(self):
        rb = F("deploy.text.base-apps/api/runbook.md", {"text": "# Runbook\n\nRollback: argocd app rollback api\n"},
               "base-apps/api/runbook.md")
        got = ev.evaluate(doc(rb), CHECKS)["checks"]
        rollback = next(c for c in got if c["id"] == "orr.rollback")
        self.assertIn({"evidence": "base-apps/api/runbook.md:3", "text": "Rollback: argocd app rollback api"},
                      rollback["hints"])
        self.assertEqual(rollback["facts"], ["deploy.text.base-apps/api/runbook.md"])

    def test_case_insensitive_capped_and_clipped(self):
        text = "\n".join(["SLO: 99.9%", "x" * 200 + " slo", "error budget policy", "SLA four", "nothing here"])
        got = self.hints(F("app.text.README.md", {"text": text}, "README.md"))
        self.assertEqual([h["evidence"] for h in got["orr.slo"]], ["README.md:1", "README.md:2", "README.md:3"])
        self.assertEqual(len(got["orr.slo"][1]["text"]), 160)
        self.assertEqual(got["orr.oncall"], [])

    def test_only_text_facts_are_read(self):
        got = self.hints(F("deploy.host_mentions.rollback.example.com", [{"file": "a", "line": 1,
                                                                          "text": "rollback"}]),
                         F("deploy.file.runbook", {"exists": True, "path": "rollback.md"}))
        self.assertEqual(got["orr.rollback"], [])


class VerdictTest(unittest.TestCase):
    CHECKS = [{"id": "b", "kind": "rule", "blocker": True}, {"id": "n", "kind": "rule", "blocker": False},
              {"id": "j", "kind": "judgment", "blocker": True}, {"id": "p", "kind": "person"}]

    def v(self, **statuses) -> str:
        return ev.verdict(self.CHECKS, {"b": "pass", "n": "pass", "j": "pass", "p": None, **statuses})

    def test_rule(self):
        self.assertEqual(self.v(), "Ready")
        self.assertEqual(self.v(b="partial"), "Ready with gaps")
        self.assertEqual(self.v(b="unknown"), "Ready with gaps")
        self.assertEqual(self.v(n="fail"), "Ready with gaps")
        self.assertEqual(self.v(b="fail"), "Not ready")
        self.assertEqual(self.v(j="fail", n="partial"), "Not ready")
        self.assertEqual(self.v(n="unknown"), "Ready")
        self.assertEqual(self.v(n="n/a", b="n/a"), "Ready")
        self.assertEqual(self.v(p="fail"), "Ready")  # person checks never count

    def test_missing_status_counts_as_unknown(self):
        self.assertEqual(ev.verdict(self.CHECKS, {"b": "pass", "n": "pass"}), "Ready with gaps")

    def test_catalog_all_pass(self):
        statuses = {c["id"]: (None if c["kind"] == "person" else "pass") for c in CHECKS}
        self.assertEqual(ev.verdict(CHECKS, statuses), "Ready")


class MainTest(unittest.TestCase):
    def test_writes_results_json(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "facts.json").write_text(json.dumps(doc(*DEPLOY)))
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = ev.main(["--out", d])
            self.assertEqual(rc, 0)
            self.assertEqual(out.getvalue().strip().splitlines()[-1], f"results: {Path(d) / 'results.json'}")
            results = json.loads((Path(d) / "results.json").read_text())
            self.assertEqual(len(results["checks"]), 40)

    def test_missing_facts_json(self):
        with tempfile.TemporaryDirectory() as d:
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                rc = ev.main(["--out", d])
            self.assertEqual(rc, 1)
            self.assertIn("facts.json", err.getvalue())
            self.assertFalse((Path(d) / "results.json").exists())


if __name__ == "__main__":
    unittest.main()
