#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6", "pathspec>=0.12,<1"]
# ///
"""readiness: facts.json + report.json -> the markdown report printed in the terminal (spec §7.7), and with --html
an HTML page of the same report.

Usage: render.py --out DIR [--unverified] [--full] [--html [--standalone]]
Reads DIR, saves the full report as DIR/report.md and prints the short one (or the full one with --full). --html also
writes DIR/report.html, a page for the Artifact tool (--standalone: a complete file to open locally instead).

Prints only facts, checks and report content. Rule statuses, reasons and ORR hints are recomputed from facts.json
and checks.yaml (evaluate.py), never read from results.json, so a hand-edited results.json cannot change them.
A missing report renders the judgment checks as unknown ("no report").
"""
from __future__ import annotations

import argparse
import html
import re
import sys
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent))

from evaluate import evaluate, verdict  # noqa: E402
from readiness_model import (CREDENTIAL_URL_RE, PILLARS, PLUGIN_DIR, SECRET_RE, SOURCES, STATUSES, Facts,  # noqa: E402
                             load_checks, read_json)

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


def _deploy_refs(deploy: dict, f: Facts) -> str:
    """The deploy refs as one phrase: the ref read (when it differs from Argo's), Argo's targetRevision, and the
    entity the folder was found through."""
    rev = _s(_d(f.value("deploy.application")).get("target_revision"), "unknown")
    ref = _s(deploy.get("ref"))  # what was read: --deploy-ref, else targetRevision, else the default branch
    refs = f"reviewed ref {ref}; Argo targetRevision {rev}" if ref and ref != rev else f"Argo targetRevision {rev}"
    if _s(deploy.get("via")):  # the catalog entry lives in the app repo; collect followed the System
        refs += f"; found through {_one_line(deploy.get('via'))}"
    return refs


def _blockers(checks: list[dict], status: dict[str, str], word: str) -> tuple[str, list[str]]:
    """Why the verdict is what it is: ("failing blockers", ids) when Not ready, else ("unknown blockers", ids) when
    a blocker is unknown, else ("", [])."""
    blockers = [c for c in checks if c.get("blocker") and c.get("id") in status]
    if word == "Not ready":
        return "failing blockers", [c["id"] for c in blockers if status[c["id"]] == "fail"]
    unknown = [c["id"] for c in blockers if status[c["id"]] == "unknown"]
    return ("unknown blockers", unknown) if unknown else ("", [])


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
        lines.append(f"deploy: {_s(deploy.get('repo'), 'unknown')}/{_s(deploy.get('folder'), '')}"
                     f"@{_sha7(deploy.get('sha'))} ({_deploy_refs(deploy, f)})")
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
        via = f" (through {_one_line(deploy.get('via'))})" if _s(deploy.get("via")) else ""
        head.append(f"deploy {_s(deploy.get('repo'), 'unknown')}/{_s(deploy.get('folder'), '')}"
                    f"@{_sha7(deploy.get('sha'))}{via}")
    else:
        head.append(f"deploy not found ({_one_line(f.status('deploy')).removeprefix('unavailable: ')})")
    out.append(" · ".join(head) + "  ")
    bad = [f"{s} {_one_line(f.status(s))}" for s in SOURCES if not f.ok(s)]
    out.append("Sources: " + ("; ".join(bad) if bad else "all ok"))

    word = verdict(checks, status)
    label, ids = _blockers(checks, status, word)
    why = f" ({label}: {', '.join(ids)})" if label else ""
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


# --- HTML page (--html) ------------------------------------------------------------------------------------
# The same decided checks as the markdown reports, as one page for the Artifact tool. Every piece of text is
# escaped and has secret-looking tokens masked here; the template's script only filters and expands rows.

TEMPLATE = PLUGIN_DIR / "assets" / "report.html"
STANDALONE_HEAD = ('<!doctype html>\n<html lang="en">\n<meta charset="utf-8">\n'
                   '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n')
HTML_EVIDENCE_PER_CHECK = 12
HTML_ORDER = ("fail", "partial", "unknown", "pass", "n/a")
STATUS_CLASS = {"pass": "s-pass", "partial": "s-partial", "fail": "s-fail", "unknown": "s-unknown", "n/a": "s-na"}
VERDICT_CLASS = {"Not ready": "s-fail", "Ready with gaps": "s-partial", "Ready": "s-pass"}
_SECRET_TOKEN = re.compile(f"(?:{SECRET_RE.pattern})[A-Za-z0-9_-]*")
_GH_SLUG = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
_GH_SHA = re.compile(r"[0-9a-f]{7,40}")
_LINE_SUFFIX = re.compile(r"(.+?):(\d+)(?:-(\d+))?")
_PLACEHOLDER = re.compile(r"\{\{([A-Z_]+)\}\}")


def _mask(text: str) -> str:
    """Secret-looking tokens and URL passwords taken out of text bound for a page other people can open."""
    return CREDENTIAL_URL_RE.sub("://[REDACTED]@", _SECRET_TOKEN.sub("[REDACTED]", text))


def _h(v) -> str:
    """Untrusted text for the page: one line, secrets masked, escaped for element text and attribute values."""
    return html.escape(_mask(_one_line(v)), quote=True)


def _gh_repo(meta: dict, source) -> tuple[str, str] | None:
    """(slug, sha) of the GitHub repo a fact's evidence path is relative to: the app repo or the deploy repo."""
    m = _d(meta.get("app")) if source == "app" else _d(meta.get("deploy")) if source == "deploy" else {}
    slug, sha = m.get("slug" if source == "app" else "repo"), m.get("sha")
    if (isinstance(slug, str) and _GH_SLUG.fullmatch(slug) and _mask(slug) == slug
            and isinstance(sha, str) and _GH_SHA.fullmatch(sha)):
        return slug, sha
    return None


def _safe_url(url: str | None) -> str | None:
    """The URL, or None when any part of it looks like a secret: text is masked, so a link must not carry it."""
    return url if url and _mask(url) == url else None


def _gh_link(meta: dict, source, evidence) -> str | None:
    """A github.com link to the reviewed commit for evidence that is a repo path (maybe with lines); else None."""
    repo = _gh_repo(meta, source)
    if repo is None or not isinstance(evidence, str) or not _POINTER.fullmatch(evidence) or _mask(evidence) != evidence:
        return None  # a path holding a secret-looking token is masked in the text, so never put it in a URL
    path, anchor = evidence, ""
    m = _LINE_SUFFIX.fullmatch(evidence)
    if m:
        path, anchor = m.group(1), f"#L{m.group(2)}" + (f"-L{m.group(3)}" if m.group(3) else "")
    if path.startswith("/") or any(p in ("", ".", "..") for p in path.split("/")):
        return None
    return f"https://github.com/{repo[0]}/blob/{repo[1]}/{quote(path)}{anchor}"


def _code_link(text, link: str | None) -> str:
    code = f"<code>{_h(text)}</code>"
    link = _safe_url(link)
    return f'<a href="{html.escape(link, quote=True)}">{code}</a>' if link else code


def _evidence_items(f: Facts, meta: dict, ids) -> list[tuple[str, str | None]]:
    """(evidence, link or None) for every cited fact, in order, without repeats. A file fact for a file that does
    not exist names where it looked; that is shown but not linked."""
    out: list[tuple[str, str | None]] = []
    for i in _l(ids):
        t = f.get(i) if isinstance(i, str) else None
        ev = _s(t.get("evidence")) if t else ""
        if not ev or any(ev == e for e, _ in out):
            continue
        exists = _d(t.get("value")).get("exists")
        out.append((ev, None if exists is False else _gh_link(meta, t.get("source"), ev)))
    return out


def _html_meta(doc: dict, f: Facts) -> str:
    meta = _d(doc.get("meta"))
    app, deploy = _d(meta.get("app")), _d(meta.get("deploy"))
    entity = _d(f.value("backstage.entity"))
    rows = [("Owner", _h(_s(entity.get("owner"), "unknown"))),
            ("Lifecycle", _h(_s(entity.get("lifecycle"), "unknown")))]
    repo = _gh_repo(meta, "app")
    app_html = _code_link(f"{_s(app.get('slug'), 'unknown')}@{_sha7(app.get('sha'))}",
                          f"https://github.com/{repo[0]}/commit/{repo[1]}" if repo else None)
    app_html += f" on {_h(_s(app.get('branch'), 'an unknown branch'))}"
    if app.get("on_default_branch") is False:
        app_html += ' <span class="flag">(not the default branch)</span>'
    rows.append(("App", app_html))
    if deploy:
        repo = _gh_repo(meta, "deploy")
        folder = _s(deploy.get("folder"))
        tree = (f"https://github.com/{repo[0]}/tree/{repo[1]}/{quote(folder)}"
                if repo and folder and _POINTER.fullmatch(folder) and _mask(folder) == folder else None)
        rows.append(("Deploy", _code_link(f"{_s(deploy.get('repo'), 'unknown')}/{folder}@{_sha7(deploy.get('sha'))}",
                                          tree) + f" ({_h(_deploy_refs(deploy, f))})"))
    else:
        rows.append(("Deploy", "not found (" + _h(_one_line(f.status("deploy")).removeprefix("unavailable: ")) + ")"))
    stamps = sorted(_one_line(_d(t["value"]).get("timestamp")) for t in f.prefix("scorecard.")
                    if _d(t.get("value")).get("timestamp"))
    rows.append(("Scorecard", _h(stamps[-1] if stamps else f.status("scorecard"))))
    rows.append(("Reviewed", _h(_s(meta.get("generated_at"), "unknown"))))
    return "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in rows)


def _html_gauges(checks: list[dict], status: dict[str, str]) -> str:
    """One row per pillar: a bar of its statuses, drawn to one scale (the largest pillar fills the track)."""
    counts = {p: {s: sum(1 for c in checks if c.get("pillar") == p and status.get(c.get("id")) == s)
                  for s in STATUSES} for p in PILLARS}
    most = max((sum(n.values()) for n in counts.values()), default=0) or 1
    out = []
    for p in PILLARS:
        n = counts[p]
        total = sum(n.values())
        segs = "".join(f'<i class="{STATUS_CLASS[s]}" style="flex:{n[s]}"></i>' for s in STATUSES if n[s])
        nums = "".join(f'<span class="{STATUS_CLASS[s]}"><b>{n[s]}</b> {s}</span>' for s in HTML_ORDER if n[s])
        out.append(f'<button type="button" class="gauge" data-pillar="{_h(p)}" aria-pressed="false">'
                   f'<span class="name">{_h(p)}</span>'
                   f'<span class="track" aria-hidden="true"><span class="fill" style="width:{total / most * 100:.1f}%">'
                   f'{segs}</span></span><span class="counts">{nums or "no checks"}</span></button>')
    return "\n      ".join(out)


def _html_why(checks: list[dict], status: dict[str, str], word: str) -> str:
    label, ids = _blockers(checks, status, word)
    if label:
        links = ", ".join(f'<a href="#{_h(i)}">{_h(i)}</a>' for i in ids)
        return f"{label.capitalize()}: {links}."
    if word == "Ready with gaps":
        n = sum(1 for s in status.values() if s in ("fail", "partial"))
        return f"No blocker fails; {n} check{'' if n == 1 else 's'} fail{'s' if n == 1 else ''} or {'is' if n == 1 else 'are'} partial."
    return "Every counted check passes or does not apply."


def _html_fixes(report: dict | None, status: dict[str, str]) -> str:
    fixes = [x for x in _l(_d(report).get("fixes")) if isinstance(x, dict)][:MAX_FIXES]
    if not fixes:
        return f'<p class="empty-note">{"None listed." if report else "None: no report."}</p>'
    items = []
    for x in fixes:
        links = []
        for cid in _l(x.get("checks")):
            if isinstance(cid, str) and cid in status:  # only a check this report decided gets a link
                links.append(f'<a class="chk {STATUS_CLASS[status[cid]]}" href="#{_h(cid)}">{_h(cid)}</a>')
            else:
                links.append(f"<code>{_h(cid)}</code>")
        where = _s(x.get("where"))
        meta = (f"<span>{_h(where)}</span>" if where else "") + " ".join(links)
        items.append(f'<li data-comment-target><span class="fix-text">{_h(x.get("text", ""))}</span>'
                     f'<span class="fix-meta">{meta}</span></li>')
    return '<ol class="fixes">' + "".join(items) + "</ol>"


def _html_check(c: dict, s: str, reason: str, report: dict | None, f: Facts, meta: dict, judg: dict,
                catalog: dict[str, dict], unverified: bool) -> str:
    cid, kind = c["id"], c.get("kind")
    title = _s(c.get("title"), cid)
    ids = _d(judg.get(cid)).get("facts") if kind == "judgment" else c.get("facts")
    fix = _fix(c, s, report)
    specific = bool(_s(_d(_d(report).get("item_fixes")).get(cid)))
    evidence = _evidence_items(f, meta, ids)
    text = " ".join([cid, title, reason, fix] + [e for e, _ in evidence]).lower()

    head = [f'<span class="pill {STATUS_CLASS[s]}">{_h(s)}</span>', f'<span class="cid">{_h(cid)}</span>']
    if c.get("blocker"):
        head.append('<span class="tag">blocker</span>')
    head.append(f'<span class="ctitle">{_h(title)}</span>')
    summary = [f'<span class="line1">{"".join(head)}</span>', '<span class="chev" aria-hidden="true"></span>',
               f'<span class="reason">{_h(reason or "no reason given")}</span>']
    if fix:
        note = "for this repo" if specific else "catalog default"
        summary.append(f'<span class="fixline"><span class="label">Fix</span>{_h(fix)}'
                       f'<span class="src-note">{note}</span></span>')

    dl = []
    if evidence:
        shown = evidence[:HTML_EVIDENCE_PER_CHECK]
        lis = "".join(f"<li>{_code_link(e, link)}</li>" for e, link in shown)
        if len(evidence) > len(shown):
            lis += f"<li>and {len(evidence) - len(shown)} more</li>"
        dl.append(f"<dt>Evidence</dt><dd><ul>{lis}</ul></dd>")
    cited = [i for i in _l(ids) if isinstance(i, str)]
    if cited:
        more = f" and {len(cited) - HTML_EVIDENCE_PER_CHECK} more" if len(cited) > HTML_EVIDENCE_PER_CHECK else ""
        dl.append('<dt>Facts cited</dt><dd class="ids">'
                  + "".join(f"<code>{_h(i)}</code>" for i in cited[:HTML_EVIDENCE_PER_CHECK]) + f"{more}</dd>")
    if kind == "judgment":
        how = ("the model, from the facts cited; verify.py rejected this report" if unverified
               else "the model, from the facts cited; checked by verify.py")
    else:
        how = "a script, from the collected facts"
    dl.append(f"<dt>Decided by</dt><dd>{how}</dd>")
    cat = catalog.get(cid, {})
    ref, url = _s(cat.get("wa_ref")), _s(cat.get("wa_url"))
    if ref and ref != "none":
        url = _safe_url(url) if url.startswith("https://") else None
        link = f'<a href="{html.escape(url, quote=True)}">{_h(ref)}</a>' if url else _h(ref)
        dl.append(f"<dt>Well-Architected</dt><dd>{link}</dd>")

    blocker = "1" if c.get("blocker") else "0"
    return (f'<details class="check" id="{_h(cid)}" data-status="{_h(s)}" data-pillar="{_h(c.get("pillar"))}" '
            f'data-blocker="{blocker}" data-text="{_h(text)}" data-comment-target>'
            f'<summary>{"".join(summary)}</summary>'
            f'<div class="body"><dl>{"".join(dl)}</dl>'
            f'<button type="button" class="ask" hidden>Comment on this check</button></div></details>')


def _html_cve(f: Facts) -> str:
    """The Scorecard CVE cards as tiles, and the critical-no-fix awareness line: context next to sec.cve."""
    out = []
    cards = {mid: f.get(f"scorecard.cve.{mid}") for mid, _, _ in CVE_CARDS}
    present = [t for t in cards.values() if t]
    if present:
        values = {mid: _int(_d(t["value"]).get("value")) if t else None for mid, t in cards.items()}
        source = _code_link(present[0].get("evidence", ""), None)
        if all(v is None for v in values.values()):
            errors = list(dict.fromkeys(_s(_d(t["value"]).get("error"), "no value") for t in present))
            out.append(f'<p class="aware"><span class="label">Scorecard CVE cards</span> {_h("; ".join(errors))}</p>')
        else:
            tiles = []
            for mid, _, alone in CVE_CARDS:
                n = values[mid]
                cls = ("s-fail" if mid in ("criticalFixable", "kevFixable") else "s-partial") if n else ""
                label = alone if mid != "imagesNotScanned" or n != 1 else "image not scanned"
                tiles.append(f'<div class="tile {cls}"><b>{"–" if n is None else n}</b>'
                             f'<span>{_h(label)}{"" if n is not None else " (no value)"}</span></div>')
            out.append('<div class="cve"><p class="label">Scorecard CVE cards: running images, not counted</p>'
                       f'<div class="tiles">{"".join(tiles)}</div><p class="aware">From {source}. '
                       "sec.cve above reads the images in the deploy repo.</p></div>")
    cve = f.get("backstage.cve")
    n = _int(_d(_d(cve["value"]).get("totals")).get("critical_no_fix")) if cve else None
    if n:
        noun = "CVE" if n == 1 else "CVEs"
        out.append(f'<p class="aware">{n} critical {noun} with no fix yet in the scanned images (not counted) '
                   f'{_code_link(cve.get("evidence", ""), None)}</p>')
    return "".join(out)


def _html_people(checks: list[dict], f: Facts, meta: dict) -> str:
    people = [c for c in checks if c.get("kind") == "person"]
    if not people:
        return '<p class="empty-note">None.</p>'
    items = []
    for c in people:
        hints = []
        for h in (_d(x) for x in _l(c.get("hints"))):
            ev = _s(h.get("evidence"))
            path = ev.rsplit(":", 1)[0]
            source = next((s for s in ("app", "deploy") if f.get(f"{s}.text.{path}")), None)
            link = _gh_link(meta, source, ev) if source else None
            hints.append(f"<li>{_code_link(ev, link)} {_h(h.get('text', ''))}</li>")
        hint_html = f'<ul class="hints">{"".join(hints)}</ul>' if hints else ""
        items.append(f'<li data-comment-target><span class="q">{_h(_s(c.get("title"), c.get("id")))}</span>'
                     f"{hint_html}</li>")
    return '<ul class="people">' + "".join(items) + "</ul>"


def render_html(facts_doc: dict, report: dict | None, unverified: bool = False, checks: list[dict] | None = None,
                standalone: bool = False) -> str:
    """The HTML page: an Artifact page fragment (the publish skeleton adds doctype and head), or with standalone
    a complete file to open in a browser."""
    catalog_list = load_checks() if checks is None else checks
    f, checks, report, status, reason, judg, title = _prepare(facts_doc, report, catalog_list)
    meta = _d(facts_doc.get("meta"))
    catalog = {c.get("id"): c for c in catalog_list if isinstance(c, dict)}
    word = verdict(checks, status)
    name = re.split(r"[:/]", title)[-1] or title
    tally = {s: sum(1 for v in status.values() if v == s) for s in HTML_ORDER}
    people = sum(1 for c in checks if c.get("kind") == "person")

    pillars = []
    for p in PILLARS:
        mine = [c for c in checks if c.get("pillar") == p and c.get("id") in status]
        mine.sort(key=lambda c: HTML_ORDER.index(status[c["id"]]))
        rows = "".join(_html_check(c, status[c["id"]], reason[c["id"]], report, f, meta, judg, catalog, unverified)
                       for c in mine)
        note = _s(_d(_d(report).get("pillar_notes")).get(p))
        extra = _html_cve(f) if p == "Security" else ""
        pillars.append(f'<section class="pillar" data-pillar="{_h(p)}">'
                       f'<div class="head-row"><h3>{_h(p)}</h3>'
                       f'<button type="button" class="ask" hidden>Comment</button></div>'
                       + (f'<p class="note">{_h(note)}</p>' if note else "")
                       + (f'<div class="rows">{rows}</div>' if rows else '<p class="empty-note">No checks.</p>')
                       + extra + "</section>")

    sources = "".join(
        f'<li class="ok"><span class="dot"></span>{s}</li>' if f.ok(s)
        else f'<li class="off"><span class="dot"></span>{s} <span>{_h(f.status(s))}</span></li>' for s in SOURCES)
    not_checked = [f"<li>{s}: {_h(f.status(s))}</li>" for s in SOURCES if not f.ok(s)] + [f"<li>{_h(CVE_NOTE)}</li>"]
    chips = "".join(f'<button type="button" class="chip {STATUS_CLASS[s]}" data-status="{_h(s)}" aria-pressed="true">'
                    f'<span class="dot"></span>{_h(s)}<b>{tally[s]}</b></button>' for s in HTML_ORDER if tally[s])
    parts = {
        "TITLE": f"{_h(name)} readiness review",
        "BANNER": ('<p class="banner" role="alert">Unverified: verify.py rejected this report. '
                   "Read the evidence before acting on it.</p>") if unverified else "",
        "EYEBROW": f"Production readiness · {_h(title)}",
        "NAME": _h(name),
        "META": _html_meta(facts_doc, f),
        "VERDICT_CLASS": VERDICT_CLASS.get(word, "s-unknown"),
        "VERDICT": _h(word),
        "WHY": _html_why(checks, status, word),
        "TALLY": f"{len(status)} checks: " + " · ".join(f"{tally[s]} {s}" for s in HTML_ORDER if tally[s])
                 + (f". {people} questions need a person." if people else "."),
        "GAUGES": _html_gauges(checks, status),
        "SOURCES": sources,
        "FIXES": _html_fixes(report, status),
        "CHIPS": chips,
        "PILLARS": "\n    ".join(pillars),
        "PEOPLE": _html_people(checks, f, meta),
        "NOT_CHECKED": "".join(not_checked),
        "FOOTER": ("Rule checks are decided by scripts from the facts collected at the commits above. The judgment "
                   "checks are the model's, each citing facts, and checked by verify.py"
                   + (" (which rejected this report)" if unverified else "") + ". The verdict follows the checks: "
                   "Not ready when a blocker fails; Ready with gaps when any check fails or is partial, or a blocker "
                   "is unknown; otherwise Ready."),
    }
    page = _PLACEHOLDER.sub(lambda m: parts[m.group(1)], TEMPLATE.read_text())  # one pass: inserted text is final
    return (STANDALONE_HEAD + page) if standalone else page


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="render.py", description="Render the readiness report as markdown")
    ap.add_argument("--out", required=True, help="directory with facts.json and report.json")
    ap.add_argument("--unverified", action="store_true", help="put the UNVERIFIED banner first")
    ap.add_argument("--full", action="store_true", help="print the full report instead of the short one")
    ap.add_argument("--html", action="store_true", help="also write DIR/report.html, a page for the Artifact tool")
    ap.add_argument("--standalone", action="store_true",
                    help="with --html: write a complete HTML file to open in a browser instead")
    args = ap.parse_args(argv)
    if args.standalone and not args.html:
        ap.error("--standalone needs --html")
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
    if args.html:
        page_path = out / "report.html"
        try:
            page_path.write_text(render_html(facts_doc, report, unverified=args.unverified,
                                             standalone=args.standalone))
        except OSError as err:
            print(f"render: cannot write {page_path} ({type(err).__name__})", file=sys.stderr)
            return 1
        print(f"HTML report: {page_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
