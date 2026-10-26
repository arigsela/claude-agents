# Production readiness: component:demo/demo

group:default/platform · production · app arigsela/demo@0123456 (main) · deploy arigsela/kubernetes/base-apps/demo@fedcba9  
Sources: all ok

**Verdict: Not ready** (failing blockers: ops.alerts, sec.nonroot, sec.secrets, rel.probes, rel.resources)

## Top fixes

1. Add alert rules (ops.alerts) — base-apps/demo/alerts.yaml
2. Back up the PVC (rel.state) — base-apps/demo

| Pillar | pass | partial | fail | unknown | n/a |
|---|---|---|---|---|---|
| Operational excellence | 7 | 0 | 1 | 0 | 0 |
| Security | 5 | 4 | 4 | 1 | 0 |
| Reliability | 2 | 1 | 3 | 0 | 1 |
| Performance efficiency | 0 | 1 | 0 | 1 | 0 |
| Cost optimization | 2 | 0 | 0 | 0 | 0 |
| Sustainability | 1 | 0 | 0 | 0 | 0 |

## Findings

**Operational excellence**

- **fail** ops.alerts: no alert rules found `README.md` → fix: Add an alert rule for the workload being down or crash-looping

Passed: ops.catalog, ops.runbook, ops.docs, ops.ci, ops.release, ops.telemetry, ops.open_prs

**Security**

- **fail** sec.image_digest: Deployment/demo/init-db uses busybox:1.36 (no digest); Deployment/demo/app uses… `base-apps/demo/deployment.yaml:1-49` → fix: Pin every container image by digest
- **fail** sec.nonroot: Deployment/valkey/valkey sets neither runAsNonRoot nor a non-zero runAsUser `base-apps/demo/deployment.yaml:51-61` → fix: Set runAsNonRoot: true or a non-zero runAsUser
- **fail** sec.secrets: Secret/demo-secret at base-apps/demo/objects.yaml:15-20 holds data in Git (keys: password) → fix: Move demo-secret's password to an ExternalSecret
- **fail** sec.dep_updates: no Dependabot or Renovate config (.github/dependabot.yml, renovate.json) → fix: Add .github/dependabot.yml or renovate.json
- **partial** sec.hardening: Deployment/demo/init-db lacks readOnlyRootFilesystem, allowPrivilegeEscalation: false, drop ALL… `base-apps/demo/deployment.yaml:1-49` → fix: Set readOnlyRootFilesystem, allowPrivilegeEscalation: false and drop ALL
- **partial** sec.netpol: no NetworkPolicy selects Deployment/valkey `base-apps/demo/deployment.yaml:51-61` → fix: Add a NetworkPolicy that selects the pods
- **partial** sec.sa_token: Deployment/valkey mounts the default service account's token `base-apps/demo/deployment.yaml:51-61` → fix: Set automountServiceAccountToken: false or use a dedicated service account
- **partial** sec.repo_hygiene: missing SECURITY.md; has CODEOWNERS, default-branch protection `.github/CODEOWNERS` → fix: Add CODEOWNERS and SECURITY.md and protect the default branch
- **unknown** sec.dependabot: Dependabot alerts are on; scorecard has no dependabot critical metric; scorecard dependabot.alertsHigh errored: Failed to fetch metric…

Passed: sec.base_digest, sec.cve, sec.actions_pinned, sec.token_perms, sec.exposure

Awareness: 1 critical CVE with no fix yet in the scanned images (not counted)

**Reliability**

- **fail** rel.probes: Deployment/demo/oauth2-proxy has no readiness or liveness probe; Deployment/valkey/valkey has no readiness or liveness… `base-apps/demo/deployment.yaml:1-49` → fix: Add readiness and liveness probes to every container
- **fail** rel.resources: Deployment/demo/init-db has no requests.cpu, requests.memory, limits.cpu, limits.memory; Deployment/demo/app has no… `base-apps/demo/deployment.yaml:1-49` → fix: Set CPU and memory requests and limits for each container
- **fail** rel.restarts: Deployment/demo: OOMKilled in demo-7d9f8c6b5-aaaaa, 3 restarts across 2 pods; Deployment/valkey: not found live → fix: Find the cause of the restarts or OOMKills in logs and limits
- **partial** rel.state: state is on a PVC without backups `.github/CODEOWNERS` → fix: Add a backup and a tested restore for the stateful dependency

Passed: rel.replicas, rel.dependencies

**Performance efficiency**

- **partial** perf.rightsize: Deployment/demo/app memory 180Mi is above its 128Mi request `base-apps/demo/deployment.yaml:1-49` → fix: Raise the requests to live usage and keep headroom under limits
- **unknown** perf.scaling: no metrics read

**Cost optimization**

Passed: cost.overprovision, cost.registry

**Sustainability**

Passed: sus.utilization

**Needs a person**

- Who gets paged, and how?
- Is there an SLO or an agreed error budget?
- Has a rollback been done or rehearsed recently?
- Expected load and the plan when it is exceeded
- What happens when each dependency is down?
- Has the runbook been used in an incident or drill?

Full report: /tmp/run-1/report.md
