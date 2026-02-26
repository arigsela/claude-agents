"""Orchestrator classification keywords.

Only the keyword lists are used by the orchestrator flow for
deterministic routing. Agent identity for delegates is defined
inline in orchestrator/agents.py.
"""

# Keywords for deterministic routing
K8S_KEYWORDS = [
    "pod", "pods", "deployment", "namespace", "kubectl", "crash",
    "restart", "oom", "crashloop", "health", "node", "service",
    "container", "logs", "events", "sealed", "vault", "unseal",
    "kube", "k8s", "cluster", "replica", "scaling", "ingress",
    "diagnose", "troubleshoot", "investigate", "status",
]

GITHUB_KEYWORDS = [
    "pr", "pull request", "manifest", "gitops", "yaml", "deployment.yaml",
    "github", "actions", "workflow", "branch", "commit", "merge",
    "argocd", "sync", "remediation", "create pr", "file", "directory",
    "base-apps", "document", "runbook",
]
