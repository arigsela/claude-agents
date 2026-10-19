"""Report rendering: per-doc outcomes become the Markdown report and the Slack text.

The Markdown report is the full record (A2A task, job log). The Slack text is a
bounded digest: the n8n webhook cuts bodies at 3000 characters, so the footer that
says what was left out must always fit, and findings are added only while they do.

Escaping for Slack (mrkdwn): ``&``, ``<`` and ``>`` become ``&amp;``, ``&lt;`` and
``&gt;``. That alone stops every control sequence (``<@U123>``, ``<!here>``,
``<!channel>``, ``<https://...|label>``), because Slack only parses them inside
angle brackets. A plain ``@here`` or ``@channel`` can still ping when the webhook
posts with ``link_names``, so a zero-width space follows every ``@``. Untrusted text
(doc paths, claims, replacements, reasons) is also put in a code span, where Slack
does not auto-link bare URLs; backticks inside it are replaced so it cannot be
closed early. Everything passes ``redact`` before it is escaped or measured.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

from pydantic import BaseModel, Field

from docs_checker.ledger import RunSummary
from docs_checker.redact import redact
from docs_checker.state import DocOutcome, Finding

ZWSP = "\u200b"
_WS = re.compile(r"\s+")
_EVIDENCE_CHARS = 600


class Report(BaseModel):
    run_id: str
    commit: str
    findings: list[Finding] = Field(default_factory=list)  # new, confident
    needs_look: list[Finding] = Field(default_factory=list)
    carried: list[Finding] = Field(default_factory=list)  # still open, from memory
    failed: list[str] = Field(default_factory=list)  # "doc: reason"
    incomplete: list[str] = Field(default_factory=list)
    skipped_budget: list[str] = Field(default_factory=list)
    skipped_sources: list[str] = Field(default_factory=list)
    truncated: bool = False
    dismissal_errors: list[str] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)
    refused: int = 0
    workload_usd: float = 0.0
    cash_usd: float = 0.0
    complete_cost: bool = True
    notes: list[str] = Field(default_factory=list)

    @property
    def coverage_incomplete(self) -> bool:
        return bool(
            self.failed
            or self.incomplete
            or self.skipped_budget
            or self.skipped_sources
            or self.truncated
        )


def _order(f: Finding) -> tuple[float, str, int]:
    return (-f.confidence, f.doc, f.line_start)


def _one_line(text: str) -> str:
    return _WS.sub(" ", redact(text)).strip()


def _code(text: str) -> str:
    """Inline code span that the text cannot close."""
    return "`" + _one_line(text).replace("`", "'") + "`"


def _reasoned(outcome: DocOutcome) -> str:
    return f"{outcome.doc}: {outcome.reason}" if outcome.reason else outcome.doc


def render_report(
    outcomes: Iterable[DocOutcome],
    *,
    run_id: str,
    commit: str,
    summary: RunSummary,
    notes: Mapping[str, Any] | None = None,
) -> tuple[str, Report]:
    """Markdown report plus the structured ``Report``.

    ``notes`` carries what only the caller knows: ``truncated`` (bool),
    ``skipped_sources`` and ``dismissal_errors`` (lists of strings), ``lines``
    (free-text lines shown under Notes).
    """
    notes = notes or {}
    outs = sorted(outcomes, key=lambda o: o.doc)
    findings: list[Finding] = []
    needs_look: list[Finding] = []
    carried: list[Finding] = []
    for o in outs:
        for f in o.findings:
            (carried if f.carried else needs_look if f.needs_look else findings).append(f)
    findings.sort(key=_order)
    needs_look.sort(key=_order)
    carried.sort(key=_order)
    by_status: dict[str, int] = {}
    for o in outs:
        by_status[o.status] = by_status.get(o.status, 0) + 1
    all_found = findings + needs_look + carried
    counts = {
        "docs": len(outs),
        **{f"docs_{k.replace('-', '_')}": v for k, v in sorted(by_status.items())},
        "findings": len(findings),
        "needs_look": len(needs_look),
        "carried": len(carried),
        "fix_withheld": sum(1 for f in all_found if f.fix_withheld),
    }
    report = Report(
        run_id=_one_line(run_id),
        commit=commit,
        findings=findings,
        needs_look=needs_look,
        carried=carried,
        failed=[_one_line(_reasoned(o)) for o in outs if o.status == "failed"],
        incomplete=[_one_line(_reasoned(o)) for o in outs if o.status == "incomplete"],
        skipped_budget=[_one_line(_reasoned(o)) for o in outs if o.status == "skipped-budget"],
        skipped_sources=[_one_line(str(s)) for s in notes.get("skipped_sources", [])],
        truncated=bool(notes.get("truncated", False)),
        dismissal_errors=[_one_line(str(s)) for s in notes.get("dismissal_errors", [])],
        counts=counts,
        refused=sum(o.refused for o in outs),
        workload_usd=summary.workload_cost_usd,
        cash_usd=summary.cash_cost_usd,
        complete_cost=summary.complete,
        notes=[_one_line(str(s)) for s in notes.get("lines", [])],
    )
    return redact(_markdown(report)), report


def _spend(report: Report) -> str:
    bound = "" if report.complete_cost else " (lower bound)"
    return f"workload ${report.workload_usd:.4f}{bound}, cash ${report.cash_usd:.4f}{bound}"


def _fence(text: str) -> str:
    text = redact(text)
    ticks = max((len(m) for m in re.findall(r"`+", text)), default=0)
    fence = "`" * max(3, ticks + 1)
    return f"{fence}\n{text}\n{fence}"


def _finding_md(f: Finding) -> list[str]:
    where = f"{f.doc}:{f.line_start}" + (f"-{f.line_end}" if f.line_end != f.line_start else "")
    out = [
        f"### {_code(where)} at `{f.commit[:12]}`: {f.verdict} (confidence {f.confidence:.2f})",
        "",
        f"- Claim: {_code(f.claim.text)}",
    ]
    if f.evidence:
        e = f.evidence
        out.append(f"- Evidence: {_code(f'{e.source}:{e.start}-{e.end}')}")
        quote = redact(e.text)[:_EVIDENCE_CHARS]
        out += ["", _fence(quote), ""]
    else:
        out.append("- Evidence: none found")
    out.append(f"- Old text: {_code(f.old_text)}")
    if f.fix_withheld:
        out.append(f"- Fix withheld: {_one_line(f.fix_withheld)}")
    else:
        out.append(f"- Replacement: {_code(f.replacement)}")
    out += [f"- Evidence hash: `{f.evidence_hash}`", f"- Action digest: `{f.action_digest}`", ""]
    return out


def _markdown(r: Report) -> str:
    c = r.counts
    lines = [
        f"# Weekly docs check (run {r.run_id})",
        "",
        (
            f"Commit `{r.commit}`. {c['docs']} docs; {c['findings']} findings, "
            f"{c['needs_look']} need a look, {c['carried']} still open, "
            f"{c['fix_withheld']} fixes withheld; {r.refused} refused."
        ),
        f"Spend: {_spend(r)}.",
    ]
    if r.coverage_incomplete:
        lines.append("**Coverage incomplete.**")
    lines.append("")

    def section(title: str, items: list[Finding]) -> None:
        if items:
            lines.extend([f"## {title}", ""])
            for f in items:
                lines.extend(_finding_md(f))

    section("Findings", r.findings)
    section("Needs a look", r.needs_look)
    section("Still open", r.carried)

    def plain(title: str, items: list[str]) -> None:
        if items:
            lines.extend([f"## {title}", ""] + [f"- {_code(i)}" for i in items] + [""])

    plain("Failed", r.failed)
    plain("Incomplete", r.incomplete)
    plain("Skipped (budget)", r.skipped_budget)
    plain("Skipped sources", r.skipped_sources)
    plain("Dismissal errors", r.dismissal_errors)
    if r.truncated:
        lines += ["## Truncated", "", "The doc list was truncated at the discovery cap.", ""]
    plain("Notes", r.notes)
    return "\n".join(lines).rstrip() + "\n"


def _esc(text: str) -> str:
    """Slack mrkdwn escaping, and no bare ``@`` that could be read as a mention."""
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return text.replace("@", "@" + ZWSP)


def _slack_code(text: str) -> str:
    return "`" + _esc(_one_line(text).replace("`", "'")) + "`"


def _fit(make, text: str, max_line: int) -> str:
    """``make(text)``, with the text shortened (ellipsis) until it fits ``max_line``."""
    text = _one_line(text)
    if len(make(text)) <= max_line:
        return make(text)
    while text and len(make(text + "\u2026")) > max_line:
        text = text[:-1]
    return make(text.rstrip() + "\u2026")


def _slack_finding(f: Finding, max_line: int) -> str:
    where = _slack_code(f"{f.doc}:{f.line_start}")
    prefix = f"- {f.confidence:.2f} {where} {f.verdict}: "
    if f.fix_withheld:
        reason = _fit(_slack_code, f.fix_withheld, 70)
        tail = f" (fix withheld: {reason})"
    elif f.replacement:
        tail = f" fix {_fit(_slack_code, f.replacement, 70)}"
    else:
        tail = ""
    room = max_line - len(prefix) - len(tail)
    room = max(room, 20)  # a long path: the claim is the part to give up
    claim = _fit(_slack_code, f.claim.text, room)
    return _fit_line(prefix + claim + tail, max_line)


def _fit_line(line: str, max_line: int) -> str:
    return line if len(line) <= max_line else line[: max_line - 1] + "…"


def slack_text(
    report: Report, limit: int = 3000, max_findings: int = 15, max_line: int = 200
) -> str:
    """The Slack body: counts, spend, the top findings, and what was left out."""
    c = report.counts
    head = [
        _fit_line(
            f"Weekly docs check at {_esc(report.commit[:12])}: {c.get('findings', 0)} findings, "
            f"{c.get('needs_look', 0)} need a look, {c.get('carried', 0)} still open"
            + (f", {c['fix_withheld']} fixes withheld" if c.get("fix_withheld") else ""),
            max_line,
        ),
        _fit_line(f"Spend: {_spend(report)}", max_line),
    ]
    if report.coverage_incomplete:
        head.append("coverage incomplete")
    total_items = len(report.findings) + len(report.needs_look) + len(report.carried)

    def footer(listed: int) -> list[str]:
        left = total_items - listed
        if left <= 0:
            return []
        return [
            _fit_line(
                f"+{left} more; full report in the job log (run {_slack_code(report.run_id)})",
                max_line,
            )
        ]

    lines = list(head)
    listed = 0
    for f in sorted(report.findings, key=_order)[:max_findings]:
        line = _slack_finding(f, max_line)
        candidate = lines + [line]
        if len("\n".join(candidate + footer(listed + 1))) > limit:
            break
        lines = candidate
        listed += 1
    out = redact("\n".join(lines + footer(listed)))
    if len(out) > limit:  # only a pathological header; the footer is kept
        out = out[: limit - 1] + "…"
    return out
