# Slack Integration Setup Guide

This document covers everything needed to connect the OnCall Agent API (`oncall.arigsela.com`) to Slack. It is split into two parts:

1. **GitOps / K8s resource changes** - what to deploy on the cluster
2. **Slack platform setup** - creating and configuring the Slack app

---

## Part 1: GitOps / K8s Resource Preparation

All K8s manifests live in `oncall-agent-api/k8s/`. The code changes in this branch already updated these files, but the cluster resources need to be applied in order.

### 1.1 Store Secrets in Vault

The ExternalSecret operator syncs secrets from Vault into the `oncall-agent-secrets` Kubernetes Secret. Two new properties need to be added under the existing `oncall-agent` Vault key.

```bash
# SSH into a machine with Vault CLI access, or use port-forward:
# kubectl port-forward -n vault svc/vault 8200:8200

# Write the Slack secrets (you'll get these values from Part 2)
vault kv put k8s-secrets/oncall-agent \
  anthropic-api-key="$(vault kv get -field=anthropic-api-key k8s-secrets/oncall-agent)" \
  github-token="$(vault kv get -field=github-token k8s-secrets/oncall-agent)" \
  api-keys="$(vault kv get -field=api-keys k8s-secrets/oncall-agent)" \
  slack-bot-token="xoxb-YOUR-BOT-TOKEN" \
  slack-signing-secret="YOUR-SIGNING-SECRET"
```

> **Note**: Vault KV v2 `put` replaces all keys, so you must include existing keys in the command. Alternatively, use `vault kv patch` if your Vault version supports it:
>
> ```bash
> vault kv patch k8s-secrets/oncall-agent \
>   slack-bot-token="xoxb-YOUR-BOT-TOKEN" \
>   slack-signing-secret="YOUR-SIGNING-SECRET"
> ```

### 1.2 Apply K8s Manifests

Apply in this order to avoid dependency issues:

```bash
cd oncall-agent-api/k8s

# Step 1: Update ConfigMap (adds SLACK_ENABLED, SLACK_ALERT_CHANNEL, SLACK_ALERT_MIN_SEVERITY)
kubectl apply -f configmap.yaml

# Step 2: Update ExternalSecret (adds slack-bot-token and slack-signing-secret refs)
kubectl apply -f external-secret.yaml

# Step 3: Verify the ExternalSecret synced successfully
kubectl get externalsecret oncall-agent-secrets -n oncall-agent
# STATUS should show "SecretSynced"

# Step 4: Verify the K8s secret now contains the new keys
kubectl get secret oncall-agent-secrets -n oncall-agent -o jsonpath='{.data}' | python3 -c "
import sys, json, base64
data = json.load(sys.stdin)
for key in sorted(data):
    print(f'  {key}: {len(base64.b64decode(data[key]))} bytes')
"
# Should show slack-bot-token and slack-signing-secret

# Step 5: Update Deployment (adds SLACK_BOT_TOKEN and SLACK_SIGNING_SECRET env vars)
kubectl apply -f deployment.yaml

# Step 6: Wait for rollout
kubectl rollout status deployment/oncall-agent-api -n oncall-agent --timeout=120s
```

### 1.3 Verify Ingress Routing

The existing ingress already has `path: /` with `pathType: Prefix`, so `/slack/command`, `/slack/health`, and `/slack/events` are all routed automatically. No ingress changes needed.

Verify:

```bash
curl https://oncall.arigsela.com/slack/health
```

Expected response:

```json
{
  "status": "configured",
  "enabled": true,
  "signing_secret_set": true,
  "bot_token_set": true,
  "alert_channel": "#oncall-alerts",
  "agent_ready": true,
  "endpoint": "/slack/command"
}
```

### 1.4 Build and Push Container Image

The new code adds `slack_sdk` as a dependency and new Python modules. You need to rebuild and push:

```bash
cd oncall-agent-api
docker build -t YOUR_AWS_ACCOUNT.dkr.ecr.us-east-2.amazonaws.com/oncall-agent:latest .
docker push YOUR_AWS_ACCOUNT.dkr.ecr.us-east-2.amazonaws.com/oncall-agent:latest

# Then restart the deployment to pick up the new image
kubectl rollout restart deployment/oncall-agent-api -n oncall-agent
```

### 1.5 Create the Alert Channel

Create `#oncall-alerts` in Slack (or change `SLACK_ALERT_CHANNEL` in the ConfigMap to match an existing channel). The bot must be able to post to this channel - if the channel is private, invite the bot first.

---

## Part 2: Slack Platform Setup

### 2.1 Create a Slack App

1. Go to **https://api.slack.com/apps**
2. Click **Create New App** > **From scratch**
3. **App Name**: `OnCall Agent`
4. **Workspace**: Select your workspace
5. Click **Create App**

### 2.2 Configure Slash Command

1. Left sidebar > **Slash Commands**
2. Click **Create New Command**
3. Fill in:

| Field | Value |
|-------|-------|
| Command | `/oncall` |
| Request URL | `https://oncall.arigsela.com/slack/command` |
| Short Description | `Query the OnCall troubleshooting agent` |
| Usage Hint | `check cluster health` |

4. Click **Save**

### 2.3 Add OAuth Scopes

1. Left sidebar > **OAuth & Permissions**
2. Scroll to **Scopes** > **Bot Token Scopes**
3. Add these scopes:

| Scope | Purpose |
|-------|---------|
| `commands` | Handle slash commands (auto-added) |
| `chat:write` | Post responses and alerts to channels |
| `chat:write.public` | Post to channels the bot hasn't been invited to |

### 2.4 Install to Workspace

1. Left sidebar > **Install App**
2. Click **Install to Workspace**
3. Review the permission request and click **Allow**
4. **Copy the Bot User OAuth Token** - it starts with `xoxb-`
   - This is the value for `slack-bot-token` in Vault

### 2.5 Get the Signing Secret

1. Left sidebar > **Basic Information**
2. Scroll to **App Credentials**
3. **Copy the Signing Secret**
   - This is the value for `slack-signing-secret` in Vault

### 2.6 (Optional) Enable Events API

Only needed if you want `@OnCall Agent` mention support in addition to `/oncall`:

1. Left sidebar > **Event Subscriptions**
2. Toggle **Enable Events** to **On**
3. **Request URL**: `https://oncall.arigsela.com/slack/events`
   - Slack will send a verification challenge - the API handles it automatically
   - Wait for the green "Verified" checkmark
4. Under **Subscribe to bot events**, click **Add Bot User Event**:
   - Add `app_mention`
5. Click **Save Changes**
6. Slack will prompt you to reinstall the app - click **reinstall**

### 2.7 (Optional) Customize App Appearance

1. Left sidebar > **Basic Information** > **Display Information**
2. Set:
   - **App name**: `OnCall Agent`
   - **Short description**: `K8s incident analysis and cluster health checks`
   - **App icon**: Upload a relevant icon
   - **Background color**: `#2C2D30` (Slack dark)

---

## Verification Checklist

Run through these steps after both parts are complete:

### Health Check

```bash
curl https://oncall.arigsela.com/slack/health
# All fields should show configured/true
```

### Slash Command

1. Open Slack
2. Go to any channel
3. Type: `/oncall check cluster health`
4. You should see "Thinking..." immediately, then a formatted Block Kit response within 10-30 seconds

### Proactive Alerts

Test by sending an incident that exceeds the severity threshold:

```bash
curl -X POST https://oncall.arigsela.com/incident \
  -H "Content-Type: application/json" \
  -H "X-API-Key: YOUR_API_KEY" \
  -d '{
    "service": "test-service",
    "namespace": "default",
    "error": "OOMKilled",
    "restart_count": 15,
    "cluster": "default"
  }'
```

Check `#oncall-alerts` - a Block Kit alert should appear with severity "CRITICAL".

### Troubleshooting

| Symptom | Check |
|---------|-------|
| `/slack/health` shows `bot_token_set: false` | Vault secret not synced. Check ExternalSecret status: `kubectl get es -n oncall-agent` |
| Slash command returns "dispatch_failed" in Slack | Request URL unreachable. Verify `curl https://oncall.arigsela.com/slack/command` returns 200 |
| "Thinking..." but no response | Background task failed. Check pod logs: `kubectl logs -n oncall-agent deploy/oncall-agent-api --tail=50` |
| Alerts not posting to channel | Check `SLACK_ENABLED=true` in ConfigMap and severity meets `SLACK_ALERT_MIN_SEVERITY` threshold |
| 401 from `/slack/command` | Signing secret mismatch. Verify the secret in Vault matches Slack's Basic Information page |

---

## Configuration Reference

### Environment Variables

| Variable | Source | Default | Description |
|----------|--------|---------|-------------|
| `SLACK_ENABLED` | ConfigMap | `"true"` | Master toggle for Slack integration |
| `SLACK_ALERT_CHANNEL` | ConfigMap | `"#oncall-alerts"` | Channel for proactive incident alerts |
| `SLACK_ALERT_MIN_SEVERITY` | ConfigMap | `"high"` | Minimum severity to trigger alerts (`low`, `medium`, `high`, `critical`) |
| `SLACK_BOT_TOKEN` | Vault/Secret | _(none)_ | Bot User OAuth Token (`xoxb-...`) |
| `SLACK_SIGNING_SECRET` | Vault/Secret | _(none)_ | App Signing Secret for request HMAC verification |

### API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/slack/command` | POST | Receives slash command payloads from Slack |
| `/slack/health` | GET | Returns integration configuration status |
| `/slack/events` | POST | Handles Events API (URL verification, future @mentions) |
