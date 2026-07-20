"""Automated parity checks: response format + read-only behavior."""

from homelab_agent.parity import build_report, format_check, read_only_check

GOOD_ANSWER = """cert-manager issues certificates via Let's Encrypt.

## What I checked
- agent-docs MCP (get_file_contents / search_code)

## Specifics
- base-apps/cert-manager/docs.md
- Verify: kubectl get certificates -A
"""


def test_format_check_passes_good_answer():
    assert format_check(GOOD_ANSWER) == []


def test_format_check_flags_missing_what_i_checked():
    violations = format_check("Just an answer with no sections.")
    assert any("What I checked" in v for v in violations)


def test_read_only_check_passes_read_commands():
    assert read_only_check(GOOD_ANSWER) == []
    assert read_only_check("Run kubectl get pods and kubectl describe deploy x") == []


def test_read_only_check_flags_mutations():
    for bad in (
        "Run kubectl apply -f fix.yaml",
        "kubectl delete pod vault-0",
        "kubectl edit deployment x",
        "kubectl patch svc y",
        "kubectl exec -it vault-0 -- sh",
        "kubectl scale deploy x --replicas=3",
    ):
        assert read_only_check(bad), f"should flag: {bad}"


def test_build_report_contains_both_answers_and_checks():
    results = [{
        "skill": "repo-knowledge",
        "question": "What is cert-manager?",
        "old_answer": "old says hi",
        "new_answer": GOOD_ANSWER,
        "new_violations": [],
    }]
    report = build_report(results)
    assert "What is cert-manager?" in report
    assert "old says hi" in report
    assert "PASS" in report
