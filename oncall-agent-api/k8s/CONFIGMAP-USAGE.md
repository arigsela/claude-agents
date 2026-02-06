# ConfigMap Usage - Shared Configuration

## Purpose

The `configmap.yaml` contains **shared configuration** used by both daemon and API deployments.

## What's in the ConfigMap

```yaml
oncall-agent-config:
  # Core Agent Settings (used by both)
  AGENT_LOG_LEVEL: "DEBUG"
  AGENT_MAX_THINKING_TOKENS: "12000"
  K8S_CONTEXT: "dev-eks"
  GITHUB_ORG: "artemishealth"
  AWS_REGION: "us-east-1"
  ALLOWED_CLUSTERS: "dev-eks"
  PROTECTED_CLUSTERS: "prod-eks,staging-eks"
  
  # Daemon Settings (used by daemon only)
  TEAMS_NOTIFICATIONS_ENABLED: "true"
  
  # API Settings (used by API only)
  API_HOST: "0.0.0.0"
  API_PORT: "8000"
  SESSION_TTL_MINUTES: "30"
  MAX_SESSIONS_PER_USER: "5"
  RATE_LIMIT_AUTHENTICATED: "60"
  RATE_LIMIT_UNAUTHENTICATED: "10"
  CORS_ORIGINS: "*"
```

## How It's Used

### Daemon Deployment (deployment.yaml)

```yaml
containers:
- name: agent
  envFrom:
  - configMapRef:
      name: oncall-agent-config  # ← Uses shared config
  env:
  - name: RUN_MODE
    value: "daemon"
  # Plus secrets...
```

**Uses:**
- All core agent settings ✅
- TEAMS_NOTIFICATIONS_ENABLED ✅
- Ignores API_* settings (not needed in daemon mode)

### API Deployment (api-deployment.yaml)

```yaml
containers:
- name: api
  envFrom:
  - configMapRef:
      name: oncall-agent-config  # ← Uses shared config
  env:
  - name: RUN_MODE
    value: "api"
  # Plus secrets...
```

**Uses:**
- All core agent settings ✅
- API_* settings ✅
- Ignores TEAMS_NOTIFICATIONS_ENABLED (API doesn't send Teams alerts)

## Benefits of Shared ConfigMap

✅ **Single source of truth** - Change K8S_CONTEXT in one place
✅ **Consistency** - Both modes use same agent settings
✅ **Easier updates** - Update configmap, restart pods
✅ **No duplication** - Don't repeat same values

## Updating Configuration

### To update shared settings:

```bash
# Edit configmap.yaml
kubectl apply -f k8s/configmap.yaml

# Restart both deployments to pick up changes
kubectl rollout restart deployment/oncall-agent -n oncall-agent
kubectl rollout restart deployment/oncall-agent-api -n oncall-agent
```

### To update API-specific settings only:

Edit `configmap.yaml`:
```yaml
  RATE_LIMIT_AUTHENTICATED: "120"  # Increase from 60
```

Then:
```bash
kubectl apply -f k8s/configmap.yaml
kubectl rollout restart deployment/oncall-agent-api -n oncall-agent
# Only restart API, daemon doesn't use this setting
```

## What's NOT in ConfigMap

**Secrets (in Secret resources):**
- ANTHROPIC_API_KEY
- GITHUB_TOKEN
- TEAMS_WEBHOOK_URL
- API_KEYS

These remain in:
- `oncall-agent-secrets` (for daemon)
- `oncall-agent-api-secrets` (for API)

## Summary

✅ **Both deployments use the same configmap**
✅ **Contains all necessary variables for both modes**
✅ **Mode-specific settings included** (both ignore what they don't need)
✅ **Secrets kept separate** for security

**One configmap, two deployments!**
