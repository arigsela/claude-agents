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


def esc(value) -> str:
    return html.escape(str(value), quote=True)


def label(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9 ._:/-]", " ", str(text))[:60].strip() or "?"


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
            url += f"R{start}"
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
              + (f' · <span class="pill">{esc(triage["label"])}</span>' if triage.get("label") else ""))
    subs = {
        "TITLE": esc(f"PR {pr['number']} explainer"),
        "PR_TITLE": esc(pr["title"]),
        "HEADER": header,
        "BANNER": banner,
        "TLDR": esc(expl.get("tldr", "")),
        "MERMAID": esc(mermaid(facts)),
        "BEHAVIOR": "".join(f'<tr><td>{esc(b.get("app", ""))}</td><td>{esc(b.get("before", ""))}</td>'
                            f'<td>{esc(b.get("after", ""))}</td><td>{refs(b.get("refs", []))}</td></tr>'
                            for b in expl.get("behavior_changes", [])),
        "CALLOUTS": "".join(f'<li class="{SEVERITY_CLASS.get(c.get("severity"), "sev-info")}">'
                            f'<span class="sev">{esc(c.get("severity", "info"))}</span> {esc(c.get("text", ""))} '
                            f'{refs(c.get("refs", []))}</li>' for c in expl.get("callouts", [])),
        "MUST_READ": "".join(f'<li>{ref_html(m.get("ref", ""))} — {esc(m.get("why", ""))}</li>'
                             for m in expl.get("must_read", [])),
        "ORDER": "".join(f"<li>{ref_html(r)}</li>" for r in expl.get("reading_order", [])),
        "NOT_COVERED": "".join(f"<li>{esc(n)}</li>" for n in expl.get("not_covered", []))
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
    ap.add_argument("--errors")
    ap.add_argument("--out", required=True)
    ap.add_argument("--standalone", action="store_true")
    args = ap.parse_args()
    facts = json.loads(Path(args.facts).read_text())
    expl = json.loads(Path(args.explainer).read_text())
    errors = json.loads(Path(args.errors).read_text()) if args.errors and Path(args.errors).exists() else []
    page = render(facts, expl, errors)
    Path(args.out).write_text(STANDALONE_HEAD + page + STANDALONE_TAIL if args.standalone else page)
    print(f"render: wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
