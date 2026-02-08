# Cluster Scanner — Claude Code Context

## Project Identity

Autonomous K3s cluster health scanner that runs as a Ralph orchestration loop.
Scans services via oncall-agent-api, analyzes findings for severity and trends,
alerts via Slack when warranted.

**Architecture**: 3 Ralph hats (scanner → analyzer → notifier), no Python, no kubectl.
All cluster data comes from oncall-agent-api `/query` endpoint.

## oncall-agent-api Usage

**Endpoint**: `POST $ONCALL_API_URL/query`

**Authentication**: `X-API-Key: $ONCALL_API_KEY` header

**Rate limit**: 60 requests/minute

**Request format**:
```json
{
  "prompt": "Your question about the cluster",
  "namespace": "default",
  "session_id": null
}
```

**Response format**:
```json
{
  "status": "success",
  "responses": [{"type": "text", "content": "The answer..."}],
  "query": "Your question",
  "duration_ms": 1234.56
}
```

**Example curl**:
```bash
curl -s -X POST "$ONCALL_API_URL/query" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $ONCALL_API_KEY" \
  -d '{"prompt": "Check pod health in chores-tracker-backend namespace", "namespace": "chores-tracker-backend"}'
```

## Service Catalog Summary

### P0 — Business Critical (0 min max downtime)
| Service | Namespace | Notes |
|---------|-----------|-------|
| chores-tracker-backend | chores-tracker-backend | 2 replicas, slow startup (5-6 min) |
| chores-tracker-frontend | chores-tracker-frontend | HTMX frontend |
| n8n | n8n | Single replica, AI workflows |
| postgresql | postgresql | Single replica, data layer for n8n + chores-tracker |
| nginx-ingress | ingress-nginx | All external traffic |
| oncall-agent | oncall-agent | 2 replicas, incident response |

### P1 — Infrastructure Dependencies (5-15 min max downtime)
| Service | Namespace | Notes |
|---------|-----------|-------|
| vault | vault | Manual unseal after restart |
| external-secrets-operator | external-secrets | Secret syncing |
| cert-manager | cert-manager | TLS automation |
| ecr-credentials-sync | ecr-auth | ECR token refresh |
| crossplane | crossplane-system | AWS provisioning |

Full service catalog: `docs/reference/services.txt`

## Known Issues (DO NOT alert on these)

1. **chores-tracker-backend slow startup** — Takes 5-6 minutes. Expected behavior.
2. **vault manual unseal** — Required after pod restart. Expected behavior.
3. **Single replica databases** — postgresql runs single replica. Architectural choice. mysql is P2 (legacy, no active dependents).
4. **Certificate renewal attempts** — cert-manager renews proactively. Only alert if cert actually expired.

## Ralph Memory Operations

```bash
# Add a memory
ralph tools memory add "scan summary: 2026-02-08 — SEV-4. All P0 healthy." -t context

# Search memories
ralph tools memory search "scan summary"
ralph tools memory search "incident"

# List recent memories
ralph tools memory list --recent 5
```

## Environment Variables

| Variable | Description | Source |
|----------|-------------|--------|
| `ONCALL_API_URL` | oncall-agent-api base URL | ConfigMap |
| `ONCALL_API_KEY` | API authentication key | Secret (Vault) |
| `SLACK_BOT_TOKEN` | Slack Bot OAuth token | Secret (Vault) |
| `SLACK_CHANNEL` | Target Slack channel | ConfigMap |
| `ANTHROPIC_API_KEY` | Claude API key | Secret (Vault) |
| `ANTHROPIC_MODEL` | Claude model ID | ConfigMap |

## Cost Note

Model defaults to `claude-haiku-4-5-20251001` via `ANTHROPIC_MODEL` env var.
3 hat sessions per cycle x ~5K tokens each = ~15K tokens/cycle.
At 48 cycles/day: ~$0.90-$1.50/year.
