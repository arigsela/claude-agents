# Run: uv run --with pyyaml --with "pathspec<1" python -m unittest discover -s tests/explainer
"""Plan mode: a one-pager as the source, its terms searched in a repo with no Applications."""
from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills/explainer/scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import facts_lib  # noqa: E402
import render  # noqa: E402
import verify  # noqa: E402
from test_system_facts import SystemFactsBase  # noqa: E402

ONE_PAGER = """# EDP SageMaker MVP

Deploy SageMaker through `edp-terraform` on its own role, separate from `github-deploy-tf-{env}`,
modeled on `bidw-aws-lambda`. Studio uses `PublicInternetOnly`. Pins `v1.4.1`; never `iam:*` on
`role/*`; `data` sources; `pip` installs; `just apply` is retired; owners `@chghealthcare/bidw`.
"""

IAM_TF = """locals {
  gha_deploy_role_name = "github-deploy-tf-${var.environment}"
  authorized_repos     = ["repo:chghealthcare/bidw-aws-lambda:*"]
}

resource "aws_iam_role" "gha_deploy" {
  name = local.gha_deploy_role_name
}
"""


def make_plan_repo(tmp: Path) -> Path:
    """A Terraform-only repo: no Argo CD Applications at all."""
    (tmp / "terraform/cicd").mkdir(parents=True)
    (tmp / "terraform/cicd/iam.tf").write_text(IAM_TF)
    (tmp / "terraform/cicd/backend.dev.hcl").write_text('bucket = "terraform-state-us-west-2-dev-bidw"\n')
    (tmp / "Justfile").write_text("apply env:\n    terraform apply -var-file=config.{{env}}.tfvars\n")
    facts_lib.sh("git", "init", "-q", "-b", "main", cwd=tmp)
    facts_lib.sh("git", "remote", "add", "origin", str(tmp), cwd=tmp)
    facts_lib.sh("git", "add", ".", cwd=tmp)
    facts_lib.sh("git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init", cwd=tmp)
    return tmp


class PlanTermsTest(unittest.TestCase):
    def test_backticked_identifiers_in_order(self):
        docs = [{"text": ONE_PAGER}]
        self.assertEqual(facts_lib.plan_terms(docs, "chghealthcare/edp-terraform"),
                         ["github-deploy-tf", "bidw-aws-lambda", "PublicInternetOnly", "chghealthcare/bidw"])

    def test_dedupes_case_insensitively(self):
        docs = [{"text": "`VpcOnly` then `vpconly` then `VpcOnly`"}]
        self.assertEqual(facts_lib.plan_terms(docs, "o/r"), ["VpcOnly"])

    def test_nothing_backticked(self):
        self.assertEqual(facts_lib.plan_terms([{"text": "no code here"}], "o/r"), [])


class PlanFactsTest(SystemFactsBase):
    def collect(self, terms=None):
        repo = make_plan_repo(self.tmp)
        doc = Path(self._tmp.name) / "one-pager.md"
        doc.write_text(ONE_PAGER)
        with self.trees(repo) as t:
            return facts_lib.collect_system("o/edp-terraform", t, [], [str(doc)], None, False, True, terms)

    def test_title_skips_frontmatter(self):
        doc = Path(self._tmp.name) / "fm.md"
        doc.write_text("---\ntype: project\nstatus: active\n---\n\n# EDP SageMaker MVP\n")
        docs, _ = facts_lib.doc_facts([str(doc)])
        self.assertEqual(docs[0]["title"], "EDP SageMaker MVP")
        self.assertIn("type: project", docs[0]["text"])

    def test_no_application_needed(self):
        facts = self.collect()
        self.assertEqual(facts["mode"], "plan")
        self.assertEqual(facts["apps"], [])
        self.assertEqual(facts["docs"][0]["title"], "EDP SageMaker MVP")

    def test_terms_hit_locals_and_blocks(self):
        facts = self.collect()
        hits = facts["query"]["term_hits"]
        files = {f["id"]: f["file"] for f in facts["non_manifest_changes"]}
        self.assertEqual([files[i] for i in hits["github-deploy-tf"] if i.startswith("f")], ["terraform/cicd/iam.tf"])
        self.assertIn("bidw-aws-lambda", next(f["terms"] for f in facts["non_manifest_changes"]))
        self.assertEqual(hits["PublicInternetOnly"], [])
        self.assertEqual({n["key"] for n in facts["notes"]} >= {"plan", "terms"}, True)
        self.assertIn("PublicInternetOnly", next(n["text"] for n in facts["notes"] if n["key"] == "terms"))

    def test_extra_terms_add_to_the_plan_terms(self):
        facts = self.collect(terms=["terraform-state"])
        self.assertIn("github-deploy-tf", facts["query"]["terms"])
        hit = facts["query"]["term_hits"]["terraform-state"]
        files = {f["id"]: f["file"] for f in facts["non_manifest_changes"]}
        self.assertEqual([files[i] for i in hit], ["terraform/cicd/backend.dev.hcl"])

    def test_file_name_counts_as_a_mention(self):
        facts = self.collect(terms=["Justfile"])
        files = {f["id"]: f["file"] for f in facts["non_manifest_changes"]}
        self.assertEqual([files[i] for i in facts["query"]["term_hits"]["Justfile"]], ["Justfile"])

    def test_broad_term_is_capped_per_term(self):
        repo = make_plan_repo(self.tmp)
        for i in range(facts_lib.MAX_FILES_PER_TERM + 2):
            (repo / f"backend{i:02}.hcl").write_text('bucket = "terraform-state-x"\n')
        (repo / "zz.txt").write_text("VpcOnly\n")  # sorts last: a narrow term still gets its file
        facts_lib.sh("git", "add", ".", cwd=repo)
        facts_lib.sh("git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "more", cwd=repo)
        doc = Path(self._tmp.name) / "one-pager.md"
        doc.write_text("Uses `terraform-state` and `VpcOnly`.")
        with self.trees(repo) as t:
            facts = facts_lib.collect_system("o/r", t, [], [str(doc)], None, False, True)
        hits = facts["query"]["term_hits"]
        self.assertEqual(len([i for i in hits["terraform-state"] if i.startswith("f")]), facts_lib.MAX_FILES_PER_TERM)
        self.assertEqual(len(hits["VpcOnly"]), 1)
        note = next(n["text"] for n in facts["notes"] if n["key"] == "mentions")
        self.assertIn(f"terraform-state ({facts_lib.MAX_FILES_PER_TERM + 3} files)", note)

    def test_file_mentions_record_lines(self):
        facts = self.collect()
        iam = next(f for f in facts["non_manifest_changes"] if f["file"] == "terraform/cicd/iam.tf")
        self.assertEqual(iam["lines"], [2, 3])
        self.assertEqual(iam["status"], "mentions")


PLAN_FACTS = {
    "mode": "plan", "pr": None, "triage": None,
    "query": {"service": [], "matched_by": [], "inferred": False, "ref": "main",
              "sha": "abcdef1234567890abcdef1234567890abcdef12", "repo": "o/edp-terraform",
              "terms": ["github-deploy-tf", "PublicInternetOnly"],
              "term_hits": {"github-deploy-tf": ["f1"], "PublicInternetOnly": []}},
    "apps": [], "resources": [], "edges": [], "config": [], "terraform": [], "terraform_plans": [], "workflows": [],
    "non_manifest_changes": [{"id": "f1", "file": "terraform/cicd/iam.tf", "status": "mentions", "lines": [2],
                              "terms": ["github-deploy-tf"], "summary": {"names": ["github-deploy-tf"], "lines": [2]}}],
    "docs": [{"id": "d1", "title": "EDP SageMaker MVP", "source": "file", "path": "one-pager.md", "chars": 100,
              "truncated": False, "text": ONE_PAGER}],
    "related_prs": [], "jira": None, "policy_hits": [],
    "notes": [{"key": "plan", "text": "method"}, {"key": "terms", "text": "PublicInternetOnly"}],
}

GOOD_PLAN = {
    "tldr": "The plan adds a SageMaker module beside the existing CI role.",
    "background": [{"text": "The repo already holds a GitHub Actions deploy role.", "refs": ["f1"]}],
    "plan": {"steps": [
        {"text": "Give SageMaker its own deploy role", "status": "would_change", "reason": "", "refs": ["f1"]},
        {"text": "Studio in PublicInternetOnly", "status": "new", "reason": "No Studio domain exists yet.", "refs": ["d1"]},
    ]},
    "components": [], "how_it_works": [], "where_it_runs": [], "config_that_matters": [],
    "open_questions": [{"text": "Who approves prod applies?", "refs": ["no fact"]}],
    "docs_summary": [{"doc": "d1", "asks": ["SageMaker in dev and prod"]}],
    "callouts": [], "must_read": [{"ref": "f1", "why": "the role the plan must not change"}],
    "reading_order": [{"ref": "f1", "note": "the shared CI role"}],
    "not_covered": ["plan: substring match only", "terms: PublicInternetOnly is new"],
    "quiz": [{"question": f"Which role stays as is? ({n})", "options": [
        {"text": "github-deploy-tf", "correct": True, "explanation": "bidw-aws-lambda uses it."},
        {"text": "a new SageMaker role", "correct": False, "explanation": "That one is added."}], "refs": ["f1"]}
        for n in range(3)],
    "narrator_model": "claude-opus-5-5",
}


class PlanVerifyTest(unittest.TestCase):
    def test_good_plan_passes(self):
        self.assertEqual(verify.verify(PLAN_FACTS, GOOD_PLAN), [])

    def test_plan_section_required(self):
        bad = {k: v for k, v in GOOD_PLAN.items() if k != "plan"}
        self.assertIn("facts.mode is 'plan' but the explainer has no plan section", verify.verify(PLAN_FACTS, bad))

    def test_status_rules(self):
        bad = copy.deepcopy(GOOD_PLAN)
        bad["plan"]["steps"] = [
            {"text": "a", "status": "would_change", "refs": ["d1"]},
            {"text": "b", "status": "new", "reason": "x", "refs": ["f1"]},
            {"text": "c", "status": "unclear", "refs": ["f1"]},
            {"text": "d", "status": "covered", "reason": "x", "refs": ["f1"]},
        ]
        errors = verify.verify(PLAN_FACTS, bad)
        self.assertIn("plan.steps[0] is would_change but cites nothing in the repo; cite the block, workflow or file", errors)
        self.assertIn("plan.steps[1] is new but does not cite the plan (d*)", errors)
        self.assertIn("plan.steps[2] is unclear but has no reason", errors)
        self.assertTrue(any(e.startswith("plan.steps[3] status 'covered'") for e in errors))

    def test_open_questions_required(self):
        bad = {**GOOD_PLAN, "open_questions": []}
        self.assertIn("open_questions is empty; list what the plan leaves open that the repo cannot answer",
                      verify.verify(PLAN_FACTS, bad))

    def test_plan_section_rejected_outside_plan_mode(self):
        facts = {**PLAN_FACTS, "mode": "service", "query": {**PLAN_FACTS["query"], "service": ["x"]}}
        self.assertIn("explainer has a plan section but facts.mode is 'service'", verify.verify(facts, GOOD_PLAN))


class PlanPageTest(unittest.TestCase):
    def test_plan_card_terms_and_title(self):
        page = render.render(PLAN_FACTS, GOOD_PLAN, [])
        self.assertIn("<title>Plan explainer: EDP SageMaker MVP</title>", page)
        self.assertIn("EDP SageMaker MVP — where it lands in o/edp-terraform", page)
        self.assertIn("The plan does", page)
        self.assertIn('<span class="pill">would change</span>', page)
        self.assertIn('<span class="pill">new</span>', page)
        self.assertIn("<code>PublicInternetOnly</code></td><td><span class=\"meta\">not in this repo</span>", page)
        self.assertIn("https://github.com/o/edp-terraform/blob/abcdef1/terraform/cicd/iam.tf#L2", page)
        self.assertLess(page.index("The plan does"), page.index("Components"))
        self.assertNotIn("{{", page)

    def test_rejected_shapes_still_render(self):
        bad = {**GOOD_PLAN, "plan": {"steps": ["x", {"status": ["new"]}]}}
        page = render.render(PLAN_FACTS, bad, ["broken"])
        self.assertIn("Unverified", page)

    def test_service_page_has_no_plan_card(self):
        facts = {**PLAN_FACTS, "mode": "service"}
        self.assertNotIn("The plan does", render.render(facts, GOOD_PLAN, []))


if __name__ == "__main__":
    unittest.main()
