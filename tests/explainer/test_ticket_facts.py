# Run: uv run --with pyyaml --with "pathspec<1" python -m unittest discover -s tests/explainer
"""Ticket mode: the ticket by key, the service inferred from its text, related PRs."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills/explainer/scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import facts_lib  # noqa: E402
from test_system_facts import SystemFactsBase, make_repo  # noqa: E402

JIRA = {"key": "IFS-9", "source": "argument", "url": "https://x.atlassian.net/browse/IFS-9", "summary": "Upgrade grafana-agent",
        "status": "To Do", "type": "Task", "parent": None, "description": "Bump grafana-agent to 0.40 in prod.", "comments": []}
JIRA_NO_APP = {**JIRA, "summary": "Rotate the cluster CA", "description": "No app named here."}


class InferServiceTest(unittest.TestCase):
    found = [("grafana", "argo/prod/grafana.yaml", {}), ("grafana-agent", "argo/prod/ga.yaml", {}),
             ("loki", "argo/prod/loki.yaml", {})]

    def test_longest_name_in_text_wins(self):
        self.assertEqual(facts_lib.infer_service(self.found, ["Upgrade grafana-agent to 0.40", "feature/IFS-1-ga"]), ["grafana-agent"])

    def test_match_is_case_insensitive_and_by_directory_too(self):
        found = [("web", "argo/prod/payments/web.yaml", {})]
        self.assertEqual(facts_lib.infer_service(found, ["Fix Payments checkout"]), ["web"])
        self.assertEqual(facts_lib.infer_service(self.found, ["LOKI is slow"]), ["loki"])

    def test_nothing_named(self):
        self.assertEqual(facts_lib.infer_service(self.found, ["nothing here", "", None]), [])

    def test_shared_environment_directories_are_not_aliases(self):
        # Two apps under argo/prod: "prod" names an environment, not a service, and "production"
        # must not match "prod" as a substring.
        found = [("grafana", "argo/prod/grafana.yaml", {}), ("loki", "argo/prod/loki.yaml", {})]
        self.assertEqual(facts_lib.infer_service(found, ["Fix production alerts"]), [])
        self.assertEqual(facts_lib.infer_service(found, ["prod is down"]), [])
        # A directory unique to one app still names it, as a whole word.
        found = [("web", "argo/prod/payments/web.yaml", {}), ("loki", "argo/prod/loki.yaml", {})]
        self.assertEqual(facts_lib.infer_service(found, ["Fix payments checkout"]), ["web"])
        self.assertEqual(facts_lib.infer_service(found, ["repaymentsx"]), [])

    def test_names_match_as_whole_words(self):
        self.assertEqual(facts_lib.infer_service(self.found, ["grafana-agents are slow"]), [])
        self.assertEqual(facts_lib.infer_service(self.found, ["the grafana-agent, restarted"]), ["grafana-agent"])
        self.assertEqual(facts_lib.infer_service(self.found, ["feature/IFS-1-grafana"]), ["grafana"])


class TicketFactsTest(SystemFactsBase):
    def test_ticket_without_match_keeps_going(self):
        repo = make_repo(self.tmp)
        with self.trees(repo) as t, \
             mock.patch.object(facts_lib, "jira_facts_for_key", return_value=(JIRA_NO_APP, [])), \
             mock.patch.object(facts_lib, "related_prs", return_value=([], [])):
            facts = facts_lib.collect_system("o/r", t, [], [], "IFS-9", False)
        self.assertEqual(facts["mode"], "ticket")
        self.assertEqual(facts["apps"], [])
        self.assertEqual(facts["jira"]["key"], "IFS-9")
        self.assertEqual(facts["notes"][0]["key"], "match")
        self.assertEqual(facts["query"]["service"], [])

    def test_ticket_infers_the_service_from_text_and_branches(self):
        repo = make_repo(self.tmp, apps=["grafana", "grafana-agent"])
        prs = [{"number": 7, "title": "x", "state": "OPEN", "url": "https://github.com/o/r/pull/7", "head_ref": "feature/IFS-9-grafana-agent"}]
        with self.trees(repo) as t, \
             mock.patch.object(facts_lib, "jira_facts_for_key", return_value=({**JIRA, "summary": "Upgrade the agent"}, [])), \
             mock.patch.object(facts_lib, "related_prs", return_value=(prs, [])):
            facts = facts_lib.collect_system("o/r", t, [], [], "IFS-9", False)
        self.assertEqual(facts["query"]["service"], ["grafana-agent"])
        self.assertEqual(facts["query"]["inferred"], True)
        self.assertEqual([a["app"] for a in facts["apps"]], ["grafana-agent"])
        self.assertEqual(facts["related_prs"], prs)

    def test_explicit_service_wins_over_inference(self):
        repo = make_repo(self.tmp, apps=["grafana", "grafana-agent"])
        with self.trees(repo) as t, \
             mock.patch.object(facts_lib, "jira_facts_for_key", return_value=(JIRA, [])), \
             mock.patch.object(facts_lib, "related_prs", return_value=([], [])):
            facts = facts_lib.collect_system("o/r", t, ["grafana"], [], "IFS-9", False)
        self.assertEqual(facts["query"]["inferred"], False)
        self.assertEqual(sorted({a["app"] for a in facts["apps"]}), ["grafana", "grafana-agent"])  # substring match

    def test_jira_failure_is_a_note(self):
        repo = make_repo(self.tmp)
        with self.trees(repo) as t, \
             mock.patch.object(facts_lib, "jira_facts_for_key", return_value=(None, [{"key": "jira", "text": "IFS-9 could not be read."}])), \
             mock.patch.object(facts_lib, "related_prs", return_value=([], [{"key": "related_prs", "text": "gh failed"}])):
            facts = facts_lib.collect_system("o/r", t, ["grafana"], [], "IFS-9", False)
        self.assertIsNone(facts["jira"])
        self.assertEqual({n["key"] for n in facts["notes"]}, {"jira", "related_prs", "policy"})


class RelatedPrsTest(unittest.TestCase):
    def test_related_prs_parses_gh_output(self):
        out = '[{"number": 7, "title": "t", "state": "OPEN", "url": "https://github.com/o/r/pull/7", "headRefName": "feature/IFS-9"}]'
        with mock.patch.object(facts_lib, "sh", return_value=out) as m:
            prs, notes = facts_lib.related_prs("o/r", "IFS-9")
        self.assertEqual(prs, [{"number": 7, "title": "t", "state": "OPEN", "url": "https://github.com/o/r/pull/7", "head_ref": "feature/IFS-9"}])
        self.assertEqual(notes, [])
        self.assertTrue(any("IFS-9" in " ".join(c.args) for c in m.call_args_list))

    def test_related_prs_includes_branch_only_references(self):
        # gh --search covers title and body only; a PR whose branch alone names the key is found
        # by listing open PRs and filtering on headRefName.
        def fake_sh(*args, **kw):
            if "--search" in args:
                return '[{"number": 7, "title": "t", "state": "OPEN", "url": "https://github.com/o/r/pull/7", "headRefName": "feature/IFS-9"}]'
            return ('[{"number": 8, "title": "no key here", "state": "OPEN", "url": "https://github.com/o/r/pull/8", "headRefName": "fix/ifs-9-retry"},'
                    ' {"number": 9, "title": "other", "state": "OPEN", "url": "https://github.com/o/r/pull/9", "headRefName": "fix/IFS-90"},'
                    ' {"number": 7, "title": "t", "state": "OPEN", "url": "https://github.com/o/r/pull/7", "headRefName": "feature/IFS-9"}]')
        with mock.patch.object(facts_lib, "sh", side_effect=fake_sh):
            prs, notes = facts_lib.related_prs("o/r", "IFS-9")
        self.assertEqual([p["number"] for p in prs], [7, 8])  # deduplicated; IFS-90 is not IFS-9
        self.assertEqual(notes, [])

    def test_related_prs_failure_is_a_note(self):
        with mock.patch.object(facts_lib, "sh", side_effect=RuntimeError("gh: not logged in")):
            prs, notes = facts_lib.related_prs("o/r", "IFS-9")
        self.assertEqual(prs, [])
        self.assertEqual(notes[0]["key"], "related_prs")


if __name__ == "__main__":
    unittest.main()
