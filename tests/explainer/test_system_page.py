# Run: uv run --with pyyaml --with "pathspec<1" python -m unittest discover -s tests/explainer
"""verify.py and render.py in service (and later ticket) mode."""
from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills/explainer/scripts"))
import render  # noqa: E402
import verify  # noqa: E402


def res(rid, kind, name, scope, **extra):
    return {"id": rid, "app": "grafana", "scope": scope, "kind": kind, "namespace": "mon", "name": name,
            "action": "focus", "changed_paths": [], "file": f"apps/grafana/{kind.lower()}.yaml", "lines": [1, 20],
            "risk": None, "summary": {}, **extra}


SYSTEM_FACTS = {
    "mode": "service", "pr": None, "triage": None,
    "query": {"service": ["grafana"], "matched_by": [{"app": "grafana", "name": "grafana", "by": "name"}],
              "ref": "main", "sha": "abcdef1234567890abcdef1234567890abcdef12", "repo": "o/r"},
    "apps": [{"app": "grafana", "application_file": "argo/prod/grafana.yaml", "scope": "argo/prod",
              "source_kind": "directory", "render": "rendered", "render_note": ""},
             {"app": "grafana", "application_file": "argo/nonprod/grafana.yaml", "scope": "argo/nonprod",
              "source_kind": "directory", "render": "rendered", "render_note": ""}],
    "resources": [
        res("r1", "Deployment", "grafana", "argo/prod", summary={"image": "grafana/grafana:10.1", "replicas": 2,
                                                              "probes": {"readiness": "GET /api/health:3000"},
                                                              "env_keys": ["DB_PASSWORD"]}),
        res("r2", "Service", "grafana", "argo/prod", summary={"ports": ["80->3000"]}),
        res("r3", "HTTPRoute", "grafana", "argo/prod", summary={"hosts": ["grafana.example.com"], "backends": ["grafana:80"]}),
        res("r4", "Application", "grafana", "argo/prod", namespace="argo-cd", file="argo/prod/grafana.yaml", lines=[1, 14]),
        res("r5", "Deployment", "grafana", "argo/nonprod", summary={"image": "grafana/grafana:10.2", "replicas": 1}),
        res("r6", "Secret", "grafana-admin", "argo/prod", action="generated", file=None, lines=None),
    ],
    "edges": [{"from": "r2", "to": "r1", "type": "selects"}, {"from": "r3", "to": "r2", "type": "routes-to"}],
    "config": [{"id": "c1", "app": "grafana", "scope": "argo/prod", "source": "inline-values",
                "file": "argo/prod/grafana.yaml", "keys": ["adminPassword", "replicas"]}],
    "terraform": [{"id": "t1", "address": "aws_s3_bucket.grafana_dashboards", "action": "focus", "source": "source-ref",
                   "type": "aws_s3_bucket", "name": "grafana_dashboards", "file": "infra/main.tf", "lines": [1]}],
    "terraform_plans": [],
    "workflows": [{"id": "w1", "workflow": ".github/workflows/deploy.yaml", "element": "job", "event": "", "name": "deploy",
                   "action": "focus", "changed_paths": [], "file": ".github/workflows/deploy.yaml", "lines": [9]}],
    "non_manifest_changes": [],
    "docs": [{"id": "d1", "title": "One-pager", "source": "file", "path": "/w/docs/one-pager.md", "chars": 40,
              "truncated": False, "text": "Grafana needs SSO and a second replica in prod."}],
    "related_prs": [], "jira": None, "policy_hits": [], "notes": [],
}

GOOD_SYSTEM = {
    "tldr": "Grafana is the dashboards UI in mon, exposed at grafana.example.com.",
    "background": [{"text": "Grafana is deployed by Argo CD from apps/grafana.", "refs": ["r4"]}],
    "components": [{"app": "grafana", "role": "Dashboards UI behind an HTTPRoute.", "refs": ["r1", "r3"]}],
    "how_it_works": [
        {"trigger": "a request to grafana.example.com", "path": "HTTPRoute sends it to the Service, which selects the pods.", "refs": ["r3", "r2", "r1"]},
        {"trigger": "a push to main", "path": "The deploy job syncs the Application.", "refs": ["w1", "r4"]},
    ],
    "where_it_runs": [{"scope": "argo/prod", "differs": "2 replicas, image 10.1", "refs": ["r1"]},
                      {"scope": "argo/nonprod", "differs": "1 replica, image 10.2", "refs": ["r5"]}],
    "config_that_matters": [{"key": "adminPassword", "why": "the admin login; set per environment", "refs": ["c1"]}],
    "open_questions": [{"text": "Who owns this app? No owner annotation.", "refs": ["no fact"]},
                       {"text": "nonprod runs one replica; is that intended?", "refs": ["r5"]}],
    "docs_summary": [{"doc": "d1", "asks": ["SSO for Grafana", "a second replica in prod"]}],
    "callouts": [],
    "must_read": [{"ref": "r4", "why": "the Application spec"}],
    "reading_order": [{"ref": "r4", "note": "Start with the Application."}, {"ref": "r1", "note": "Then the workload."},
                      {"ref": "c1", "note": "The values this repo sets."}, {"ref": "t1", "note": "The bucket."}],
    "not_covered": [],
    "quiz": [
        {"question": "Which host reaches Grafana?", "options": [{"text": "grafana.example.com", "correct": True, "explanation": "The HTTPRoute hostname."},
                                                                {"text": "mon.example.com", "correct": False, "explanation": "No such route."}], "refs": ["r3"]},
        {"question": "How many replicas in prod?", "options": [{"text": "1", "correct": False, "explanation": "That is nonprod."},
                                                               {"text": "2", "correct": True, "explanation": "Yes."}], "refs": ["r1"]},
        {"question": "What syncs the app?", "options": [{"text": "The deploy job", "correct": True, "explanation": "Yes."},
                                                        {"text": "A cron", "correct": False, "explanation": "No."}], "refs": ["w1"]},
    ],
    "narrator_model": "claude-opus-5-5",
}


def bad(**changes) -> dict:
    expl = copy.deepcopy(GOOD_SYSTEM)
    expl.update(changes)
    return expl


class SystemVerifyTest(unittest.TestCase):
    def test_good_system_explainer_passes(self):
        self.assertEqual(verify.verify(SYSTEM_FACTS, GOOD_SYSTEM), [])

    def test_scenario_not_required_when_how_it_works_present(self):
        self.assertNotIn("scenario is missing: one concrete trigger walked before and after the change",
                         verify.verify(SYSTEM_FACTS, bad(scenario=None)))

    def test_components_one_per_app(self):
        errs = verify.verify(SYSTEM_FACTS, bad(components=[]))
        self.assertTrue(any("components" in e and "grafana" in e for e in errs), errs)
        errs = verify.verify(SYSTEM_FACTS, bad(components=[{"app": "loki", "role": "x", "refs": ["r1"]}]))
        self.assertTrue(any("loki" in e for e in errs), errs)

    def test_how_it_works_count_and_fields(self):
        errs = verify.verify(SYSTEM_FACTS, bad(how_it_works=[GOOD_SYSTEM["how_it_works"][0]]))
        self.assertTrue(any("how_it_works has 1" in e for e in errs), errs)
        errs = verify.verify(SYSTEM_FACTS, bad(how_it_works=[{"trigger": "", "path": "", "refs": []}] * 2))
        self.assertIn("how_it_works[0].trigger is empty", errs)
        self.assertIn("how_it_works[0] cites nothing", errs)

    def test_where_it_runs_one_per_scope(self):
        errs = verify.verify(SYSTEM_FACTS, bad(where_it_runs=[]))
        self.assertTrue(any("where_it_runs" in e and "argo/prod" in e for e in errs), errs)
        facts = {**SYSTEM_FACTS, "apps": [{**SYSTEM_FACTS["apps"][0], "scope": ""}]}
        self.assertEqual(verify.verify(facts, bad(where_it_runs=[])), [])

    def test_config_refs_must_be_config_or_resources(self):
        self.assertEqual(verify.verify(SYSTEM_FACTS, bad(config_that_matters=[{"key": "x", "why": "y", "refs": ["r1"]}])), [])
        errs = verify.verify(SYSTEM_FACTS, bad(config_that_matters=[{"key": "x", "why": "y", "refs": ["t1"]}]))
        self.assertTrue(any("config_that_matters[0]" in e for e in errs), errs)
        errs = verify.verify(SYSTEM_FACTS, bad(config_that_matters=[{"key": "", "why": "", "refs": ["c1"]}]))
        self.assertIn("config_that_matters[0].key is empty", errs)

    def test_open_questions_refs_or_no_fact(self):
        errs = verify.verify(SYSTEM_FACTS, bad(open_questions=None))
        self.assertTrue(any("open_questions" in e for e in errs), errs)
        errs = verify.verify(SYSTEM_FACTS, bad(open_questions=[{"text": "x", "refs": []}]))
        self.assertTrue(any("open_questions[0]" in e and "no fact" in e for e in errs), errs)
        errs = verify.verify(SYSTEM_FACTS, bad(open_questions=[{"text": "x", "refs": ["zz"]}]))
        self.assertTrue(any("unknown id 'zz'" in e for e in errs), errs)

    def test_docs_summary_one_per_doc(self):
        errs = verify.verify(SYSTEM_FACTS, bad(docs_summary=[]))
        self.assertTrue(any("docs_summary" in e and "d1" in e for e in errs), errs)
        errs = verify.verify(SYSTEM_FACTS, bad(docs_summary=[{"doc": "d1", "asks": []}]))
        self.assertTrue(any("docs_summary[0]" in e and "asks" in e for e in errs), errs)
        facts = {**SYSTEM_FACTS, "docs": []}
        self.assertEqual(verify.verify(facts, bad(docs_summary=[])), [])

    def test_background_may_cite_config_and_docs(self):
        self.assertEqual(verify.verify(SYSTEM_FACTS, bad(background=[{"text": "x", "refs": ["c1", "d1"]}])), [])

    def test_pr_mode_unaffected(self):
        from test_explainer_page import FACTS, GOOD
        self.assertEqual(verify.verify(FACTS, GOOD), [])
        errs = verify.verify(FACTS, {**GOOD, "scenario": None})
        self.assertIn("scenario is missing: one concrete trigger walked before and after the change", errs)


class SystemRenderTest(unittest.TestCase):
    def page(self, expl=GOOD_SYSTEM, errors=(), facts=SYSTEM_FACTS):
        return render.render(facts, expl, list(errors), {})

    def test_sections_and_header(self):
        page = self.page()
        for h in ("<h2>Background", "<h2>Components", "<h2>How it works", "<h2>Resource map", "<h2>Where it runs",
                  "<h2>Config that matters", "<h2>What the docs ask", "<h2>Risk callouts", "<h2>Open these files first",
                  "<h2>Open questions", "<h2>Walkthrough", "<h2>Not covered", "<h2>Check your understanding"):
            self.assertIn(h, page, h)
        self.assertNotIn("<h2>Before → after", page)
        self.assertIn("<title>Service explainer: grafana</title>", page)
        self.assertIn("o/r</a> @ main", page)
        self.assertIn('<span class="pill">argo/prod</span>', page)
        self.assertIn("a request to grafana.example.com", page)
        self.assertIn("SSO for Grafana", page)
        self.assertIn("Who owns this app?", page)
        self.assertIn("no fact", page)

    def test_focus_nodes_and_links_to_the_ref(self):
        page = self.page()
        self.assertIn(":::focus", page)
        self.assertIn("classDef focus", page)
        self.assertIn("https://github.com/o/r/blob/abcdef1/apps/grafana/deployment.yaml#L1", page)
        self.assertIn("https://github.com/o/r/blob/abcdef1/infra/main.tf#L1", page)
        self.assertIn("values · grafana · argo/prod/grafana.yaml", page)
        self.assertIn("doc · One-pager", page)

    def test_walkthrough_shows_summary_and_config_keys(self):
        page = self.page()
        self.assertIn("image: grafana/grafana:10.1", page)
        self.assertIn("probes.readiness: GET /api/health:3000", page)
        self.assertIn("keys: adminPassword, replicas", page)
        self.assertNotIn("No hunk in the diff", page)

    def test_rejected_shapes_still_render(self):
        errors = ["components is missing a row for grafana"]
        for expl in (bad(components="x"), bad(how_it_works=[None, "x"]), bad(where_it_runs=None),
                     bad(config_that_matters=[None]), bad(open_questions="x"), bad(docs_summary=[{"doc": None, "asks": "x"}]),
                     "not an object"):
            page = self.page(expl, errors)
            self.assertIn("<strong>Unverified.</strong>", page)

    def test_model_text_is_escaped_and_masked(self):
        page = self.page(bad(open_questions=[{"text": "<img src=x onerror=alert(1)> password: hunter2hunter2", "refs": ["no fact"]}]))
        self.assertNotIn("<img", page)
        self.assertNotIn("hunter2", page)


JIRA = {"key": "IFS-9", "source": "argument", "url": "https://x.atlassian.net/browse/IFS-9", "summary": "Add SSO to Grafana",
        "status": "To Do", "type": "Task", "parent": None, "description": "Enable SSO and keep two replicas.",
        "comments": [{"id": "j1", "author": "A", "created": "2026-10-01", "url": "https://x/j1", "body": "Prod only."}]}
RELATED = [{"number": 7, "title": "feat: grafana sso", "state": "OPEN", "url": "https://github.com/o/r/pull/7", "head_ref": "feature/IFS-9-sso"}]
TICKET_FACTS = {**SYSTEM_FACTS, "mode": "ticket", "jira": JIRA, "related_prs": RELATED}
GOOD_TICKET = {**GOOD_SYSTEM, "ticket": {
    "intent": "Turn on SSO for Grafana in prod.", "pr": 7,
    "criteria": [{"text": "SSO enabled", "status": "would_change", "refs": ["c1", "r1"]},
                 {"text": "two replicas in prod", "status": "already_true", "reason": "prod runs 2", "refs": ["r1"]},
                 {"text": "nonprod unchanged", "status": "out_of_scope", "reason": "the ticket names prod", "refs": ["j1"]},
                 {"text": "audit logging", "status": "unclear", "reason": "no fact about logging", "refs": ["r1"]}]}}


def bad_ticket(**changes) -> dict:
    expl = copy.deepcopy(GOOD_TICKET)
    expl.update(changes)
    return expl


class TicketVerifyTest(unittest.TestCase):
    def test_good_ticket_passes(self):
        self.assertEqual(verify.verify(TICKET_FACTS, GOOD_TICKET), [])

    def test_ticket_section_required_in_ticket_mode(self):
        errs = verify.verify(TICKET_FACTS, bad_ticket(ticket=None))
        self.assertTrue(any("no ticket section" in e for e in errs), errs)

    def test_ticket_statuses_are_the_system_set(self):
        t = copy.deepcopy(GOOD_TICKET["ticket"]); t["criteria"][1]["status"] = "covered"
        errs = verify.verify(TICKET_FACTS, bad_ticket(ticket=t))
        self.assertTrue(any("criteria[1] status 'covered'" in e for e in errs), errs)
        t = copy.deepcopy(GOOD_TICKET["ticket"]); t["criteria"][0]["refs"] = ["j1"]
        errs = verify.verify(TICKET_FACTS, bad_ticket(ticket=t))
        self.assertTrue(any("criteria[0] would change but cites no resource" in e for e in errs), errs)
        t = copy.deepcopy(GOOD_TICKET["ticket"]); t["criteria"][3]["reason"] = ""
        errs = verify.verify(TICKET_FACTS, bad_ticket(ticket=t))
        self.assertTrue(any("criteria[3] is unclear but has no reason" in e for e in errs), errs)

    def test_ticket_pr_must_be_a_related_pr(self):
        t = copy.deepcopy(GOOD_TICKET["ticket"]); t["pr"] = 99
        errs = verify.verify(TICKET_FACTS, bad_ticket(ticket=t))
        self.assertTrue(any("ticket.pr" in e and "99" in e for e in errs), errs)
        t = copy.deepcopy(GOOD_TICKET["ticket"]); del t["pr"]
        errs = verify.verify(TICKET_FACTS, bad_ticket(ticket=t))
        self.assertTrue(any("ticket.pr" in e and "7" in e for e in errs), errs)  # an open PR exists: name it

    def test_pr_mode_statuses_unchanged(self):
        from test_explainer_page import FACTS, GOOD
        facts = {**FACTS, "jira": JIRA}
        expl = {**GOOD, "ticket": {"intent": "i", "criteria": [{"text": "a", "status": "covered", "refs": ["r1"]}]}}
        self.assertEqual(verify.verify(facts, expl), [])
        expl["ticket"]["criteria"][0]["status"] = "would_change"
        self.assertTrue(any("status 'would_change'" in e for e in verify.verify(facts, expl)))


class NoAppTicketTest(unittest.TestCase):
    """A ticket that names no Application still gets a verified page: the ticket itself is citable."""
    FACTS = {**TICKET_FACTS, "apps": [], "resources": [], "edges": [], "config": [], "terraform": [], "workflows": [],
             "docs": [], "related_prs": [], "query": {**TICKET_FACTS["query"], "service": [], "inferred": True},
             "jira": {**JIRA, "comments": []},
             "notes": [{"key": "match", "text": "No Application name appears in IFS-9's summary."}]}
    EXPL = {"tldr": "IFS-9 asks for SSO on Grafana; no Application in this repo matched.",
            "background": [{"text": "The ticket asks for SSO.", "refs": ["IFS-9"]}],
            "components": [], "how_it_works": [], "where_it_runs": [], "config_that_matters": [],
            "open_questions": [{"text": "Which app is Grafana deployed by?", "refs": ["IFS-9"]}], "docs_summary": [],
            "callouts": [], "must_read": [], "reading_order": [], "not_covered": ["match"],
            "ticket": {"intent": "SSO for Grafana.", "criteria": [{"text": "SSO", "status": "unclear", "reason": "no app matched", "refs": ["IFS-9"]}]},
            "quiz": [{"question": f"q{i}", "options": [{"text": "a", "correct": True, "explanation": "e"}, {"text": "b", "correct": False, "explanation": "e"}], "refs": ["IFS-9"]} for i in range(3)],
            "narrator_model": "claude-opus-5-5"}

    def test_ticket_key_is_citable_and_scenarios_optional_without_apps(self):
        self.assertEqual(verify.verify(self.FACTS, self.EXPL), [])
        errs = verify.verify(TICKET_FACTS, {**GOOD_TICKET, "how_it_works": []})
        self.assertTrue(any("how_it_works has 0" in e for e in errs))  # with apps, scenarios stay required

    def test_ticket_key_renders_as_a_link(self):
        page = render.render(self.FACTS, self.EXPL, [], {})
        self.assertNotIn("<strong>Unverified.</strong>", page)
        self.assertIn('<a href="https://x.atlassian.net/browse/IFS-9">ticket IFS-9</a>', page)


class RenderRobustnessTest(unittest.TestCase):
    def test_list_valued_status_and_severity_do_not_crash(self):
        expl = bad_ticket(callouts=[{"severity": ["high"], "text": "x", "refs": ["r1"]}])
        expl["ticket"]["criteria"][0]["status"] = ["would_change"]
        page = render.render(TICKET_FACTS, expl, ["bad"], {})
        self.assertIn("<strong>Unverified.</strong>", page)

    def test_invalid_explainer_json_still_renders_unverified(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "explainer.json"
            p.write_text("{not json")
            expl, errors = render.load_explainer(p)
        self.assertEqual(expl, {})
        self.assertTrue(errors and "not valid JSON" in errors[0])
        page = render.render(SYSTEM_FACTS, expl, errors, {})
        self.assertIn("<strong>Unverified.</strong>", page)

    def test_doc_title_is_masked_on_the_page(self):
        facts = {**SYSTEM_FACTS, "docs": [{**SYSTEM_FACTS["docs"][0], "title": "password: hunter2hunter2 notes"}]}
        page = render.render(facts, GOOD_SYSTEM, [], {})
        self.assertNotIn("hunter2", page)


class TicketRenderTest(unittest.TestCase):
    def test_ticket_card_statuses_and_related_prs(self):
        page = render.render(TICKET_FACTS, GOOD_TICKET, [], {})
        self.assertIn("<title>Ticket explainer: IFS-9</title>", page)
        self.assertIn("IFS-9 — Add SSO to Grafana", page)
        for label in ("would change", "already true", "out of scope", "unclear"):
            self.assertIn(label, page, label)
        self.assertIn("https://github.com/o/r/pull/7", page)
        self.assertIn("/pr-explainer 7", page)
        self.assertIn("Turn on SSO for Grafana in prod.", page)
        self.assertIn("<h2>Ticket", page)

    def test_ticket_render_tolerates_rejected_shapes(self):
        for expl in (bad_ticket(ticket="x"), bad_ticket(ticket={"criteria": "x", "pr": "seven", "intent": None})):
            page = render.render(TICKET_FACTS, expl, ["ticket is wrong"], {})
            self.assertIn("<strong>Unverified.</strong>", page)
        page = render.render({**TICKET_FACTS, "related_prs": []}, GOOD_TICKET, [], {})
        self.assertNotIn("/pr-explainer", page)


if __name__ == "__main__":
    unittest.main()
