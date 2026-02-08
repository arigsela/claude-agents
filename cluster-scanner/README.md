# Cluster Scanner

Autonomous K3s cluster health scanner using [Ralph Orchestrator](https://github.com/ralphel/ralph-orchestrator) with 3 hats. Replaces `k8s-monitor/` with a simpler architecture: no Python, no kubectl, no RBAC.

## Architecture

```
scan.start → [scanner] → scan.complete → [analyzer] → escalate.alert → [notifier] → SCAN_COMPLETE
                                                     → escalate.none  → [notifier] → SCAN_COMPLETE
```

| Hat | Role | Triggers | Publishes |
|-----|------|----------|-----------|
| **scanner** | Queries oncall-agent-api for cluster health | `scan.start` | `scan.complete` |
| **analyzer** | Classifies severity (SEV-1–4), detects trends | `scan.complete` | `escalate.alert` / `escalate.none` |
| **notifier** | Posts Slack alerts or logs all-clear | `escalate.alert` / `escalate.none` | `SCAN_COMPLETE` |

All cluster data comes from the **oncall-agent-api** `/query` endpoint. The scanner never touches kubectl directly.

## Quick Start

### Local Testing

```bash
# Port-forward oncall-agent-api
kubectl port-forward -n oncall-agent svc/oncall-agent-api 8000:80 &

# Set env vars
export ANTHROPIC_API_KEY="sk-ant-..."
export ONCALL_API_KEY="your-api-key"
export SLACK_BOT_TOKEN="xoxb-..."

# Run
./test-local.sh
```

### Container Testing

```bash
docker build -t cluster-scanner .
docker run --env-file .env cluster-scanner
```

### Deploy to K8s

```bash
# Build and push image
./deploy-to-ecr.sh v1.0.0

# Apply K8s manifests
kubectl apply -f k8s/

# Test with manual job
kubectl create job --from=cronjob/cluster-scanner test-scan -n cluster-scanner

# Watch logs
kubectl logs -n cluster-scanner -l app=cluster-scanner -f
```

## Configuration

### Environment Variables

| Variable | Source | Description |
|----------|--------|-------------|
| `ANTHROPIC_API_KEY` | Secret | Claude API key |
| `ONCALL_API_URL` | ConfigMap | oncall-agent-api URL |
| `ONCALL_API_KEY` | Secret | API authentication key |
| `SLACK_BOT_TOKEN` | Secret | Slack Bot OAuth token |
| `SLACK_CHANNEL` | ConfigMap | Target Slack channel |
| `ANTHROPIC_MODEL` | ConfigMap | Claude model (default: haiku) |

### Vault Prerequisites

```bash
# Create secret path
vault kv put k8s-secrets/cluster-scanner \
  anthropic-api-key="sk-ant-..." \
  oncall-api-key="<one of oncall-agent-api's API_KEYS>" \
  slack-bot-token="xoxb-..."

# Create Kubernetes auth role
vault write auth/kubernetes/role/cluster-scanner \
  bound_service_account_names=default \
  bound_service_account_namespaces=cluster-scanner \
  policies=cluster-scanner-read \
  ttl=24h
```

## Severity Classification

| Level | Criteria | Action |
|-------|----------|--------|
| **SEV-1** | P0 service down, data layer unavailable, ingress down | Slack alert (immediate) |
| **SEV-2** | P1 service down >5min, P0 degraded, imminent risk | Slack alert |
| **SEV-3** | P1 degraded/recovering, P2 down, warnings | Log only |
| **SEV-4** | Known issues, P2-P3, informational | No action |

## Trend Detection

Ralph memories persist across scan cycles via PVC. The analyzer compares current findings to previous scans to detect:
- **New issues** not seen before
- **Recurring issues** persisting across scans
- **Resolved issues** that cleared since last scan

## Cost

Same Haiku model as k8s-monitor. ~15K tokens/cycle, 48 cycles/day = **~$0.90-$1.50/year**.

## Migration from k8s-monitor

1. Deploy cluster-scanner alongside k8s-monitor (scanner to `#test-alerts`)
2. Compare coverage for 1-2 weeks
3. Switch scanner to `#oncall-alerts`, scale k8s-monitor to 0
4. Archive k8s-monitor
