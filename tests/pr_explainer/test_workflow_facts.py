# Run: uv run --with pyyaml --with "pathspec<1" python -m unittest discover -s tests/pr_explainer
"""GitHub Actions facts in pr-explainer's collect.py, render.py and ref_groups.py."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills/pr-explainer/skills/pr-explainer/scripts"))
import collect  # noqa: E402
import ref_groups  # noqa: E402
import render  # noqa: E402

BASE = """\
name: build-deploy
on:
  workflow_call:
    inputs:
      environment:
        type: string
        required: true
      enableAurora:
        type: boolean
        default: false
    outputs:
      clusterId:
        value: ${{ jobs.provision.outputs.cluster_id }}
permissions: {}
jobs:
  build:
    uses: org/repo/.github/workflows/build.yaml@v1
  provision:
    needs: [build]
    uses: org/repo/.github/workflows/aurora.yaml@v1
  deploy:
    needs: [build, provision]
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4
      - name: Helm
        run: helm upgrade
"""

HEAD = """\
name: build-deploy
on:
  workflow_call:
    inputs:
      environment:
        type: string
        required: true
      region:
        type: string
        required: true
permissions:
  contents: read
jobs:
  build:
    uses: org/repo/.github/workflows/build.yaml@v1
  deploy:
    needs: [build]
    runs-on: ubuntu-latest
    steps:
      - name: Lint
        run: make lint
      - name: Checkout
        uses: actions/checkout@v4
      - name: Helm
        run: helm upgrade
"""

PATH = ".github/workflows/build-deploy.yaml"


def trees(base: str | None, head: str | None, path: str = PATH) -> SimpleNamespace:
    tmp = Path(tempfile.mkdtemp())
    for side, text in (("base", base), ("head", head)):
        (tmp / side).mkdir()
        if text is not None:
            (tmp / side / path).parent.mkdir(parents=True, exist_ok=True)
            (tmp / side / path).write_text(text)
    return SimpleNamespace(base=tmp / "base", head=tmp / "head")


def by_name(entries: list[dict]) -> dict[tuple[str, str], dict]:
    return {(w["element"], w["name"]): w for w in entries}


class WorkflowFacts(unittest.TestCase):
    def setUp(self):
        self.wf, self.edges, self.notes = collect.workflow_facts([{"filename": PATH}], trees(BASE, HEAD))
        self.idx = by_name(self.wf)

    def test_actions(self):
        self.assertEqual(self.idx[("input", "enableAurora")]["action"], "removed")
        self.assertEqual(self.idx[("input", "region")]["action"], "added")
        self.assertEqual(self.idx[("output", "clusterId")]["action"], "removed")
        self.assertEqual(self.idx[("job", "provision")]["action"], "removed")
        self.assertEqual(self.idx[("job", "deploy")]["action"], "modified")
        self.assertEqual(self.idx[("setting", "permissions")]["action"], "modified")
        self.assertEqual(self.idx[("job", "build")]["action"], "context")
        self.assertNotIn(("input", "environment"), self.idx)

    def test_inserted_step_does_not_mark_later_steps_changed(self):
        paths = self.idx[("job", "deploy")]["changed_paths"]
        self.assertIn("steps.Lint", paths)
        self.assertFalse(any(p.startswith(("steps.Checkout", "steps.Helm")) for p in paths), paths)

    def test_needs_edges_use_base_and_head(self):
        ids = {w["id"]: w["name"] for w in self.wf}
        pairs = {(ids[e["from"]], ids[e["to"]]) for e in self.edges}
        self.assertEqual(pairs, {("deploy", "build"), ("deploy", "provision"), ("provision", "build")})
        self.assertTrue(all(e["type"] == "needs" for e in self.edges))

    def test_lines_point_at_the_key_on_the_right_side(self):
        self.assertEqual(self.idx[("input", "enableAurora")]["lines"], [8])  # base side
        self.assertEqual(self.idx[("input", "region")]["lines"], [8])  # head side
        self.assertEqual(self.idx[("job", "deploy")]["lines"], [16])

    def test_uses_and_input_flags(self):
        self.assertEqual(self.idx[("job", "provision")]["uses"], "org/repo/.github/workflows/aurora.yaml@v1")
        self.assertTrue(self.idx[("input", "region")]["required"])
        self.assertFalse(self.idx[("input", "region")]["has_default"])

    def test_policy_hits(self):
        rules = {w["name"]: (collect.workflow_hit(w) or (None,))[0] for w in self.wf}
        self.assertEqual(rules["enableAurora"], "workflow_call input removed")
        self.assertEqual(rules["clusterId"], "workflow_call output removed")
        self.assertEqual(rules["region"], "workflow_call input now required")
        self.assertEqual(rules["permissions"], "workflow permissions changed")
        self.assertIsNone(rules["deploy"])
        self.assertIsNone(rules["build"])

    def test_note_names_the_limits(self):
        self.assertEqual([n["key"] for n in self.notes], ["actions"])


class WorkflowScope(unittest.TestCase):
    def test_only_top_level_workflow_files(self):
        self.assertTrue(collect.is_workflow(".github/workflows/ci.yml"))
        self.assertFalse(collect.is_workflow("docs/examples/x/.github/workflows/ci.yml"))
        self.assertFalse(collect.is_workflow(".github/workflows/sub/ci.yml"))
        self.assertFalse(collect.is_workflow(".github/workflows/README.md"))

    def test_added_and_deleted_files(self):
        added, _, _ = collect.workflow_facts([{"filename": PATH}], trees(None, HEAD))
        self.assertTrue(added and all(w["action"] == "added" for w in added))
        removed, _, _ = collect.workflow_facts([{"filename": PATH}], trees(BASE, None))
        self.assertTrue(removed and all(w["action"] == "removed" for w in removed))

    def test_unparseable_file_is_noted(self):
        wf, _, notes = collect.workflow_facts([{"filename": PATH}], trees(BASE, "jobs: [unclosed"))
        self.assertEqual(wf, [])
        self.assertEqual([n["key"] for n in notes], ["workflows"])

    def test_trigger_forms(self):
        self.assertEqual(collect.workflow_triggers(yaml.safe_load("on: push")), {"push": {}})
        self.assertEqual(collect.workflow_triggers(yaml.safe_load("on: [push, pull_request]")),
                         {"push": {}, "pull_request": {}})
        self.assertEqual(set(collect.workflow_triggers({"on": {"push": None}})), {"push"})


class WorkflowRender(unittest.TestCase):
    def test_graph_and_ref_groups(self):
        wf, edges, _ = collect.workflow_facts([{"filename": PATH}], trees(BASE, HEAD))
        graph = render.mermaid({"resources": [], "terraform": [], "workflows": wf, "edges": edges})
        idx = by_name(wf)
        build, provision, deploy = (idx[("job", n)]["id"] for n in ("build", "provision", "deploy"))
        self.assertIn(f"{build} --> {deploy}", graph)  # run order, not "needs" direction
        self.assertIn(f"{provision} --> {deploy}", graph)
        self.assertIn('subgraph wf0[".github/workflows/build-deploy.yaml"]', graph)
        inputs = [w for w in wf if w["element"] == "input" and w["action"] == "removed"]
        removed = [ref_groups.entry(w, w["id"]) for w in inputs + [idx[("output", "clusterId")]]]
        self.assertEqual(len(ref_groups.group(removed)), 2)  # inputs and outputs do not merge


if __name__ == "__main__":
    unittest.main()
