# Kubernetes Deployment Guide
## On-Call Troubleshooting Agent

---

## Prerequisites

- Kubernetes cluster (dev-eks) with kubectl access
- Docker for building images
- AWS ECR access (or other container registry)
- Required credentials:
  - Anthropic API key
  - GitHub token (repo + workflow permissions)
  - Teams webhook URL
  - AWS credentials (for Secrets Manager and ECR verification)
    - **Recommended**: Use IRSA (IAM Roles for Service Accounts) for EKS
    - **Alternative**: Static AWS access keys (less secure)

---

## Quick Deployment

### 1. Build and Push Docker Image

```bash
# Build the image
docker build -t oncall-agent:v0.1.0 .

# Tag for ECR (adjust for your ECR URL)
docker tag oncall-agent:v0.1.0 082902060548.dkr.ecr.us-east-1.amazonaws.com/oncall-agent:v0.1.0

# Login to ECR
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin 082902060548.dkr.ecr.us-east-1.amazonaws.com

# Push to ECR
docker push 082902060548.dkr.ecr.us-east-1.amazonaws.com/oncall-agent:v0.1.0
```

### 2. Create Kubernetes Resources

```bash
# Create namespace
kubectl apply -f k8s/namespace.yaml

# Create configmap
kubectl apply -f k8s/configmap.yaml

# Create credentials secret (replace with actual values)
# Option 1: With static AWS credentials (simple but less secure)
kubectl create secret generic oncall-agent-secrets \
  --namespace=oncall-agent \
  --from-literal=anthropic-api-key=sk-ant-your-key-here \
  --from-literal=github-token=ghp_your-token-here \
  --from-literal=teams-webhook-url=https://your-webhook-url \
  --from-literal=aws-access-key-id=AKIA... \
  --from-literal=aws-secret-access-key=...

# Option 2: Using IRSA (recommended for EKS - see "AWS Authentication" section below)
kubectl create secret generic oncall-agent-secrets \
  --namespace=oncall-agent \
  --from-literal=anthropic-api-key=sk-ant-your-key-here \
  --from-literal=github-token=ghp_your-token-here \
  --from-literal=teams-webhook-url=https://your-webhook-url
# Note: AWS credentials provided automatically via IRSA annotation on ServiceAccount

# Create RBAC (service account, role, binding)
kubectl apply -f k8s/rbac.yaml

# Deploy the agent
kubectl apply -f k8s/deployment.yaml
```

### 3. Verify Deployment

```bash
# Check pod status
kubectl get pods -n oncall-agent

# View logs
kubectl logs -f deployment/oncall-agent -n oncall-agent

# Check events
kubectl get events -n oncall-agent --sort-by='.lastTimestamp'
```

---

## Local Docker Testing (Before K8s Deployment)

### Using Docker Compose

```bash
# 1. Create .env file with credentials
cat > .env << 'EOF'
ANTHROPIC_API_KEY=sk-ant-your-key-here
GITHUB_TOKEN=ghp_your-token-here
TEAMS_WEBHOOK_URL=https://your-webhook-url
EOF

# 2. Start container
docker-compose up -d

# 3. Watch logs
docker-compose logs -f

# 4. Stop container
docker-compose down
```

### Using Docker Directly

```bash
# Build
docker build -t oncall-agent:local .

# Run
docker run -d \
  --name oncall-agent \
  -e ANTHROPIC_API_KEY=sk-ant-... \
  -e GITHUB_TOKEN=ghp_... \
  -e TEAMS_WEBHOOK_URL=https://... \
  -e K8S_CONTEXT=dev-eks \
  -e TEAMS_NOTIFICATIONS_ENABLED=true \
  -e AWS_ACCESS_KEY_ID=AKIA... \
  -e AWS_SECRET_ACCESS_KEY=... \
  -e AWS_REGION=us-east-1 \
  -v ~/.kube/config:/root/.kube/config:ro \
  oncall-agent:local

# Logs
docker logs -f oncall-agent

# Stop
docker stop oncall-agent && docker rm oncall-agent
```

---

## Configuration Files

### Manifest Overview

| File | Purpose |
|------|---------|
| `namespace.yaml` | Creates oncall-agent namespace |
| `configmap.yaml` | Non-sensitive configuration |
| `secret.yaml` | Template for sensitive credentials |
| `rbac.yaml` | Service account + read-only K8s permissions |
| `deployment.yaml` | Agent deployment spec |

### RBAC Permissions

The agent has **read-only** access to:
- ✅ Pods (including logs and status)
- ✅ Events
- ✅ Deployments and ReplicaSets
- ✅ Namespaces
- ✅ Services
- ✅ ExternalSecrets CRD (for AWS Secrets Manager sync verification)

The agent **CANNOT**:
- ❌ Create/modify/delete any K8s resources
- ❌ Execute commands in pods
- ❌ Modify deployments
- ❌ Change configurations

All remediation actions go through **GitOps workflow** (PR-based) via Deploy GHA.

### AWS Authentication

The agent uses **AWSIntegrator** for verifying AWS resources (Secrets Manager, ECR). Two authentication options:

**Option 1: IRSA (Recommended for EKS)**
```yaml
# Annotate ServiceAccount in k8s/rbac.yaml:
apiVersion: v1
kind: ServiceAccount
metadata:
  name: oncall-agent
  namespace: oncall-agent
  annotations:
    eks.amazonaws.com/role-arn: arn:aws:iam::082902060548:role/OncallAgentRole
```

**Required IAM Policy:**
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "secretsmanager:DescribeSecret",
        "secretsmanager:GetSecretValue"
      ],
      "Resource": "arn:aws:secretsmanager:us-east-1:082902060548:secret:*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "ecr:DescribeImages",
        "ecr:DescribeRepositories"
      ],
      "Resource": "*"
    }
  ]
}
```

**Option 2: Static Credentials (Less Secure)**
- Include `aws-access-key-id` and `aws-secret-access-key` in secret (as shown above)
- Not recommended for production

---

## Environment Variables

### Required Secrets (in k8s/secret.yaml)
```yaml
anthropic-api-key: Your Anthropic API key
github-token: GitHub PAT with repo + workflow permissions
teams-webhook-url: Microsoft Teams incoming webhook URL
aws-access-key-id: AWS access key (optional if using IRSA)
aws-secret-access-key: AWS secret key (optional if using IRSA)
```

### Required Config (in k8s/configmap.yaml)
```yaml
K8S_CONTEXT: dev-eks
GITHUB_ORG: artemishealth
AWS_REGION: us-east-1
TEAMS_NOTIFICATIONS_ENABLED: "true"
AGENT_LOG_LEVEL: INFO
```

### Kubernetes Authentication

The agent uses **in-cluster configuration** when running inside Kubernetes:
- No kubeconfig file needed
- Uses ServiceAccount token from `/var/run/secrets/kubernetes.io/serviceaccount/token`
- Automatically configured via `load_incluster_config()`
- Falls back to kubeconfig for local development

---

## Monitoring the Agent

### View Real-Time Logs
```bash
kubectl logs -f deployment/oncall-agent -n oncall-agent
```

### Check Agent Status
```bash
kubectl get pods -n oncall-agent
kubectl describe pod -l app=oncall-agent -n oncall-agent
```

### View Recent Events
```bash
kubectl get events -n oncall-agent --sort-by='.lastTimestamp' | tail -20
```

### Check Resource Usage
```bash
kubectl top pod -n oncall-agent
```

---

## Updating the Agent

### Rolling Update
```bash
# Build new version
docker build -t oncall-agent:v0.2.0 .

# Push to registry
docker push 082902060548.dkr.ecr.us-east-1.amazonaws.com/oncall-agent:v0.2.0

# Update deployment
kubectl set image deployment/oncall-agent \
  agent=082902060548.dkr.ecr.us-east-1.amazonaws.com/oncall-agent:v0.2.0 \
  -n oncall-agent

# Watch rollout
kubectl rollout status deployment/oncall-agent -n oncall-agent
```

### Configuration Update
```bash
# Update configmap
kubectl apply -f k8s/configmap.yaml

# Restart pods to pick up changes
kubectl rollout restart deployment/oncall-agent -n oncall-agent
```

---

## Troubleshooting

### Pod Won't Start
```bash
# Check pod events
kubectl describe pod -l app=oncall-agent -n oncall-agent

# Common issues:
# 1. Missing secrets → Create k8s/secret.yaml
# 2. Image pull errors → Check ECR permissions
# 3. RBAC issues → Verify service account exists
```

### MCP Server Connection Failures
```bash
# Check logs for npx download issues
kubectl logs deployment/oncall-agent -n oncall-agent | grep npx

# Common issues:
# 1. No internet access → Check cluster network policies
# 2. npm registry blocked → Configure npm proxy
# 3. Slow downloads → Increase initialDelaySeconds in probes
```

### Agent Not Processing Events
```bash
# Verify K8s RBAC permissions
kubectl auth can-i get pods --as=system:serviceaccount:oncall-agent:oncall-agent

# Check event watcher logs
kubectl logs deployment/oncall-agent -n oncall-agent | grep "K8s event watcher"

# Verify service account mounted
kubectl exec -it deployment/oncall-agent -n oncall-agent -- ls -la /var/run/secrets/kubernetes.io/serviceaccount/
```

### AWS Integration Issues
```bash
# Check if AWSIntegrator initialized
kubectl logs deployment/oncall-agent -n oncall-agent | grep "AWSIntegrator"

# Common issues:
# 1. boto3 not available → Check container has boto3 installed
# 2. AWS credentials not found → Verify secret or IRSA annotation
# 3. Access denied → Check IAM policy permissions for Secrets Manager/ECR
# 4. Wrong region → Verify AWS_REGION in configmap

# Test AWS access from inside pod
kubectl exec -it deployment/oncall-agent -n oncall-agent -- python3 -c "
import boto3
try:
    client = boto3.client('secretsmanager', region_name='us-east-1')
    print('✓ AWS Secrets Manager client created successfully')
except Exception as e:
    print(f'✗ Error: {e}')
"
```

---

## Security Considerations

### Secrets Management
**DO NOT commit k8s/secret.yaml with real credentials!**

Use one of:
1. **kubectl create secret** (shown above)
2. **Sealed Secrets** (encrypted secrets in git)
3. **External Secrets Operator** (AWS Secrets Manager, Vault)
4. **AWS Parameter Store** (for EKS clusters with IRSA)

### RBAC Principle of Least Privilege
The agent only has **read** access to K8s resources. All write operations go through:
- GitHub PRs (Deploy GHA workflow)
- Human approval process
- ArgoCD reconciliation

### Network Policies
Consider adding NetworkPolicy to restrict agent egress:
```yaml
# Only allow:
- Anthropic API (api.anthropic.com)
- GitHub API (api.github.com)
- Teams webhook (*.office.com)
- K8s API server
```

---

## CI/CD Integration

### GitHub Actions Workflow Example

```yaml
name: Build and Deploy On-Call Agent

on:
  push:
    branches: [main]
    paths:
      - 'src/**'
      - 'config/**'
      - 'Dockerfile'

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Configure AWS credentials
        uses: aws-actions/configure-aws-credentials@v2
        with:
          role-to-assume: arn:aws:iam::082902060548:role/GithubActionsRole
          aws-region: us-east-1

      - name: Login to ECR
        run: |
          aws ecr get-login-password | docker login --username AWS --password-stdin 082902060548.dkr.ecr.us-east-1.amazonaws.com

      - name: Build and push
        run: |
          docker build -t oncall-agent:${{ github.sha }} .
          docker tag oncall-agent:${{ github.sha }} 082902060548.dkr.ecr.us-east-1.amazonaws.com/oncall-agent:${{ github.sha }}
          docker tag oncall-agent:${{ github.sha }} 082902060548.dkr.ecr.us-east-1.amazonaws.com/oncall-agent:latest
          docker push 082902060548.dkr.ecr.us-east-1.amazonaws.com/oncall-agent:${{ github.sha }}
          docker push 082902060548.dkr.ecr.us-east-1.amazonaws.com/oncall-agent:latest

      - name: Update K8s deployment
        run: |
          kubectl set image deployment/oncall-agent \
            agent=082902060548.dkr.ecr.us-east-1.amazonaws.com/oncall-agent:${{ github.sha }} \
            -n oncall-agent
```

---

**Last Updated:** 2025-10-03
**Status:** Container configuration complete with AWS integrator support, ready for deployment
