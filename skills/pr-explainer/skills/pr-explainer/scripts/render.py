#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///
"""pr-explainer: render facts.json + explainer.json into one HTML page (spec §6.5).

The Mermaid graph comes only from facts.json; every text field is HTML-escaped.
Default output is an Artifact page fragment (the Artifact host renders <pre class="mermaid">
natively). --standalone adds a doctype and the Mermaid script for local viewing.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
from pathlib import Path

MAX_NODES = 40
NODE_CLASS = {"added": "added", "modified": "modified", "removed": "removed",
              "context": "context", "generated": "context"}
# Plan actions from a plan comment, then source-level actions from the no-plan block comparison.
TF_CLASS = {"create": "added", "update": "modified", "replace": "modified", "destroy": "removed", "read": "context",
            "added": "added", "modified": "modified", "removed": "removed"}
SEVERITY_CLASS = {"high": "sev-high", "medium": "sev-med", "info": "sev-info"}
STANDALONE_HEAD = ('<!doctype html>\n<meta charset="utf-8">\n'
                   '<meta name="viewport" content="width=device-width, initial-scale=1">\n')
# The Artifact host renders mermaid natively, so the fragment loads no library.
# A standalone file has no host, so it loads Mermaid itself.
STANDALONE_TAIL = '''
<script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"></script>
<script>
  const root = document.documentElement.dataset.theme;
  const dark = root === "dark" || (root !== "light" && matchMedia("(prefers-color-scheme: dark)").matches);
  mermaid.initialize({ startOnLoad: true, securityLevel: "strict", theme: dark ? "dark" : "default" });
</script>
'''


SECRET_VALUE_RE = re.compile(
    r"(?i)((?:password|passwd|token|secret|api[_-]?key|private[_-]?key)\s*[:=]\s*)(\S{8,})")


def esc(value) -> str:
    return html.escape(str(value), quote=True)


def mask(value) -> str:
    """Mask secret-looking values in model text; apply before esc()."""
    return SECRET_VALUE_RE.sub(r"\1[REDACTED]", str(value))


def label(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9 ._:/-]", " ", str(text))[:60].strip() or "?"


def tf_label(t: dict) -> str:
    """type · name, with a for_each key or count index in parentheses: aws_x · y (search)."""
    index = re.search(r'\[("?)([^\]"]*)\1\]$', t["address"])
    return f'{label(t["type"])} · {label(t["name"])}' + (f" ({label(index.group(2))})" if index else "")


def mermaid(facts: dict) -> str:
    res = facts["resources"]
    if len(res) > MAX_NODES:
        res = [r for r in res if r["action"] not in ("context", "generated")]
    lines = ["flowchart LR"]
    if len(res) > MAX_NODES:  # collapse per (app, action)
        groups: dict[tuple[str, str], list[dict]] = {}
        for r in res:
            groups.setdefault((r["app"] or "other", r["action"]), []).append(r)
        for i, ((app, action), rs) in enumerate(sorted(groups.items())):
            kinds = ", ".join(sorted({r["kind"] for r in rs}))
            lines.append(f'  g{i}["{label(app)} · {len(rs)} {action} · {label(kinds)}"]:::{NODE_CLASS[action]}')
    else:
        by_app: dict[str, list[dict]] = {}
        for r in res:
            by_app.setdefault(r["app"] or "other", []).append(r)
        for i, (app, rs) in enumerate(sorted(by_app.items())):
            lines.append(f'  subgraph s{i}["{label(app)}"]')
            lines += [f'    {r["id"]}["{label(r["kind"])} · {label(r["name"])}"]:::{NODE_CLASS[r["action"]]}'
                      for r in rs]
            lines.append("  end")
        shown = {r["id"] for r in res}
        lines += [f'  {e["from"]} -->|{e["type"]}| {e["to"]}' for e in facts["edges"]
                  if e["from"] in shown and e["to"] in shown]
    tf = facts.get("terraform") or []
    if len(tf) > MAX_NODES:  # collapse per action
        for action in sorted({t["action"] for t in tf}):
            ts = [t for t in tf if t["action"] == action]
            types = ", ".join(sorted({t["type"] for t in ts}))
            lines.append(f'  tg_{action}["terraform · {len(ts)} {action} · {label(types)}"]:::{TF_CLASS[action]}')
    elif tf:
        by_file: dict[str, list[dict]] = {}
        for t in tf:
            by_file.setdefault(t.get("file") or "plan", []).append(t)
        for i, (file, ts) in enumerate(sorted(by_file.items())):
            lines.append(f'  subgraph tf{i}["{label(file)}"]')
            lines += [f'    {t["id"]}["{tf_label(t)}<br/>{t["action"]}"]:::{TF_CLASS[t["action"]]}' for t in ts]
            lines.append("  end")
        tf_ids = {t["id"] for t in tf}
        lines += [f'  {e["from"]} -->|{e["type"]}| {e["to"]}' for e in facts["edges"]
                  if e["from"] in tf_ids and e["to"] in tf_ids]
    lines += ["  classDef added fill:#dcfce7,stroke:#16a34a,color:#052e16",
              "  classDef modified fill:#fef3c7,stroke:#d97706,color:#451a03",
              "  classDef removed fill:#fee2e2,stroke:#dc2626,color:#450a0a,stroke-dasharray:4 3",
              "  classDef context fill:#f1f5f9,stroke:#94a3b8,color:#334155"]
    return "\n".join(lines)


def render(facts: dict, expl: dict, errors: list[str]) -> str:
    pr = facts["pr"]
    index = {x["id"]: x for key in ("resources", "non_manifest_changes", "terraform") for x in facts[key]}

    def ref_html(rid: str) -> str:
        item = index.get(rid)
        if not item:
            return f"<code>{esc(rid)}</code>"
        if "kind" in item:
            text = f'{item["kind"]} {item["namespace"] + "/" if item["namespace"] else ""}{item["name"]}'
        elif "address" in item:
            text = f'{item["address"]} ({item["action"]})'
        else:
            text = item["file"]
        path = item.get("file")
        if not path:
            return esc(text)
        url = f'{pr["url"]}/files#diff-{hashlib.sha256(path.encode()).hexdigest()}'
        start = (item.get("lines") or [None])[0] or ((item.get("hunks") or [[None]])[0][0])
        if start:
            # A removed block's line number is on the base side of the diff.
            url += f'{"L" if item.get("action") in ("removed", "destroy") else "R"}{start}'
        return f'<a href="{esc(url)}">{esc(text)}</a>'

    def refs(ids: list[str]) -> str:
        return " ".join(ref_html(r) for r in ids)

    banner = ""
    if errors:
        banner = ('<div class="banner"><strong>Unverified.</strong> These checks failed:<ul>'
                  + "".join(f"<li>{esc(e)}</li>" for e in errors) + "</ul></div>")
    triage = facts.get("triage") or {}
    header = (f'<a href="{esc(pr["url"])}">{esc(pr["repo"])}#{pr["number"]}</a> · head '
              f'<code>{esc(pr["head_sha"][:7])}</code>'
              + (f' · <span class="pill">{esc(triage["label"])}</span>' if triage.get("label") else "")
              + f' · narrated by <code>{esc(expl.get("narrator_model") or "unknown model")}</code>')

    plans = ""
    if facts.get("terraform_plans"):
        rows = []
        for p in facts["terraform_plans"]:
            t = p.get("totals") or {}
            counts = " · ".join(f"{t[k]} to {k}" for k in ("add", "change", "destroy", "replace") if k in t) or "no summary"
            flags = [p["status"]] + (["stale"] if p.get("stale") else []) + (
                [f'{p["listed"]} mapped'] if t and p["listed"] < sum(t.values()) else [])
            env = esc(p.get("environment") or p["source"])
            link = f'<a href="{esc(p["run_url"])}">{env}</a>' if p.get("run_url") else env
            rows.append(f'<tr><td>{link}</td><td>{esc(counts)}</td><td>{esc(", ".join(flags))}</td></tr>')
        plans = ('<div class="scroll"><table><thead><tr><th>Plan</th><th>Summary</th><th>Status</th></tr></thead><tbody>'
                 + "".join(rows) + "</tbody></table></div>")

    ticket_html = ""
    jira, ticket = facts.get("jira"), expl.get("ticket") or {}
    if jira:
        key = esc(jira["key"])
        link = f'<a href="{esc(jira["url"])}">{key}</a>' if jira.get("url") else key
        parent = jira.get("parent") or {}
        meta = " · ".join(x for x in (
            link, esc(jira.get("type") or ""),
            f'<span class="pill">{esc(jira["status"])}</span>' if jira.get("status") else "",
            f'parent {esc(parent.get("key") or "")} {esc(mask(parent.get("summary") or ""))}' if parent else "") if x)
        criteria = "".join(f'<tr><td>{esc(mask(c.get("text", "")))}</td><td>{esc(c.get("status", ""))}</td>'
                           f'<td>{refs(c.get("refs", []))}</td></tr>' for c in ticket.get("criteria", []))
        ticket_html = ('<h2>Ticket</h2><div class="card">'
                       f'<div class="meta">{meta}</div><p><strong>{esc(mask(jira.get("summary") or ""))}</strong></p>'
                       + (f'<p>{esc(mask(ticket["intent"]))}</p>' if ticket.get("intent") else "")
                       + ('<div class="scroll"><table><thead><tr><th>Ticket asks for</th><th>Status</th><th>Refs</th>'
                          f'</tr></thead><tbody>{criteria}</tbody></table></div>' if criteria else "")
                       + "</div>")
    subs = {
        "TITLE": esc(f"PR {pr['number']} explainer"),
        "PR_TITLE": esc(pr["title"]),
        "HEADER": header,
        "BANNER": banner,
        "TLDR": esc(mask(expl.get("tldr", ""))),
        "TICKET": ticket_html,
        "PLANS": plans,
        "MERMAID": esc(mermaid(facts)),
        "BEHAVIOR": "".join(f'<tr><td>{esc(mask(b.get("app", "")))}</td><td>{esc(mask(b.get("before", "")))}</td>'
                            f'<td>{esc(mask(b.get("after", "")))}</td><td>{refs(b.get("refs", []))}</td></tr>'
                            for b in expl.get("behavior_changes", [])),
        "CALLOUTS": "".join(f'<li class="{SEVERITY_CLASS.get(c.get("severity"), "sev-info")}">'
                            f'<span class="sev">{esc(mask(c.get("severity", "info")))}</span> {esc(mask(c.get("text", "")))} '
                            f'{refs(c.get("refs", []))}</li>' for c in expl.get("callouts", [])),
        "MUST_READ": "".join(f'<li>{ref_html(m.get("ref", ""))} — {esc(mask(m.get("why", "")))}</li>'
                             for m in expl.get("must_read", []))
                     + "".join(f'<li>+{esc(h["more"])} more matching {esc(mask(h.get("rule", "")))} — see the PR\'s Files view</li>'
                               for h in facts.get("policy_hits", []) if h.get("more")),
        "ORDER": "".join(f"<li>{ref_html(r)}</li>" for r in expl.get("reading_order", [])),
        "NOT_COVERED": "".join(f"<li>{esc(mask(n))}</li>" for n in expl.get("not_covered", []))
                       or "<li>Nothing: every changed app was rendered.</li>",
    }
    page = (Path(__file__).resolve().parent.parent / "assets" / "template.html").read_text()
    for key, value in subs.items():
        page = page.replace("{{" + key + "}}", value)
    return page


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--facts", required=True)
    ap.add_argument("--explainer", required=True)
    ap.add_argument("--errors", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--standalone", action="store_true")
    args = ap.parse_args()
    facts = json.loads(Path(args.facts).read_text())
    expl = json.loads(Path(args.explainer).read_text())
    errors = []
    if args.errors:
        try:
            errors = json.loads(Path(args.errors).read_text())
            if not isinstance(errors, list):
                raise ValueError("not a list")
        except Exception:
            errors = ["verify did not complete (errors file missing or invalid)"]
    page = render(facts, expl, errors)
    Path(args.out).write_text(STANDALONE_HEAD + page + STANDALONE_TAIL if args.standalone else page)
    print(f"render: wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
