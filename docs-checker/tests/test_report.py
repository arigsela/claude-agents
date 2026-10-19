from docs_checker.ledger import RunSummary
from docs_checker.report import ZWSP, render_report, slack_text
from docs_checker.state import Claim, DocOutcome, Finding, Window

_D = dict


def summary(**kw):
    base = _D(
        run_id="r1", context_id="c", outcome="verified", calls=3, unknown_calls=0,
        uncached_input=1, cache_write=0, cache_read=0, output=1, cost_usd_known=0.12,
        workload_cost_usd=0.12, cash_cost_usd=0.05, reserved_unsettled_usd=0.0,
        complete=True, cache_hit_rate=None, by_node={}, rate_card_version="v",
    )  # fmt: skip
    return RunSummary(**{**base, **kw})


def finding(doc="a.md", line=3, conf=0.9, claim="uses nginx 1.2", **kw):
    c = Claim(doc=doc, line_start=line, line_end=line, kind="version", text=claim, values=["1.2"])
    base = _D(
        id=f"{doc}{line}", instance="i", commit="c" * 40, doc=doc, line_start=line,
        line_end=line, claim=c, verdict="stale",
        evidence=Window(source="apps/x/values.yaml", start=4, end=6, text="tag: 1.3"),
        evidence_hash="hash123", confidence=conf, old_text="1.2", replacement="1.3",
    )  # fmt: skip
    return Finding(**{**base, **kw})


def outcome(doc, findings=(), status="checked", **kw):
    return DocOutcome(doc=doc, commit="c" * 40, status=status, findings=list(findings), **kw)


def render(outs, **kw):
    return render_report(outs, run_id="run-1", commit="c" * 40, summary=summary(), **kw)


def test_slack_text_fits_with_40_findings_and_states_omissions():
    fs = [finding(doc=f"d{i}.md", conf=0.7 + i / 1000, claim="x" * 300) for i in range(40)]
    _, rep = render([outcome("all.md", fs)])
    text = slack_text(rep)
    assert len(text) <= 3000
    assert all(len(line) <= 200 for line in text.splitlines())
    listed = [line for line in text.splitlines() if line.startswith("- ")]
    assert len(listed) <= 15
    assert f"+{40 - len(listed)} more; full report in the job log (run `run-1`)" in text


def test_slack_no_omission_line_when_everything_fits():
    _, rep = render([outcome("a.md", [finding()])])
    text = slack_text(rep)
    assert "more;" not in text
    assert "coverage incomplete" not in text


def test_coverage_incomplete_when_doc_failed_or_truncated():
    _, rep = render([outcome("a.md", status="incomplete", reason="budget")])
    assert "coverage incomplete" in slack_text(rep)
    _, rep = render([outcome("a.md")], notes={"truncated": True})
    assert "coverage incomplete" in slack_text(rep)
    _, rep = render([outcome("a.md", status="skipped-budget")])
    assert "coverage incomplete" in slack_text(rep)


def test_slack_escapes_mentions_and_brackets():
    evil = "see <!channel> <@U123> @here & <https://evil.example|click> https://x.example"
    _, rep = render([outcome("a.md", [finding(claim=evil, replacement="<!here> @all")])])
    text = slack_text(rep)
    assert "<" not in text and ">" not in text
    assert "&lt;!channel&gt;" in text and "&amp;" in text
    assert "@here" not in text and "@all" not in text
    assert "@" + ZWSP + "here" in text
    assert "`" in text and "https://x.example" in text.replace("`", "")  # only inside code


def test_sorted_by_confidence():
    fs = [
        finding(doc="b.md", conf=0.8),
        finding(doc="a.md", conf=0.8),
        finding(doc="z.md", conf=0.95),
    ]
    _, rep = render([outcome("m.md", fs)])
    assert [f.doc for f in rep.findings] == ["z.md", "a.md", "b.md"]
    lines = [x for x in slack_text(rep).splitlines() if x.startswith("- ")]
    assert "z.md" in lines[0] and "a.md" in lines[1] and "b.md" in lines[2]


def test_report_lists_evidence_hash_and_commit():
    md, _ = render([outcome("a.md", [finding()])])
    assert "a.md:3" in md and "c" * 12 in md
    assert "apps/x/values.yaml:4-6" in md
    assert "hash123" in md and "`1.3`" in md and "stale" in md and "uses nginx 1.2" in md


def test_report_redacts_evidence():
    ev = Window(source="s.yaml", start=1, end=2, text="password: hunter2hunter2\nok: 1")
    md, _ = render([outcome("a.md", [finding(evidence=ev)])])
    assert "hunter2" not in md and "[REDACTED]" in md


def test_lower_bound_marker_when_cost_incomplete():
    s = summary(complete=False)
    _, rep = render_report([outcome("a.md")], run_id="r", commit="c", summary=s)
    assert "(lower bound)" in slack_text(rep)
    assert "workload" in slack_text(rep) and "cash" in slack_text(rep)
    _, rep = render([outcome("a.md")])
    assert "lower bound" not in slack_text(rep)


def test_withheld_fix_and_carried_sections():
    w = finding(replacement="", fix_withheld="changes link target")
    k = finding(doc="k.md", carried=True)
    md, rep = render([outcome("a.md", [w]), outcome("k.md", [k], status="unchanged")])
    assert "Fix withheld: `changes link target`" in md
    assert "## Still open" in md
    assert rep.counts["fix_withheld"] == 1 and rep.counts["carried"] == 1
    assert "fix withheld" in slack_text(rep)
    assert w.action_digest == finding(replacement="", fix_withheld="other").action_digest


def test_needs_look_separate_and_counted():
    _, rep = render([outcome("a.md", [finding(needs_look=True, conf=0.5)])])
    assert rep.findings == [] and len(rep.needs_look) == 1
    assert "+1 more" in slack_text(rep)


def _check_lines(text):
    import re

    for line in text.splitlines():
        assert len(line) <= 200
        assert line.count("`") % 2 == 0
        assert not re.search(r"&(?!amp;|lt;|gt;)", line)


def test_slack_lines_safe_with_hostile_paths():
    nasty = "<&>" * 84  # 252 chars, 3 entities each when escaped
    astral = "\U0001d54f" * 120 + "&" * 80
    fs = [
        finding(doc=nasty, conf=0.95, fix_withheld="x" * 90, replacement=""),
        finding(doc=astral + ".md", conf=0.9, claim="a\r\nb\r\n" * 60),
        finding(doc="ok.md", conf=0.8),
    ]
    _, rep = render([outcome("m.md", fs + [finding(doc=f"d{i}.md") for i in range(30)])])
    text = slack_text(rep)
    _check_lines(text)
    assert len(text) <= 3000
    assert "more; full report in the job log (run `run-1`)" in text.splitlines()[-1]
    assert "\r" not in text


def test_markdown_has_no_links_from_untrusted_fields():
    from markdown_it import MarkdownIt

    evil = "[click](http://evil.example) <img src=x> ![i](http://e)"
    f = finding(claim=evil, replacement="", fix_withheld=evil, old_text=evil)
    md, _ = render_report([outcome("a.md", [f])], run_id=evil, commit="c" * 40, summary=summary())
    toks = []
    for t in MarkdownIt("commonmark").parse(md):
        toks += [t] + list(t.children or [])
    kinds = {t.type for t in toks}
    assert not kinds & {"link_open", "image", "html_inline", "html_block"}


def test_only_the_weekly_run_is_titled_weekly():
    """An on-demand check (the kagent UI, ask-hk) was titled "Weekly docs check"."""
    md, rep = render_report([outcome("a.md")], run_id="r", commit="c" * 40, summary=summary())
    assert md.startswith("# Docs check (run ") and slack_text(rep).startswith("Docs check at ")
    md, rep = render_report(
        [outcome("a.md")], run_id="r", commit="c" * 40, summary=summary(), scheduled=True
    )
    assert md.startswith("# Weekly docs check (run ")
    assert slack_text(rep).startswith("Weekly docs check at ")
