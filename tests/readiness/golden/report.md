# Production readiness: component:demo/demo

owner: group:default/platform, lifecycle: production  
app: arigsela/demo@0123456 (main, on default branch: yes)  
deploy: arigsela/kubernetes/base-apps/demo@fedcba9 (Argo targetRevision main)  
scorecard: 2026-10-25T08:30:00Z  
sources: app ok, deploy ok, backstage ok, scorecard ok, cluster ok, github ok  

**Verdict: Not ready**

## Top fixes

1. Add alert rules (ops.alerts) — base-apps/demo/alerts.yaml
2. Back up the PVC (rel.state) — base-apps/demo

## Pillar summary

| Pillar | pass | partial | fail | unknown | n/a |
|---|---|---|---|---|---|
| Operational excellence | 7 | 0 | 1 | 0 | 0 |
| Security | 5 | 4 | 4 | 1 | 0 |
| Reliability | 2 | 1 | 3 | 0 | 1 |
| Performance efficiency | 0 | 1 | 0 | 1 | 0 |
| Cost optimization | 2 | 0 | 0 | 0 | 0 |
| Sustainability | 1 | 0 | 0 | 0 | 0 |

## Findings

### Operational excellence

Note: CI is solid; alerting is missing.

- **fail** ops.alerts — An alert rule fires when this workload is down, crash-looping or erroring: no alert rules found `README.md` `.github/CODEOWNERS` `SECURITY.md, .github/SECURITY.md`
  - Fix: Add an alert rule for the workload being down or crash-looping
Passed: ops.catalog, ops.runbook, ops.docs, ops.ci, ops.release, ops.telemetry, ops.open_prs

### Security

- **fail** sec.image_digest — Every container image is pinned by digest: Deployment/demo/init-db uses busybox:1.36 (no digest); Deployment/demo/app uses 123.dkr.ecr.us-east-1.amazonaws.com/demo:v1 (no digest); Deployment/valkey/valkey uses valkey/valkey:8 (no digest) `base-apps/demo/deployment.yaml:1-49` `base-apps/demo/deployment.yaml:51-61`
  - Fix: Pin every container image by digest
- **fail** sec.nonroot — Runs as non-root (pod or container runAsNonRoot, Dockerfile USER): Deployment/valkey/valkey sets neither runAsNonRoot nor a non-zero runAsUser `base-apps/demo/deployment.yaml:51-61`
  - Fix: Set runAsNonRoot: true or a non-zero runAsUser
- **fail** sec.secrets — No Secret manifests with data in Git, and secrets come from ExternalSecrets: Secret/demo-secret at base-apps/demo/objects.yaml:15-20 holds data in Git (keys: password) `base-apps/demo/objects.yaml:15-20`
  - Fix: Move demo-secret's password to an ExternalSecret
- **fail** sec.dep_updates — A dependency update tool is configured (dependabot.yml or renovate.json): no Dependabot or Renovate config (.github/dependabot.yml, renovate.json) `.github/dependabot.yml, .github/dependabot.yaml` `renovate.json, renovate.json5, .github/renovate.json`
  - Fix: Add .github/dependabot.yml or renovate.json
- **partial** sec.hardening — readOnlyRootFilesystem, allowPrivilegeEscalation: false, capabilities dropped: Deployment/demo/init-db lacks readOnlyRootFilesystem, allowPrivilegeEscalation: false, drop ALL; Deployment/demo/oauth2-proxy lacks readOnlyRootFilesystem, allowPrivilegeEscalation: false, drop ALL; Deployment/valkey/valkey lacks readOnlyRootFilesystem, allowPrivilegeEscalation: false, drop ALL `base-apps/demo/deployment.yaml:1-49` `base-apps/demo/deployment.yaml:51-61`
  - Fix: Set readOnlyRootFilesystem, allowPrivilegeEscalation: false and drop ALL
- **partial** sec.netpol — A NetworkPolicy selects the pods: no NetworkPolicy selects Deployment/valkey `base-apps/demo/deployment.yaml:51-61`
  - Fix: Add a NetworkPolicy that selects the pods
- **partial** sec.sa_token — The service-account token is not mounted, or a dedicated SA is used: Deployment/valkey mounts the default service account's token `base-apps/demo/deployment.yaml:51-61`
  - Fix: Set automountServiceAccountToken: false or use a dedicated service account
- **partial** sec.repo_hygiene — CODEOWNERS and SECURITY.md exist; the default branch is protected: missing SECURITY.md; has CODEOWNERS, default-branch protection `.github/CODEOWNERS` `SECURITY.md, .github/SECURITY.md` `gh api -i repos/arigsela/demo/branches/main/protection`
  - Fix: Add CODEOWNERS and SECURITY.md and protect the default branch
- **unknown** sec.dependabot — Dependabot alerts are on, and the open critical/high counts are within threshold: Dependabot alerts are on; scorecard has no dependabot critical metric; scorecard dependabot.alertsHigh errored: Failed to fetch metric: 403 Resource not accessible by integration `gh api -i repos/arigsela/demo/vulnerability-alerts` `https://backstage.test/api/scorecard/metrics/catalog/component/demo/demo`

Passed: sec.base_digest, sec.cve, sec.actions_pinned, sec.token_perms, sec.exposure

Awareness: 1 critical CVE with no fix yet in the scanned images (not counted) `POST https://backstage.test/api/cve/report`

### Reliability

Note: Single replica state.

- **fail** rel.probes — Readiness and liveness probes on every container: Deployment/demo/oauth2-proxy has no readiness or liveness probe; Deployment/valkey/valkey has no readiness or liveness probe `base-apps/demo/deployment.yaml:1-49` `base-apps/demo/deployment.yaml:51-61`
  - Fix: Add readiness and liveness probes to every container
- **fail** rel.resources — CPU and memory requests and limits on every container: Deployment/demo/init-db has no requests.cpu, requests.memory, limits.cpu, limits.memory; Deployment/demo/app has no limits.cpu; Deployment/demo/oauth2-proxy has no requests.cpu, requests.memory, limits.cpu, limits.memory; Deployment/valkey/valkey has no requests.cpu, requests.memory, limits.cpu, limits.memory `base-apps/demo/deployment.yaml:1-49` `base-apps/demo/deployment.yaml:51-61`
  - Fix: Set CPU and memory requests and limits for each container
- **fail** rel.restarts — No restarts or OOMKills in the pods' current lifetime (live): Deployment/demo: OOMKilled in demo-7d9f8c6b5-aaaaa, 3 restarts across 2 pods; Deployment/valkey: not found live `kubectl get deploy,statefulset,pods -n demo -o json --request-timeout=5s`
  - Fix: Find the cause of the restarts or OOMKills in logs and limits
- **partial** rel.state — Stateful dependencies (PVCs, databases) have backup/restore (n/a when stateless): state is on a PVC without backups `.github/CODEOWNERS` `SECURITY.md, .github/SECURITY.md`
  - Fix: Add a backup and a tested restore for the stateful dependency
Passed: rel.replicas, rel.dependencies

### Performance efficiency

- **partial** perf.rightsize — Live usage is under requests and nothing runs near its limits: Deployment/demo/app memory 180Mi is above its 128Mi request `kubectl top pods -n demo --containers --no-headers --request-timeout=5s` `base-apps/demo/deployment.yaml:1-49`
  - Fix: Raise the requests to live usage and keep headroom under limits
- **unknown** perf.scaling — An HPA exists, or the fixed size is justified: no metrics read

### Cost optimization

Passed: cost.overprovision, cost.registry

### Sustainability

Passed: sus.utilization

## Needs a person

- Who gets paged, and how?
- Is there an SLO or an agreed error budget?
- Has a rollback been done or rehearsed recently?
- Expected load and the plan when it is exceeded
- What happens when each dependency is down?
- Has the runbook been used in an incident or drill?

## Not checked

- CVEs other than fixable criticals and actively exploited (CISA KEV) ones are not counted, and a week the scan could not reach the KEV feed reads as 0 exploited.
