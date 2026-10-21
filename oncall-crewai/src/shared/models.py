"""Pydantic output models and task guardrails for CrewAI agents.

Structured outputs ensure reliable inter-crew data flow.
Guardrails validate task results before acceptance.
"""

from pydantic import BaseModel


# ============================================================
# Structured output models
# ============================================================


class K8sDiagnosisOutput(BaseModel):
    """Structured output for K8s diagnostics crew."""

    service: str = ""
    namespace: str = ""
    current_state: str = ""
    root_cause: str = ""
    priority: str = ""  # P0, P1, P2
    remediation_steps: list[str] = []


class GitOpsOutput(BaseModel):
    """Structured output for GitOps operations crew."""

    action: str = ""  # inspected, listed, pr_created, deployments_searched
    summary: str = ""
    pr_url: str = ""
    files_referenced: list[str] = []
    recommendations: list[str] = []


# ============================================================
# Task guardrails
# ============================================================


def validate_k8s_diagnosis(result):
    """Guardrail: ensure K8s diagnosis is substantive and actionable.

    Validates that the agent produced a real diagnosis rather than
    a stub or error message.
    """
    text = result.raw if hasattr(result, "raw") else str(result)

    if len(text.strip()) < 50:
        return (False, "Diagnosis is too short. Provide a detailed analysis "
                "including service identification, root cause, priority level, "
                "and remediation steps.")

    return (True, result)


def validate_gitops_output(result):
    """Guardrail: ensure GitOps output is substantive.

    Validates that the agent produced meaningful output about
    manifests, deployments, or PR creation.
    """
    text = result.raw if hasattr(result, "raw") else str(result)

    if len(text.strip()) < 30:
        return (False, "Response is too short. Provide detailed findings "
                "about the requested manifests, deployments, or PR status.")

    # Safety check: PR creation without approval mention
    text_lower = text.lower()
    if "create_remediation_pr" in text_lower and "approv" not in text_lower:
        return (False, "PR creation detected without mentioning user approval. "
                "Always confirm user approval before creating PRs.")

    return (True, result)
