#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///
"""review-retro: build retro-case.json from review transcripts + GitHub ground truth (spec §7.3).

Token notes: session totals come from the transcript's last `cost-state` record (authoritative,
includes subagents). Per-agent tokens are summed from message.usage deduplicated by requestId and
are labelled approximate: per-step output_tokens under-count.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from followups import followups_for, merged_prs, parse_ts  # noqa: E402

LINK_RE = re.compile(r"https://github\.com/[^/\s]+/[^/\s]+/blob/[0-9a-f]{7,40}/(\S+?)#L(\d+)(?:-L(\d+))?")
ITEM_RE = re.compile(r"^\s*(\d+)\.\s+(.+)$")
TRUNC_RE = re.compile(r"(?i)(output too large|truncated|tool-results/)")
HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", re.M)
REVIEW_HEADER = "## Code review"
PATCH_CAP = 8000
MARKERS = ("<!-- pr-triage -->", "<!-- pr-explainer")


def gh_json(*args: str):
    return json.loads(subprocess.run(["gh", *args], capture_output=True, text=True, check=True).stdout)


def gh_pages(path: str) -> list[dict]:
    return [x for page in gh_json("api", "--paginate", "--slurp", path) for x in page]


def load(path: Path) -> list[tuple[int, dict]]:
    out = []
    with path.open(errors="replace") as fh:
        for i, line in enumerate(fh, start=1):
            try:
                out.append((i, json.loads(line)))
            except json.JSONDecodeError:
                pass
    return out


def blocks(rec: dict) -> list[dict]:
    content = (rec.get("message") or {}).get("content")
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return [b for b in content or [] if isinstance(b, dict)]


def result_text(block: dict) -> str:
    content = block.get("content")
    if isinstance(content, str):
        return content
    return "\n".join(x.get("text", "") for x in content or [] if isinstance(x, dict))


def hunks(patch: str) -> list[list[int]]:
    out = []
    for m in HUNK_RE.finditer(patch or ""):
        start = int(m.group(1))
        out.append([start, start + max(int(m.group(2) or 1), 1) - 1])
    return out


def summarize(path: Path, recs, changed: list[str], start: int = 1, end: int | None = None):
    """Per-transcript activity inside [start, end]. Returns (summary, tool_use ids, tool results)."""
    tool_uses: dict[str, tuple[str, dict]] = {}
    seen, partial, usage, texts, results = set(), set(), {}, [], []
    pending_reads: dict[str, tuple[str, bool]] = {}
    handback = None
    started = ended = None
    for ln, rec in recs:
        if ln < start or (end is not None and ln > end):
            continue
        ts = rec.get("timestamp")
        started, ended = started or ts, ts or ended
        if rec.get("type") == "assistant":
            u = (rec.get("message") or {}).get("usage")
            if u and rec.get("requestId"):
                usage[rec["requestId"]] = u
            for b in blocks(rec):
                if b.get("type") == "tool_use":
                    tool_uses[b.get("id")] = (b.get("name"), b.get("input") or {})
                    if b.get("name") == "Read":
                        inp = b.get("input") or {}
                        ranged = inp.get("offset") is not None or inp.get("limit") is not None
                        pending_reads[b.get("id")] = (str(inp.get("file_path", "")), ranged)
                    elif b.get("name") == "SubagentHandback":
                        msg = (b.get("input") or {}).get("message")
                        if isinstance(msg, str) and msg.strip():
                            handback = (ln, msg)
                elif b.get("type") == "text" and b.get("text", "").strip():
                    texts.append((ln, b["text"]))
        elif rec.get("type") == "user":
            for b in blocks(rec):
                if b.get("type") != "tool_result":
                    continue
                name, _ = tool_uses.get(b.get("tool_use_id"), ("?", {}))
                text = result_text(b)
                results.append({"tool": name, "chars": len(text), "ref": f"{path}:{ln}"})
                if b.get("tool_use_id") in pending_reads:
                    fp, ranged = pending_reads.pop(b["tool_use_id"])
                    rbucket = partial if (ranged or b.get("is_error") or TRUNC_RE.search(text)) else seen
                    rbucket.update(p for p in changed if fp == p or fp.endswith("/" + p))
                bucket = partial if TRUNC_RE.search(text) else seen
                bucket.update(p for p in changed if f"diff --git a/{p} b/{p}" in text or (name == "Grep" and p in text))
    tokens = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
    for u in usage.values():
        tokens["input"] += u.get("input_tokens", 0)
        tokens["output"] += u.get("output_tokens", 0)
        tokens["cache_read"] += u.get("cache_read_input_tokens", 0)
        tokens["cache_write"] += u.get("cache_creation_input_tokens", 0)
    summary = {"tool_calls": len(tool_uses), "files_seen": sorted(seen), "files_partial": sorted(partial - seen),
               "tokens_approx": tokens, "started": started, "ended": ended,
               "final_text": (handback or (texts[-1] if texts else (0, "")))[1][:4000],
               "final_text_ref": (f"{path}:{(handback or texts[-1])[0]}" if (handback or texts) else None)}
    return summary, set(tool_uses), results


def parse_findings(text: str, ref: str) -> list[dict]:
    lines = text.splitlines()
    start = next((i for i, l in enumerate(lines) if l.strip().startswith(REVIEW_HEADER)), None)
    if start is None:
        return []
    section = []
    for l in lines[start + 1:]:
        if l.startswith("## "):
            break
        section.append(l)
    items, current, pending_blank = [], None, False
    for line in section:
        if m := ITEM_RE.match(line):
            current = {"n": int(m.group(1)), "parts": [m.group(2).strip()], "links": [], "transcript_ref": ref}
            items.append(current)
            pending_blank = False
            rest = m.group(2)
        elif current is None:
            continue
        elif not line.strip():
            pending_blank = True
            continue
        elif line.lstrip().startswith("#"):
            current = None
            continue
        else:
            rest = line
            current["parts"].append(line.strip())
        if current is not None:
            for link in LINK_RE.finditer(rest):
                current["links"].append({"file": link.group(1),
                                         "lines": [int(link.group(2)), int(link.group(3) or link.group(2))]})
    return [{"n": it["n"], "text": " ".join(it["parts"]).strip(), "links": it["links"],
             "transcript_ref": it["transcript_ref"]} for it in items]


def review(session: Path, start: int, changed: list[str]) -> dict:
    recs = load(session)
    end_ln, output = recs[-1][0] if recs else start, None
    for ln, rec in recs:
        if ln > start and rec.get("type") == "assistant":
            hit = next((b["text"] for b in blocks(rec) if b.get("type") == "text" and REVIEW_HEADER in b.get("text", "")), None)
            if hit:
                end_ln, output = ln, hit
                break
    main_sum, main_tools, results = summarize(session, recs, changed, start, end_ln)
    agents = []
    sub_dir = session.with_suffix("") / "subagents"
    for af in sorted(sub_dir.glob("agent-*.jsonl")) if sub_dir.exists() else []:
        meta_path = af.with_name(af.stem + ".meta.json")
        meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
        if meta.get("toolUseId") and meta["toolUseId"] not in main_tools:
            continue  # spawned outside the review window
        s, _, r = summarize(af, load(af), changed)
        results += r
        agents.append({"id": af.stem, "type": meta.get("agentType"), "description": meta.get("description"),
                       **{k: s[k] for k in ("tool_calls", "files_seen", "files_partial", "tokens_approx",
                                            "final_text", "final_text_ref")}})
    seen = set(main_sum["files_seen"]).union(*[a["files_seen"] for a in agents])
    partial = set(main_sum["files_partial"]).union(*[a["files_partial"] for a in agents]) - seen
    cost = next((r for _, r in reversed(recs) if r.get("type") == "cost-state"), None)
    return {
        "session": str(session),
        "window": {"start_line": start, "end_line": end_ln, "started": main_sum["started"], "ended": main_sum["ended"]},
        "output_ref": f"{session}:{end_ln}" if output else None,
        "findings": parse_findings(output, f"{session}:{end_ln}") if output else [],
        "coverage": {p: "seen" if p in seen else "partial" if p in partial else "unseen" for p in changed},
        "main": {"tool_calls": main_sum["tool_calls"], "tokens_approx": main_sum["tokens_approx"]},
        "agents": agents,
        "cost": ({"source": "cost-state (whole session, includes subagents)", "total_usd": cost.get("totalCostUSD"),
                  "by_model": cost.get("modelUsage")} if cost else None),
        "largest_tool_results": sorted(results, key=lambda x: -x["chars"])[:10],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--pr", type=int, required=True)
    ap.add_argument("--session", action="append", required=True)
    ap.add_argument("--line", type=int, action="append", default=[])
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    lines = args.line + [1] * (len(args.session) - len(args.line))
    pr = gh_json("pr", "view", str(args.pr), "-R", args.repo, "--json", "number,title,url,mergedAt")
    files = gh_pages(f"repos/{args.repo}/pulls/{args.pr}/files?per_page=100")
    changed = [f["filename"] for f in files]
    case = {"pr": {"number": pr["number"], "title": pr["title"], "url": pr["url"], "merged_at": pr["mergedAt"],
                   "files": [{"path": f["filename"], "status": f["status"], "hunks": hunks(f.get("patch"))}
                             for f in files]},
            "reviews": [review(Path(s), ln, changed) for s, ln in zip(args.session, lines)],
            "followups": [], "human_comments": []}
    prs = merged_prs(args.repo)
    me = next((p for p in prs if p["number"] == args.pr), None)
    for q in followups_for(me, prs) if me else []:
        qfiles = gh_pages(f"repos/{args.repo}/pulls/{q['number']}/files?per_page=100")
        case["followups"].append({"number": q["number"], "title": q["title"], "merged_at": q["mergedAt"],
                                  "shared_components": sorted(me["comps"] & q["comps"]),
                                  "files": [{"path": f["filename"], "patch": (f.get("patch") or "")[:PATCH_CAP]}
                                            for f in qfiles]})
    ends = [r["window"]["ended"] for r in case["reviews"] if r["window"]["ended"]]
    review_end = max(parse_ts(e) for e in ends) if ends else None
    sources = [("issue", gh_pages(f"repos/{args.repo}/issues/{args.pr}/comments?per_page=100"), "created_at"),
               ("review-comment", gh_pages(f"repos/{args.repo}/pulls/{args.pr}/comments?per_page=100"), "created_at"),
               ("review", gh_pages(f"repos/{args.repo}/pulls/{args.pr}/reviews?per_page=100"), "submitted_at")]
    for kind, items, ts_key in sources:
        for c in items:
            body = c.get("body") or ""
            if ((c.get("user") or {}).get("type") == "Bot" or not body.strip() or any(m in body for m in MARKERS)
                    or body.strip().startswith(REVIEW_HEADER)):
                continue
            if review_end and c.get(ts_key) and parse_ts(c[ts_key]) <= review_end:
                continue
            case["human_comments"].append({"author": (c.get("user") or {}).get("login"), "created_at": c.get(ts_key),
                                           "kind": kind, "path": c.get("path"), "line": c.get("line"),
                                           "url": c.get("html_url"), "body": body[:2000]})
    Path(args.out).write_text(json.dumps(case, indent=2))
    cov = [v for r in case["reviews"] for v in r["coverage"].values()]
    print(f"extract: {len(case['reviews'])} review(s), {sum(len(r['findings']) for r in case['reviews'])} findings, "
          f"coverage seen/partial/unseen = {cov.count('seen')}/{cov.count('partial')}/{cov.count('unseen')}, "
          f"{len(case['followups'])} follow-ups, {len(case['human_comments'])} human comments -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
