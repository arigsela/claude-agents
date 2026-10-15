#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///
"""explainer: render facts.json + explainer.json into one HTML page (spec §6.5).

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

import ref_groups

MAX_NODES = 40
NODE_CLASS = {"added": "added", "modified": "modified", "removed": "removed",
              "context": "context", "generated": "context"}
# Plan actions from a plan comment, then source-level actions from the no-plan block comparison.
TF_CLASS = {"create": "added", "update": "modified", "replace": "modified", "destroy": "removed", "read": "context",
            "added": "added", "modified": "modified", "removed": "removed"}
# Ticket criterion statuses as the reader sees them; verify.py owns the allowed set.
STATUS_LABEL = {"covered": "covered", "not_covered": "not covered", "unclear": "unclear",
                "out_of_band": "done outside this PR", "respected": "respected"}
SEVERITY_CLASS = {"high": "sev-high", "medium": "sev-med", "info": "sev-info"}
# Walkthrough hunks are read inline; past this many lines the step links to the PR instead.
MAX_HUNK_LINES = 60
HUNK_HEADER_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
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


# A secret-looking key, bare (YAML, env, HCL) or quoted (JSON, "key": "value"), followed by a value.
SECRET_VALUE_RE = re.compile(
    r"(?i)(['\"]?(?:password|passwd|token|secret|api[_-]?key|private[_-]?key|credential)s?[\w-]*['\"]?\s*[:=]\s*['\"]?)"
    r"([^'\"\s]{8,})")
# Kubernetes Secret data is base64; a long base64 value after a key is masked wherever it appears.
BASE64_VALUE_RE = re.compile(r"^([+\- ]?\s*[\w.\-/\"']+\s*:\s*['\"]?)([A-Za-z0-9+/]{24,}={0,2})(['\"]?\s*)$")
# A YAML "key:" line in a diff: diff prefix, indentation, key (with the colon), value (may be empty).
KEY_LINE_RE = re.compile(r"^([+\- ]?)(\s*)([\w.\-/\"']+\s*:)(\s*)(.*)$")
SECRET_KEY_RE = re.compile(r"(?i)(?:password|passwd|token|secret|api[_-]?key|private[_-]?key|credential)")
BLOCK_SCALAR_RE = re.compile(r"^[|>][-+0-9]*\s*(#.*)?$")
# In a Secret's hunk a value survives only when it is a top-level structural key, or sits under
# metadata: (names and labels). Every other line is masked by position, because a hunk deep
# inside data:/stringData: shows no block header and a data entry may be called name or type.
SECRET_TOP_KEYS = {"apiversion", "kind", "metadata", "type", "immutable", "data", "stringdata", "spec"}
SECRET_META_KEYS = {"name", "namespace", "generatename", "labels", "annotations"}
HUNK_CONTEXT_RE = re.compile(r"^@@[^@]*@@\s*(.*)$")


def esc(value) -> str:
    return html.escape(str(value), quote=True)


def mask(value) -> str:
    """Mask secret-looking values in model text; apply before esc()."""
    return SECRET_VALUE_RE.sub(r"\1[REDACTED]", str(value))


def parse_diff(text: str) -> dict[str, list[dict]]:
    """{path: [{"old": [start, end], "new": [start, end], "lines": [...]}, ...]} from a unified diff.
    A file is keyed by its head path, or by its base path when the PR deletes it."""
    files: dict[str, list[dict]] = {}
    path, hunk, left = None, None, [0, 0]  # left: old and new lines still owed to the open hunk
    for line in text.splitlines():
        if hunk is not None and (left[0] > 0 or left[1] > 0):
            # Inside a hunk every line is content, including "--- x" (a removed "-- x") or "+++ x".
            if line.startswith("\\"):
                hunk["lines"].append(line)
                continue
            kind = line[:1] if line else " "
            if kind == "-":
                left[0] -= 1
            elif kind == "+":
                left[1] -= 1
            elif kind == " ":
                left[0] -= 1
                left[1] -= 1
            else:
                hunk = None  # a malformed diff: stop the hunk rather than swallow the next file
            if hunk is not None:
                hunk["lines"].append(line)
                continue
        if line.startswith("diff --git "):
            path, hunk = None, None
        elif line.startswith(("--- ", "+++ ")):
            name = line[4:].split("\t")[0]
            if name != "/dev/null":  # "--- a/x" is set first; "+++ b/x" overrides it unless the file was deleted
                path = name[2:] if name[:2] in ("a/", "b/") else name
            hunk = None
        elif m := HUNK_HEADER_RE.match(line):
            if path is None:
                continue
            old, old_n = int(m.group(1)), int(m.group(2)) if m.group(2) is not None else 1
            new, new_n = int(m.group(3)), int(m.group(4)) if m.group(4) is not None else 1
            hunk = {"old": [old, old + max(old_n, 1) - 1], "new": [new, new + max(new_n, 1) - 1], "lines": [line]}
            left = [old_n, new_n]
            files.setdefault(path, []).append(hunk)
    return files


def hunks_for(item: dict, diff: dict[str, list[dict]], end: int | None = None) -> list[dict]:
    """The hunks of the diff a ref points at. A resource with a line range takes the hunks that
    overlap it. A Terraform block or workflow job knows only its first line; `end` is the first
    line of the next item in the same file (the caller computes it), and the block takes the hunks
    between the two. Without a boundary it takes the hunk holding its first line, or else the next
    hunk below only when that hunk's header context names the item (git puts the enclosing
    `resource "type" "name"` line there), so another block's edit is never shown as this one's. A
    file without line info (a script, a values file) takes every hunk. A rendered resource whose
    file is not in the diff (a chart bump) gets none: the page shows its changed paths instead."""
    path = item.get("file")
    if not path or path not in diff:
        return []
    side = "old" if item.get("action") in ("removed", "destroy") else "new"
    lines = [n for n in (item.get("lines") or []) if isinstance(n, int)]
    if not lines:
        return diff[path]
    lo, hi = lines[0], lines[-1]
    if len(lines) == 1 and end is not None and end > lo:
        hi = end - 1
    hit = [h for h in diff[path] if h[side][0] <= hi and h[side][1] >= lo]
    if not hit and len(lines) == 1 and end is None:
        name = str(item.get("name") or "")
        below = [h for h in diff[path] if h[side][0] > lo][:1]
        hit = [h for h in below if name and f'"{name}"' in h["lines"][0]]
    return hit


def next_item_start(item: dict, index: dict[str, dict]) -> int | None:
    """The first line of the next item in the same file, so a single-line ref stops there."""
    path, lines = item.get("file"), item.get("lines") or []
    if not path or not lines or not isinstance(lines[0], int):
        return None
    starts = [x["lines"][0] for x in index.values()
              if x is not item and x.get("file") == path and isinstance((x.get("lines") or [None])[0], int)
              and x["lines"][0] > lines[0]]
    return min(starts) if starts else None


def mask_hunk_lines(lines: list[str], secret: bool = False) -> list[str]:
    """Mask credentials in diff lines. On top of mask(): long base64 values after any key; the
    indented lines of a block scalar under a secret-looking key (password: |); and, when the hunk
    belongs to a Secret (the caller says so, or a Secret is named in the hunk), every line except
    top-level structural keys and the names and labels under metadata:. The section is tracked by
    indentation from the hunk header's context and the top-level keys seen, so a hunk deep inside
    data: or stringData:, with no block header in view, masks everything indented. Keys stay
    visible so the reader still sees what changed."""
    out = []
    if any(re.search(r"kind:\s*['\"]?(Sealed)?Secret\b", ln) for ln in lines):
        secret = True
    section, meta_sub, block = None, None, None  # top-level key; key under metadata; block-scalar indent
    for line in lines:
        if line.startswith("@@"):
            ctx = HUNK_CONTEXT_RE.match(line)
            head = (ctx.group(1).strip() if ctx else "")
            section = head[:-1].strip().lower() if head.endswith(":") and " " not in head else None
            meta_sub, block = None, None
            out.append(line)
            continue
        if line.startswith("\\"):
            out.append(line)
            continue
        m = KEY_LINE_RE.match(line)
        prefix = line[:1] if line[:1] in "+- " else ""
        body = line[len(prefix):]
        indent, blank = len(body) - len(body.lstrip()), not body.strip()
        if block is not None:
            if not blank and indent <= block:
                block = None  # the scalar ended
            else:
                out.append(line if blank else f"{prefix}{' ' * indent}[REDACTED]")
                continue
        if m:
            key = m.group(3)[:-1].strip().strip("\"'").lower()
            value = m.group(5)
            if indent == 0:
                section, meta_sub = key, None
            elif section == "metadata" and indent <= 2:
                meta_sub = key
            if SECRET_KEY_RE.search(key) and BLOCK_SCALAR_RE.match(value.strip()):
                block = indent
            if secret:
                safe = ((indent == 0 and key in SECRET_TOP_KEYS)
                        or (section == "metadata" and (key in SECRET_META_KEYS or meta_sub == "labels")))
                if not safe and value.strip():
                    line = f"{m.group(1)}{m.group(2)}{m.group(3)}{m.group(4)}[REDACTED]"
                elif not safe and (indent == 0 or section in ("data", "stringdata", None)):
                    block = indent  # an empty value opens a nested block inside data: mask its children
        elif secret and not blank and not (section == "metadata" and meta_sub == "labels"):
            line = f"{prefix}{' ' * indent}[REDACTED]"
        line = mask(line)
        line = BASE64_VALUE_RE.sub(r"\1[REDACTED]\3", line)
        out.append(line)
    return out


def hunk_html(hunks: list[dict], secret: bool = False) -> str:
    """One <pre> per step; +/- lines carry a class, every line is masked then escaped."""
    out, shown, total = [], 0, sum(len(h["lines"]) for h in hunks)
    for h in hunks:
        for line in mask_hunk_lines(h["lines"], secret):
            if shown >= MAX_HUNK_LINES:
                break
            cls = "add" if line.startswith("+") else "del" if line.startswith("-") else "hdr" if line.startswith("@@") else ""
            text = esc(line)
            out.append(f'<span class="{cls}">{text}</span>' if cls else text)
            shown += 1
    if shown < total:
        out.append(f'<span class="hdr">… {total - shown} more lines; open the PR to read the rest</span>')
    return '<pre class="hunk">' + "\n".join(out) + "</pre>"


def label(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9 ._:/-]", " ", str(text))[:60].strip() or "?"


def tf_label(t: dict) -> str:
    """type · name, with a for_each key or count index in parentheses: aws_x · y (search)."""
    index = re.search(r'\[("?)([^\]"]*)\1\]$', t["address"])
    return f'{label(t["type"])} · {label(t["name"])}' + (f" ({label(index.group(2))})" if index else "")


def edge_line(e: dict, src: str, dst: str) -> str:
    # "references" is the default relationship; labelling every arrow with it only adds noise.
    return f"  {src} --> {dst}" if e["type"] == "references" else f'  {src} -->|{e["type"]}| {dst}'


def tf_groups(tf: list[dict]) -> list[list[dict]]:
    """for_each/count instances of one block with the same action, so N instances draw as one node."""
    groups: dict[tuple, list[dict]] = {}
    for t in tf:
        groups.setdefault((t.get("file") or "plan", t["type"], t["name"], t["action"]), []).append(t)
    return list(groups.values())


def base_app(r: dict) -> str:
    """The app name without its environment directory, so one app deployed per environment groups."""
    app, scope = r.get("app") or "other", r.get("scope") or ""
    if scope and app.startswith(scope + "/"):
        return app[len(scope) + 1:]
    return app.rsplit(":", 1)[-1] if scope else app


def res_groups(res: list[dict]) -> list[list[dict]]:
    """The same object with the same action in several environments, so it draws as one node."""
    groups: dict[tuple, list[dict]] = {}
    for r in res:
        groups.setdefault((base_app(r), r["kind"], r["namespace"], r["name"], r["action"]), []).append(r)
    return list(groups.values())


def workflow_lines(facts: dict) -> list[str]:
    """One subgraph per workflow file: a node per job, wired by `needs` in run order, and one node
    per (element, action) for settings, triggers, inputs, outputs and secrets, which have no edges."""
    wf = facts.get("workflows") or []
    if not wf:
        return []
    jobs = [w for w in wf if w["element"] == "job"]
    lines, node_of = [], {}
    by_file: dict[str, list[str]] = {}
    if len(jobs) > MAX_NODES:  # collapse jobs per (file, action)
        groups: dict[tuple, list[dict]] = {}
        for w in jobs:
            groups.setdefault((w["file"], w["action"]), []).append(w)
        for i, ((file, action), ws) in enumerate(sorted(groups.items())):
            by_file.setdefault(file, []).append(f'    wj{i}["{len(ws)} jobs {action}"]:::{NODE_CLASS[action]}')
    else:
        for w in jobs:
            node_of[w["id"]] = w["id"]
            calls = f'<br/>uses {label(w["uses"].rsplit("/", 1)[-1])}' if w.get("uses") else ""
            by_file.setdefault(w["file"], []).append(
                f'    {w["id"]}["job · {label(w["name"])}{calls}<br/>{w["action"]}"]:::{NODE_CLASS[w["action"]]}')
    rest: dict[tuple, list[dict]] = {}
    for w in wf:
        if w["element"] != "job":
            rest.setdefault((w["file"], w["element"], w["action"]), []).append(w)
    for i, ((file, element, action), ws) in enumerate(sorted(rest.items(), key=lambda kv: kv[0])):
        text = f'{element} · {label(ws[0]["name"])}' if len(ws) == 1 else f"{len(ws)} {element}s"
        by_file.setdefault(file, []).append(f'    wg{i}["{text}<br/>{action}"]:::{NODE_CLASS[action]}')
    for i, (file, nodes) in enumerate(sorted(by_file.items())):
        lines.append(f'  subgraph wf{i}["{label(file)}"]')
        lines += nodes
        lines.append("  end")
    seen: set[tuple[str, str]] = set()
    for e in facts["edges"]:
        if e["type"] != "needs":
            continue
        # "from needs to" means "to" runs first, so the arrow follows run order.
        src, dst = node_of.get(e["to"]), node_of.get(e["from"])
        if src and dst and (src, dst) not in seen:
            seen.add((src, dst))
            lines.append(f"  {src} --> {dst}")
    return lines


def mermaid(facts: dict) -> str:
    res = facts["resources"]
    groups = res_groups(res)
    if len(groups) > MAX_NODES:
        res = [r for r in res if r["action"] not in ("context", "generated")]
        groups = res_groups(res)
    lines = ["flowchart LR"]
    if len(groups) > MAX_NODES:  # collapse per (app, action)
        collapsed: dict[tuple[str, str], list[dict]] = {}
        for r in res:
            collapsed.setdefault((base_app(r), r["action"]), []).append(r)
        for i, ((app, action), rs) in enumerate(sorted(collapsed.items())):
            kinds = ", ".join(sorted({r["kind"] for r in rs}))
            lines.append(f'  g{i}["{label(app)} · {len(rs)} {action} · {label(kinds)}"]:::{NODE_CLASS[action]}')
    else:
        node_of: dict[str, str] = {}  # resource id -> mermaid node id
        by_app: dict[str, list[str]] = {}
        for i, g in enumerate(groups):
            first = g[0]
            node = first["id"] if len(g) == 1 else f"rg{i}"
            count = f" ×{len(g)}" if len(g) > 1 else ""
            node_of.update({r["id"]: node for r in g})
            by_app.setdefault(base_app(first), []).append(
                f'    {node}["{label(first["kind"])} · {label(first["name"])}{count}"]:::{NODE_CLASS[first["action"]]}')
        for i, (app, nodes) in enumerate(sorted(by_app.items())):
            lines.append(f'  subgraph s{i}["{label(app)}"]')
            lines += nodes
            lines.append("  end")
        seen_edges: set[tuple[str, str, str]] = set()
        for e in facts["edges"]:
            src, dst = node_of.get(e["from"]), node_of.get(e["to"])
            if src and dst and src != dst and (src, dst, e["type"]) not in seen_edges:
                seen_edges.add((src, dst, e["type"]))
                lines.append(edge_line(e, src, dst))
    tf = facts.get("terraform") or []
    groups = tf_groups(tf)
    if len(groups) > MAX_NODES:  # collapse per action
        for action in sorted({t["action"] for t in tf}):
            ts = [t for t in tf if t["action"] == action]
            types = ", ".join(sorted({t["type"] for t in ts}))
            lines.append(f'  tg_{action}["terraform · {len(ts)} {action} · {label(types)}"]:::{TF_CLASS[action]}')
    elif tf:
        node_of: dict[str, str] = {}  # terraform id -> mermaid node id
        by_file: dict[str, list[str]] = {}
        for i, g in enumerate(groups):
            first = g[0]
            if len(g) == 1:
                node, text = first["id"], tf_label(first)
            else:
                node, text = f"tfg{i}", f'{label(first["type"])} · {label(first["name"])} ×{len(g)}'
            node_of.update({t["id"]: node for t in g})
            by_file.setdefault(first.get("file") or "plan", []).append(
                f'    {node}["{text}<br/>{first["action"]}"]:::{TF_CLASS[first["action"]]}')
        for i, (file, nodes) in enumerate(sorted(by_file.items())):
            lines.append(f'  subgraph tf{i}["{label(file)}"]')
            lines += nodes
            lines.append("  end")
        seen: set[tuple[str, str, str]] = set()
        for e in facts["edges"]:
            src, dst = node_of.get(e["from"]), node_of.get(e["to"])
            if src and dst and src != dst and (src, dst, e["type"]) not in seen:
                seen.add((src, dst, e["type"]))
                lines.append(edge_line(e, src, dst))
    lines += workflow_lines(facts)
    lines += ["  classDef added fill:#dcfce7,stroke:#16a34a,color:#052e16",
              "  classDef modified fill:#fef3c7,stroke:#d97706,color:#451a03",
              "  classDef removed fill:#fee2e2,stroke:#dc2626,color:#450a0a,stroke-dasharray:4 3",
              "  classDef context fill:#f1f5f9,stroke:#94a3b8,color:#334155"]
    return "\n".join(lines)


def template_path(mode: str) -> Path:
    """assets/template-<mode>.html at the plugin root; pr and system pages differ in their sections."""
    return Path(__file__).resolve().parent.parent / "assets" / f"template-{mode}.html"


def as_list(value) -> list:
    return value if isinstance(value, list) else []


def as_dicts(value) -> list[dict]:
    return [v for v in as_list(value) if isinstance(v, dict)]


def as_dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def as_refs(value) -> list[str]:
    return [r for r in as_list(value) if isinstance(r, str)]


def render(facts: dict, expl: dict, errors: list[str], diff: dict[str, list[dict]] | None = None) -> str:
    """The page. A failed verify still renders (with the Unverified banner), so every explainer
    field is read through as_list/as_dict/as_refs and a wrong-shaped entry is skipped, never raised on."""
    pr = facts["pr"]
    diff = diff or {}
    expl = as_dict(expl)
    index = {x["id"]: x for key in ("resources", "non_manifest_changes", "terraform", "workflows")
             for x in facts.get(key) or []}
    index.update({c["id"]: c for c in (facts.get("jira") or {}).get("comments") or [] if c.get("id")})

    def ref_url(item: dict) -> str | None:
        if "created" in item:  # ticket comment
            return item.get("url")
        path = item.get("file")
        if not path:
            return None
        url = f'{pr["url"]}/files#diff-{hashlib.sha256(path.encode()).hexdigest()}'
        start = (item.get("lines") or [None])[0] or ((item.get("hunks") or [[None]])[0][0])
        if start:
            # A removed block's line number is on the base side of the diff.
            url += f'{"L" if item.get("action") in ("removed", "destroy") else "R"}{start}'
        return url

    def ref_link(item: dict | None, text: str) -> str:
        url = ref_url(item) if item else None
        return f'<a href="{esc(url)}">{esc(text)}</a>' if url else (esc(text) if item else f"<code>{esc(text)}</code>")

    def ref_html(rid) -> str:
        rid = rid if isinstance(rid, str) else str(rid)
        item = index.get(rid)
        return ref_link(item, "".join(ref_groups.segments(item, rid)))

    def refs(ids: list[str]) -> str:
        """One line per group; refs that differ in one place render as prefix{a, b, c}suffix."""
        out = []
        for pos, members in ref_groups.group([ref_groups.entry(index.get(r), r) for r in as_refs(ids)]):
            if pos is None:
                out.append(f'<span class="ref">{ref_html(members[0][0])}</span>')
                continue
            segs = members[0][1]
            pre, core, suf = ref_groups.trim([m[1][pos] for m in members])
            links = ", ".join(ref_link(index.get(m[0]), c) for m, c in zip(members, core))
            out.append(f'<span class="ref">{esc("".join(segs[:pos]) + pre)}{{{links}}}{esc(suf + "".join(segs[pos + 1:]))}</span>')
        return "".join(out)

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
    jira, ticket = facts.get("jira"), as_dict(expl.get("ticket"))
    if jira:
        key = esc(jira["key"])
        link = f'<a href="{esc(jira["url"])}">{key}</a>' if jira.get("url") else key
        parent = jira.get("parent") or {}
        meta = " · ".join(x for x in (
            link, esc(jira.get("type") or ""),
            f'<span class="pill">{esc(jira["status"])}</span>' if jira.get("status") else "",
            f'parent {esc(parent.get("key") or "")} {esc(mask(parent.get("summary") or ""))}' if parent else "") if x)
        criteria = "".join(f'<tr><td>{esc(mask(c.get("text", "")))}</td>'
                           f'<td><span class="pill">{esc(STATUS_LABEL.get(c.get("status"), c.get("status", "")))}</span></td>'
                           f'<td>{esc(mask(c.get("reason", "")))}</td><td>{refs(c.get("refs", []))}</td></tr>'
                           for c in as_dicts(ticket.get("criteria")))
        ticket_html = ('<h2>Ticket</h2><div class="card">'
                       f'<div class="meta">{meta}</div><p><strong>{esc(mask(jira.get("summary") or ""))}</strong></p>'
                       + (f'<p>{esc(mask(ticket["intent"]))}</p>' if isinstance(ticket.get("intent"), str) else "")
                       + ('<div class="scroll"><table><thead><tr><th>Ticket asks for</th><th>Status</th><th>Why</th><th>Refs</th>'
                          f'</tr></thead><tbody>{criteria}</tbody></table></div>' if criteria else "")
                       + "</div>")
    must_refs = {m.get("ref") for m in as_dicts(expl.get("must_read"))}
    steps = []
    for step in as_list(expl.get("reading_order")):
        rid = step.get("ref") if isinstance(step, dict) else step
        rid = rid if isinstance(rid, str) else str(rid)
        note = f' — {esc(mask(step.get("note", "")))}' if isinstance(step, dict) and step.get("note") else ""
        item = index.get(rid) or {}
        hunks = hunks_for(item, diff, next_item_start(item, index)) if item else []
        if hunks:
            # Must-read hunks start open; the rest fold so a long PR still skims.
            secret = str(item.get("kind", "")).endswith("Secret") or any(
                str(r.get("kind", "")).endswith("Secret") for r in facts.get("resources") or [] if r.get("file") == item.get("file"))
            steps.append(f'<li><details{" open" if rid in must_refs else ""}><summary>{ref_html(rid)}{note}</summary>'
                         f'{hunk_html(hunks, secret)}</details></li>')
        else:
            paths = item.get("changed_paths") or []
            where = (f'<p class="meta">Changed: {", ".join(f"<code>{esc(x)}</code>" for x in paths)}</p>' if paths
                     else '<p class="meta">No hunk in the diff for this item.</p>' if item else "")
            steps.append(f"<li>{ref_html(rid)}{note}{where}</li>")

    quiz = []
    for q in as_dicts(expl.get("quiz")):
        opts = "".join(
            f'<button type="button" class="opt" data-correct="{1 if o.get("correct") is True else 0}" '
            f'data-why="{esc(mask(o.get("explanation", "")))}">{esc(mask(o.get("text", "")))}</button>'
            for o in as_dicts(q.get("options")))
        quiz.append(f'<li class="q"><p>{esc(mask(q.get("question", "")))}</p><div class="opts">{opts}</div>'
                    f'<div class="why" hidden></div><p class="meta">{refs(q.get("refs", []))}</p></li>')

    scenario = as_dict(expl.get("scenario"))
    scenario_html = (
        f'<div class="card"><p><strong>Trigger:</strong> {esc(mask(scenario.get("trigger", "")))}</p>'
        '<div class="scroll"><table><thead><tr><th>Before this PR</th><th>After this PR</th></tr></thead>'
        f'<tbody><tr><td>{esc(mask(scenario.get("before", "")))}</td><td>{esc(mask(scenario.get("after", "")))}</td></tr>'
        f'</tbody></table></div><p class="meta">{refs(scenario.get("refs", []))}</p></div>'
        if scenario else '<div class="card"><p class="meta">No scenario was written.</p></div>')

    subs = {
        "TITLE": esc(f"PR {pr['number']} explainer"),
        "PR_TITLE": esc(pr["title"]),
        "HEADER": header,
        "BANNER": banner,
        "TLDR": esc(mask(expl.get("tldr", ""))),
        "BACKGROUND": "".join(f'<p>{esc(mask(b.get("text", "")))} <span class="meta">{refs(b.get("refs", []))}</span></p>'
                              for b in as_dicts(expl.get("background")))
                      or '<p class="meta">No background was written.</p>',
        "SCENARIO": scenario_html,
        "TICKET": ticket_html,
        "PLANS": plans,
        "MERMAID": esc(mermaid(facts)),
        "BEHAVIOR": "".join(f'<tr><td>{esc(mask(b.get("app", "")))}</td><td>{esc(mask(b.get("before", "")))}</td>'
                            f'<td>{esc(mask(b.get("after", "")))}</td><td>{refs(b.get("refs", []))}</td></tr>'
                            for b in as_dicts(expl.get("behavior_changes"))),
        "CALLOUTS": "".join(f'<li class="{SEVERITY_CLASS.get(c.get("severity"), "sev-info")}">'
                            f'<span class="sev">{esc(mask(c.get("severity", "info")))}</span> {esc(mask(c.get("text", "")))} '
                            f'{refs(c.get("refs", []))}</li>' for c in as_dicts(expl.get("callouts"))),
        "MUST_READ": "".join(f'<li>{ref_html(m.get("ref", ""))} — {esc(mask(m.get("why", "")))}</li>'
                             for m in as_dicts(expl.get("must_read")))
                     + "".join(f'<li>+{esc(h["more"])} more matching {esc(mask(h.get("rule", "")))} — see the PR\'s Files view</li>'
                               for h in facts.get("policy_hits", []) if h.get("more")),
        "WALKTHROUGH": "".join(steps) or '<li class="meta">No reading order was written.</li>',
        "QUIZ": "".join(quiz) or '<li class="meta">No quiz was written.</li>',
        "NOT_COVERED": "".join(f"<li>{esc(mask(n))}</li>" for n in as_list(expl.get("not_covered")))
                       or "<li>Nothing: every changed app was rendered.</li>",
    }
    page = template_path(facts.get("mode") or "pr").read_text()
    for key, value in subs.items():
        page = page.replace("{{" + key + "}}", value)
    return page


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--facts", required=True)
    ap.add_argument("--explainer", required=True)
    ap.add_argument("--errors", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--diff", help="the PR's unified diff (collect.py's diff.patch), for inline walkthrough hunks")
    ap.add_argument("--standalone", action="store_true")
    args = ap.parse_args()
    facts = json.loads(Path(args.facts).read_text())
    expl = json.loads(Path(args.explainer).read_text())
    diff = parse_diff(Path(args.diff).read_text()) if args.diff and Path(args.diff).is_file() else {}
    errors = []
    if args.errors:
        try:
            errors = json.loads(Path(args.errors).read_text())
            if not isinstance(errors, list):
                raise ValueError("not a list")
        except Exception:
            errors = ["verify did not complete (errors file missing or invalid)"]
    page = render(facts, expl, errors, diff)
    Path(args.out).write_text(STANDALONE_HEAD + page + STANDALONE_TAIL if args.standalone else page)
    print(f"render: wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
