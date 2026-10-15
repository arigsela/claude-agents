# Run: uv run --with pyyaml --with "pathspec<1" python -m unittest discover -s tests/explainer
"""Ticket mode for greenfield work: term search, linked Confluence pages, new status, primer."""
from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills/explainer/scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import facts_lib  # noqa: E402
import infographic  # noqa: E402
import render  # noqa: E402
import verify  # noqa: E402
from test_plan_mode import GOOD_PLAN, PLAN_FACTS, make_plan_repo  # noqa: E402
from test_system_facts import SystemFactsBase  # noqa: E402
from test_system_page import GOOD_SYSTEM, GOOD_TICKET, SYSTEM_FACTS, TICKET_FACTS  # noqa: E402

SITE = "chghealthcare.atlassian.net"
ONE_PAGER = f"https://{SITE}/wiki/spaces/SRE/pages/5290688580/EDP+SageMaker+MVP"


def para_with_link(text: str, href: str) -> dict:
    return {"type": "paragraph", "content": [{"type": "text", "text": text, "marks": [{"type": "link", "attrs": {"href": href}}]}]}


class LinksTest(unittest.TestCase):
    def test_adf_links_reads_marks_and_cards(self):
        doc = {"type": "doc", "content": [para_with_link("one-pager", ONE_PAGER),
                                          {"type": "paragraph", "content": [{"type": "inlineCard", "attrs": {"url": "https://x/y"}}]}]}
        self.assertEqual(facts_lib.adf_links(doc), [ONE_PAGER, "https://x/y"])

    def test_adf_text_keeps_inline_code_as_backticks(self):
        doc = {"type": "doc", "content": [{"type": "paragraph", "content": [
            {"type": "text", "text": "Add "}, {"type": "text", "text": "terraform/sagemaker/studio", "marks": [{"type": "code"}]}]}]}
        self.assertEqual(facts_lib.adf_text(doc, 100), "Add `terraform/sagemaker/studio`")

    def test_only_confluence_on_the_jira_site(self):
        urls = [ONE_PAGER, f"https://{SITE}/browse/IFS-1", "https://evil.example/wiki/spaces/X/pages/1", ONE_PAGER]
        self.assertEqual(facts_lib.confluence_links(urls, SITE), [ONE_PAGER])
        self.assertEqual(facts_lib.confluence_links(urls, None), [])

    def test_ticket_reads_its_epics_links(self):
        story = {"key": "IFS-522", "fields": {"summary": "Studio", "description": {"type": "doc", "content": []},
                                              "parent": {"key": "IFS-519", "fields": {"summary": "Epic"}}}}
        epic = {"key": "IFS-519", "fields": {"description": {"type": "doc", "content": [para_with_link("one-pager", ONE_PAGER)]}}}

        def fake_sh(*args, **kw):
            if args[:3] == ("acli", "jira", "auth"):
                return f"Site: {SITE}\n"
            return json.dumps(epic if "IFS-519" in args else story)

        with mock.patch.object(facts_lib.shutil, "which", return_value="/bin/acli"), \
             mock.patch.object(facts_lib, "sh", side_effect=fake_sh):
            jira, notes = facts_lib.jira_facts_for_key("IFS-522")
        self.assertEqual(jira["doc_links"], [ONE_PAGER])
        self.assertEqual(notes, [])


class DocSourceTest(SystemFactsBase):
    def test_source_comment_becomes_the_doc_url(self):
        doc = self.tmp / "one-pager.md"
        doc.write_text(f"<!-- source: {ONE_PAGER} -->\n# EDP SageMaker MVP\n")
        docs, _ = facts_lib.doc_facts([str(doc)])
        self.assertEqual(docs[0]["url"], ONE_PAGER)
        self.assertEqual(docs[0]["title"], "EDP SageMaker MVP")
        plain = self.tmp / "plain.md"
        plain.write_text("# Notes\n")
        self.assertIsNone(facts_lib.doc_facts([str(plain)])[0][0]["url"])


class TicketTermsTest(SystemFactsBase):
    def test_greenfield_ticket_gets_repo_facts_from_its_terms(self):
        repo = make_plan_repo(self.tmp)
        jira = {"key": "IFS-522", "source": "argument", "url": None, "summary": "Studio domains", "status": "To Do",
                "type": "Story", "parent": None, "doc_links": [], "comments": [],
                "description": "Add `terraform/sagemaker/studio` beside `github-deploy-tf-{env}`, state in `terraform-state`."}
        with self.trees(repo) as t, \
             mock.patch.object(facts_lib, "jira_facts_for_key", return_value=(jira, [])), \
             mock.patch.object(facts_lib, "related_prs", return_value=([], [])):
            facts = facts_lib.collect_system("o/edp-terraform", t, [], [], "IFS-522", False)
        self.assertEqual(facts["mode"], "ticket")
        self.assertEqual(facts["apps"], [])
        hits = facts["query"]["term_hits"]
        files = {f["id"]: f["file"] for f in facts["non_manifest_changes"]}
        self.assertEqual(hits["terraform/sagemaker/studio"], [])
        self.assertIn("terraform/cicd/iam.tf", [files[i] for i in hits["github-deploy-tf"] if i.startswith("f")])
        self.assertIn("terraform/cicd/backend.dev.hcl", [files[i] for i in hits["terraform-state"]])
        self.assertTrue({"match", "search", "terms"} <= {n["key"] for n in facts["notes"]})


class TicketNewStatusTest(unittest.TestCase):
    def test_new_cites_the_ticket_or_a_doc(self):
        expl = copy.deepcopy(GOOD_TICKET)
        expl["ticket"]["criteria"].append({"text": "a new root module", "status": "new", "reason": "nothing there yet", "refs": ["IFS-9"]})
        self.assertEqual(verify.verify(TICKET_FACTS, expl), [])
        expl["ticket"]["criteria"][-1]["refs"] = ["r1"]
        self.assertIn("ticket.criteria[4] is new but cites neither the ticket nor a doc", verify.verify(TICKET_FACTS, expl))

    def test_new_renders_as_a_status(self):
        expl = copy.deepcopy(GOOD_TICKET)
        expl["ticket"]["criteria"].append({"text": "a new root module", "status": "new", "reason": "x", "refs": ["IFS-9"]})
        self.assertIn('<span class="pill">new</span>', render.render(TICKET_FACTS, expl, []))


PRIMER = {"topic": "Amazon SageMaker", "text": "SageMaker is AWS's managed service for building and training ML models."}


class PrimerTest(unittest.TestCase):
    def test_primer_is_optional_and_checked(self):
        self.assertEqual(verify.verify(TICKET_FACTS, {**GOOD_TICKET, "primer": PRIMER}), [])
        self.assertIn("primer must be an object with a topic and text",
                      verify.verify(TICKET_FACTS, {**GOOD_TICKET, "primer": {"topic": "x"}}))
        long = {**PRIMER, "text": "x" * (verify.MAX_PRIMER_CHARS + 1)}
        self.assertTrue(any(e.startswith("primer.text is") for e in verify.verify(TICKET_FACTS, {**GOOD_TICKET, "primer": long})))
        self.assertIn("primer takes no refs: it is general background, labelled as not checked against facts",
                      verify.verify(TICKET_FACTS, {**GOOD_TICKET, "primer": {**PRIMER, "refs": ["r1"]}}))

    def test_primer_renders_labelled_after_tldr(self):
        page = render.render(TICKET_FACTS, {**GOOD_TICKET, "primer": PRIMER}, [])
        self.assertIn("What Amazon SageMaker is", page)
        self.assertIn("It is not checked against the repo or the ticket", page)
        self.assertLess(page.index("What Amazon SageMaker is"), page.index("Background"))

    def test_primer_leads_the_infographic_brief(self):
        brief = infographic.brief(TICKET_FACTS, {**GOOD_TICKET, "primer": PRIMER}, 3)
        self.assertLess(brief.index("## What Amazon SageMaker is"), brief.index("## In one paragraph"))
        self.assertIn("the first is what it is and how it is used here", brief)


class HeadingsTest(unittest.TestCase):
    def test_open_questions_heading_per_mode(self):
        self.assertIn("Open questions for the one-pager", render.render(SYSTEM_FACTS, GOOD_SYSTEM, []))
        self.assertIn("Open questions for the ticket", render.render(TICKET_FACTS, GOOD_TICKET, []))
        self.assertIn("Open questions for the plan", render.render(PLAN_FACTS, GOOD_PLAN, []))

    def test_linked_docs_are_named_under_the_heading(self):
        facts = copy.deepcopy(PLAN_FACTS)
        facts["docs"][0]["url"] = ONE_PAGER
        page = render.render(facts, GOOD_PLAN, [])
        self.assertIn(f'Read alongside <a href="{ONE_PAGER}">EDP SageMaker MVP</a>.', page)

    def test_empty_walkthrough_says_why(self):
        facts = {**PLAN_FACTS, "non_manifest_changes": []}
        page = render.render(facts, {**GOOD_PLAN, "reading_order": [], "must_read": []}, [])
        self.assertIn("Nothing in the repo relates to this yet", page)


if __name__ == "__main__":
    unittest.main()
