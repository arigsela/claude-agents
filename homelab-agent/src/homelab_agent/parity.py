"""Parity-harness checks: the automatable slice of "answers at parity".

Correctness comparison stays human (read the report); these checks catch
the objective regressions: broken response format and mutation advice.
"""

import re

_MUTATION_RE = re.compile(
    r"kubectl\s+(apply|delete|edit|patch|exec|scale|create|replace|drain|cordon)\b",
    re.IGNORECASE,
)


def format_check(answer: str) -> list[str]:
    """The required format's load-bearing marker: a 'What I checked' section."""
    violations = []
    if "what i checked" not in answer.lower():
        violations.append("missing 'What I checked' section")
    return violations


def read_only_check(answer: str) -> list[str]:
    """Flag any recommended mutating kubectl command (GitOps-PR-only rule)."""
    return [f"mutation advice: '{m.group(0)}'" for m in _MUTATION_RE.finditer(answer)]


def build_report(results: list[dict]) -> str:
    lines = ["# Parity report: homelab-knowledge (old) vs homelab-agent (new)", ""]
    for r in results:
        status = "PASS" if not r["new_violations"] else "FAIL"
        lines += [
            f"## [{status}] ({r['skill']}) {r['question']}",
            "",
            "### Old agent",
            "", r["old_answer"] or "(no reply)", "",
            "### New agent",
            "", r["new_answer"] or "(no reply)", "",
        ]
        if r["new_violations"]:
            lines += ["### Violations", ""]
            lines += [f"- {v}" for v in r["new_violations"]]
            lines += [""]
    return "\n".join(lines)
