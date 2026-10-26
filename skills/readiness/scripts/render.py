#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6", "pathspec>=0.12,<1"]
# ///
"""readiness: facts.json + report.json -> the markdown report printed in the terminal (spec §7.7).

Usage: render.py --out DIR [--unverified] [--full]
Reads DIR, saves the full report as DIR/report.md and prints the short one (or the full one with --full).

Prints only facts, checks and report content. Rule statuses, reasons and ORR hints are recomputed from facts.json
and checks.yaml (evaluate.py), never read from results.json, so a hand-edited results.json cannot change them.
A missing report renders the judgment checks as unknown ("no report").
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from evaluate import evaluate, verdict  # noqa: E402
from readiness_model import PILLARS, STATUSES, Facts, SOURCES, load_checks, read_json  # noqa: E402

BANNER = "> UNVERIFIED: verify.py rejected this report; read the evidence before acting on it."
CVE_NOTE = ("CVEs other than fixable criticals and actively exploited (CISA KEV) ones are not counted, and a week "
            "the scan could not reach the KEV feed reads as 0 exploited.")
EVIDENCE_PER_CHECK = 3
MAX_FIXES = 5
ORDER = ("fail", "partial", "unknown")


def _d(v) -> dict:
    return v if isinstance(v, dict) else {}


def _l(v) -> list:
    return v if isinstance(v, list) else []


def _one_line(v) -> str:
    return " ".join(str(v).split())


def _s(v, default: str = "") -> str:
    """A non-empty string from untrusted data, collapsed to one line; else the default."""
    return _one_line(v) if isinstance(v, str) and v.strip() else default


def _sha7(v) -> str:
    return _s(v)[:7] or "unknown"


def _code(v) -> str:
    """Untrusted text as a one-line code span; backticks inside would close it early."""
    return "`" + _one_line(v).replace("`", "'") + "`"


def _header(doc: dict, f: Facts) -> list[str]:
    meta = _d(doc.get("meta"))
    app, deploy = _d(meta.get("app")), _d(meta.get("deploy"))
    entity = _d(f.value("backstage.entity"))
    default = app.get("on_default_branch")
    on_default = "yes" if default is True else "no" if default is False else "unknown"
    lines = [f"owner: {_s(entity.get('owner'), 'unknown')}, lifecycle: {_s(entity.get('lifecycle'), 'unknown')}",
             f"app: {_s(app.get('slug'), 'unknown')}@{_sha7(app.get('sha'))} "
             f"({_s(app.get('branch'), 'unknown')}, on default branch: {on_default})"]
    if deploy:
        rev = _s(_d(f.value("deploy.application")).get("target_revision"), "unknown")
        ref = _s(deploy.get("ref"))  # what was read: --deploy-ref, else targetRevision, else the default branch
        refs = f"reviewed ref {ref}; Argo targetRevision {rev}" if ref and ref != rev else f"Argo targetRevision {rev}"
        lines.append(f"deploy: {_s(deploy.get('repo'), 'unknown')}/{_s(deploy.get('folder'), '')}"
                     f"@{_sha7(deploy.get('sha'))} ({refs})")
    else:
        reason = _one_line(f.status("deploy")).removeprefix("unavailable: ")
        lines.append(f"deploy: not found ({reason})")
    stamps = sorted(_one_line(_d(t["value"]).get("timestamp")) for t in f.prefix("scorecard.")
                    if _d(t.get("value")).get("timestamp"))
    lines.append(f"scorecard: {stamps[-1] if stamps else _one_line(f.status('scorecard'))}")
    srcs = ", ".join(f"{s} {'ok' if f.ok(s) else _one_line(f.status(s))}" for s in SOURCES)
    lines.append(f"sources: {srcs}")
    return lines


def _resolve(checks: list[dict], report: dict | None) -> tuple[dict[str, str], dict[str, str]]:
    """(status, reason) per check id; person checks are left out."""
    judgments = _d(_d(report).get("judgments"))
    status, reason = {}, {}
    for c in checks:
        cid, kind = c.get("id"), c.get("kind")
        if kind == "person":
            continue
        if kind == "judgment":
            j = _d(judgments.get(cid))
            s, r = j.get("status"), j.get("reason")
            if s not in STATUSES:
                s, r = "unknown", "no report" if report is None else "not judged in the report"
        else:
            s, r = c.get("status"), c.get("reason")
            if s not in STATUSES:
                s = "unknown"
        status[cid], reason[cid] = s, _one_line(r) if r else ""
    return status, reason


def _evidence(f: Facts, ids) -> list[str]:
    out: list[str] = []
    for i in _l(ids):
        t = f.get(i) if isinstance(i, str) else None
        ev = _s(t.get("evidence")) if t else ""
        if ev and ev not in out:
            out.append(ev)
        if len(out) == EVIDENCE_PER_CHECK:
            break
    return out


def _int(v) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) else None


# The portal's Scorecard CVE cards (running images), shown next to sec.cve (rendered images): (id, as a count, alone)
CVE_CARDS = (("criticalFixable", "critical with a fix", "critical with a fix"),
             ("kevFixable", "actively exploited with a fix", "actively exploited"),
             ("criticalNoFix", "critical with no fix", "critical with no fix"),
             ("imagesNotScanned", "image not scanned", "images not scanned"))


def _scorecard_cve_line(f: Facts, evidence: bool) -> str | None:
    cards = {mid: f.get(f"scorecard.cve.{mid}") for mid, _, _ in CVE_CARDS}
    present = [t for t in cards.values() if t]
    if not present:
        return None
    values = {mid: _int(_d(t["value"]).get("value")) if t else None for mid, t in cards.items()}
    if all(v is None for v in values.values()):
        errors = list(dict.fromkeys(_s(_d(t["value"]).get("error"), "no value") for t in present))
        text = "; ".join(errors)
    else:
        parts = []
        for mid, counted, alone in CVE_CARDS:
            n = values[mid]
            if n is None:
                parts.append(f"{alone}: no value")
            elif mid == "imagesNotScanned":
                parts.append(f"{n} image{'' if n == 1 else 's'} not scanned")
            else:
                parts.append(f"{n} {counted}")
        text = " · ".join(parts)
    line = f"Scorecard CVE cards: {text}"
    return line + (" " + _code(present[0].get("evidence", "")) if evidence else "")


def _awareness(f: Facts, evidence: bool = True) -> dict[str, list[str]]:
    """Lines shown under a pillar whatever the checks decided: context that is not counted."""
    out: dict[str, list[str]] = {}
    card_line = _scorecard_cve_line(f, evidence)
    if card_line:
        out.setdefault("Security", []).append(card_line)
    cve = f.get("backstage.cve")
    n = _int(_d(_d(cve["value"]).get("totals")).get("critical_no_fix")) if cve else None
    if n:
        noun = "CVE" if n == 1 else "CVEs"
        out.setdefault("Security", []).append(
            f"Awareness: {n} critical {noun} with no fix yet in the scanned images (not counted)"
            + (" " + _code(cve.get("evidence", "")) if evidence else ""))
    return out


def _prepare(facts_doc: dict, report: dict | None, checks: list[dict] | None):
    """(facts, decided checks, report or None, status, reason, judgments, title) shared by both reports."""
    f = Facts(facts_doc)
    checks = evaluate(facts_doc, load_checks() if checks is None else checks)["checks"]
    report = report if isinstance(report, dict) else None
    status, reason = _resolve(checks, report)
    judg = _d(_d(report).get("judgments"))
    meta = _d(facts_doc.get("meta"))
    title = _s(meta.get("entity_ref")) or _s(_d(meta.get("app")).get("slug"), "unknown")
    return f, checks, report, status, reason, judg, title


def _fix(c: dict, status: str, report: dict | None) -> str:
    """The fix shown on a failing or partial line: the report's specific one, else the catalog's generic one."""
    if status not in ("fail", "partial"):
        return ""
    return _s(_d(_d(report).get("item_fixes")).get(c.get("id"))) or _s(c.get("fix"))


def _clip(text: str, n: int) -> str:
    """One line of at most n characters, cut at a word boundary."""
    text = _one_line(text)
    if len(text) <= n:
        return text
    cut = text[:n - 1]
    return (cut.rsplit(" ", 1)[0] if " " in cut else cut).rstrip(" ,;:") + "…"


_POINTER = re.compile(r"[A-Za-z0-9_.@/-]+(:\d+(-\d+)?)?")


def _pointer(f: Facts, ids) -> str | None:
    """The first evidence that is a repo path (a file, maybe with lines): not a command, URL or list."""
    for ev in _evidence(f, ids):
        if _POINTER.fullmatch(ev):  # spaces, commas and "scheme://" never match
            return ev
    return None


def render_short(facts_doc: dict, report: dict | None, unverified: bool = False, checks: list[dict] | None = None,
                 full_path: Path | None = None) -> str:
    """The default terminal report: header, verdict and why, top fixes, the pillar table, one line per finding.
    Titles, pillar notes, keyword hints and command evidence stay in the full report (render)."""
    f, checks, report, status, reason, judg, title = _prepare(facts_doc, report, checks)
    meta = _d(facts_doc.get("meta"))
    app, deploy = _d(meta.get("app")), _d(meta.get("deploy"))
    entity = _d(f.value("backstage.entity"))

    out: list[str] = [BANNER, ""] if unverified else []
    out += [f"# Production readiness: {title}", ""]
    branch = _s(app.get("branch"), "unknown")
    if app.get("on_default_branch") is False:
        branch += ", not the default branch"
    head = [_s(entity.get("owner"), "no owner"), _s(entity.get("lifecycle"), "no lifecycle"),
            f"app {_s(app.get('slug'), 'unknown')}@{_sha7(app.get('sha'))} ({branch})"]
    if deploy:
        head.append(f"deploy {_s(deploy.get('repo'), 'unknown')}/{_s(deploy.get('folder'), '')}"
                    f"@{_sha7(deploy.get('sha'))}")
    else:
        head.append(f"deploy not found ({_one_line(f.status('deploy')).removeprefix('unavailable: ')})")
    out.append(" · ".join(head) + "  ")
    bad = [f"{s} {_one_line(f.status(s))}" for s in SOURCES if not f.ok(s)]
    out.append("Sources: " + ("; ".join(bad) if bad else "all ok"))

    word = verdict(checks, status)
    blockers = [c for c in checks if c.get("blocker") and c.get("id") in status]
    why = ""
    if word == "Not ready":
        why = " (failing blockers: " + ", ".join(c["id"] for c in blockers if status[c["id"]] == "fail") + ")"
    elif any(status[c["id"]] == "unknown" for c in blockers):
        why = " (unknown blockers: " + ", ".join(c["id"] for c in blockers if status[c["id"]] == "unknown") + ")"
    out += ["", f"**Verdict: {word}**{why}", "", "## Top fixes", ""]
    fixes = [x for x in _l(_d(report).get("fixes")) if isinstance(x, dict)][:MAX_FIXES]
    for n, x in enumerate(fixes, 1):
        ids = ", ".join(_one_line(c) for c in _l(x.get("checks")))
        out.append(f"{n}. {_clip(x.get('text', ''), 120)} ({_clip(ids, 50)}) — {_clip(x.get('where', ''), 60)}")
    if not fixes:
        out.append("None listed." if report else "None: no report.")

    out += ["", "| Pillar | pass | partial | fail | unknown | n/a |", "|---|---|---|---|---|---|"]
    for p in PILLARS:
        counts = [sum(1 for c in checks if c.get("pillar") == p and status.get(c.get("id")) == s) for s in STATUSES]
        out.append(f"| {p} | " + " | ".join(str(n) for n in counts) + " |")

    out += ["", "## Findings"]
    aware = _awareness(f, evidence=False)
    for p in PILLARS:
        out += ["", f"**{p}**", ""]
        mine = [c for c in checks if c.get("pillar") == p and c.get("id") in status]
        for s in ORDER:
            for c in (c for c in mine if status[c["id"]] == s):
                cid = c["id"]
                ids = _d(judg.get(cid)).get("facts") if c.get("kind") == "judgment" else c.get("facts")
                fix = _fix(c, s, report)
                text = _clip(reason[cid] or "no reason given", 120 if fix else 140)
                ptr = _pointer(f, ids)
                out.append(f"- **{s}** {cid}: {text}" + (f" {_code(ptr)}" if ptr and ptr not in text else "")
                           + (f" → fix: {_clip(fix, 90)}" if fix else ""))
        passed = [c["id"] for c in mine if status[c["id"]] == "pass"]
        if passed:
            if out[-1].startswith("- "):
                out.append("")
            out.append(f"Passed: {', '.join(passed)}")
        for line in aware.get(p, []):
            out += ["", _clip(line, 230)]

    people = [c for c in checks if c.get("kind") == "person"]
    if people:
        out += ["", "**Needs a person**", ""]
        out += [f"- {_s(c.get('title'), c.get('id'))}" for c in people]
    if bad:
        out += ["", "Not checked: " + "; ".join(bad)]
    if full_path is not None:
        out += ["", f"Full report: {full_path}"]
    return "\n".join(out) + "\n"


def render(facts_doc: dict, report: dict | None, unverified: bool = False, checks: list[dict] | None = None) -> str:
    """The full report (saved as <R>/report.md). `checks` is the catalog (default checks.yaml); the rule checks
    are decided here from the facts."""
    f, checks, report, status, reason, judg, title = _prepare(facts_doc, report, checks)

    out: list[str] = []
    if unverified:
        out += [BANNER, ""]
    out += [f"# Production readiness: {title}", ""]
    out += [f"{l}  " for l in _header(facts_doc, f)]
    out += ["", f"**Verdict: {verdict(checks, status)}**", "", "## Top fixes", ""]
    fixes = [x for x in _l(_d(report).get("fixes")) if isinstance(x, dict)][:MAX_FIXES]
    if fixes:
        for n, x in enumerate(fixes, 1):
            ids = ", ".join(_one_line(c) for c in _l(x.get("checks")))
            out.append(f"{n}. {_one_line(x.get('text', ''))} ({ids}) — {_one_line(x.get('where', ''))}")
    else:
        out.append("None listed." if report else "None: no report.")

    out += ["", "## Pillar summary", "", "| Pillar | pass | partial | fail | unknown | n/a |",
            "|---|---|---|---|---|---|"]
    for p in PILLARS:
        counts = [sum(1 for c in checks if c.get("pillar") == p and status.get(c.get("id")) == s) for s in STATUSES]
        out.append(f"| {p} | " + " | ".join(str(n) for n in counts) + " |")

    out += ["", "## Findings"]
    notes = _d(_d(report).get("pillar_notes"))
    aware = _awareness(f)
    for p in PILLARS:
        out += ["", f"### {p}", ""]
        if _s(notes.get(p)):
            out += [f"Note: {_one_line(notes[p])}", ""]
        mine = [c for c in checks if c.get("pillar") == p and c.get("id") in status]
        for s in ORDER:
            for c in mine:
                if status[c["id"]] != s:
                    continue
                cid = c["id"]
                ids = _d(judg.get(cid)).get("facts") if c.get("kind") == "judgment" else c.get("facts")
                line = f"- **{s}** {cid} — {_s(c.get('title'), cid)}: {reason[cid] or 'no reason given'}"
                ev = _evidence(f, ids)
                if ev:
                    line += " " + " ".join(_code(e) for e in ev)
                out.append(line)
                fix = _fix(c, s, report)
                if fix:
                    out.append(f"  - Fix: {fix}")
        passed = [c["id"] for c in mine if status[c["id"]] == "pass"]
        if passed:
            if out[-1].startswith("- "):
                out.append("")  # else markdown folds the line into the last bullet
            out.append(f"Passed: {', '.join(passed)}")
        if not mine:
            out.append("No checks.")
        for line in aware.get(p, []):
            out += ["", line]  # its own paragraph, never folded into a bullet or the Passed line

    out += ["", "## Needs a person", ""]
    people = [c for c in checks if c.get("kind") == "person"]
    for c in people:
        out.append(f"- {_s(c.get('title'), c.get('id'))}")
        for h in _l(c.get("hints")):
            h = _d(h)
            out.append(f"  - {_code(h.get('evidence', ''))} {_one_line(h.get('text', ''))}")
    if not people:
        out.append("None.")

    out += ["", "## Not checked", ""]
    for s in SOURCES:
        if not f.ok(s):
            out.append(f"- {s}: {_one_line(f.status(s))}")
    out.append(f"- {CVE_NOTE}")
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="render.py", description="Render the readiness report as markdown")
    ap.add_argument("--out", required=True, help="directory with facts.json and report.json")
    ap.add_argument("--unverified", action="store_true", help="put the UNVERIFIED banner first")
    ap.add_argument("--full", action="store_true", help="print the full report instead of the short one")
    args = ap.parse_args(argv)
    out = Path(args.out).expanduser()
    try:
        facts_doc = read_json(out / "facts.json")
    except (OSError, ValueError) as err:
        print(f"render: cannot read inputs in {out} ({type(err).__name__})", file=sys.stderr)
        return 1
    try:
        report = read_json(out / "report.json")
    except (OSError, ValueError):
        report = None
    full = render(facts_doc, report, unverified=args.unverified)
    full_path: Path | None = out / "report.md"
    try:
        full_path.write_text(full)
    except OSError:
        full_path = None
    print(full if args.full else render_short(facts_doc, report, unverified=args.unverified, full_path=full_path),
          end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
