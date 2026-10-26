"""collect: one app-repo path in, facts.json out; every source fails soft."""
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

import collect as c  # noqa: E402
import deploy_facts as df  # noqa: E402
from readiness_model import SOURCES, Facts  # noqa: E402
from tests.readiness import fixtures as fx  # noqa: E402
from tests.readiness.test_app_facts import DOCKERFILE  # noqa: E402
from tests.readiness.test_deploy_facts import APP as DEPLOY_APP, FILES as DEPLOY_FILES  # noqa: E402

DATA = Path(__file__).resolve().parent / "data"
BASE = "https://backstage.test"
SLUG = "arigsela/demo"
DEPLOY_REPO = "arigsela/kubernetes"
LOCATION = f"url:https://github.com/{DEPLOY_REPO}/tree/main/base-apps/demo/catalog-info.yaml"
# deploy_facts.image_refs order: Deployment/demo's init container, its containers, then Deployment/valkey.
IMAGES = ["busybox:1.36", "123.dkr.ecr.us-east-1.amazonaws.com/demo:v1",
          "quay.io/oauth2-proxy/oauth2-proxy:v7@sha256:" + "a" * 64, "valkey/valkey:8"]
CI = """name: ci
on: [push]
permissions: {contents: read}
jobs:
  t:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1
      - run: pytest -q
"""
APP_FILES = {"Dockerfile": DOCKERFILE, ".github/workflows/ci.yml": CI, "README.md": "# demo\n",
             ".github/CODEOWNERS": "* @arigsela\n", "tests/test_demo.py": "",
             "pyproject.toml": 'dependencies = ["opentelemetry-sdk>=1.0"]\n'}
GET_CMD = "kubectl get deploy,statefulset,pods -n demo -o json --request-timeout=5s"
TOP_CMD = "kubectl top pods -n demo --containers --no-headers --request-timeout=5s"
OK200 = (0, "HTTP/2.0 200 OK\r\n\r\n{}", "")


def entity(name: str = "demo", location: str = LOCATION) -> dict:
    e = json.loads((DATA / "entity.json").read_text())
    e["metadata"].update(name=name, namespace="demo")
    e["metadata"]["annotations"].update({"backstage.io/managed-by-location": location,
                                         "github.com/project-slug": SLUG,
                                         "backstage.io/kubernetes-namespace": "demo"})
    return e


def app_checkout(tmp: Path, files: dict[str, str]) -> Path:
    """A clone whose origin is a file:// bare repo at <tmp>/github.com/arigsela/demo.git: the slug parses as
    arigsela/demo and `git ls-remote origin` stays local."""
    src = fx.git_repo(tmp, files)
    owner, name = SLUG.split("/")
    bare = tmp / "github.com" / owner / f"{name}.git"
    bare.parent.mkdir(parents=True)
    fx.git(tmp, "clone", "--quiet", "--bare", str(src), str(bare))
    fx.git(bare, "symbolic-ref", "HEAD", "refs/heads/main")
    work = tmp / "checkout"
    fx.git(tmp, "clone", "--quiet", bare.as_uri(), str(work))
    return work


class World:
    """The app checkout, a deploy remote, a fake Backstage (fetch) and fake kubectl/gh (run)."""

    def __init__(self, tmp: Path, entities: list[dict] | None = None, deploy_files: dict | None = None,
                 deploy_branches: dict | None = None):
        self.tmp = tmp
        self.app = app_checkout(tmp, APP_FILES)
        self.deploy_url = fx.bare_remote(tmp, deploy_files or DEPLOY_FILES, deploy_branches)
        self.entities = [entity()] if entities is None else entities
        self.override: dict[str, object] = {}  # path prefix -> (status, body) or an exception to raise
        self.fetches: list[tuple] = []
        self.runs: list[list[str]] = []
        self.env = {"BACKSTAGE_URL": BASE}
        self.repo_urls = {DEPLOY_REPO: self.deploy_url}
        self.responses = {
            GET_CMD: (0, (DATA / "kubectl_get.json").read_text(), ""),
            TOP_CMD: (0, (DATA / "kubectl_top.txt").read_text(), ""),
            f"gh api -i repos/{SLUG}": OK200,
            f"gh api -i repos/{SLUG}/vulnerability-alerts": (0, "HTTP/2.0 204 No Content\r\n\r\n", ""),
            f"gh api -i repos/{SLUG}/branches/main/protection": OK200,
        }
        self.out = tmp / "out"

    def fetch(self, method, url, body, headers, timeout):
        self.fetches.append((method, url, body, dict(headers)))
        assert url.startswith(BASE), url
        path = url[len(BASE):]
        for prefix, resp in self.override.items():
            if path.startswith(prefix):
                if isinstance(resp, BaseException):
                    raise resp
                return resp
        if path.startswith("/api/catalog/entities/by-query?"):
            return 200, json.dumps({"items": self.entities}).encode()
        if path.startswith("/api/catalog/entities/by-name/"):
            kind, ns, name = path.split("/")[-3:]
            return 200, json.dumps({"kind": kind, "metadata": {"name": name, "namespace": ns},
                                    "spec": {"lifecycle": "production"}}).encode()
        if (method, path) == ("POST", "/api/cve/report"):
            return 200, (DATA / "cve.json").read_bytes()
        if path == "/api/scorecard/metrics/catalog/component/demo/demo":
            return 200, (DATA / "scorecard.json").read_bytes()
        return 404, b"{}"

    def run(self, argv):
        self.runs.append(list(argv))
        return self.responses.get(" ".join(argv), (1, "", "no response"))

    def deps(self) -> c.Deps:
        return c.Deps(fetch=self.fetch, run=self.run, repo_url=lambda slug: self.repo_urls[slug], env=self.env)

    def collect(self, **kw) -> dict:
        with contextlib.redirect_stderr(io.StringIO()):
            return c.collect(self.app, self.out, deps=self.deps(), **kw)

    def main(self, *args: str) -> tuple[int, str, str]:
        o, e = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(o), contextlib.redirect_stderr(e):
            rc = c.main([str(self.app), "--out", str(self.out), *args], deps=self.deps())
        return rc, o.getvalue(), e.getvalue()

    def doc(self) -> dict:
        return json.loads((self.out / "facts.json").read_text())

    def posts(self) -> list[tuple]:
        return [f for f in self.fetches if f[0] == "POST"]


def by_id(doc: dict) -> dict[str, dict]:
    return {f["id"]: f for f in doc["facts"]}


def happy_path_facts() -> dict:
    """Task 7's happy-path facts doc, for tests of the later scripts (evaluate, render)."""
    with tempfile.TemporaryDirectory() as d:
        return World(Path(d)).collect()


class Case(unittest.TestCase):
    def world(self, **kw) -> World:
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        return World(Path(t.name), **kw)


class ParseManagedByTest(unittest.TestCase):
    def test_forms(self):
        self.assertEqual(c.parse_managed_by(
            "url:https://github.com/arigsela/kubernetes/tree/main/base-apps/hk-demo/catalog-info.yaml"),
            ("arigsela/kubernetes", "base-apps/hk-demo"))
        self.assertEqual(c.parse_managed_by("url:https://github.com/o/r/blob/v1/a/b/catalog-info.yaml"),
                         ("o/r", "a/b"))
        self.assertEqual(c.parse_managed_by("url:https://github.com/arigsela/beacon/blob/main/catalog-info.yaml"),
                         ("arigsela/beacon", ""))

    def test_other_locations(self):
        for loc in ("", "file:/tmp/catalog-info.yaml", "url:https://github.com/o/r",
                    "url:https://gitlab.com/o/r/-/blob/main/catalog-info.yaml",
                    "url:https://github.com/o/r/edit/main/x/catalog-info.yaml",
                    "url:https://evilgithub.com/o/r/tree/main/x/catalog-info.yaml",
                    # catalog data must not steer reads outside the deploy clone
                    "url:https://github.com/o/r/tree/main/../../../../etc/catalog-info.yaml",
                    "url:https://github.com/o/r/tree/main/a/../../b/catalog-info.yaml",
                    "url:https://github.com/o/r/blob/main/a/..",
                    "url:https://github.com/o/r/tree/main/./a/catalog-info.yaml",
                    "url:https://github.com/o/r/tree/main/a/./catalog-info.yaml",
                    "url:https://github.com/o/r/tree/main/a//b/catalog-info.yaml",
                    "url:https://github.com/o/r/tree/main//a/catalog-info.yaml"):
            self.assertIsNone(c.parse_managed_by(loc), loc)

    def test_dotted_names_are_not_traversal(self):
        self.assertEqual(c.parse_managed_by("url:https://github.com/o/r/tree/main/a/...b/.x/catalog-info.yaml"),
                         ("o/r", "a/...b/.x"))


class HappyPathTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        t = tempfile.TemporaryDirectory()
        cls.addClassCleanup(t.cleanup)
        cls.w = World(Path(t.name))
        cls.made: list[str] = []
        real = tempfile.mkdtemp

        def mkdtemp(*a, **k):
            p = real(*a, **k)
            cls.made.append(p)
            return p

        with mock.patch.object(c.tempfile, "mkdtemp", mkdtemp):
            cls.rc, cls.stdout, cls.stderr = cls.w.main()
        cls.d = cls.w.doc()
        cls.by = by_id(cls.d)

    def test_exit_and_last_line(self):
        self.assertEqual(self.rc, 0)
        self.assertEqual(self.stdout.strip().splitlines()[-1], f"facts: {self.w.out}/facts.json")
        self.assertEqual(self.stdout.strip().splitlines(), [f"facts: {self.w.out}/facts.json"])

    def test_every_source_ok(self):
        self.assertEqual(self.d["meta"]["sources"], {s: "ok" for s in SOURCES})

    def test_facts_accessor_reads_collect_doc(self):
        f = Facts(self.d)
        self.assertIs(f.ok("app"), True)
        self.assertTrue(all(f.ok(s) for s in SOURCES))
        self.assertEqual(f.value("backstage.entity")["ref"], "component:demo/demo")

    def test_meta(self):
        meta = self.d["meta"]
        self.assertEqual(meta["entity_ref"], "component:demo/demo")
        self.assertEqual(meta["backstage_url"], BASE)
        self.assertEqual(meta["app"]["slug"], SLUG)
        self.assertIs(meta["app"]["on_default_branch"], True)
        self.assertEqual(meta["app"]["default_branch"], "main")
        self.assertEqual(meta["app"]["sha"], fx.git(self.w.app, "rev-parse", "HEAD"))
        sha = fx.git(self.w.tmp, "ls-remote", self.w.deploy_url, "refs/heads/main").split()[0]
        self.assertEqual(meta["deploy"], {"repo": DEPLOY_REPO, "folder": "base-apps/demo", "ref": "main",
                                          "sha": sha, "application_file": "base-apps/demo.yaml"})
        self.assertRegex(meta["generated_at"], r"^\d{4}-\d\d-\d\dT")

    def test_facts_shape(self):
        for f in self.d["facts"]:
            self.assertEqual(set(f), {"id", "source", "value", "evidence"})
            self.assertIn(f["source"], SOURCES)
            self.assertEqual(f["id"].split(".")[0], f["source"], f["id"])
            self.assertIsInstance(f["evidence"], str)
        for prefix in ("app.file.readme", "app.dockerfile.user", "app.workflow.ci", "deploy.application",
                       "deploy.workload.Deployment/demo", "cluster.workload.Deployment/demo",
                       "github.dependabot_alerts", "github.branch_protection"):
            self.assertIn(prefix, self.by)

    def test_entity_and_dependencies(self):
        e = self.by["backstage.entity"]["value"]
        self.assertEqual(e["ref"], "component:demo/demo")
        self.assertEqual((e["owner"], e["lifecycle"], e["system"]),
                         ("group:default/platform", "production", "default/platform-observability"))
        self.assertIn("component:dex/dex", e["depends_on"])
        self.assertEqual(e["provides_apis"], ["default/hk-demo-api"])
        self.assertEqual(e["annotations"]["backstage.io/kubernetes-namespace"], "demo")
        self.assertEqual(self.by["backstage.entity"]["evidence"],
                         BASE + "/api/catalog/entities/by-name/component/demo/demo")
        deps = sorted(i for i in self.by if i.startswith("backstage.dependency."))
        self.assertEqual(len(deps), 6)
        self.assertEqual(self.by["backstage.dependency.component:dex/dex"]["value"]["lifecycle"], "production")

    def test_cve(self):
        posts = self.w.posts()
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0][1], BASE + "/api/cve/report")
        self.assertEqual(json.loads(posts[0][2]), {"images": IMAGES})
        self.assertEqual(json.loads(posts[0][2])["images"], df.image_refs(self.d["facts"]))
        v = self.by["backstage.cve"]["value"]
        self.assertIs(v["ok"], True)
        self.assertEqual(v["scanned_at"], "2026-10-25")
        self.assertEqual(v["totals"], {"critical": 0, "high": 2})
        self.assertEqual(len(v["matched"]), 1)
        self.assertEqual(v["unmatched"], [])
        self.assertEqual(v["findings"][0], {"id": "CVE-2026-1111", "severity": "HIGH", "pkg": "libssl3",
                                            "fixed": "3.0.15-1", "image": v["matched"][0]})

    def test_scorecard(self):
        self.assertEqual(self.by["scorecard.github.openPRs"]["value"],
                         {"value": 3, "evaluation": "success", "status": "success", "error": None,
                          "timestamp": "2026-10-25T09:00:00.000Z"})
        self.assertEqual(self.by["scorecard.github.openPRs"]["evidence"],
                         BASE + "/api/scorecard/metrics/catalog/component/demo/demo")
        high = self.by["scorecard.dependabot.alertsHigh"]["value"]
        self.assertEqual((high["status"], high["evaluation"], high["value"]), ("error", None, None))
        self.assertIn("403", high["error"])

    def test_live_reads(self):
        kubectl = [" ".join(a) for a in self.w.runs if a[0] == "kubectl"]
        self.assertEqual(kubectl, [GET_CMD, TOP_CMD])
        self.assertTrue(self.by["cluster.workload.Deployment/demo"]["value"]["found"])
        self.assertFalse(self.by["cluster.workload.Deployment/valkey"]["value"]["found"])
        self.assertIs(self.by["github.dependabot_alerts"]["value"]["enabled"], True)
        self.assertIs(self.by["github.branch_protection"]["value"]["protected"], True)

    def test_temp_dirs_removed(self):
        self.assertEqual(len(self.made), 1)
        self.assertFalse(Path(self.made[0]).exists())
        self.assertEqual(sorted(p.name for p in self.w.out.iterdir()), ["facts.json"])

    def test_progress_on_stderr(self):
        self.assertIn("collect:", self.stderr)
        self.assertNotIn("facts:", self.stderr)


class WorkingTreeTest(Case):
    def test_untracked_and_dirty_files_ignored(self):
        w = self.world()
        (w.app / "app-token.txt").write_text("TOKEN-CANARY\n")
        (w.app / "README.md").write_text("# dirty TOKEN-CANARY\n")
        d = w.collect()
        self.assertNotIn("TOKEN-CANARY", (w.out / "facts.json").read_text())
        self.assertEqual(by_id(d)["app.text.README.md"]["value"]["text"], "# demo\n")


class BackstageFailureTest(Case):
    def test_http_500(self):
        w = self.world()
        w.override = {"/": (500, b"boom")}
        rc, out, _ = w.main()
        self.assertEqual(rc, 0)
        d = w.doc()
        s = d["meta"]["sources"]
        self.assertEqual(s["backstage"], "unavailable: HTTP 500")
        self.assertTrue(s["deploy"].startswith("unavailable: "), s["deploy"])
        self.assertTrue(s["scorecard"].startswith("unavailable"), s["scorecard"])
        self.assertEqual(s["app"], "ok")
        self.assertEqual(s["cluster"], "unavailable: no namespace")
        self.assertEqual(s["github"], "ok")
        self.assertTrue(any(f["id"].startswith("app.") for f in d["facts"]))
        self.assertNotIn("backstage.entity", by_id(d))
        self.assertIsNone(d["meta"]["deploy"])
        self.assertIsNone(d["meta"]["entity_ref"])
        self.assertEqual(w.posts(), [])
        self.assertEqual(out.strip().splitlines()[-1], f"facts: {w.out}/facts.json")

    def test_non_json_and_timeout(self):
        for resp, reason in (((200, b"<html>"), "invalid JSON"), (TimeoutError(), "timeout")):
            w = self.world()
            w.override = {"/": resp}
            d = w.collect()
            self.assertEqual(d["meta"]["sources"]["backstage"], f"unavailable: {reason}")
            self.assertEqual(d["meta"]["sources"]["app"], "ok")

    def test_scorecard_404(self):
        w = self.world()
        w.override = {"/api/scorecard/": (404, b"")}
        d = w.collect()
        self.assertEqual(d["meta"]["sources"]["scorecard"], "not installed (404)")
        self.assertFalse([f for f in d["facts"] if f["id"].startswith("scorecard.")])
        self.assertEqual(d["meta"]["sources"]["backstage"], "ok")

    def test_cve_failure_keeps_catalog(self):
        w = self.world()
        w.override = {"/api/cve/": (502, b"")}
        d = w.collect()
        self.assertEqual(d["meta"]["sources"]["backstage"], "ok")
        v = by_id(d)["backstage.cve"]["value"]
        self.assertIs(v["ok"], False)
        self.assertEqual(v["error"], "HTTP 502")
        self.assertEqual(v["unmatched"], IMAGES)
        self.assertIn("backstage.entity", by_id(d))


class CatalogMatchTest(Case):
    def test_two_entities(self):
        w = self.world(entities=[entity(), entity(name="demo2")])
        rc, out, err = w.main()
        self.assertEqual(rc, 1)
        self.assertIn("component:demo/demo\n", out + err)
        self.assertIn("component:demo/demo2", out + err)
        self.assertFalse((w.out / "facts.json").exists())
        with self.assertRaises(c.Ambiguous) as cm, contextlib.redirect_stderr(io.StringIO()):
            c.collect(w.app, w.tmp / "out2", deps=w.deps())
        self.assertEqual(sorted(cm.exception.refs), ["component:demo/demo", "component:demo/demo2"])

    def test_entity_flag_skips_lookup(self):
        w = self.world(entities=[entity(), entity(name="demo2")])
        w.override = {"/api/catalog/entities/by-name/component/demo/demo": (200, json.dumps(entity()).encode())}
        d = w.collect(entity="component:demo/demo")
        self.assertEqual(d["meta"]["entity_ref"], "component:demo/demo")
        self.assertEqual(d["meta"]["sources"]["deploy"], "ok")
        self.assertFalse([f for f in w.fetches if "by-query" in f[1]])

    def test_no_entity(self):
        w = self.world(entities=[])
        d = w.collect()
        f = by_id(d)["backstage.entity"]
        self.assertIsNone(f["value"])
        s = d["meta"]["sources"]
        self.assertEqual(s["backstage"], "ok")
        self.assertEqual(s["deploy"], "unavailable: not in catalog")
        self.assertEqual(s["scorecard"], "skipped: not in catalog")
        self.assertEqual(s["cluster"], "unavailable: no namespace")
        self.assertIsNone(d["meta"]["entity_ref"])
        self.assertEqual(w.posts(), [])

    def test_catalog_entry_in_app_repo(self):  # Review Focus 2
        w = self.world(entities=[entity(location=f"url:https://github.com/{SLUG}/blob/main/catalog-info.yaml")])
        d = w.collect()
        s = d["meta"]["sources"]
        self.assertEqual(s["deploy"], "unavailable: catalog entry lives in the app repo")
        self.assertIsNone(d["meta"]["deploy"])
        self.assertEqual(s["backstage"], "ok")
        self.assertEqual(s["scorecard"], "ok")
        # No rendered workloads to match pods against: the cluster is not read, so live checks stay unknown.
        self.assertEqual(s["cluster"], "unavailable: no rendered workloads")
        self.assertFalse([a for a in w.runs if a[0] == "kubectl"])
        self.assertFalse([f for f in d["facts"] if f["source"] == "deploy"])


class DeployRevisionTest(Case):
    BRANCHES = {"release": {"base-apps/demo/runbook.md": "# Runbook\nrelease notes\n"}}

    def release_sha(self, w: World) -> str:
        return fx.git(w.tmp, "ls-remote", w.deploy_url, "refs/heads/release").split()[0]

    def test_deploy_ref(self):
        w = self.world(deploy_branches=self.BRANCHES)
        d = w.collect(deploy_ref="release")
        self.assertEqual(d["meta"]["deploy"]["ref"], "release")
        self.assertEqual(d["meta"]["deploy"]["sha"], self.release_sha(w))
        self.assertIn("release notes", by_id(d)["deploy.text.base-apps/demo/runbook.md"]["value"]["text"])

    def test_target_revision(self):
        app = DEPLOY_APP.replace("targetRevision: main", "targetRevision: release")
        w = self.world(deploy_files={**DEPLOY_FILES, "base-apps/demo.yaml": app}, deploy_branches=self.BRANCHES)
        d = w.collect()
        self.assertEqual(d["meta"]["deploy"]["ref"], "release")
        self.assertEqual(d["meta"]["deploy"]["sha"], self.release_sha(w))
        self.assertIn("release notes", by_id(d)["deploy.text.base-apps/demo/runbook.md"]["value"]["text"])

    def test_unreachable_deploy_repo(self):
        w = self.world()
        w.repo_urls = {DEPLOY_REPO: (w.tmp / "missing.git").as_uri()}
        d = w.collect()
        s = d["meta"]["sources"]
        self.assertTrue(s["deploy"].startswith("unavailable: clone failed"), s["deploy"])
        self.assertEqual(d["meta"]["deploy"]["repo"], DEPLOY_REPO)
        self.assertIsNone(d["meta"]["deploy"]["sha"])
        self.assertEqual(s["cluster"], "unavailable: no rendered workloads")
        self.assertEqual((s["app"], s["backstage"], s["github"]), ("ok", "ok", "ok"))

    def test_folder_escaping_the_clone(self):
        """A deploy folder that resolves outside the clone (a committed symlink) is never read."""
        w = self.world(entities=[entity(location=LOCATION.replace("base-apps/demo/", "base-apps/evil/"))])
        outside = w.tmp / "outside"
        fx.write_tree(outside, {"runbook.md": "OUTSIDE-CANARY\n",
                                "deployment.yaml": DEPLOY_FILES["base-apps/demo/deployment.yaml"]})
        src = fx.git_repo(w.tmp, DEPLOY_FILES)
        (src / "base-apps" / "evil").symlink_to(outside, target_is_directory=True)
        fx.commit_files(src, {}, "link")
        bare = w.tmp / "evil-remote.git"
        fx.git(w.tmp, "clone", "--quiet", "--bare", str(src), str(bare))
        w.repo_urls = {DEPLOY_REPO: bare.as_uri()}
        d = w.collect()
        self.assertEqual(d["meta"]["sources"]["deploy"], "unavailable: unsafe folder")
        self.assertFalse([f for f in d["facts"] if f["source"] == "deploy"])
        self.assertNotIn("OUTSIDE-CANARY", (w.out / "facts.json").read_text())

    def test_symlink_inside_folder_escaping_the_clone(self):
        """deploy.text would copy a runbook.md -> <outside file> link's target into facts.json."""
        w = self.world()
        secret = w.tmp / "secret.txt"
        secret.write_text("OUTSIDE-CANARY\n")
        src = fx.git_repo(w.tmp, {k: v for k, v in DEPLOY_FILES.items() if k != "base-apps/demo/runbook.md"})
        (src / "base-apps" / "demo" / "runbook.md").symlink_to(secret)
        fx.commit_files(src, {}, "link")
        bare = w.tmp / "evil-remote.git"
        fx.git(w.tmp, "clone", "--quiet", "--bare", str(src), str(bare))
        w.repo_urls = {DEPLOY_REPO: bare.as_uri()}
        d = w.collect()
        self.assertEqual(d["meta"]["sources"]["deploy"], "unavailable: unsafe folder")
        self.assertNotIn("OUTSIDE-CANARY", (w.out / "facts.json").read_text())

    def test_entity_namespace_reaches_alert_rules(self):
        """ApplicationSet apps have no hand-written Application: the entity's namespace scopes the alert rules."""
        w = self.world(deploy_files={k: v for k, v in DEPLOY_FILES.items() if k != "base-apps/demo.yaml"})
        d = w.collect()
        by = by_id(d)
        self.assertEqual(by["deploy.application"]["value"]["render"], "no-application")
        self.assertEqual(sorted(i for i in by if i.startswith("deploy.alert_rule.")),
                         ["deploy.alert_rule.demo-up", "deploy.alert_rule.generic-mem"])
        with mock.patch.object(c.df, "deploy_facts", wraps=c.df.deploy_facts) as spy:
            w.collect()
        self.assertEqual(spy.call_args.kwargs.get("namespace"), "demo")

    def test_missing_target_revision(self):
        app = DEPLOY_APP.replace("targetRevision: main", "targetRevision: gone")
        w = self.world(deploy_files={**DEPLOY_FILES, "base-apps/demo.yaml": app})
        d = w.collect()
        self.assertEqual(d["meta"]["sources"]["deploy"], "unavailable: checkout of 'gone' failed (git exited 128)")
        self.assertEqual(d["meta"]["deploy"]["ref"], "gone")
        self.assertEqual(d["meta"]["deploy"]["application_file"], "base-apps/demo.yaml")
        self.assertIsNone(d["meta"]["deploy"]["sha"])  # nothing was read at the deployed revision
        self.assertFalse([f for f in d["facts"] if f["source"] == "deploy"])


class LiveTest(Case):
    def test_no_live(self):
        w = self.world()
        d = w.collect(live=False)
        self.assertEqual(d["meta"]["sources"]["cluster"], "skipped: --no-live")
        self.assertFalse([a for a in w.runs if a[0] == "kubectl"])
        self.assertFalse([f for f in d["facts"] if f["source"] == "cluster"])
        self.assertEqual(d["meta"]["sources"]["github"], "ok")


class TokenTest(Case):
    def files_text(self, w: World) -> str:
        return "".join(p.read_text(errors="replace") for p in w.out.rglob("*") if p.is_file())

    def test_token_not_written(self):
        w = self.world()
        w.env = {**w.env, "BACKSTAGE_TOKEN": "t0k"}
        rc, out, err = w.main()
        self.assertEqual(rc, 0)
        self.assertTrue(w.fetches)
        self.assertTrue(all(f[3].get("Authorization") == "Bearer t0k" for f in w.fetches))
        self.assertNotIn("t0k", self.files_text(w))
        self.assertNotIn("t0k", out + err)

    def test_no_token_no_header(self):
        w = self.world()
        w.collect()
        self.assertFalse([f for f in w.fetches if "Authorization" in f[3]])

    def test_unexpected_errors_record_class_names_only(self):
        w = self.world()
        w.env = {**w.env, "BACKSTAGE_TOKEN": "t0k"}
        w.override = {"/api/scorecard/": ValueError("t0k in a message")}
        with mock.patch.object(c.af, "app_facts", side_effect=RuntimeError("t0k again")):
            rc, out, err = w.main()
        self.assertEqual(rc, 0)
        s = w.doc()["meta"]["sources"]
        self.assertEqual(s["scorecard"], "unavailable: ValueError")
        self.assertEqual(s["app"], "unavailable: RuntimeError")
        self.assertEqual(s["deploy"], "ok")
        self.assertNotIn("t0k", self.files_text(w))
        self.assertNotIn("t0k", out + err)


class InputTest(Case):
    def test_not_a_git_repo(self):
        with tempfile.TemporaryDirectory() as d:
            o, e = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(o), contextlib.redirect_stderr(e):
                rc = c.main([d, "--out", str(Path(d) / "out")], deps=c.Deps(fetch=None, run=None))
            self.assertEqual(rc, 1)
            self.assertIn("not a git repository", e.getvalue())
            self.assertFalse((Path(d) / "out" / "facts.json").exists())

    def test_bad_ref(self):
        w = self.world()
        rc, _, err = w.main("--ref", "no-such-ref")
        self.assertEqual(rc, 1)
        self.assertIn("no-such-ref", err)
        self.assertEqual(w.fetches, [])


if __name__ == "__main__":
    unittest.main()
