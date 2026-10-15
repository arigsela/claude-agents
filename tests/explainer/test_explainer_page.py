# Run: uv run --with pyyaml --with "pathspec<1" python -m unittest discover -s tests/explainer
"""verify.py and render.py for the background, scenario, walkthrough and quiz sections."""
from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills/explainer/scripts"))
import collect_pr  # noqa: E402
import facts_lib  # noqa: E402
import render  # noqa: E402
import verify  # noqa: E402

FACTS = {
    "pr": {"repo": "o/r", "number": 7, "title": "chore: bump grafana", "url": "https://github.com/o/r/pull/7",
           "head_sha": "abcdef1234567", "merge_base": "0000000"},
    "triage": {"label": "read", "why": ""},
    "apps": [{"app": "grafana", "application_file": "argo/grafana.yaml", "source_kind": "directory",
              "render": "rendered", "render_note": ""}],
    "resources": [
        {"id": "r1", "app": "grafana", "scope": "", "kind": "Deployment", "namespace": "mon", "name": "grafana",
         "action": "modified", "changed_paths": ["spec.template.spec.containers[0].startupProbe.failureThreshold"],
         "file": "apps/grafana/deploy.yaml", "lines": [1, 12], "risk": None},
        {"id": "r2", "app": "grafana", "scope": "", "kind": "Service", "namespace": "mon", "name": "grafana",
         "action": "context", "changed_paths": [], "file": "apps/grafana/svc.yaml", "lines": [1, 9], "risk": None},
        {"id": "r3", "app": "grafana", "scope": "", "kind": "ConfigMap", "namespace": "mon", "name": "grafana-ini",
         "action": "modified", "changed_paths": ["data.grafana.ini"], "file": None, "lines": None, "risk": None},
    ],
    "edges": [{"from": "r2", "to": "r1", "type": "selects"}],
    "non_manifest_changes": [{"id": "f1", "file": "scripts/reload.sh", "status": "modified", "hunks": [[3, 4]]}],
    "terraform": [], "terraform_plans": [], "workflows": [], "policy_hits": [], "notes": [], "jira": None,
}

DIFF = """diff --git a/apps/grafana/deploy.yaml b/apps/grafana/deploy.yaml
--- a/apps/grafana/deploy.yaml
+++ b/apps/grafana/deploy.yaml
@@ -8,4 +8,4 @@ spec:
       startupProbe:
-        failureThreshold: 1
+        failureThreshold: 5
         periodSeconds: 1
diff --git a/scripts/reload.sh b/scripts/reload.sh
--- a/scripts/reload.sh
+++ b/scripts/reload.sh
@@ -2,3 +2,4 @@ set -e
 curl -s localhost/reload
+echo "password: hunter2hunter2"
 exit 0
"""

GOOD = {
    "tldr": "Grafana's startup probe gives up after 5 s instead of 1 s.",
    "background": [{"text": "Grafana runs in mon behind a Service.", "refs": ["r2"]}],
    "scenario": {"trigger": "a grafana pod restarts", "before": "killed after 1 s", "after": "has 5 s", "refs": ["r1"]},
    "behavior_changes": [{"app": "grafana", "before": "1 s", "after": "5 s", "refs": ["r1"]}],
    "callouts": [],
    "must_read": [{"ref": "f1", "why": "the reload script changed"}],
    "reading_order": [{"ref": "r3", "note": "Config first."}, {"ref": "r1", "note": "Then the probe."},
                      {"ref": "f1", "note": "The script that reloads it."}],
    "not_covered": [],
    "quiz": [
        {"question": "A pod takes 3 s to start. What happens after this merges?",
         "options": [{"text": "It is killed", "correct": False, "explanation": "The threshold is now 5 s."},
                     {"text": "It starts", "correct": True, "explanation": "5 s covers 3 s."}],
         "refs": ["r1"]},
        {"question": "Which namespace?", "options": [{"text": "mon", "correct": True, "explanation": "Yes."},
                                                     {"text": "default", "correct": False, "explanation": "No."}],
         "refs": ["r1"]},
        {"question": "Which object fronts the pods?", "options": [{"text": "Service", "correct": True, "explanation": "Yes."},
                                                                  {"text": "Ingress", "correct": False, "explanation": "No."}],
         "refs": ["r2"]},
    ],
    "narrator_model": "claude-opus-5-5",
}

QUIZ = GOOD.pop("quiz")  # the quiz is opt-in (--quiz): tests that check it pass quiz=True


def bad(**changes) -> dict:
    expl = copy.deepcopy(GOOD)
    expl.update(changes)
    return expl


class LayoutTest(unittest.TestCase):
    """PR 1 of the explainer plugin: shared scripts, thin collect_pr main, template per mode."""

    def test_collect_pr_is_a_thin_main_over_facts_lib(self):
        self.assertIs(collect_pr.collect, facts_lib.collect)
        self.assertTrue(callable(collect_pr.main))
        self.assertFalse(hasattr(facts_lib, "main"))

    def test_template_is_chosen_by_mode(self):
        self.assertEqual(render.template_path("pr").name, "template-pr.html")
        self.assertTrue(render.template_path("pr").is_file())
        self.assertEqual(render.template_path("system").name, "template-system.html")

    def test_collect_marks_pr_mode(self):
        import tempfile
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as tmp:
            base, head = Path(tmp) / "base", Path(tmp) / "head"
            base.mkdir(); head.mkdir()
            trees = SimpleNamespace(base=base, head=head, dir=Path(tmp), merge_base="0" * 40, local=None)
            pr = {"number": 1, "title": "t", "html_url": "https://github.com/o/r/pull/1", "body": "",
                  "base": {"sha": "0" * 40}, "head": {"sha": "1" * 40, "ref": "feature/x"}}
            facts = facts_lib.collect("o/r", pr, [], [], trees)
        self.assertEqual(facts["mode"], "pr")
        self.assertEqual(facts["pr"]["number"], 1)


class VerifyTest(unittest.TestCase):
    def test_good_explainer_passes(self):
        self.assertEqual(verify.verify(FACTS, GOOD), [])

    def test_legacy_reading_order_strings_still_pass(self):
        self.assertEqual(verify.verify(FACTS, bad(reading_order=["r1", "f1"])), [])

    def test_background_required_and_cited(self):
        self.assertTrue(any("background is missing" in e for e in verify.verify(FACTS, bad(background=[]))))
        errs = verify.verify(FACTS, bad(background=[{"text": "x", "refs": []}]))
        self.assertTrue(any("cites nothing" in e for e in errs))
        errs = verify.verify(FACTS, bad(background=[{"text": "x", "refs": ["zz"]}]))
        self.assertTrue(any("unknown id 'zz'" in e for e in errs))
        errs = verify.verify(FACTS, bad(background=[{"text": "x", "refs": ["r1"]}] * 4))
        self.assertTrue(any("max 3" in e for e in errs))

    def test_scenario_fields(self):
        self.assertTrue(any("scenario is missing" in e for e in verify.verify(FACTS, bad(scenario=None))))
        errs = verify.verify(FACTS, bad(scenario={"trigger": "", "before": "b", "after": "a", "refs": []}))
        self.assertIn("scenario.trigger is empty", errs)
        self.assertIn("scenario cites nothing", errs)

    def test_walkthrough_note_required_for_step_objects(self):
        errs = verify.verify(FACTS, bad(reading_order=[{"ref": "r1", "note": " "}]))
        self.assertTrue(any("empty note" in e for e in errs))

    def test_quiz_is_off_by_default(self):
        self.assertEqual(verify.verify(FACTS, GOOD), [])
        self.assertIn("quiz written without --quiz; leave it out unless the user asked for one",
                      verify.verify(FACTS, bad(quiz=QUIZ)))
        self.assertEqual(verify.verify(FACTS, bad(quiz=QUIZ), quiz=True), [])

    def test_quiz_count_and_shape(self):
        self.assertTrue(any("quiz has 0 questions" in e for e in verify.verify(FACTS, bad(quiz=[]), quiz=True)))
        q = copy.deepcopy(QUIZ)
        q[0]["options"][0]["correct"] = True  # two correct
        self.assertTrue(any("2 correct options" in e for e in verify.verify(FACTS, bad(quiz=q), quiz=True)))
        q = copy.deepcopy(QUIZ)
        q[1]["options"][1]["explanation"] = ""
        self.assertTrue(any("options[1] has no explanation" in e for e in verify.verify(FACTS, bad(quiz=q), quiz=True)))
        q = copy.deepcopy(QUIZ)
        q[2]["refs"] = []
        self.assertTrue(any("quiz[2] cites nothing" in e for e in verify.verify(FACTS, bad(quiz=q), quiz=True)))
        q = copy.deepcopy(QUIZ)
        q[0]["options"] = q[0]["options"][:1]
        self.assertTrue(any("quiz[0] has 1 options" in e for e in verify.verify(FACTS, bad(quiz=q), quiz=True)))

    def test_secret_in_quiz_is_rejected(self):
        q = copy.deepcopy(QUIZ)
        q[0]["options"][0]["explanation"] = "password: hunter2hunter2"
        self.assertIn("explainer text contains a secret-looking value", verify.verify(FACTS, bad(quiz=q), quiz=True))
        q[0]["options"][0]["explanation"] = 'set "token": "abcdefgh12345678" in the config'
        self.assertIn("explainer text contains a secret-looking value", verify.verify(FACTS, bad(quiz=q), quiz=True))

    def test_null_text_is_empty_not_the_word_none(self):
        self.assertIn("tldr is empty", verify.verify(FACTS, bad(tldr=None)))
        errs = verify.verify(FACTS, bad(background=[{"text": None, "refs": ["r1"]}]))
        self.assertIn("background[0] has no text", errs)
        errs = verify.verify(FACTS, bad(scenario={"trigger": None, "before": "b", "after": "a", "refs": ["r1"]}))
        self.assertIn("scenario.trigger is empty", errs)
        q = copy.deepcopy(QUIZ)
        q[0]["options"][0]["explanation"] = None
        self.assertIn("quiz[0].options[0] has no explanation", verify.verify(FACTS, bad(quiz=q), quiz=True))
        q[0]["question"] = None
        self.assertIn("quiz[0] has no question", verify.verify(FACTS, bad(quiz=q), quiz=True))
        errs = verify.verify(FACTS, bad(reading_order=[{"ref": "r1", "note": None}]))
        self.assertTrue(any("empty note" in e for e in errs))

    def test_malformed_input_is_an_error_not_a_crash(self):
        cases = [
            bad(background=[{"text": "x", "refs": "r1"}]),          # refs not a list
            bad(background=[{"text": "x", "refs": 7}]),
            bad(background=["just a string"]),
            bad(scenario={"trigger": "t", "before": "b", "after": "a", "refs": None}),
            bad(scenario={"trigger": "t", "before": "b", "after": "a", "refs": [None]}),
            bad(reading_order=[None, 5, {"note": "no ref"}]),
            bad(reading_order="r1"),
        ]
        q = copy.deepcopy(QUIZ); q[0]["options"] = "It starts"; cases.append(bad(quiz=q))
        q = copy.deepcopy(QUIZ); q[0]["options"] = [None, "x"]; cases.append(bad(quiz=q))
        q = copy.deepcopy(QUIZ); q[0]["refs"] = {"r1": 1}; cases.append(bad(quiz=q))
        q = copy.deepcopy(QUIZ); q[0] = "not an object"; cases.append(bad(quiz=q))
        for expl in cases:
            errs = verify.verify(FACTS, expl, quiz=True)   # must not raise
            self.assertTrue(errs, expl)
            self.assertFalse(any("crashed" in e for e in errs), errs)
        self.assertIn("background[0].refs must be a list of ids", verify.verify(FACTS, cases[0]))
        self.assertIn("quiz[0].options must be a list", verify.verify(FACTS, cases[7], quiz=True))


class DiffTest(unittest.TestCase):
    def test_parse_diff_keys_files_and_ranges(self):
        d = render.parse_diff(DIFF)
        self.assertEqual(sorted(d), ["apps/grafana/deploy.yaml", "scripts/reload.sh"])
        h = d["apps/grafana/deploy.yaml"][0]
        self.assertEqual(h["old"], [8, 11])
        self.assertEqual(h["new"], [8, 11])
        self.assertEqual(len(h["lines"]), 5)

    def test_removed_lines_that_look_like_headers_stay_in_the_hunk(self):
        # A removed "-- comment" line appears as "--- comment"; an added "++ x" as "+++ x".
        text = ("diff --git a/q.sql b/q.sql\n--- a/q.sql\n+++ b/q.sql\n"
                "@@ -1,3 +1,3 @@\n-- old comment\n--- a removed sql comment\n+++ an added line\n select 1\n"
                "diff --git a/z.txt b/z.txt\n--- a/z.txt\n+++ b/z.txt\n@@ -1 +1 @@\n-a\n+b\n")
        d = render.parse_diff(text)
        self.assertEqual(sorted(d), ["q.sql", "z.txt"])
        self.assertEqual(d["q.sql"][0]["lines"][1:], ["-- old comment", "--- a removed sql comment", "+++ an added line", " select 1"])
        self.assertEqual(d["z.txt"][0]["lines"][1:], ["-a", "+b"])

    def test_no_newline_marker_and_empty_context_lines(self):
        text = "diff --git a/f b/f\n--- a/f\n+++ b/f\n@@ -1,2 +1,2 @@\n\n-x\n\\ No newline at end of file\n+y\n"
        d = render.parse_diff(text)
        self.assertEqual(d["f"][0]["lines"][1:], ["", "-x", "\\ No newline at end of file", "+y"])

    def test_deleted_file_keeps_base_path(self):
        d = render.parse_diff("diff --git a/x.yaml b/x.yaml\n--- a/x.yaml\n+++ /dev/null\n@@ -1,2 +0,0 @@\n-a\n-b\n")
        self.assertEqual(list(d), ["x.yaml"])
        self.assertEqual(d["x.yaml"][0]["old"], [1, 2])

    def test_hunks_for_overlap_single_line_and_no_file(self):
        d = render.parse_diff(DIFF)
        self.assertEqual(len(render.hunks_for(FACTS["resources"][0], d)), 1)  # range 1-12 overlaps 8-11
        self.assertEqual(render.hunks_for({"file": "apps/grafana/deploy.yaml", "lines": [30, 40]}, d), [])
        # A block header above the hunk takes the next hunk below it only when that hunk names it.
        self.assertEqual(len(render.hunks_for({"file": "apps/grafana/deploy.yaml", "lines": [2], "name": "x"}, d)), 0)
        self.assertEqual(len(render.hunks_for({"file": "apps/grafana/deploy.yaml", "lines": [2]}, d, end=12)), 1)
        self.assertEqual(render.hunks_for(FACTS["resources"][2], d), [])  # no file: rendered from a chart
        self.assertEqual(len(render.hunks_for(FACTS["non_manifest_changes"][0], d)), 1)  # every hunk in the file

    def test_hunk_html_caps_and_masks(self):
        d = render.parse_diff(DIFF)
        out = render.hunk_html(d["scripts/reload.sh"])
        self.assertIn("[REDACTED]", out)
        self.assertNotIn("hunter2", out)
        big = [{"old": [1, 1], "new": [1, 1], "lines": ["@@ -1 +1 @@"] + ["+x"] * 100}]
        out = render.hunk_html(big)
        self.assertIn("41 more lines", out)

    def test_hunk_masks_json_and_quoted_credentials(self):
        lines = ["@@ -1,3 +1,4 @@", '+  "token": "abcdefgh12345678",', "+  API_KEY=Z9y8x7w6v5u4t3s2", ' "name": "grafana",',
                 "+  aws_secret_access_key = \"wJalrXUtnFEMI/K7MDENG\""]
        out = render.hunk_html([{"old": [1, 3], "new": [1, 4], "lines": lines}])
        for leak in ("abcdefgh12345678", "Z9y8x7w6v5u4t3s2", "wJalrXUtnFEMI"):
            self.assertNotIn(leak, out)
        self.assertIn("&quot;token&quot;: &quot;[REDACTED]", out)
        self.assertIn("grafana", out)  # ordinary values stay readable

    def test_hunk_masks_kubernetes_secret_data_under_any_key(self):
        lines = ["@@ -1,6 +1,7 @@", " apiVersion: v1", " kind: Secret", " data:",
                 "+  db-url: cG9zdGdyZXM6Ly91c2VyOnBhc3NAaG9zdC9kYg==", "-  banana: c2hvcnQ=", " stringData:",
                 "+  anything: plain-text-value-here", " metadata:", "+  name: creds"]
        out = render.hunk_html([{"old": [1, 6], "new": [1, 7], "lines": lines}])
        for leak in ("cG9zdGdyZXM6", "c2hvcnQ=", "plain-text-value-here"):
            self.assertNotIn(leak, out)
        self.assertIn("db-url: [REDACTED]", out)
        self.assertIn("name: creds", out)  # metadata after the block is not masked
        # The kind may sit outside the hunk: the caller says the file is a Secret.
        lines = ["@@ -5,2 +5,2 @@", " stringData:", "-  pw: old-plain-value", "+  pw: new-plain-value"]
        out = render.hunk_html([{"old": [5, 6], "new": [5, 6], "lines": lines}], secret=True)
        self.assertNotIn("plain-value", out)
        out = render.hunk_html([{"old": [5, 6], "new": [5, 6], "lines": lines}])
        self.assertIn("new-plain-value", out)  # a ConfigMap's stringData-like block stays readable

    def test_secret_hunk_without_block_header_is_still_masked(self):
        # The hunk starts deep inside data:, so no data:/stringData: line is visible.
        lines = ["@@ -12,3 +12,3 @@ data:", "   other: YWJj", "-  pw: c2hvcnQ=", "+  pw: bmV3cHc=", "+  url: postgres://u:p@h/db"]
        out = render.hunk_html([{"old": [12, 14], "new": [12, 14], "lines": lines}], secret=True)
        for leak in ("YWJj", "c2hvcnQ=", "bmV3cHc=", "postgres://"):
            self.assertNotIn(leak, out)
        self.assertIn("pw: [REDACTED]", out)
        # Structural keys stay readable in a Secret hunk; the kind inside the hunk is enough.
        lines = ["@@ -1,5 +1,5 @@", " kind: Secret", " metadata:", "-  name: creds-v1", "+  name: creds-v2",
                 "   namespace: mon", "+  token: c2hvcnQ="]
        out = render.hunk_html([{"old": [1, 5], "new": [1, 5], "lines": lines}])
        self.assertIn("name: creds-v2", out)
        self.assertIn("namespace: mon", out)
        self.assertNotIn("c2hvcnQ=", out)
        # Without the Secret flag the same short value is an ordinary ConfigMap entry.
        out = render.hunk_html([{"old": [12, 14], "new": [12, 14], "lines": ["@@ -1 +1 @@", "+  pw: c2hvcnQ="]}])
        self.assertIn("c2hvcnQ=", out)

    def test_multiline_secret_values_are_masked(self):
        # A block scalar inside a Secret, and one under a secret-looking key in any file.
        lines = ["@@ -3,4 +3,5 @@ stringData:", "   other: v1", "+  pw: |", "+    first plaintext line", "+",
                 "+    second plaintext line", "   next: v2"]
        out = render.hunk_html([{"old": [3, 6], "new": [3, 7], "lines": lines}], secret=True)
        for leak in ("v1", "first plaintext", "second plaintext", "v2"):
            self.assertNotIn(leak, out)
        self.assertEqual(out.count("[REDACTED]"), 5)
        lines = ["@@ -1,3 +1,5 @@", "+password: |-", "+  hunter2", "+  line two", " image: nginx", "+ADMIN_TOKEN: >", "+  abc"]
        out = render.hunk_html([{"old": [1, 3], "new": [1, 5], "lines": lines}])
        for leak in ("hunter2", "line two", "+  abc"):
            self.assertNotIn(leak, out)
        self.assertIn("image: nginx", out)
        self.assertIn("password: |-", out)

    def test_secret_data_keys_that_look_structural_are_masked(self):
        # data entries named name, namespace or type are values, not metadata.
        lines = ["@@ -5,4 +5,4 @@ data:", "   name: c2VjcmV0", "-  namespace: b2xk", "+  namespace: bmV3", "+  type: dHlwZQ=="]
        out = render.hunk_html([{"old": [5, 8], "new": [5, 8], "lines": lines}], secret=True)
        for leak in ("c2VjcmV0", "b2xk", "bmV3", "dHlwZQ=="):
            self.assertNotIn(leak, out)
        # With no section in view, indented names are masked too; top-level structure stays.
        lines = ["@@ -5,2 +5,2 @@", "-  name: old-plain", "+  name: new-plain", " type: Opaque"]
        out = render.hunk_html([{"old": [5, 6], "new": [5, 6], "lines": lines}], secret=True)
        self.assertNotIn("plain", out)
        self.assertIn("type: Opaque", out)
        # Under metadata the name, namespace and labels are readable; annotations are not.
        lines = ["@@ -2,6 +2,6 @@ metadata:", "   name: creds", "+  namespace: mon", "   labels:", "+    app: grafana",
                 "   annotations:", "+    note: something-sensitive", " data:", "+  name: c2VjcmV0"]
        out = render.hunk_html([{"old": [2, 7], "new": [2, 7], "lines": lines}], secret=True)
        for keep in ("name: creds", "namespace: mon", "app: grafana"):
            self.assertIn(keep, out)
        for leak in ("something-sensitive", "c2VjcmV0"):
            self.assertNotIn(leak, out)

    def test_single_line_refs_do_not_take_another_blocks_hunk(self):
        text = ('diff --git a/main.tf b/main.tf\n--- a/main.tf\n+++ b/main.tf\n'
                '@@ -22,3 +22,3 @@ resource "aws_db_instance" "b" {\n   engine = "postgres"\n-  size = 10\n+  size = 20\n')
        d = render.parse_diff(text)
        a = {"id": "t1", "file": "main.tf", "lines": [1], "name": "a", "type": "aws_instance", "action": "modified",
             "address": "aws_instance.a", "source": "source-diff"}
        b = {"id": "t2", "file": "main.tf", "lines": [20], "name": "b", "type": "aws_db_instance", "action": "modified",
             "address": "aws_db_instance.b", "source": "source-diff"}
        index = {"t1": a, "t2": b}
        # With b below it, a stops at line 19 and gets nothing; b takes the hunk.
        self.assertEqual(render.next_item_start(a, index), 20)
        self.assertEqual(render.hunks_for(a, d, render.next_item_start(a, index)), [])
        self.assertEqual(len(render.hunks_for(b, d, render.next_item_start(b, index))), 1)
        # Alone in the file, a takes the next hunk only when its header names a.
        self.assertEqual(render.hunks_for(a, d, None), [])
        self.assertEqual(len(render.hunks_for(b, d, None)), 1)
        self.assertEqual(len(render.hunks_for({"file": "main.tf", "lines": [1], "name": "other"}, d, None)), 0)
        page = render.render({**FACTS, "terraform": [a, b], "resources": []},
                             bad(reading_order=[{"ref": "t1", "note": "a"}, {"ref": "t2", "note": "b"}],
                                 background=[{"text": "x", "refs": ["t1"]}], scenario={"trigger": "t", "before": "b", "after": "a", "refs": ["t1"]},
                                 behavior_changes=[], must_read=[], quiz=[dict(q, refs=["t1"]) for q in QUIZ]),
                             [], d)
        self.assertEqual(page.count('<pre class="hunk">'), 1)
        self.assertIn("No hunk in the diff for this item.", page)

    def test_long_base64_after_any_key_is_masked_even_without_secret_context(self):
        lines = ["@@ -1 +1 @@", "+  ca.crt: LS0tLS1CRUdJTiBDRVJUSUZJQ0FURS0tLS0tCk1JSUJrVENDQVRlZ0F3SUJBZ0lVZkY="]
        out = render.hunk_html([{"old": [1, 1], "new": [1, 1], "lines": lines}])
        self.assertNotIn("LS0tLS1CRUdJ", out)
        self.assertIn("ca.crt: [REDACTED]", out)

    def test_render_marks_secret_resources_for_masking(self):
        facts = copy.deepcopy(FACTS)
        facts["resources"].append({"id": "r4", "app": "grafana", "scope": "", "kind": "Secret", "namespace": "mon",
                                   "name": "creds", "action": "modified", "changed_paths": ["stringData.pw"],
                                   "file": "apps/grafana/secret.yaml", "lines": [1, 6], "risk": None})
        diff = DIFF + ("diff --git a/apps/grafana/secret.yaml b/apps/grafana/secret.yaml\n"
                       "--- a/apps/grafana/secret.yaml\n+++ b/apps/grafana/secret.yaml\n"
                       "@@ -4,3 +4,3 @@ metadata:\n stringData:\n-  pw: old-plain-value\n+  pw: new-plain-value\n")
        expl = bad(reading_order=[{"ref": "r4", "note": "The credential."}])
        page = render.render(facts, expl, [], render.parse_diff(diff))
        self.assertNotIn("plain-value", page)
        self.assertIn("pw: [REDACTED]", page)


class RenderTest(unittest.TestCase):
    def page(self, expl=GOOD, errors=(), diff=DIFF, quiz=False):
        return render.render(FACTS, expl, list(errors), render.parse_diff(diff), quiz=quiz)

    def test_sections_present_with_hunks_and_quiz(self):
        page = self.page(bad(quiz=QUIZ), quiz=True)
        self.assertIn("<h2>Background", page)
        self.assertIn("Grafana runs in mon", page)
        self.assertIn("<strong>Trigger:</strong> a grafana pod restarts", page)
        self.assertIn('<pre class="hunk">', page)
        self.assertIn("failureThreshold: 5", page)
        self.assertIn("<details open>", page)   # f1 is must-read
        self.assertIn("<details>", page)        # r1 is not
        self.assertIn("<code>data.grafana.ini</code>", page)  # r3 has no hunk: changed paths instead
        self.assertEqual(page.count('<li class="q">'), 3)
        self.assertEqual(page.count('data-correct="1"'), 3)
        self.assertIn('data-why="5 s covers 3 s."', page)
        self.assertIn("[REDACTED]", page)
        self.assertNotIn("hunter2", page)

    def test_no_quiz_section_without_the_flag(self):
        page = self.page(bad(quiz=QUIZ))
        self.assertNotIn("Check your understanding", page)
        self.assertNotIn('<ol class="quiz">', page)
        self.assertIn("Check your understanding", self.page(bad(quiz=QUIZ), quiz=True))

    def test_without_diff_steps_still_render(self):
        page = self.page(diff="")
        self.assertNotIn('<pre class="hunk">', page)
        self.assertIn("Config first.", page)
        self.assertIn("No hunk in the diff for this item.", page)

    def test_model_text_is_escaped(self):
        expl = bad(scenario={"trigger": "<img src=x onerror=alert(1)>", "before": "b", "after": "a", "refs": ["r1"]})
        page = self.page(expl)
        self.assertNotIn("<img", page)
        self.assertIn("&lt;img", page)
        q = copy.deepcopy(QUIZ)
        q[0]["options"][0]["explanation"] = 'x" onclick="alert(1)'
        page = self.page(bad(quiz=q), quiz=True)
        self.assertNotIn('onclick="alert', page)

    def test_rejected_shapes_still_render_an_unverified_page(self):
        errors = ["quiz[0] is not an object", "scenario is missing: one concrete trigger walked before and after the change"]
        cases = [
            bad(quiz=["invalid"]), bad(quiz="invalid"), bad(quiz=[{"question": "q", "options": "x", "refs": "r1"}]),
            bad(quiz=[{"question": None, "options": [None, {"text": None, "correct": "yes", "explanation": None}], "refs": [None]}]),
            bad(scenario="invalid"), bad(scenario={"trigger": None, "refs": "r1"}),
            bad(background="invalid"), bad(background=[None, "x", {"text": None, "refs": 3}]),
            bad(reading_order=[None, 5, {"note": "no ref"}, {"ref": ["r1"]}]), bad(reading_order="r1"),
            bad(must_read="x"), bad(must_read=[None, {"ref": None, "why": None}]),
            bad(behavior_changes=[None, {"refs": "r1"}]), bad(callouts=["x", {"severity": None, "refs": [None]}]),
            bad(not_covered="x"), bad(not_covered=[None, 3]), bad(ticket="x"), bad(ticket={"criteria": "x", "intent": 5}),
            bad(tldr=None), "not even an object",
        ]
        for expl in cases:
            page = render.render(FACTS, expl, errors, render.parse_diff(DIFF), quiz=True)  # must not raise
            self.assertIn("<strong>Unverified.</strong>", page, expl)
            self.assertIn("quiz[0] is not an object", page)
        self.assertIn("No quiz was written.", render.render(FACTS, bad(quiz=["invalid"]), errors, {}, quiz=True))
        self.assertIn("No scenario was written.", render.render(FACTS, bad(scenario="invalid"), errors, {}))

    def test_legacy_reading_order_strings(self):
        page = self.page(bad(reading_order=["r1"]))
        self.assertIn('<ol class="walk">', page)
        self.assertIn("Deployment mon/grafana", page)


if __name__ == "__main__":
    unittest.main()
