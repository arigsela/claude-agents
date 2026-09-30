"""CLI: python -m pr_triage features ..."""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict

from . import gh
from .features import extract_features
from .policy import load_policy
from .rules import apply_rules

POLICY_PATH = ".github/review-policy.yaml"


def policy_text(repo: str, ref: str, policy_file: str | None) -> str:
    if policy_file:
        with open(policy_file) as fh:
            return fh.read()
    text = gh.get_file(repo, POLICY_PATH, ref)
    if text is None:
        sys.exit(f"pr-triage: {POLICY_PATH} not found at {ref} (pass --policy-file)")
    return text


def make_fetch(repo: str):
    cache: dict[tuple[str, str], str | None] = {}

    def fetch(path: str, ref: str) -> str | None:
        if (path, ref) not in cache:
            cache[(path, ref)] = gh.get_file(repo, path, ref)
        return cache[(path, ref)]
    return fetch


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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="pr_triage")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("features", help="print deterministic features + rule result for one PR")
    p.add_argument("--repo", required=True)
    p.add_argument("--pr", type=int, required=True)
    p.add_argument("--policy-ref")
    p.add_argument("--policy-file")
    args = ap.parse_args(argv)
    return cmd_features(args)


if __name__ == "__main__":
    sys.exit(main())
