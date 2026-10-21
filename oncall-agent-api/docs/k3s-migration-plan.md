# OnCall Agent API: EKS to K3s Migration Plan

**Created**: 2026-02-06
**Status**: In Progress
**Goal**: Deploy `oncall-agent-api/` to Ari's K3s homelab, replacing the existing `oncall/` deployment.

---

## Overview

The `oncall-agent-api/` was built for AWS EKS (us-east-1, org: artemishealth). We need to adapt it
for the K3s homelab cluster that currently runs `oncall/`. The existing `oncall/` already has
the correct homelab system prompt, ECR region (us-east-2), and service catalog.

**Key Principle**: Disable EKS-only features rather than delete them, so they can be re-enabled later.

---

## Phase 1: Configuration & Manifests

### Task 1.1: Update ConfigMap for K3s ✅ DONE
- [x] **File**: `k8s/configmap.yaml`
- [x] Change `K8S_CONTEXT: "dev-eks"` → removed (in-cluster auth via ServiceAccount)
- [x] Change `GITHUB_ORG: "artemishealth"` → `"arigsela"`
- [x] Change `AWS_REGION: "us-east-1"` → `"us-east-2"`
- [x] Change `ALLOWED_CLUSTERS: "dev-eks"` → `"default"`
- [x] Change `PROTECTED_CLUSTERS: "prod-eks,staging-eks"` → `""` (empty)
- [x] Zeus settings commented out, `ZEUS_INTEGRATION_ENABLED` set to `"false"`
- [x] Removed `DATADOG_SITE`
- [x] Kept: `API_HOST`, `API_PORT`, `SESSION_TTL_MINUTES`, `MAX_SESSIONS_PER_USER`, `RATE_LIMIT_*`, `CORS_ORIGINS`, `AGENT_LOG_LEVEL`

### Task 1.2: Update Deployment Manifest ✅ DONE
- [x] **File**: `k8s/deployment.yaml`
- [x] Changed image to `YOUR_AWS_ACCOUNT.dkr.ecr.us-east-2.amazonaws.com/oncall-agent:latest`
- [x] Changed `replicas: 2` → `replicas: 1`
- [x] Removed env vars: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION` (secretKeyRef), `DATADOG_API_KEY`, `DATADOG_APP_KEY`, `ZEUS_WEB_BASIC_AUTH_USERNAME`, `ZEUS_WEB_BASIC_AUTH_PASSWORD`
- [x] Kept env vars: `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`, `GITHUB_TOKEN`, `API_KEYS`
- [x] Reduced resources: requests 256Mi/250m, limits 512Mi/500m
- [x] Added volume mount for incident memory PVC (LanceDB at `/app/data/incidents`)
- [x] Removed commented-out ingress block (handled separately in Task 1.5)
- [ ] TODO: Add `imagePullSecrets` if k3s ecr-auth CronJob uses a named secret

### Task 1.3: Update Secrets for Vault + ExternalSecret ✅ DONE
- [x] **File**: `k8s/secret.yaml` — trimmed to fallback template (anthropic-api-key, github-token, api-keys only)
- [x] Removed: aws-*, datadog-*, zeus-* secrets
- [x] **Created**: `k8s/secret-store.yaml` — Vault SecretStore (from existing oncall/ pattern)
- [x] **Created**: `k8s/external-secret.yaml` — ExternalSecret syncing from Vault path `k8s-secrets/oncall-agent`
- [x] Aligned target secret name: `oncall-agent-secrets` (matches deployment.yaml secretKeyRef)
- [x] ExternalSecret syncs only: `anthropic-api-key`, `github-token`, `api-keys`
- [x] Note: Vault role `oncall-agent` must exist with policy to read `k8s-secrets/oncall-agent`

### Task 1.4: Update PVC for K3s Storage ✅ DONE
- [x] **File**: `k8s/incident-memory-pvc.yaml`
- [x] Set `storageClassName: local-path` (k3s default provisioner)
- [x] Kept `storage: 1Gi` and `ReadWriteOnce`

### Task 1.5: Replace Ingress for K3s ✅ DONE
- [x] **Replaced**: `k8s/oncall-agent-external-ingress.yaml` — removed AWS ALB config (ACM certs, WAF, VPC subnets, ALB annotations)
- [x] Replaced with nginx-ingress for k3s homelab:
  - `ingressClassName: nginx`
  - TLS via cert-manager (`letsencrypt-prod` cluster-issuer)
  - Host: `oncall.arigsela.com`
  - Routes all paths to `oncall-agent-api` service on port 80
- [x] Note: DNS record for `oncall.arigsela.com` must point to k3s ingress IP

### Task 1.6: RBAC (minimal changes)
- [ ] **File**: `k8s/rbac.yaml` - works as-is on K3s
- [ ] Verify `external-secrets.io` API group exists in your cluster (it should since you run external-secrets)
- [ ] No changes needed

---

## Phase 2: Build & Deploy Scripts

### Task 2.1: Update deploy-to-ecr.sh ✅ DONE
- [x] **File**: `deploy-to-ecr.sh`
- [x] Changed `ECR_REPO` to `YOUR_AWS_ACCOUNT.dkr.ecr.us-east-2.amazonaws.com/oncall-agent`
- [x] Changed `REGION` to `us-east-2`
- [x] Removed `--profile admin` from all aws commands
- [x] Kept platform `linux/amd64` (k3s runs x86_64, M1 Mac cross-compiles via buildx)
- [x] Updated comments and "Next steps" text to reference k3s instead of EKS

### Task 2.2: Update build.sh ✅ DONE
- [x] **File**: `build.sh`
- [x] Changed `ECR_REGISTRY` to `YOUR_AWS_ACCOUNT.dkr.ecr.us-east-2.amazonaws.com`
- [x] Removed `us-east-1` reference from ECR login hint in next-steps text

### Task 2.3: Update docker-compose.yml (local dev) ✅ DONE
- [x] **File**: `docker-compose.yml`
- [x] Changed `GITHUB_ORG` from `artemishealth` → `arigsela`
- [x] Changed `AWS_REGION` default from `us-east-1` → `us-east-2`
- [x] Added `ALLOWED_CLUSTERS=default`, `PROTECTED_CLUSTERS=`, `ZEUS_INTEGRATION_ENABLED=false`
- [x] Removed: `K8S_CONTEXT`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `DATADOG_*`, `AWS_COST_EXPLORER_*`, `ATHENA_*`, `TEAMS_*`
- [x] Kubeconfig mount: changed from hardcoded EKS kubeconfig to `${KUBECONFIG:-~/.kube/config}`

---

## Phase 3: Source Code Changes

### Task 3.1: Replace System Prompt with Homelab Context ✅ DONE
- [x] **File**: `src/api/agent_client.py` — `_get_system_prompt()` method
- [x] Replaced EKS-centric prompt with homelab service catalog from `oncall/`
- [x] Includes: P0/P1 services, dependencies, known issues, GitOps workflow, vault unsealing
- [x] Kept tool docs for: K8s tools, GitHub tools, AWS (ECR/Secrets), incident memory, composite analysis
- [x] Removed tool docs for: Zeus, NAT gateway, Datadog, Cost Explorer, VPC endpoints
- [x] Removed EKS namespace patterns (artemis-auth-dev, proteus-dev) — homelab uses single namespaces
- [x] Added incident memory step to troubleshooting workflow (step 4: search_past_incidents)

### Task 3.2: Update Default Cluster References in Source ✅ DONE
All functional `"dev-eks"` defaults changed to `"default"` (8 edits across 7 files):

- [x] `src/api/models.py`: `K8S_CONTEXT` default and `ALLOWED_CLUSTERS` default
- [x] `src/api/memory.py`: `_get_default_cluster()` return value
- [x] `src/api/agent_client.py`: cluster variable in store_incident call
- [x] `src/memory/incident_store.py`: example cluster parameter
- [x] `src/memory/models.py`: Field description example
- [x] `src/tools/zeus_analyzer.py`: both `get_zeus_namespaces()` and `ZeusAnalyzer.__init__()` defaults
- [x] Remaining `"dev-eks"` references are example/doc values only (Task 3.3)

### Task 3.3: Update Example Values in Models ✅ DONE
- [x] `src/api/models.py`: incident example → chores-tracker-backend, cluster "default"
- [x] `src/api/models.py`: user_id examples → "ari" (2 locations)
- [x] `src/api/models.py`: image URL examples → ECR us-east-2 / chores-tracker-backend
- [x] `src/memory/__init__.py`: docstring example → chores-tracker-backend, cluster "default"
- [x] `src/memory/models.py`: schema example → chores-tracker-backend, cluster "default"
- [x] `src/api/agent_client.py`: tool description repo example → "arigsela/chores-tracker"
- [x] Remaining `artemishealth`/`dev-eks` refs only in `teams_notifier.py` (Task 3.5) and `api/README.md`

### Task 3.4: Remove Unused Routers from api_server.py ✅ DONE
- [x] **File**: `src/api/api_server.py`
- [x] Removed imports: `athena_costs`, `cost_explorer`, `hermes_chartdata`, `teams_webhook`
- [x] Removed router registrations for all 4 disabled modules
- [x] Kept `images.router` (useful for tracking ECR image deployments)
- [x] Updated root endpoint `/` — removed cost_explorer, athena_costs, hermes_chartdata, teams entries
- [x] Updated `/query` docstring — removed NAT gateway, Zeus, AWS credentials sections; added homelab examples

### Task 3.5: Remove Teams Notifier ✅ DONE
- [x] Deleted `src/notifications/teams_notifier.py`
- [x] Deleted `src/notifications/__init__.py`
- [x] Deleted `src/api/teams_models.py`
- [x] Deleted `src/api/teams_webhook.py`
- [x] Removed `src/notifications/` directory entirely

### Task 3.6: Update AWS Integrator Defaults ✅ DONE
- [x] **File**: `src/tools/aws_integrator.py` — `DEFAULT_REGION` changed from `"us-east-1"` → `"us-east-2"`

---

## Phase 4: Dockerfile & Dependencies

### Task 4.1: Review Dockerfile ✅ DONE
- [x] **File**: `Dockerfile`
- [x] Removed AWS CLI install block — all AWS operations use boto3 (Python SDK), not CLI binary (~300MB saved)
- [x] Kept `curl` install (needed for health check)
- [x] Updated `docker-entrypoint.sh` — changed `K8S_CONTEXT` default from `dev-eks` to `in-cluster`

### Task 4.2: Review requirements.txt ✅ DONE
- [x] **File**: `requirements.txt`
- [x] Updated header comment (ArtemisHealth → K3s Homelab)
- [x] Removed `datadog-api-client` (Datadog tools still in code but dormant — no docs in system prompt)
- [x] Kept `boto3` (actively used by aws_integrator.py and custom_tools.py for ECR/Secrets Manager)
- [x] Kept all core deps: `anthropic`, `fastapi`, `uvicorn`, `kubernetes`, `pydantic`, `PyGithub`, `slowapi`, `lancedb`

---

## Phase 5: Local Testing

### Task 5.1: Test Locally Before K3s Deploy ✅ DONE
- [x] Created `.env` with homelab values
- [x] Set `ANTHROPIC_API_KEY`, `GITHUB_TOKEN`, `K8S_CONTEXT`, `ALLOWED_CLUSTERS`
- [x] Ran API server locally
- [x] Verified health check and Swagger UI
- [x] Tested query endpoint (note: field is `prompt`, not `query`)
- [x] Verified K8s tools work against k3s cluster

### Task 5.2: Test Docker Build Locally ✅ DONE
- [x] Ran `docker compose up` with updated docker-compose.yml
- [x] Verified container starts and passes health check
- [x] Tested query through the container

---

## Phase 6: K3s Deployment

### Task 6.1: Build and Push Image
- [ ] Run updated `./deploy-to-ecr.sh v2.0.0`
- [ ] Verify image appears in your ECR repo (us-east-2)

### Task 6.2: Deploy to K3s
- [ ] Apply manifests in order:
  ```bash
  kubectl apply -f k8s/namespace.yaml
  kubectl apply -f k8s/rbac.yaml
  kubectl apply -f k8s/configmap.yaml
  kubectl apply -f k8s/incident-memory-pvc.yaml
  kubectl apply -f k8s/secret-store.yaml
  kubectl apply -f k8s/external-secret.yaml
  # Verify ExternalSecret synced successfully:
  kubectl get externalsecret -n oncall-agent
  kubectl get secret oncall-agent-secrets -n oncall-agent
  kubectl apply -f k8s/deployment.yaml
  ```
- [ ] Wait for pod to be ready: `kubectl get pods -n oncall-agent -w`
- [ ] Check logs: `kubectl logs -n oncall-agent -l app=oncall-agent-api -f`

### Task 6.3: Verify Deployment
- [ ] Port-forward and test: `kubectl port-forward -n oncall-agent svc/oncall-agent-api 8000:80`
- [ ] Health check: `curl http://localhost:8000/health`
- [ ] Test query against live cluster
- [ ] Verify incident memory PVC is mounted and writable
- [ ] Apply ingress if needed: `kubectl apply -f k8s/ingress.yaml`

### Task 6.4: Update n8n Integration
- [ ] Update n8n workflow to point to new service URL
- [ ] If using ClusterIP: `http://oncall-agent-api.oncall-agent.svc.cluster.local`
- [ ] If using ingress: `https://oncall.yourdomain.com`
- [ ] Test end-to-end through n8n

---

## Phase 7: Cleanup

### Task 7.1: Remove Old oncall/ Deployment
- [ ] Scale down old deployment: `kubectl scale deployment oncall-agent -n oncall-agent --replicas=0`
- [ ] Verify new deployment handles all traffic
- [ ] Delete old deployment resources once confirmed working

### Task 7.2: Update Repository Documentation
- [ ] Update `oncall-agent-api/CLAUDE.md` to reflect k3s deployment
- [ ] Update root `CLAUDE.md` project table if oncall-agent-api replaces oncall
- [ ] Update `oncall-agent-api/README.md` with k3s-specific instructions

---

## File Change Summary

| File | Change Type | Priority |
|------|-------------|----------|
| `k8s/configmap.yaml` | Edit (cluster/org/region values) | P0 |
| `k8s/deployment.yaml` | Edit (image, replicas, env vars) | P0 |
| `k8s/secret.yaml` | Edit (trimmed to fallback template) | P0 |
| `k8s/secret-store.yaml` | Create (Vault SecretStore) | P0 |
| `k8s/external-secret.yaml` | Create (Vault ExternalSecret) | P0 |
| `k8s/incident-memory-pvc.yaml` | Edit (storageClassName) | P1 |
| `k8s/oncall-agent-external-ingress.yaml` | Delete (AWS ALB) | P0 |
| `k8s/ingress.yaml` | Create (nginx, optional) | P2 |
| `deploy-to-ecr.sh` | Edit (ECR repo, region, profile) | P0 |
| `build.sh` | Edit (ECR repo) | P1 |
| `docker-compose.yml` | Edit (kubeconfig, env vars) | P1 |
| `src/api/agent_client.py` | Edit (system prompt, defaults) | P0 |
| `src/api/api_server.py` | Edit (disable routers) | P0 |
| `src/api/models.py` | Edit (default values, examples) | P1 |
| `src/api/memory.py` | Edit (default cluster) | P1 |
| `src/memory/incident_store.py` | Edit (default cluster) | P1 |
| `src/memory/models.py` | Edit (default cluster) | P1 |
| `src/tools/aws_integrator.py` | Edit (default region) | P1 |
| `src/tools/zeus_analyzer.py` | Edit (default cluster) | P2 |
| `src/notifications/teams_notifier.py` | Edit (URLs) | P2 |
| `Dockerfile` | Review (optional slim) | P2 |
| `requirements.txt` | Review (optional trim) | P2 |

---

## Risk Assessment

| Risk | Mitigation |
|------|------------|
| Breaking existing oncall/ while migrating | Keep old deployment running until new one is verified |
| K8s auth failure in k3s | Code already handles `load_incluster_config()` — works with ServiceAccount |
| Missing ECR pull credentials | Existing `ecr-auth` CronJob handles this |
| LanceDB PVC issues on local-path | Test PVC creation before deploying |
| Disabled features needed later | Comment out rather than delete — easy to re-enable |

---

## Notes

- The in-cluster K8s auth (`load_incluster_config()`) is already implemented in `custom_tools.py`,
  `hermes_chartdata.py`, `images.py`, and `zeus_analyzer.py` — no kubeconfig file needed when
  running inside k3s with a ServiceAccount.
- The `ecr-auth` CronJob in the homelab already syncs ECR credentials to `kube-system`,
  so imagePullSecrets should work without changes.
- All env var defaults flow from `K8S_CONTEXT` and `ALLOWED_CLUSTERS` — setting these correctly
  in the ConfigMap covers most runtime behavior even without code changes to defaults.
