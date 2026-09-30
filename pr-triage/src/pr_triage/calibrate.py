"""Replay triage on merged PRs and measure it against the follow-up heuristic (spec §5.7)."""
from __future__ import annotations

import sys
from collections import Counter
from dataclasses import replace
from datetime import datetime

import yaml

from . import gh
from .claude import ClaudeError, claude_decide, make_client
from .decide import classify
from .followups import MergedPR, find_followups, followup_components
from .jev import PRICE_PER_MTOK
from .pipeline import policy_text, triage_pr
from .policy import Thresholds, load_policy

HOT_MIN_RATE, HOT_MIN_PRS = 0.40, 3
READ_GRID = (0.20, 0.30, 0.40, 0.50)
SKIP_GRID = (0.80, 0.90, 0.95)
BUCKETS = ("tiny", "small", "medium", "large")


def hot_components(prs: list[MergedPR], followups: dict[int, list[int]]) -> dict[str, float]:
    touched, hit = Counter(), Counter()
    for p in prs:
        for c in followup_components(p.paths):
            touched[c] += 1
            hit[c] += bool(followups[p.number])
    return {c: round(hit[c] / n, 2) for c, n in sorted(touched.items())
            if n >= HOT_MIN_PRS and hit[c] / n >= HOT_MIN_RATE}


def relabel(rec: dict, t: Thresholds) -> str:
    """Decision for a stored record under other thresholds (no API calls)."""
    if rec["by"] == "rules" or rec["jev"] is None:
        return rec["label"]
    label, _ = classify(rec["jev"], t)
    if label == "escalate":
        label = rec["claude_label"] or "read"
    if label == "skip" and rec["hot"]:
        label = "skim"
    return label


def metrics(records: list[dict], labels: list[str]) -> dict:
    fu = [lab for rec, lab in zip(records, labels) if rec["followup"]]
    return {"followups": len(fu), "fu_skip": fu.count("skip"), "fu_read": fu.count("read"),
            "skip_share": labels.count("skip") / len(labels) if labels else 0.0}


def pct(a: int, b: int) -> str:
    return f"{a / b:.0%}" if b else "n/a"


def cmd_calibrate(args) -> int:
    rows = gh.list_merged_prs(args.repo, args.limit)
    print(f"calibrate: fetching files for {len(rows)} merged PRs", file=sys.stderr)
    files_by = {r["number"]: gh.get_pr_files(args.repo, r["number"]) for r in rows}
    prs = sorted((MergedPR(r["number"], r["title"],
                           datetime.fromisoformat(r["mergedAt"].replace("Z", "+00:00")),
                           [f["filename"] for f in files_by[r["number"]]]) for r in rows),
                 key=lambda p: p.merged_at)
    followups = find_followups(prs)
    half = len(prs) // 2
    train, test = prs[:half], prs[half:]
    policy = replace(load_policy(policy_text(args.repo, "main", args.policy_file)),
                     hot_components=hot_components(train, followups))
    records, client = [], None
    for i, p in enumerate(test, start=1):
        print(f"calibrate: {i}/{len(test)} #{p.number}", file=sys.stderr)
        pr = gh.get_pr(args.repo, p.number)
        features, d = triage_pr(args.repo, pr, files_by[p.number], policy,
                                jev_model=args.jev_model, claude_model=args.claude_model)
        rec = {"number": p.number, "followup": bool(followups[p.number]), "bucket": features.size_bucket,
               "label": d.label, "by": d.decided_by, "jev": d.jev, "hot": bool(features.hot_components_touched),
               "claude_label": d.label if d.decided_by == "claude" else None}
        if args.compare == "haiku" and d.decided_by != "rules":
            client = client or make_client()
            try:
                rec["compare"] = claude_decide(client, args.claude_model, features.jev_state(), None)[0]
            except ClaudeError as err:
                rec["compare"] = f"error: {err}"
        records.append(rec)
    with open(args.out, "w") as fh:
        fh.write(render_report(args, prs, train, test, followups, policy, records))
    print(f"calibrate: wrote {args.out}")
    return 0


def render_report(args, prs, train, test, followups, policy, records) -> str:
    labels = [r["label"] for r in records]
    m = metrics(records, labels)
    tokens = sum(r["jev"].input_tokens for r in records if r["jev"])
    out = [f"# pr-triage calibration — {args.repo}", "",
           f"- PRs: {len(prs)} merged; older {len(train)} → hot components, newer {len(test)} evaluated",
           f"- Follow-up PRs in the evaluated half: {m['followups']}",
           f"- **Follow-up PRs labelled skip: {m['fu_skip']} ({pct(m['fu_skip'], m['followups'])})** — target ≤ 5%",
           f"- Share of all PRs labelled skip: {m['skip_share']:.0%} — target ≥ 20%",
           f"- Follow-up PRs labelled read: {m['fu_read']} ({pct(m['fu_read'], m['followups'])})",
           f"- Jev input tokens: {tokens:,} (≈ ${tokens / 1e6 * PRICE_PER_MTOK:.4f})",
           f"- Hot components (train half): {policy.hot_components or 'none'}", "",
           "## By size bucket", "", "| bucket | PRs | follow-ups | skip | skim | read | follow-ups in skip |",
           "|---|---|---|---|---|---|---|"]
    for b in BUCKETS:
        rs = [r for r in records if r["bucket"] == b]
        ls = [r["label"] for r in rs]
        out.append(f"| {b} | {len(rs)} | {sum(r['followup'] for r in rs)} | {ls.count('skip')} | "
                   f"{ls.count('skim')} | {ls.count('read')} | "
                   f"{sum(r['followup'] and r['label'] == 'skip' for r in rs)} |")
    out += ["", "## By decided_by", "", "| decided_by | PRs | skip | skim | read |", "|---|---|---|---|---|"]
    for by in ("rules", "jev", "claude", "degraded"):
        ls = [r["label"] for r in records if r["by"] == by]
        out.append(f"| {by} | {len(ls)} | {ls.count('skip')} | {ls.count('skim')} | {ls.count('read')} |")
    compared = [r for r in records if "compare" in r]
    if compared:
        agree = sum(r["compare"] == r["label"] for r in compared)
        fu_skip = sum(r["followup"] and r["compare"] == "skip" for r in compared)
        out += ["", "## Claude-only comparison", "",
                f"- Agreement with the cascade: {agree}/{len(compared)}",
                f"- Follow-up PRs Claude-only would skip: {fu_skip}"]
    out += ["", "## Threshold sweep (offline, same Jev answers)", "",
            "| read_if_p_read_gte | skip_if_p_skip_gte | follow-ups in skip | skip share |", "|---|---|---|---|"]
    best, best_share = None, -1.0
    candidates = [policy.thresholds] + [replace(policy.thresholds, read_if_p_read_gte=r_t, skip_if_p_skip_gte=s_t)
                                        for r_t in READ_GRID for s_t in SKIP_GRID]
    for t in candidates:
        mm = metrics(records, [relabel(r, t) for r in records])
        if t is not policy.thresholds:
            out.append(f"| {t.read_if_p_read_gte:.2f} | {t.skip_if_p_skip_gte:.2f} | "
                       f"{mm['fu_skip']} ({pct(mm['fu_skip'], mm['followups'])}) | {mm['skip_share']:.0%} |")
        safe = mm["followups"] == 0 or mm["fu_skip"] / mm["followups"] <= 0.05
        if safe and mm["skip_share"] > best_share:
            best, best_share = t, mm["skip_share"]
    out += ["", "Escalations without a stored Claude answer count as read (conservative).", ""]
    if best is None:
        best = policy.thresholds
        out += ["> WARNING: no threshold combination met the ≤ 5% follow-up-skip target; "
                "tighten always_read instead of relying on these thresholds.", ""]
    patch = {"thresholds": vars(best), "hot_components": hot_components(prs, followups)}
    out += ["## Suggested policy patch (all PRs for hot components; best safe thresholds)", "",
            "```yaml", yaml.safe_dump(patch, sort_keys=False).rstrip(), "```", ""]
    return "\n".join(out)
