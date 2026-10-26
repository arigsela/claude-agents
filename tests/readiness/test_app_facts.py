import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "readiness" / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import app_facts as af  # noqa: E402
from fixtures import write_tree  # noqa: E402

D1 = "a" * 64
D2 = "b" * 64
DOCKERFILE = f"""ARG PYTHON_IMAGE=python:3.12-slim@sha256:{D1}
FROM ghcr.io/astral-sh/uv:0.12.19@sha256:{D2} AS uv
FROM ${{PYTHON_IMAGE}} AS build
RUN echo hi
FROM ${{PYTHON_IMAGE}}
USER 10001
"""


def run(files):
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        write_tree(root, files)
        return {f["id"]: f for f in af.app_facts(root)}


class AppFactsTest(unittest.TestCase):
    def test_dockerfile_from_resolves_args_and_skips_aliases(self):
        facts = run({"Dockerfile": DOCKERFILE})
        froms = sorted(k for k in facts if k.startswith("app.dockerfile.from."))
        self.assertEqual(len(froms), 3)
        vals = [facts[k]["value"] for k in froms]
        self.assertTrue(all(v["pinned"] for v in vals))
        self.assertEqual(vals[1]["image"], f"python:3.12-slim@sha256:{D1}")
        self.assertEqual(facts[froms[0]]["evidence"], "Dockerfile:2")
        self.assertEqual(facts[froms[2]]["evidence"], "Dockerfile:5")
        facts = run({"Dockerfile": DOCKERFILE + "FROM build AS final\n"})
        self.assertEqual(len([k for k in facts if k.startswith("app.dockerfile.from.")]), 3)

    def test_unpinned_from(self):
        facts = run({"Dockerfile": "FROM python:3.12\n"})
        self.assertFalse(facts["app.dockerfile.from.1"]["value"]["pinned"])
        self.assertEqual(facts["app.dockerfile.user"]["value"], {"user": None, "path": "Dockerfile"})

    def test_user(self):
        facts = run({"Dockerfile": DOCKERFILE})
        self.assertEqual(facts["app.dockerfile.user"]["value"], {"user": "10001", "path": "Dockerfile"})
        self.assertEqual(facts["app.dockerfile.files"]["value"], {"paths": ["Dockerfile"]})

    def test_dockerfile_below_the_root(self):  # a Backstage repo keeps it at packages/backend/Dockerfile
        facts = run({"packages/backend/Dockerfile": "FROM node:24-trixie-slim\nUSER node\n", "README.md": "x"})
        self.assertEqual(facts["app.dockerfile.from.1"]["value"],
                         {"image": "node:24-trixie-slim", "pinned": False})
        self.assertEqual(facts["app.dockerfile.from.1"]["evidence"], "packages/backend/Dockerfile:1")
        self.assertEqual(facts["app.dockerfile.user"]["value"], {"user": "node", "path": "packages/backend/Dockerfile"})

    def test_several_dockerfiles(self):
        facts = run({"Dockerfile": "FROM alpine:3\nUSER 10001\n",
                     "tools/Dockerfile.dev": "FROM python:3.12\n",
                     "deploy/api.Dockerfile": "FROM golang:1.25\n"})
        self.assertEqual(facts["app.dockerfile.files"]["value"],
                         {"paths": ["Dockerfile", "deploy/api.Dockerfile", "tools/Dockerfile.dev"]})
        evidence = sorted(f["evidence"] for k, f in facts.items() if k.startswith("app.dockerfile.from."))
        self.assertEqual(evidence, ["Dockerfile:1", "deploy/api.Dockerfile:1", "tools/Dockerfile.dev:1"])
        self.assertEqual(facts["app.dockerfile.user"]["value"], {"user": "10001", "path": "Dockerfile"})  # the root's

    def test_several_dockerfiles_none_at_the_root_names_no_user(self):
        # Which one builds the deployed image is not knowable here, so no USER is claimed for it.
        facts = run({"a/Dockerfile": "FROM alpine:3\nUSER 1\n", "b/Dockerfile": "FROM alpine:3\n"})
        self.assertNotIn("app.dockerfile.user", facts)
        self.assertEqual(facts["app.dockerfile.files"]["value"], {"paths": ["a/Dockerfile", "b/Dockerfile"]})

    def test_dockerfiles_in_dependencies_and_fixtures_are_skipped(self):
        facts = run({"node_modules/x/Dockerfile": "FROM evil:1\n", "vendor/y/Dockerfile": "FROM evil:1\n",
                     "tests/fixtures/Dockerfile": "FROM evil:1\n", "Dockerfile.dockerignore": "node_modules\n",
                     "README.md": "x"})
        self.assertFalse([k for k in facts if k.startswith("app.dockerfile")])

    def test_workflow_on_true_key_and_uses(self):
        wf = """name: ci
on:
  push:
  pull_request:
permissions:
  contents: read
jobs:
  t:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1
      - uses: actions/setup-python@v5
      - uses: ./.github/actions/x
      - uses: docker://alpine@sha256:%s
      - run: pytest -q
""" % D1
        facts = run({".github/workflows/ci.yml": wf})
        v = facts["app.workflow.ci"]["value"]
        self.assertEqual(v["triggers"], ["push", "pull_request"])
        self.assertEqual(v["jobs_without_permissions"], [])
        self.assertFalse(v["write_all"])
        self.assertEqual([u["pinned"] for u in v["uses"]], [True, False, True, True])
        self.assertEqual(v["uses"][1]["line"], 12)
        self.assertEqual(v["run_steps"], ["pytest -q"])
        self.assertEqual(facts["app.workflow.ci"]["evidence"], ".github/workflows/ci.yml")

    def test_on_string_and_list(self):
        a = run({".github/workflows/a.yml": "on: push\njobs: {}\n"})
        self.assertEqual(a["app.workflow.a"]["value"]["triggers"], ["push"])
        b = run({".github/workflows/b.yml": "on: [push, workflow_dispatch]\njobs: {}\n"})
        self.assertEqual(b["app.workflow.b"]["value"]["triggers"], ["push", "workflow_dispatch"])

    def test_permissions(self):
        wf = ("on: push\njobs:\n  a:\n    runs-on: x\n    steps: []\n"
              "  b:\n    runs-on: x\n    permissions: {contents: read}\n    steps: []\n")
        v = run({".github/workflows/p.yml": wf})["app.workflow.p"]["value"]
        self.assertEqual(v["jobs_without_permissions"], ["a"])
        wa = run({".github/workflows/w.yaml": "on: push\npermissions: write-all\njobs: {}\n"})
        self.assertTrue(wa["app.workflow.w"]["value"]["write_all"])

    def test_files(self):
        facts = run({".github/CODEOWNERS": "* @a\n", "README.md": "# hi\n"})
        c = facts["app.file.codeowners"]
        self.assertEqual(c["value"]["exists"], True)
        self.assertEqual(c["value"]["path"], ".github/CODEOWNERS")
        s = facts["app.file.security"]["value"]
        self.assertEqual((s["exists"], s["path"]), (False, None))
        self.assertEqual(s["searched"], ["SECURITY.md", ".github/SECURITY.md"])
        self.assertIsInstance(facts["app.file.security"]["evidence"], str)

    def test_tests_dir(self):
        facts = run({"tests/test_a.py": ""})
        self.assertEqual(facts["app.file.tests_dir"]["value"]["path"], "tests")

    def test_telemetry(self):
        facts = run({"pyproject.toml": 'dependencies = ["opentelemetry-sdk>=1.0"]\n'})
        v = facts["app.deps.telemetry"]["value"]
        self.assertEqual(v["found"], ["opentelemetry-sdk"])
        self.assertEqual(v["files"], ["pyproject.toml"])

    def test_readme_text_capped(self):
        facts = run({"README.md": "x" * 30000})
        self.assertEqual(len(facts["app.text.README.md"]["value"]["text"]), 20000)

    def test_readme_only(self):
        facts = run({"README.md": "# hi\n"})
        self.assertFalse([k for k in facts if k.startswith(("app.dockerfile", "app.workflow"))])

    def test_every_fact_shape(self):
        for f in run({"Dockerfile": DOCKERFILE, "README.md": "x"}).values():
            self.assertEqual(f["source"], "app")
            self.assertIsInstance(f["evidence"], str)

    def test_user_is_final_stage(self):
        u = lambda df: run({"Dockerfile": df})["app.dockerfile.user"]["value"]["user"]
        self.assertIsNone(u("FROM alpine\nUSER 10001\nFROM alpine\n"))
        self.assertEqual(u("FROM alpine AS a\nUSER 10001\nFROM a\n"), "10001")
        self.assertIsNone(u("FROM alpine AS a\nUSER 10001\nFROM alpine AS b\nFROM b\n"))

    def test_uses_from_parsed_yaml_only(self):
        wf = """on: push
jobs:
  a:
    runs-on: x
    steps:
      - run: |
          echo "uses: actions/example@main"
      - {uses: actions/checkout@v4}
  b:
    uses: org/repo/.github/workflows/w.yml@v1
"""
        v = run({".github/workflows/u.yml": wf})["app.workflow.u"]["value"]
        self.assertEqual([u["ref"] for u in v["uses"]],
                         ["actions/checkout@v4", "org/repo/.github/workflows/w.yml@v1"])
        self.assertEqual([u["line"] for u in v["uses"]], [8, 10])

    def test_job_level_write_all(self):
        wf = "on: push\npermissions: {contents: read}\njobs:\n  a:\n    runs-on: x\n    permissions: write-all\n    steps: []\n"
        v = run({".github/workflows/j.yml": wf})["app.workflow.j"]["value"]
        self.assertTrue(v["write_all"])

    def test_bad_yaml_does_not_raise(self):
        facts = run({".github/workflows/x.yml": "on: [\n"})
        self.assertIn("app.workflow.x", facts)


if __name__ == "__main__":
    unittest.main()
