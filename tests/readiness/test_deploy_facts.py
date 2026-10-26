import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "readiness" / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import deploy_facts as df  # noqa: E402
import facts_lib  # noqa: E402
from fixtures import write_tree  # noqa: E402

REPO = "arigsela/kubernetes"
CANARY = "s3cr3t-canary-value"

APP = """apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: demo
  namespace: argocd
spec:
  destination:
    namespace: demo
    server: https://kubernetes.default.svc
  source:
    repoURL: https://github.com/arigsela/kubernetes
    targetRevision: main
    path: base-apps/demo
    directory:
      exclude: '{catalog-info.yaml,mkdocs.yml}'
"""

DEPLOY = """apiVersion: apps/v1
kind: Deployment
metadata:
  name: demo
  namespace: demo
spec:
  replicas: 1   # one in-memory run at a time
  selector:
    matchLabels:
      app: demo
  template:
    metadata:
      labels:
        app: demo
      annotations:
        prometheus.io/scrape: "true"
    spec:
      serviceAccountName: demo-sa
      automountServiceAccountToken: false
      securityContext:
        runAsNonRoot: true
      volumes:
        - name: tmp
          emptyDir: {}
      initContainers:
        - name: init-db
          image: busybox:1.36
          env:
            - name: LITERAL
              value: literal-env-value
      containers:
        - name: app
          image: 123.dkr.ecr.us-east-1.amazonaws.com/demo:v1
          readinessProbe:
            httpGet: {path: /ready, port: 8080}
          livenessProbe:
            httpGet: {path: /live, port: 8080}
          resources:
            requests: {cpu: 100m, memory: 128Mi}
            limits: {memory: 256Mi}
          securityContext:
            runAsNonRoot: true
            runAsUser: 10001
            readOnlyRootFilesystem: true
            allowPrivilegeEscalation: false
            capabilities:
              drop: [ALL]
        - name: oauth2-proxy
          image: quay.io/oauth2-proxy/oauth2-proxy:v7@sha256:%s
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: valkey
spec:
  replicas: 1
  template:
    spec:
      containers:
        - name: valkey
          image: valkey/valkey:8
""" % ("a" * 64)

OBJECTS = f"""apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: demo
spec:
  podSelector:
    matchLabels:
      app: demo
  ingress:
    - from:
        - podSelector:
            matchLabels:
              app: other
---
apiVersion: v1
kind: Secret
metadata:
  name: demo-secret
data:
  password: {CANARY}
---
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: demo-es
spec:
  target:
    name: demo-secret
  data:
    - secretKey: token
      remoteRef:
        key: demo/token
---
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: demo
spec:
  hostnames: [demo.example.com]
  rules:
    - backendRefs:
        - name: demo
          port: 80
---
apiVersion: v1
kind: Service
metadata:
  name: demo
spec:
  selector:
    app: demo
  ports:
    - port: 80
"""

RULES = """apiVersion: 1
groups:
  - name: g
    folder: f
    interval: 1m
    rules:
      - uid: demo-up
        title: Demo down
        condition: A
        data:
          - refId: A
            datasourceUid: prom
            model:
              expr: 'sum(up{namespace="demo"}) or vector(0)'
      - uid: generic-mem
        title: Memory high
        condition: A
        data:
          - refId: A
            datasourceUid: prom
            model:
              expr: '100 * max by (namespace, pod) (container_memory_working_set_bytes{container!=""}) %s'
      - uid: other-up
        title: Other down
        condition: A
        data:
          - refId: A
            datasourceUid: prom
            model:
              expr: 'sum(up{namespace="other"})'
""" % ("+ 1 " * 100)

ALERTS = ("apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: grafana-alerting\ndata:\n"
          "  contactpoints.yaml: |\n    apiVersion: 1\n  rules.yaml: |\n"
          + "".join("    " + line + "\n" for line in RULES.splitlines()))

FILES = {
    "base-apps/demo.yaml": APP,
    "base-apps/demo/deployment.yaml": DEPLOY,
    "base-apps/demo/objects.yaml": OBJECTS,
    "base-apps/demo/runbook.md": "# Runbook\nrestart it\n",
    "base-apps/demo/docs.md": "# Docs\n",
    "base-apps/demo/catalog-info.yaml": "apiVersion: backstage.io/v1alpha1\nkind: Component\nmetadata:\n  name: demo\n",
    "base-apps/logging/grafana-alerting.yaml": ALERTS,
    "base-apps/istio-ingress/authorizationpolicy.yaml":
        "apiVersion: security.istio.io/v1\nkind: AuthorizationPolicy\nmetadata:\n  name: x\nspec:\n  action: ALLOW\n  # host demo.example.com\n",
    "terraform/roots/x/ecr.tf":
        'resource "aws_ecr_lifecycle_policy" "demo" {\n  repository = "demo"\n  policy = "{}"\n}\n',
}


def run(files=None, folder="base-apps/demo"):
    with tempfile.TemporaryDirectory() as d:
        root = Path(d) / "tree"
        write_tree(root, files or FILES)
        work = Path(d) / "work"
        work.mkdir()
        facts = df.deploy_facts(root, REPO, folder, work)
        return {f["id"]: f for f in facts}, facts


class DeployFactsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.by, cls.facts = run()

    def test_application(self):
        a = self.by["deploy.application"]
        self.assertEqual(a["value"]["render"], "rendered")
        self.assertEqual(a["value"]["target_revision"], "main")
        self.assertEqual(a["value"]["file"], "base-apps/demo.yaml")
        self.assertEqual(a["value"]["namespace"], "demo")
        self.assertEqual(df.namespace_of(self.facts), "demo")
        self.assertFalse(any("catalog-info" in f["evidence"] for f in self.facts))
        self.assertTrue(all(f["source"] == "deploy" for f in self.facts))

    def test_workloads(self):
        w = self.by["deploy.workload.Deployment/demo"]
        self.assertEqual(w["value"]["replicas"], 1)
        self.assertEqual(w["value"]["replicas_comment"], "one in-memory run at a time")
        self.assertIs(w["value"]["pod_run_as_non_root"], True)
        self.assertIs(w["value"]["automount_sa_token"], False)
        self.assertEqual(w["value"]["service_account"], "demo-sa")
        self.assertEqual(w["value"]["volume_kinds"], ["emptyDir"])
        self.assertEqual(w["value"]["pod_labels"], {"app": "demo"})
        self.assertEqual(w["value"]["pod_annotations"], ["prometheus.io/scrape"])
        with tempfile.TemporaryDirectory() as d:
            write_tree(Path(d), FILES)
            lo, hi = facts_lib.find_lines(Path(d), "base-apps/demo/deployment.yaml", "Deployment", "demo")
        self.assertEqual(w["evidence"], f"base-apps/demo/deployment.yaml:{lo}-{hi}")
        self.assertIn("deploy.workload.Deployment/valkey", self.by)
        self.assertEqual(df.workload_refs(self.facts), ["Deployment/demo", "Deployment/valkey"])

    def test_containers(self):
        c = self.by["deploy.container.Deployment/demo/app"]["value"]
        self.assertFalse(c["init"])
        self.assertTrue(c["probes"]["readiness"] and c["probes"]["liveness"])
        self.assertFalse(c["probes"]["startup"])
        self.assertEqual(c["resources"]["requests"]["cpu"], "100m")
        self.assertEqual(c["resources"]["limits"]["memory"], "256Mi")
        self.assertIsNone(c["resources"]["limits"]["cpu"])
        self.assertEqual(c["security"]["runAsUser"], 10001)
        self.assertEqual(c["security"]["capabilities_drop"], ["ALL"])
        self.assertFalse(c["image_pinned"])
        init = self.by["deploy.container.Deployment/demo/init-db"]["value"]
        self.assertTrue(init["init"])
        self.assertTrue(self.by["deploy.container.Deployment/demo/oauth2-proxy"]["value"]["image_pinned"])
        self.assertEqual(len(df.image_refs(self.facts)), 4)

    def test_objects_and_secret(self):
        s = self.by["deploy.object.Secret/demo-secret"]["value"]
        self.assertEqual(s["keys"], ["password"])
        self.assertTrue(s["has_data"])
        blob = json.dumps(self.facts)
        self.assertNotIn(CANARY, blob)
        self.assertNotIn("literal-env-value", blob)
        self.assertEqual(self.by["deploy.object.NetworkPolicy/demo"]["value"], {"pod_selector": {"app": "demo"}})
        self.assertEqual(self.by["deploy.object.ExternalSecret/demo-es"]["value"],
                         {"target": "demo-secret", "keys": ["token"]})
        self.assertEqual(self.by["deploy.object.HTTPRoute/demo"]["value"],
                         {"hostnames": ["demo.example.com"], "backends": ["demo"]})
        self.assertEqual(self.by["deploy.object.Service/demo"]["value"],
                         {"selector": {"app": "demo"}, "ports": [{"port": 80}]})

    def test_files(self):
        self.assertEqual(self.by["deploy.file.runbook"]["value"], {"exists": True, "path": "base-apps/demo/runbook.md"})
        self.assertTrue(self.by["deploy.file.docs"]["value"]["exists"])
        self.assertIn("restart it", self.by["deploy.text.base-apps/demo/runbook.md"]["value"]["text"])

    def test_alert_rules(self):
        ids = sorted(i for i in self.by if i.startswith("deploy.alert_rule."))
        self.assertEqual(ids, ["deploy.alert_rule.demo-up", "deploy.alert_rule.generic-mem"])
        d = self.by["deploy.alert_rule.demo-up"]
        self.assertTrue(d["value"]["mentions_app"])
        self.assertTrue(d["value"]["namespace_filtered"])
        g = self.by["deploy.alert_rule.generic-mem"]
        self.assertFalse(g["value"]["namespace_filtered"])
        self.assertLessEqual(len(g["value"]["queries"][0]), 300)
        text = FILES["base-apps/logging/grafana-alerting.yaml"].splitlines()
        line = next(i for i, t in enumerate(text, 1) if "uid: demo-up" in t)
        self.assertEqual(d["evidence"], f"base-apps/logging/grafana-alerting.yaml:{line}")

    def test_registry(self):
        r = self.by["deploy.registry.0"]
        self.assertEqual(r["value"]["repository"], "demo")
        self.assertEqual(r["evidence"], "terraform/roots/x/ecr.tf:1")
        self.assertEqual(r["value"]["line"], 1)

    def test_host_mentions(self):
        m = self.by["deploy.host_mentions.demo.example.com"]["value"]
        self.assertEqual([x["file"] for x in m], ["base-apps/istio-ingress/authorizationpolicy.yaml"])
        self.assertEqual(m[0]["line"], 7)


class FallbackTest(unittest.TestCase):
    def test_helm_missing_falls_back(self):
        files = dict(FILES)
        files["base-apps/demo/Chart.yaml"] = "apiVersion: v2\nname: demo\nversion: 0.1.0\n"
        real = facts_lib.shutil.which
        with mock.patch.object(facts_lib.shutil, "which",
                               lambda n, *a, **k: None if "helm" in n else real(n, *a, **k)):
            by, _ = run(files)
        a = by["deploy.application"]["value"]
        self.assertEqual(a["render"], "raw-fallback")
        self.assertTrue(any("helm not installed" in n for n in a["notes"]))
        self.assertIn("deploy.workload.Deployment/demo", by)

    def test_no_application(self):
        files = {k: v for k, v in FILES.items() if k != "base-apps/demo.yaml"}
        by, facts = run(files)
        self.assertEqual(by["deploy.application"]["value"]["render"], "no-application")
        self.assertIn("deploy.workload.Deployment/demo", by)
        self.assertIsNone(df.namespace_of(facts))


if __name__ == "__main__":
    unittest.main()
