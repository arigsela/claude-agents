# Run: uv run --with pyyaml --with "pathspec<1" python -m unittest discover -s tests/explainer
"""Service-mode facts: one ref, matched Applications, summaries, config keys, mentions, docs."""
from __future__ import annotations

import contextlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills/explainer/scripts"))
import facts_lib  # noqa: E402

APP_YAML = """apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: {name}
  namespace: argo-cd
spec:
  destination:
    namespace: mon
    server: https://kubernetes.default.svc
  source:
    repoURL: https://github.com/o/r.git
    path: {path}
    targetRevision: main
"""

MANIFESTS = """apiVersion: apps/v1
kind: Deployment
metadata:
  name: grafana
  namespace: mon
spec:
  replicas: 2
  selector:
    matchLabels:
      app: grafana
  template:
    metadata:
      labels:
        app: grafana
    spec:
      containers:
        - name: grafana
          image: grafana/grafana:10.1
          ports:
            - containerPort: 3000
          env:
            - name: DB_PASSWORD
              value: hunter2hunter2
            - name: GF_SERVER_ROOT_URL
              value: https://grafana.example.com
          readinessProbe:
            httpGet:
              path: /api/health
              port: 3000
          livenessProbe:
            httpGet:
              path: /api/health
              port: 3000
---
apiVersion: v1
kind: Service
metadata:
  name: grafana
  namespace: mon
spec:
  selector:
    app: grafana
  ports:
    - port: 80
      targetPort: 3000
---
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: grafana
  namespace: mon
spec:
  hostnames:
    - grafana.example.com
  rules:
    - matches:
        - path:
            value: /
      backendRefs:
        - name: grafana
          port: 80
---
apiVersion: batch/v1
kind: CronJob
metadata:
  name: grafana-backup
  namespace: mon
spec:
  schedule: "0 3 * * *"
  jobTemplate:
    spec:
      template:
        spec:
          containers:
            - name: backup
              image: busybox:1.36
---
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: grafana-admin
  namespace: mon
spec:
  secretStoreRef:
    name: vault
    kind: ClusterSecretStore
  target:
    name: grafana-admin
  data:
    - secretKey: admin-password
      remoteRef:
        key: secret/grafana
        property: admin-password
"""


def sh(*args: str, cwd: Path) -> str:
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True).stdout


def make_repo(tmp: Path, apps: list[str] | None = None, values: dict | None = None, tf: str = "",
              workflow: str = "", envs: tuple[str, ...] = ("prod",)) -> Path:
    """A git repo with directory-sourced Applications (one per env) and grafana's manifests."""
    for env in envs:
        (tmp / "argo" / env).mkdir(parents=True, exist_ok=True)
        for name in apps or ["grafana"]:
            path = f"apps/{name}"
            (tmp / "argo" / env / f"{name}.yaml").write_text(APP_YAML.format(name=name, path=path))
            (tmp / path).mkdir(parents=True, exist_ok=True)
            (tmp / path / "all.yaml").write_text(MANIFESTS.replace("name: grafana\n", f"name: {name}\n"))
    if values is not None:
        app = yaml.safe_load(APP_YAML.format(name="grafana", path="apps/grafana"))
        app["spec"]["source"]["helm"] = {"values": yaml.safe_dump(values)}
        (tmp / "argo/prod/grafana.yaml").write_text(yaml.safe_dump(app))
    if tf:
        (tmp / "infra").mkdir(exist_ok=True)
        (tmp / "infra/main.tf").write_text(tf)
    if workflow:
        (tmp / ".github/workflows").mkdir(parents=True, exist_ok=True)
        (tmp / ".github/workflows/deploy.yaml").write_text(workflow)
    sh("git", "init", "-q", "-b", "main", cwd=tmp)
    sh("git", "remote", "add", "origin", str(tmp), cwd=tmp)
    sh("git", "add", ".", cwd=tmp)
    sh("git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init", cwd=tmp)
    return tmp


class SystemFactsBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name) / "repo"
        self.tmp.mkdir()
        self.addCleanup(self._tmp.cleanup)

    @contextlib.contextmanager
    def trees(self, repo: Path):
        with mock.patch.object(facts_lib, "repo_from_origin", return_value="o/r"), \
             mock.patch.object(facts_lib, "local_root", return_value=repo):
            t = facts_lib.Trees.at("o/r", "main")
        try:
            yield t
        finally:
            t.close()


class TreesAtTest(SystemFactsBase):
    def test_trees_at_checks_out_the_ref(self):
        repo = make_repo(self.tmp)
        with self.trees(repo) as t:
            self.assertTrue((t.head / "argo/prod/grafana.yaml").is_file())
            self.assertIsNone(t.base)
            self.assertEqual(t.ref, "main")
            self.assertEqual(len(t.sha), 40)
        self.assertFalse(t.head.exists())  # close() removed the worktree


def app(name: str, path: str) -> dict:
    return yaml.safe_load(APP_YAML.format(name=name, path=path))


class MatchTest(unittest.TestCase):
    def test_match_by_name_directory_and_source_path(self):
        found = [("grafana", "argo/prod/grafana.yaml", app("grafana", "apps/grafana")),
                 ("grafana", "argo/nonprod/grafana.yaml", app("grafana", "apps/grafana")),
                 ("metrics", "argo/prod/metrics.yaml", app("metrics", "apps/grafana-agent")),
                 ("loki", "argo/prod/loki.yaml", app("loki", "apps/loki"))]
        apps, by = facts_lib.match_applications(found, ["grafana"])
        self.assertEqual(sorted(apps), ["grafana", "metrics"])
        self.assertEqual(len(apps["grafana"]), 2)
        self.assertIn({"app": "metrics", "name": "grafana", "by": "source-path"}, by)
        self.assertIn({"app": "grafana", "name": "grafana", "by": "name"}, by)

    def test_match_by_directory(self):
        found = [("web", "argo/prod/payments/web.yaml", app("web", "apps/web"))]
        apps, by = facts_lib.match_applications(found, ["payments"])
        self.assertEqual(list(apps), ["web"])
        self.assertEqual(by, [{"app": "web", "name": "payments", "by": "directory"}])

    def test_match_is_case_insensitive_and_empty_when_nothing_matches(self):
        found = [("Grafana-UI", "argo/prod/g.yaml", app("Grafana-UI", "apps/g"))]
        self.assertEqual(list(facts_lib.match_applications(found, ["grafana"])[0]), ["Grafana-UI"])
        self.assertEqual(facts_lib.match_applications(found, ["loki"]), ({}, []))
        self.assertEqual(facts_lib.match_applications(found, [" ", ""]), ({}, []))


class CollectSystemTest(SystemFactsBase):
    def test_no_match_lists_candidates_and_fails(self):
        repo = make_repo(self.tmp)
        with self.trees(repo) as t, self.assertRaises(SystemExit) as cm:
            facts_lib.collect_system("o/r", t, ["nothing"], [], None, False)
        self.assertIn("grafana", str(cm.exception))

    def test_too_many_matches_fails_without_all(self):
        repo = make_repo(self.tmp, apps=[f"svc-{i}" for i in range(9)])
        with self.trees(repo) as t, self.assertRaises(SystemExit) as cm:
            facts_lib.collect_system("o/r", t, ["svc"], [], None, False)
        self.assertIn("--all", str(cm.exception))
        with self.trees(repo) as t:
            self.assertEqual(len(facts_lib.collect_system("o/r", t, ["svc"], [], None, True)["apps"]), 9)

    def test_service_facts_focus_resources_scopes_and_shape(self):
        repo = make_repo(self.tmp, envs=("prod", "nonprod"))
        with self.trees(repo) as t:
            facts = facts_lib.collect_system("o/r", t, ["grafana"], [], None, False)
        self.assertEqual(facts["mode"], "service")
        self.assertIsNone(facts["pr"])
        self.assertEqual(facts["query"]["service"], ["grafana"])
        self.assertEqual(facts["query"]["ref"], "main")
        self.assertEqual({a["scope"] for a in facts["apps"]}, {"argo/prod", "argo/nonprod"})
        self.assertTrue(all(a["render"] == "rendered" for a in facts["apps"]))
        kinds = {(r["kind"], r["scope"]) for r in facts["resources"]}
        self.assertIn(("Deployment", "argo/prod"), kinds)
        self.assertIn(("Application", "argo/nonprod"), kinds)
        self.assertTrue(all(r["action"] in ("focus", "generated") for r in facts["resources"]))
        self.assertIn("generated", {r["action"] for r in facts["resources"]})  # the ExternalSecret's Secret
        self.assertTrue(any(e["type"] == "selects" for e in facts["edges"]))
        dep = next(r for r in facts["resources"] if r["kind"] == "Deployment" and r["scope"] == "argo/prod")
        self.assertEqual(dep["file"], "apps/grafana/all.yaml")
        self.assertEqual(dep["lines"][0], 1)
        for key in ("config", "docs", "related_prs", "terraform", "terraform_plans", "workflows",
                    "non_manifest_changes", "policy_hits", "notes"):
            self.assertIsInstance(facts[key], list, key)
        self.assertIsNone(facts["jira"])
        json.dumps(facts)  # serialisable

    def test_render_failure_is_recorded_not_fatal(self):
        repo = make_repo(self.tmp)
        with self.trees(repo) as t, mock.patch.object(facts_lib, "render_app", side_effect=RuntimeError("helm missing")):
            facts = facts_lib.collect_system("o/r", t, ["grafana"], [], None, False)
        self.assertEqual(facts["apps"][0]["render"], "source-diff")
        self.assertIn("RuntimeError", facts["apps"][0]["render_note"])
        self.assertEqual([r["kind"] for r in facts["resources"]], ["Application"])


if __name__ == "__main__":
    unittest.main()
