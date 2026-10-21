# pr-triage calibration — arigsela/kubernetes

- PRs: 200 merged; older 100 → hot components, newer 100 evaluated
- Follow-up PRs in the evaluated half: 43
- **Follow-up PRs labelled skip: 0 (0%)** — target ≤ 5%
- Share of all PRs labelled skip: 8% — target ≥ 20%
- Follow-up PRs labelled read: 32 (74%)
- Jev input tokens: 191,195 (≈ $0.0080)
- Hot components (train half): {'base-apps/istio-ingress': 0.67, 'base-apps/nginx-ingress': 0.8, 'scripts/hop-verify.sh': 0.71, 'tests/k3s-upgrade': 0.75}

## By size bucket

| bucket | PRs | follow-ups | skip | skim | read | follow-ups in skip |
|---|---|---|---|---|---|---|
| tiny | 14 | 1 | 4 | 5 | 5 | 0 |
| small | 45 | 19 | 3 | 13 | 29 | 0 |
| medium | 23 | 12 | 0 | 4 | 19 | 0 |
| large | 18 | 11 | 1 | 0 | 17 | 0 |

## By decided_by

| decided_by | PRs | skip | skim | read |
|---|---|---|---|---|
| rules | 52 | 8 | 0 | 44 |
| jev | 46 | 0 | 20 | 26 |
| claude | 2 | 0 | 2 | 0 |
| degraded | 0 | 0 | 0 | 0 |

## Claude-only comparison

- Agreement with the cascade: 37/48
- Follow-up PRs Claude-only would skip: 1

## Threshold sweep (offline, same Jev answers)

| read_if_p_read_gte | skip_if_p_skip_gte | follow-ups in skip | skip share |
|---|---|---|---|
| 0.20 | 0.80 | 1 (2%) | 9% |
| 0.20 | 0.90 | 0 (0%) | 8% |
| 0.20 | 0.95 | 0 (0%) | 8% |
| 0.30 | 0.80 | 1 (2%) | 9% |
| 0.30 | 0.90 | 0 (0%) | 8% |
| 0.30 | 0.95 | 0 (0%) | 8% |
| 0.40 | 0.80 | 1 (2%) | 9% |
| 0.40 | 0.90 | 0 (0%) | 8% |
| 0.40 | 0.95 | 0 (0%) | 8% |
| 0.50 | 0.80 | 1 (2%) | 9% |
| 0.50 | 0.90 | 0 (0%) | 8% |
| 0.50 | 0.95 | 0 (0%) | 8% |

Escalations without a stored Claude answer count as read (conservative).

## Suggested policy patch (all PRs for hot components; best safe thresholds)

```yaml
thresholds:
  read_if_p_read_gte: 0.2
  read_if_any_flag_gte: 0.7
  skip_if_p_skip_gte: 0.8
  escalate_if_confidence_lt: 0.5
hot_components:
  .github/workflows: 0.57
  appsets/managed-apps: 0.67
  base-apps/admission-policies: 1.0
  base-apps/agent-audit-aws-infrastructure: 0.5
  base-apps/agent-audit-web: 0.5
  base-apps/argo-rollouts: 0.4
  base-apps/argo-workflow-tasks: 0.7
  base-apps/argo-workflows: 0.43
  base-apps/istio-ingress: 0.63
  base-apps/jupyter: 0.5
  base-apps/kagent: 0.5
  base-apps/kyverno: 0.67
  base-apps/kyverno-policies: 0.5
  base-apps/nginx-ingress: 0.8
  base-apps/postgresql: 0.45
  base-apps/vault: 0.5
  base-apps/wan-ip-monitor: 0.5
  base-apps/weather-kitchen-backend: 0.4
  scripts/gen-agent-capability-policy.py: 1.0
  scripts/hop-verify.sh: 0.5
  scripts/install-authn-config.sh: 0.75
  tests/admission-policies: 0.89
  tests/appset: 0.4
  tests/cve_report: 0.67
  tests/eval-corpus: 1.0
  tests/node-config: 1.0
```

## Applied (Ruling 8)

Deployed thresholds: `read_if_p_read_gte: 0.30`, `read_if_any_flag_gte: 0.70`, `skip_if_p_skip_gte: 0.90`, `escalate_if_confidence_lt: 0.50`.
The sweep's suggested 0.20/0.80 was not applied: it buys 1 percentage point of skip share for one follow-up in skip.
Deployed hot components: the 26 entries from the suggested patch above (the "Hot components (train half)" line lists only the 4 evaluated here).

Follow-up rate by assigned label (evaluated half, 100 PRs):

| label | PRs | follow-ups | rate |
|---|---|---|---|
| skip | 8 | 0 | 0/8 |
| skim | 22 | 11 | 11/22 |
| read | 70 | 32 | 32/70 |

Caveats:
- 0 follow-ups in skip over 43 follow-ups gives a 95% upper bound of about 7% (rule of three: 3/43), so the ≤5% target is not statistically established.
- Recent PRs are right-censored: they have had less than 72 h to accrue a follow-up, which understates follow-up rates for the newest PRs.
- The deployed hot components (26) differ from the 4 evaluated in the train half, so the evaluated labels are not exactly what production will produce.
- Skip share of 8% misses the spec §10 target of ≥ 20%. Keeping the conservative thresholds is an explicit owner decision.
- Re-calibrate after about 4 weeks of live operation.
