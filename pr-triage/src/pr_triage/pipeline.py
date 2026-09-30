"""One triage pass for one PR, shared by `run` and `calibrate`."""
from __future__ import annotations

import sys
from functools import partial

from . import gh
from .claude import claude_decide, make_client
from .decide import Decision, decide
from .features import Features, extract_features
from .jev import ask_jev
from .policy import Policy
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


def triage_pr(repo: str, pr: dict, files: list[dict], policy: Policy, *,
              jev_model: str, claude_model: str) -> tuple[Features, Decision]:
    features = extract_features(pr, files, policy, make_fetch(repo))
    rules = apply_rules(features, files, policy)
    clients: dict = {}

    def claude_decide_fn(state: dict, jev: dict | None) -> tuple[str, str]:
        if "c" not in clients:
            clients["c"] = make_client()
        return claude_decide(clients["c"], claude_model, state, jev)

    decision = decide(features, rules, policy, partial(ask_jev, model=jev_model), claude_decide_fn)
    return features, decision
