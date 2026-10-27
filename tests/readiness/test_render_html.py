"""render --html: the report as one page for the Artifact tool, from the same decided checks as the markdown."""
from __future__ import annotations

import contextlib
import copy
import io
import re
import sys
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills/readiness/scripts"))

import render as rd  # noqa: E402
from readiness_model import PILLARS, Facts, load_checks, write_json  # noqa: E402
from tests.readiness.test_render import SHA, fixed_report, pinned_facts, short_facts  # noqa: E402

DEPLOY_SHA = "fedcba9876543210fedcba9876543210fedcba98"
EVIL = '<script>alert(1)</script><img src=x onerror=alert(2)>" onmouseover="x {{FIXES}}'


class Page(HTMLParser):
    """Start tags with their attributes, and the decoded text, of a rendered page."""

    def __init__(self, page: str):
        super().__init__(convert_charrefs=True)
        self.tags: list[tuple[str, dict]] = []
        self.text: list[str] = []
        self.feed(page)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    def handle_startendtag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    def handle_data(self, data):
        self.text.append(data)

    def find(self, tag: str, cls: str | None = None) -> list[dict]:
        return [a for t, a in self.tags if t == tag and (cls is None or cls in (a.get("class") or "").split())]


def row(page: str, cid: str) -> str:
    """The <details> markup of one check."""
    m = re.search(rf'<details class="check" id="{re.escape(cid)}".*?</details>', page, re.S)
    assert m, cid
    return m.group(0)


class HtmlPageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.facts = pinned_facts()
        cls.report = fixed_report(cls.facts)
        cls.page = rd.render_html(cls.facts, cls.report)
        cls.parsed = Page(cls.page)
        _, cls.checks, _, cls.status, _, _, _ = rd._prepare(cls.facts, cls.report, None)

    def test_fragment_for_the_artifact_tool(self):
        self.assertTrue(self.page.startswith("<title>demo readiness review</title>"))
        self.assertNotIn("<!doctype", self.page.lower())
        self.assertNotIn("{{", self.page)  # every placeholder filled
        standalone = rd.render_html(self.facts, self.report, standalone=True)
        self.assertTrue(standalone.startswith("<!doctype html>"))
        self.assertTrue(standalone.endswith(self.page))

    def test_one_row_per_decided_check_with_its_status(self):
        rows = self.parsed.find("details", "check")
        self.assertEqual(len(rows), 34)
        self.assertEqual({r["id"]: r["data-status"] for r in rows}, self.status)
        for r in rows:
            self.assertEqual(r["data-text"], r["data-text"].lower())
            self.assertIn(r["data-pillar"], PILLARS)
        self.assertEqual({r["id"] for r in rows if r["data-blocker"] == "1"},
                         {c["id"] for c in self.checks if c.get("blocker") and c["id"] in self.status})

    def test_verdict_names_the_failing_blockers(self):
        self.assertIn('<p class="verdict">Not ready</p>', self.page)
        self.assertIn('class="placard s-fail"', self.page)
        why = re.search(r'<p class="why">(.*?)</p>', self.page).group(1)
        self.assertEqual(re.findall(r'href="#([^"]+)"', why),
                         ["ops.alerts", "sec.nonroot", "sec.secrets", "rel.probes", "rel.resources"])
        self.assertTrue(why.startswith("Failing blockers: "), why)

    def test_tally_and_pillar_gauges_match_the_markdown_table(self):
        tally = re.search(r'<p class="tally">(.*?)</p>', self.page).group(1)
        self.assertEqual(tally, "34 checks: 8 fail · 6 partial · 2 unknown · 17 pass · 1 n/a. "
                                "6 questions need a person.")
        security = re.search(r'<button type="button" class="gauge" data-pillar="Security".*?</button>',
                             self.page).group(0)
        for n, s in ((4, "fail"), (4, "partial"), (1, "unknown"), (5, "pass")):
            self.assertIn(f"<b>{n}</b> {s}</span>", security)
        self.assertNotIn("n/a", security)  # a status with no checks is left out
        self.assertIn('style="width:100.0%"', security)  # the largest pillar fills the track
        self.assertEqual(len(self.parsed.find("button", "gauge")), len(PILLARS))

    def test_top_fixes_link_to_their_checks(self):
        fixes = re.search(r'<ol class="fixes">.*?</ol>', self.page).group(0)
        self.assertIn('<a class="chk s-fail" href="#ops.alerts">ops.alerts</a>', fixes)
        self.assertIn('<a class="chk s-partial" href="#rel.state">rel.state</a>', fixes)
        report = copy.deepcopy(self.report)
        report["fixes"] = [{"text": f"fix {n}", "checks": ["ops.alerts", "no.such"], "where": "w"} for n in range(7)]
        page = rd.render_html(self.facts, report)
        fixes = re.search(r'<ol class="fixes">.*?</ol>', page).group(0)
        self.assertEqual(fixes.count("<li "), 5)
        self.assertIn("<code>no.such</code>", fixes)  # an id the report did not decide is not linked
        self.assertNotIn('href="#no.such"', fixes)

    def test_failing_and_partial_rows_name_their_fix(self):
        secrets = row(self.page, "sec.secrets")
        self.assertIn("Move demo-secret&#x27;s password to an ExternalSecret", secrets)
        self.assertIn('<span class="src-note">for this repo</span>', secrets)
        netpol = row(self.page, "sec.netpol")
        self.assertIn("Add a NetworkPolicy that selects the pods", netpol)
        self.assertIn('<span class="src-note">catalog default</span>', netpol)
        self.assertNotIn('class="fixline"', row(self.page, "perf.scaling"))  # unknown: nothing to fix yet
        self.assertNotIn('class="fixline"', row(self.page, "ops.ci"))

    def test_rows_sorted_worst_first_within_a_pillar(self):
        ops = re.search(r'<section class="pillar" data-pillar="Operational excellence">.*?</section>', self.page).group(0)
        statuses = re.findall(r'data-status="([^"]+)"', ops)
        self.assertEqual(statuses, sorted(statuses, key=rd.HTML_ORDER.index))
        self.assertIn('<p class="note">CI is solid; alerting is missing.</p>', ops)

    def test_evidence_links_to_the_reviewed_commits(self):
        rel = row(self.page, "rel.resources")
        self.assertIn(f'href="https://github.com/arigsela/kubernetes/blob/{DEPLOY_SHA}/base-apps/demo/deployment.yaml'
                      '#L1-L49"', rel)
        alerts = row(self.page, "ops.alerts")
        self.assertIn(f'href="https://github.com/arigsela/demo/blob/{SHA}/README.md"', alerts)
        self.assertIn("<li><code>SECURITY.md, .github/SECURITY.md</code></li>", alerts)  # where it looked: no link
        restarts = row(self.page, "rel.restarts")
        self.assertIn("<li><code>kubectl get deploy,statefulset,pods -n demo -o json --request-timeout=5s</code></li>",
                      restarts)
        self.assertIn("Decided by</dt><dd>a script, from the collected facts", restarts)
        self.assertIn("checked by verify.py", alerts)

    def test_evidence_items(self):
        doc = {"meta": {"app": {"slug": "o/app", "sha": "a" * 40}, "deploy": {"repo": "o/gitops", "sha": "b" * 40}},
               "facts": [
                   {"id": "x.missing", "source": "app", "value": {"exists": False}, "evidence": "SECURITY.md"},
                   {"id": "x.file", "source": "app", "value": {"exists": True}, "evidence": "src/@app/a b.py"},
                   {"id": "x.dep", "source": "deploy", "value": {}, "evidence": "apps/x/d.yaml:7"},
                   {"id": "x.dup", "source": "deploy", "value": {}, "evidence": "apps/x/d.yaml:7"},
                   {"id": "x.up", "source": "app", "value": {}, "evidence": "../etc/passwd"},
                   {"id": "x.abs", "source": "app", "value": {}, "evidence": "/etc/passwd"},
                   {"id": "x.cmd", "source": "github", "value": {}, "evidence": "gh api repos/o/app"},
                   {"id": "x.url", "source": "app", "value": {}, "evidence": "https://evil.test/x"}]}
        items = rd._evidence_items(Facts(doc), doc["meta"], [f["id"] for f in doc["facts"]] + ["nope", 3])
        self.assertEqual(items, [
            ("SECURITY.md", None),
            ("src/@app/a b.py", None),  # a space is not a repo path the scripts write
            ("apps/x/d.yaml:7", f"https://github.com/o/gitops/blob/{'b' * 40}/apps/x/d.yaml#L7"),
            ("../etc/passwd", None), ("/etc/passwd", None), ("gh api repos/o/app", None),
            ("https://evil.test/x", None)])
        doc["meta"]["app"]["slug"] = "evil.test/x?y"
        self.assertIsNone(rd._gh_link(doc["meta"], "app", "README.md"))
        doc["meta"]["app"] = {"slug": None, "sha": "a" * 40}  # not a github.com remote
        self.assertIsNone(rd._gh_link(doc["meta"], "app", "README.md"))

    def test_well_architected_link(self):
        wa = {c["id"]: c for c in load_checks()}["ops.alerts"]
        self.assertIn(f'<a href="{wa["wa_url"]}">{wa["wa_ref"]}</a>', row(self.page, "ops.alerts"))
        self.assertNotIn("Well-Architected</dt>", row(self.page, "sec.nonroot"))  # wa_ref: none

    def test_header_links_the_commits_and_names_the_refs(self):
        self.assertIn(f'<a href="https://github.com/arigsela/demo/commit/{SHA}"><code>arigsela/demo@0123456</code></a>'
                      " on main", self.page)
        self.assertIn(f'<a href="https://github.com/arigsela/kubernetes/tree/{DEPLOY_SHA}/base-apps/demo">'
                      "<code>arigsela/kubernetes/base-apps/demo@fedcba9</code></a> (Argo targetRevision main)",
                      self.page)
        facts = copy.deepcopy(self.facts)
        facts["meta"]["app"]["on_default_branch"] = False
        facts["meta"]["deploy"]["via"] = "resource:demo/demo-db"
        page = rd.render_html(facts, self.report)
        self.assertIn('<span class="flag">(not the default branch)</span>', page)
        self.assertIn("(Argo targetRevision main; found through resource:demo/demo-db)", page)
        facts["meta"]["deploy"] = None
        facts["meta"]["sources"]["deploy"] = "unavailable: catalog entry lives in the app repo"
        page = rd.render_html(facts, self.report)
        self.assertIn("<dt>Deploy</dt><dd>not found (catalog entry lives in the app repo)</dd>", page)
        self.assertIn('<li class="off"><span class="dot"></span>deploy <span>unavailable: catalog entry lives in the '
                      "app repo</span></li>", page)

    def test_people_and_their_hints(self):
        facts = copy.deepcopy(self.facts)
        for f in facts["facts"]:
            if f["id"] == "deploy.text.base-apps/demo/runbook.md":
                f["value"]["text"] = "# Runbook\nThe on-call rota is in PagerDuty\n"
        page = rd.render_html(facts, self.report)
        people = re.search(r'<section id="people">.*?</section>', page, re.S).group(0)
        self.assertEqual(people.count('<span class="q">'), 6)
        self.assertIn(f'<a href="https://github.com/arigsela/kubernetes/blob/{DEPLOY_SHA}/base-apps/demo/runbook.md#L2">'
                      "<code>base-apps/demo/runbook.md:2</code></a> The on-call rota is in PagerDuty", people)

    def test_cve_cards_as_tiles_under_security(self):
        facts = short_facts(self.facts, criticalFixable=2, kevFixable=0, criticalNoFix=1, imagesNotScanned=1)
        page = rd.render_html(facts, self.report)
        security = re.search(r'<section class="pillar" data-pillar="Security">.*?</section>', page, re.S).group(0)
        self.assertIn('<div class="tile s-fail"><b>2</b><span>critical with a fix</span></div>', security)
        self.assertIn('<div class="tile "><b>0</b><span>actively exploited</span></div>', security)
        self.assertIn('<div class="tile s-partial"><b>1</b><span>image not scanned</span></div>', security)
        self.assertIn("1 critical CVE with no fix yet in the scanned images (not counted)", security)
        err = "none of the 1 running images is in the last weekly scan (2026-10-25)"
        facts = short_facts(self.facts, criticalFixable=err, kevFixable=err, criticalNoFix=err, imagesNotScanned=err)
        self.assertIn(f'<span class="label">Scorecard CVE cards</span> {err}</p>', rd.render_html(facts, self.report))
        self.assertNotIn("Scorecard CVE cards", self.page)

    def test_unverified_banner(self):
        page = rd.render_html(self.facts, self.report, unverified=True)
        self.assertIn('<p class="banner" role="alert">Unverified: verify.py rejected this report.', page)
        self.assertIn("the model, from the facts cited; verify.py rejected this report", row(page, "ops.alerts"))
        self.assertNotIn('class="banner"', self.page)

    def test_no_report(self):
        page = rd.render_html(self.facts, None)
        self.assertIn('<p class="empty-note">None: no report.</p>', page)
        for c in self.checks:
            if c["kind"] == "judgment":
                r = row(page, c["id"])
                self.assertIn('data-status="unknown"', r)
                self.assertIn('<span class="reason">no report</span>', r)

    def test_only_allowed_external_resources(self):
        scripts = self.parsed.find("script")
        self.assertEqual(len(scripts), 1)
        self.assertFalse([s for s in scripts if s.get("src")])
        for link in self.parsed.find("link"):
            self.assertRegex(link["href"], r"^https://fonts\.(googleapis|gstatic)\.com(/|$)")
        for img in self.parsed.find("img"):
            self.fail(f"unexpected image {img}")

    def test_untrusted_text_is_escaped(self):
        facts = copy.deepcopy(self.facts)
        for f in facts["facts"]:
            f["evidence"] = EVIL
            if f["id"] == "backstage.entity":
                f["value"]["owner"] = EVIL
                f["value"]["lifecycle"] = EVIL
        facts["meta"]["entity_ref"] = EVIL
        facts["meta"]["app"]["branch"] = EVIL
        facts["meta"]["deploy"]["folder"] = EVIL
        facts["meta"]["sources"]["cluster"] = EVIL
        checks = copy.deepcopy(load_checks())
        for c in checks:
            c["title"] = EVIL
            c["wa_url"] = 'javascript:alert(1)'
        report = copy.deepcopy(self.report)
        for j in report["judgments"].values():
            j["reason"] = EVIL
        report["fixes"][0].update(text=EVIL, where=EVIL, checks=[EVIL, "ops.alerts"])
        report["pillar_notes"] = {p: EVIL for p in PILLARS}
        report["item_fixes"] = {"sec.secrets": EVIL}
        page = rd.render_html(facts, report, checks=checks)
        parsed = Page(page)
        self.assertEqual(len(parsed.find("script")), 1)  # only the template's own
        self.assertFalse(parsed.find("img"))
        for tag, attrs in parsed.tags:
            self.assertFalse([a for a in attrs if a.startswith("on")], (tag, attrs))
            self.assertFalse(str(attrs.get("href", "")).startswith("javascript:"), (tag, attrs))
        text = "".join(parsed.text)
        self.assertIn("<script>alert(1)</script>", text)  # shown as text
        self.assertEqual(page.count("{{FIXES}}"), text.count("{{FIXES}}"))  # never expanded as a placeholder
        self.assertGreater(text.count("{{FIXES}}"), 5)
        self.assertEqual(len(parsed.find("details", "check")), 34)
        self.assertEqual(sum(1 for t in parsed.text if t == "Verdict"), 1)

    def test_secret_looking_values_are_masked(self):
        token = "ghp_" + "A1b2C3d4" * 5
        facts = copy.deepcopy(self.facts)
        for f in facts["facts"]:
            if f["id"] == "deploy.workload.Deployment/demo":
                f["evidence"] = f"postgres://admin:hunter2@db:5432/x {token}"
        report = copy.deepcopy(self.report)
        report["judgments"]["ops.alerts"]["reason"] = f"token {token} found"
        page = rd.render_html(facts, report)
        self.assertNotIn(token, page)
        self.assertNotIn("ghp_", page)
        self.assertNotIn("hunter2", page)
        self.assertIn("token [REDACTED] found", page)
        self.assertIn("postgres://[REDACTED]@db:5432/x", page)

    def test_secret_looking_paths_are_never_linked(self):
        """A path that holds a token is masked in the text; its link would carry the token whole, so it has none."""
        token = "ghp_" + "A1b2C3d4" * 5
        facts = copy.deepcopy(self.facts)
        for f in facts["facts"]:
            if f["id"] == "deploy.workload.Deployment/demo":
                f["evidence"] = f"base-apps/demo/{token}.yaml:1-49"  # a repo path the pointer pattern accepts
            if f["id"] == "deploy.text.base-apps/demo/runbook.md":
                f["id"] = f"deploy.text.base-apps/{token}/runbook.md"
                f["value"]["text"] = "# Runbook\non-call: see PagerDuty\n"
        facts["meta"]["deploy"]["folder"] = f"base-apps/{token}"
        page = rd.render_html(facts, self.report)
        self.assertNotIn(token, page)
        self.assertNotIn("ghp_", page)
        self.assertIn("<code>base-apps/demo/[REDACTED].yaml:1-49</code>", page)
        self.assertIn("<code>base-apps/[REDACTED]/runbook.md:2</code> on-call: see PagerDuty", page)  # hint, unlinked
        self.assertIn("<dt>Deploy</dt><dd><code>arigsela/kubernetes/base-apps/[REDACTED]@fedcba9</code> (", page)
        meta = facts["meta"]
        self.assertIsNone(rd._gh_link(meta, "deploy", f"base-apps/{token}.yaml"))
        self.assertIsNotNone(rd._gh_link(meta, "deploy", "base-apps/demo/deployment.yaml"))

    def test_secret_looking_repo_names_are_never_linked(self):
        """A slug or catalog URL holding a token gets no link anywhere: commit, tree, evidence, hints, docs."""
        token = "ghp_" + "A1b2C3d4" * 5
        facts = copy.deepcopy(self.facts)
        facts["meta"]["app"]["slug"] = f"arigsela/{token}"
        facts["meta"]["deploy"]["repo"] = f"arigsela/{token}"
        for f in facts["facts"]:
            if f["id"] == "deploy.text.base-apps/demo/runbook.md":
                f["value"]["text"] = "# Runbook\non-call: see PagerDuty\n"
        checks = copy.deepcopy(load_checks())
        for c in checks:
            if c["id"] == "ops.alerts":
                c["wa_url"] = f"https://docs.aws.amazon.com/{token}.html"
        page = rd.render_html(facts, self.report, checks=checks)
        self.assertNotIn(token, page)
        self.assertNotIn("ghp_", page)
        hrefs = [a.get("href", "") for a in Page(page).find("a")]
        self.assertFalse([h for h in hrefs if h.startswith("https://github.com/")], hrefs)  # no repo is linkable
        self.assertIn("<code>arigsela/[REDACTED]@0123456</code> on main", page)
        self.assertIn("<code>base-apps/demo/runbook.md:2</code> on-call: see PagerDuty", page)
        self.assertIn("<dt>Well-Architected</dt><dd>OPS08-BP04</dd>", row(page, "ops.alerts"))  # ref kept, unlinked
        for bad in (f"https://github.com/o/{token}/commit/x", f"https://x.test/?p=postgres://u:pw@h"):
            self.assertEqual(rd._code_link("x", bad), "<code>x</code>")
        self.assertIn('href="https://github.com/o/r/blob/', rd._code_link("x", "https://github.com/o/r/blob/a/b"))


class HtmlCliTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.facts = pinned_facts()
        cls.report = fixed_report(cls.facts)

    def run_main(self, d: str, *args: str) -> tuple[int, str]:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = rd.main(["--out", d, *args])
        return code, buf.getvalue()

    def test_html_flag_writes_the_page_and_names_it_last(self):
        with tempfile.TemporaryDirectory() as d:
            write_json(Path(d) / "facts.json", self.facts)
            write_json(Path(d) / "report.json", self.report)
            code, out = self.run_main(d, "--html")
            self.assertEqual(code, 0)
            page = Path(d) / "report.html"
            short = rd.render_short(self.facts, self.report, full_path=Path(d) / "report.md")
            self.assertEqual(out, short + f"HTML report: {page}\n")  # the terminal report is unchanged
            self.assertEqual(page.read_text(), rd.render_html(self.facts, self.report))
            code, _ = self.run_main(d, "--html", "--standalone", "--unverified")
            self.assertEqual(code, 0)
            self.assertTrue(page.read_text().startswith("<!doctype html>"))
            self.assertIn('class="banner"', page.read_text())

    def test_no_page_without_the_flag(self):
        with tempfile.TemporaryDirectory() as d:
            write_json(Path(d) / "facts.json", self.facts)
            code, out = self.run_main(d)
            self.assertEqual(code, 0)
            self.assertFalse((Path(d) / "report.html").exists())
            self.assertNotIn("HTML report:", out)
            err = io.StringIO()
            with contextlib.redirect_stderr(err), self.assertRaises(SystemExit):
                self.run_main(d, "--standalone")
            self.assertIn("--standalone needs --html", err.getvalue())

    def test_rule_statuses_recomputed_from_facts(self):
        with tempfile.TemporaryDirectory() as d:
            write_json(Path(d) / "facts.json", self.facts)
            write_json(Path(d) / "results.json", {"checks": [{"id": "sec.nonroot", "kind": "rule", "status": "pass",
                                                              "reason": "TAMPERED"}]})
            self.run_main(d, "--html")
            page = (Path(d) / "report.html").read_text()
        self.assertIn('data-status="fail"', row(page, "sec.nonroot"))
        self.assertNotIn("TAMPERED", page)


if __name__ == "__main__":
    unittest.main()
