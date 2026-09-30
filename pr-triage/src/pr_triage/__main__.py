"""CLI: python -m pr_triage {features,run,calibrate}."""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict

from . import gh
from .claude import ClaudeError, claude_note, make_client
from .comment import apply_label, render_comment, upsert_comment
from .features import extract_features
from .pipeline import make_fetch, policy_text, triage_pr
from .policy import load_policy
from .rules import apply_rules


def cmd_features(args) -> int:
    pr = gh.get_pr(args.repo, args.pr)
    policy = load_policy(policy_text(args.repo, args.policy_ref or pr["base"]["sha"], args.policy_file))
    files = gh.get_pr_files(args.repo, args.pr)
    features = extract_features(pr, files, policy, make_fetch(args.repo))
    out = asdict(features)
    out["diff_excerpt"] = f"<{len(features.diff_excerpt)} chars>"
    out["rules"] = asdict(apply_rules(features, files, policy))
    print(json.dumps(out, indent=2))
    return 0


def cmd_run(args) -> int:
    pr = gh.get_pr(args.repo, args.pr)
    policy_ref = args.policy_ref or pr["base"]["sha"]
    policy = load_policy(policy_text(args.repo, policy_ref, args.policy_file))
    files = gh.get_pr_files(args.repo, args.pr)
    features, decision = triage_pr(args.repo, pr, files, policy,
                                   jev_model=args.jev_model, claude_model=args.claude_model)
    note: list[str] = []
    if decision.label in ("skim", "read"):
        try:
            note = claude_note(make_client(), args.claude_model, features.jev_state(),
                               decision.label, decision.reasons)
        except ClaudeError as err:
            print(f"pr-triage: note skipped: {err}", file=sys.stderr)
    versions = {"action": os.environ.get("PR_TRIAGE_REF", "local"), "jev": args.jev_model,
                "claude": args.claude_model,
                "policy": "local file" if args.policy_file else policy_ref[:7]}
    body = render_comment(args.pr, features, decision, note, versions)
    if args.dry_run:
        print(body)
        return 0
    upsert_comment(args.repo, args.pr, body)
    apply_label(args.repo, args.pr, decision.label)
    print(f"pr-triage: #{args.pr} -> review:{decision.label} ({decision.decided_by})")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="pr_triage")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("features", "run"):
        p = sub.add_parser(name)
        p.add_argument("--repo", required=True)
        p.add_argument("--pr", type=int, required=True)
        p.add_argument("--policy-ref", help="commit to read the policy from (default: PR base SHA)")
        p.add_argument("--policy-file", help="local policy file (before it is merged)")
        p.add_argument("--jev-model", default="jev-1.13.0")
        p.add_argument("--claude-model", default="claude-haiku-4-5")
        p.add_argument("--dry-run", action="store_true", help="print the comment; write nothing")
    c = sub.add_parser("calibrate", help="replay triage on merged PRs vs the follow-up heuristic")
    c.add_argument("--repo", required=True)
    c.add_argument("--limit", type=int, default=200)
    c.add_argument("--policy-file")
    c.add_argument("--compare", choices=["haiku"])
    c.add_argument("--out", default="calibration.md")
    c.add_argument("--jev-model", default="jev-1.13.0")
    c.add_argument("--claude-model", default="claude-haiku-4-5")
    args = ap.parse_args(argv)
    if args.cmd == "features":
        return cmd_features(args)
    if args.cmd == "calibrate":
        from .calibrate import cmd_calibrate
        return cmd_calibrate(args)
    return cmd_run(args)


if __name__ == "__main__":
    sys.exit(main())
