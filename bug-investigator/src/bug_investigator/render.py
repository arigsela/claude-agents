"""Render verified findings as one issue comment (markdown) with links and a footer."""

from __future__ import annotations

import argparse
import os

from bug_investigator.tickets import MARKER
from bug_investigator.trail import load_messages
from bug_investigator.util import parse_time, read_json, scrub_text

HEADERS = {"full": "🔎 Bug investigation — full", "n8n": "🔎 n8n-style baseline (ticket + code only)"}
VERDICTS = {"likely_cause": "Likely cause found", "not_a_bug": "Not a bug: works as documented",
            "needs_info": "Needs more information", "unclear": "Unclear"}
STATUS = {"supported": "✅ supported", "ruled_out": "❌ ruled out", "untested": "❔ untested"}
KIND_LABEL = {"logql": "Loki", "promql": "Prometheus"}
MAX_LEN = 60000
MAX_TRAIL = 40


def t(s) -> str:
    """Model-written text: no HTML, no @-mentions, no fake markers."""
    s = str(s or "").strip()
    return s.replace("<", "&lt;").replace("@", "@\u200b")


def inline(s) -> str:
    """One line of model text outside a table."""
    return t(s).replace("\r", " ").replace("\n", " ")


def cell(s) -> str:
    """One table cell."""
    return inline(s).replace("|", "\\|")


def when(s) -> str:
    dt = parse_time(s)
    return dt.strftime("%Y-%m-%d %H:%M UTC") if dt else t(s)


def hm(s) -> str:
    dt = parse_time(s)
    return dt.strftime("%H:%M") if dt else "?"


def run_stats(execution_file: str | None) -> dict:
    msgs = load_messages(execution_file)
    result = next((m for m in reversed(msgs) if m.get("type") == "result"), None)
    if not result:
        return {}
    return {"turns": result.get("num_turns"), "duration_ms": result.get("duration_ms"),
            "cost": result.get("total_cost_usd"), "denials": len(result.get("permission_denials") or [])}


def code(s, limit: int = 160) -> str:
    """A one-line code span; backticks inside become quotes so the span cannot break."""
    s = " ".join(str(s or "").split()).replace("`", "'")
    if len(s) > limit:
        s = s[: limit - 1] + "…"
    return f"`{s}`"


def trail_lines(trail, cap: int = MAX_TRAIL) -> list[str]:
    """The collapsed step list; anything that is not {"steps": [{...}, ...]} renders nothing."""
    steps = trail.get("steps") if isinstance(trail, dict) else None
    steps = [x for x in steps if isinstance(x, dict)] if isinstance(steps, list) else []
    if not steps:
        return []
    out = [f"<details><summary>How the agent worked ({len(steps)} steps)</summary>", ""]
    for s in steps[:cap]:
        parts = []
        if s.get("narration"):
            parts.append(inline(s["narration"]))
        if s.get("tool"):
            target = code(s.get("input"))
            link = s.get("link")
            if isinstance(link, str) and link.startswith("https://") and not any(c in link for c in " ()<>\n"):
                target = f"[{target}]({link})"
            if s.get("window"):
                target += f" {inline(s['window'])}"
            mark = "⛔ " if s.get("status") == "blocked" else ""
            parts.append(f"{mark}{inline(s['tool'])}: {target} → {inline(s.get('result'))}")
        n = s.get("n") if isinstance(s.get("n"), int) else "?"
        out.append(f"{n}. " + " — ".join(parts))
    if len(steps) > cap:
        out.append(f"\n… {len(steps) - cap} more steps (all of them are in `trail-<mode>.json` in the run artifacts)")
    out += ["", "</details>", ""]
    return out


def fix_lines(fix) -> list[str]:
    """One line about the automatic fix; anything that is not a fix-<mode>.json object renders nothing."""
    if not isinstance(fix, dict) or fix.get("status") not in ("proposed", "skipped", "rejected"):
        return []
    if fix["status"] == "proposed":
        tests = fix.get("tests") if isinstance(fix.get("tests"), dict) else {}
        tests = tests.get("summary") or "passed"
        return ["### Proposed fix", "", f"🛠 {inline(fix.get('summary'))} Tests: {inline(tests)}. "
                "A pull request follows in the next comment; a person must review and merge it.", ""]
    return [f"No fix proposed: {inline(fix.get('reason') or fix['status'])}", ""]


def evidence_link(e: dict) -> str:
    v = e.get("verified") or {}
    kind, ref, link = e.get("kind"), str(e.get("ref") or ""), v.get("link")
    if kind == "commit":
        label = f"commit `{(v.get('sha') or ref)[:10]}`"
    elif kind == "pr":
        label = f"PR #{v.get('number')}" + (f" {cell(v.get('title'))}" if v.get("title") else "")
    elif kind == "issue":
        label = f"#{v.get('number')}" + (f" {cell(v.get('title'))}" if v.get("title") else "")
    elif kind in ("file", "doc"):
        label = f"`{v.get('path')}" + (f"#L{v['line']}" if v.get("line") else "") + "`"
    elif kind in ("logql", "promql"):
        label = f"{KIND_LABEL[kind]} query"
    else:
        label = cell(ref)
    return f"[{label}]({link})" if link else label


def render(f: dict, mode: str, model: str = "", stats: dict | None = None, run_url: str = "",
           trail: dict | None = None, fix: dict | None = None) -> str:
    stats = stats or {}
    v = f.get("verification") or {}
    ev = {e["id"]: e for e in f.get("evidence") or []}
    out = [MARKER.format(mode=mode), f"## {HEADERS.get(mode, HEADERS['full'])}", ""]
    verdict = VERDICTS.get(f.get("verdict"), cell(f.get("verdict")))
    out += [f"**{verdict}** · confidence {cell(f.get('confidence') or '?')} · "
            f"verified {v.get('verified', 0)} of {v.get('total', 0)} evidence links", "", t(f.get("summary")), ""]

    lc = f.get("likely_cause")
    if not lc and f.get("verdict") == "likely_cause":
        sup = [h for h in f.get("hypotheses") or [] if h.get("status") == "supported"]
        if sup:
            ids = ", ".join(sup[0].get("evidence_ids") or [])
            out += ["### Likely cause", "", f"- {t(sup[0].get('statement'))}" + (f" ({ids})" if ids else ""), ""]
    if lc:
        out += ["### Likely cause" + (" (not confirmed)" if lc.get("unconfirmed") else ""), ""]
        cv, kv = lc.get("change_verified"), lc.get("code_verified")
        if cv:
            label = f"PR #{cv['number']}" + (f" “{cell(cv.get('title'))}”" if cv.get("title") else "") \
                if "number" in cv else f"commit `{cv['sha'][:10]}`"
            live = f", live since ≈ {when(lc.get('live_since'))}" if lc.get("live_since") else ""
            out.append(f"- **Change:** [{label}]({cv['link']}){live}")
        if kv:
            out.append(f"- **Code:** [`{kv['path']}" + (f"#L{kv['line']}" if kv.get("line") else "") + f"`]({kv['link']})")
        out += [f"- {t(lc.get('explanation'))}", ""]

    dr = f.get("docs_rule")
    if not dr:
        # Fall back to the first verified doc quote among the evidence.
        doc = next((e for e in f.get("evidence") or [] if e.get("kind") == "doc" and e.get("quote")
                    and (e.get("verified") or {}).get("link")), None)
        if doc:
            dr = {"quote": doc["quote"], "rule_id": doc["id"], "verified": doc["verified"]}
    if dr:
        dv = dr.get("verified") or {}
        quote = "\n".join("> " + t(x) for x in str(dr.get("quote") or "").strip().splitlines())
        out += ["### What the docs say should happen", "", quote, "",
                f"— rule **{cell(dr.get('rule_id'))}**, [`{dv.get('path')}#L{dv.get('line')}`]({dv.get('link')})", ""]

    tele = [e for e in f.get("evidence") or [] if e.get("kind") in ("logql", "promql")]
    out += ["### What happened", ""]
    if tele:
        for e in tele:
            vv = e.get("verified") or {}
            res = "no results (as expected)" if e.get("expect") == "none" else f"{vv.get('count')} results"
            out.append(f"- **{e['id']}** {t(e.get('detail'))} — {evidence_link(e)} · {res}, "
                       f"{when(vv.get('start'))}–{hm(vv.get('end'))}")
    else:
        out.append("No telemetry in this mode." if mode != "full" else "No verified telemetry evidence.")
    out.append("")

    hyps = f.get("hypotheses") or []
    if hyps:
        out += ["### Hypotheses", "", "| | Hypothesis | Status | Evidence |", "|---|---|---|---|"]
        for h in hyps:
            ids = ", ".join(i for i in h.get("evidence_ids") or [] if i in ev) or "—"
            out.append(f"| {cell(h.get('id'))} | {cell(h.get('statement'))} | "
                       f"{STATUS.get(h.get('status'), cell(h.get('status')))} | {ids} |")
        out.append("")

    bugs = f.get("similar_past_bugs") or []
    if bugs:
        out += ["### Similar past bugs", ""]
        for b in bugs:
            bv = b.get("verified") or {}
            out.append(f"- [#{bv.get('number')} {cell(bv.get('title'))}]({bv.get('link')}) — {t(b.get('why'))}")
        out.append("")

    if f.get("next_step"):
        out += ["### Suggested next step", "", t(f["next_step"]), ""]
    out += fix_lines(fix)
    if f.get("could_not_check"):
        out += ["### Couldn't check", ""] + [f"- {t(x)}" for x in f["could_not_check"]] + [""]
    out += trail_lines(trail)

    rest = [e for e in f.get("evidence") or [] if e.get("kind") not in ("logql", "promql")]
    if f.get("evidence"):
        out += [f"<details><summary>Evidence ({len(f['evidence'])} verified)</summary>", ""]
        for e in rest + tele:
            q = f"\n  > {inline(e['quote'])}" if e.get("quote") and e.get("kind") in ("file", "doc") else ""
            code = f"\n  `{inline(e.get('ref'))}`" if e.get("kind") in ("logql", "promql") else ""
            out.append(f"- **{e['id']}** {evidence_link(e)} — {t(e.get('detail'))}{code}{q}")
        out += ["", "</details>", ""]

    rep = f.get("report") or {}
    if any(rep.values()):
        out += ["<details><summary>The report as understood</summary>", "",
                f"- **Who:** {t(rep.get('who'))}", f"- **What:** {t(rep.get('what'))}",
                f"- **When:** {when(rep.get('when_start'))} – {when(rep.get('when_end'))}",
                f"- **Where:** {t(rep.get('where'))}", f"- **Expected:** {t(rep.get('expected'))}",
                f"- **Actual:** {t(rep.get('actual'))}", "", "</details>", ""]

    dropped, notes = v.get("dropped") or [], v.get("notes") or []
    if dropped or notes:
        out += [f"<details><summary>Dropped by verification ({len(dropped)})</summary>", ""]
        out += [f"- {inline(d.get('id'))} ({inline(d.get('kind'))} `{inline(str(d.get('ref'))[:120])}`): "
                f"{inline(d.get('reason'))}" for d in dropped]
        out += [f"- {inline(n)}" for n in notes] + ["", "</details>", ""]

    foot = [f"{mode} mode"]
    if model:
        foot.append(model)
    if stats.get("turns") is not None:
        foot.append(f"{stats['turns']} turns")
    if stats.get("duration_ms"):
        s = int(stats["duration_ms"] / 1000)
        foot.append(f"{s // 60}m {s % 60:02d}s")
    if stats.get("cost") is not None:
        foot.append(f"${stats['cost']:.2f}")
    foot.append(f"verified {v.get('verified', 0)} of {v.get('total', 0)} evidence links")
    if stats.get("denials"):
        foot.append(f"{stats['denials']} tool calls blocked")
    if run_url:
        foot.append(f"[run]({run_url})")
    out += ["---", "<sub>" + " · ".join(foot) + "</sub>", ""]
    body = scrub_text("\n".join(out))
    if len(body) > MAX_LEN:
        body = body[: MAX_LEN - 200] + "\n\n…(truncated; the full findings are in the run artifacts)\n"
    return body


def _optional_json(path: str | None) -> dict | None:
    """An optional JSON object (trail, fix); missing, unreadable or not an object counts as unavailable."""
    if not path or not os.path.isfile(path):
        return None
    try:
        data = read_json(path)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="render")
    p.add_argument("--findings", required=True)
    p.add_argument("--mode", choices=("full", "n8n"), required=True)
    p.add_argument("--model", default="")
    p.add_argument("--execution-file")
    p.add_argument("--trail", help="trail-<mode>.json (optional)")
    p.add_argument("--fix", help="fix-<mode>.json (optional)")
    p.add_argument("--out", required=True)
    a = p.parse_args(argv)
    server, repo, run_id = (os.environ.get(k) for k in ("GITHUB_SERVER_URL", "GITHUB_REPOSITORY", "GITHUB_RUN_ID"))
    run_url = f"{server}/{repo}/actions/runs/{run_id}" if server and repo and run_id else ""
    body = render(read_json(a.findings), a.mode, a.model, run_stats(a.execution_file), run_url,
                  _optional_json(a.trail), _optional_json(a.fix))
    with open(a.out, "w") as f:
        f.write(body)
    print(f"render: {len(body)} chars -> {a.out}")
    return 0
