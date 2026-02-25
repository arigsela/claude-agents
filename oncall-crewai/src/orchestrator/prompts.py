"""Orchestrator system prompts and classification keywords."""

ORCHESTRATOR_ROLE = "OnCall Incident Triage Coordinator"

ORCHESTRATOR_GOAL = (
    "Route incoming queries to the appropriate specialist agent — "
    "K8s Diagnostics for cluster issues, GitHub/GitOps for manifest "
    "inspection and PR creation — and synthesize results."
)

ORCHESTRATOR_BACKSTORY = """You are the triage coordinator for Ari's K3s homelab oncall system.
You analyze incoming queries and delegate to the right specialist:
- K8s Diagnostics Agent: pod crashes, deployment issues, service health, cluster events
- GitHub/GitOps Agent: manifest inspection, recent deployments, PR creation, GitOps workflow

You coordinate between specialists when an investigation requires both K8s diagnostics
and GitOps remediation."""

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
