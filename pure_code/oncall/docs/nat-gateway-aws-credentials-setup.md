# AWS Credentials Setup for NAT Gateway Analysis

This guide explains how to configure AWS credentials for the OnCall Agent API to access CloudWatch metrics and analyze NAT gateway traffic.

## Overview

The NAT gateway analysis feature requires AWS credentials with permissions to:
- **CloudWatch**: Read NAT gateway metrics
- **EC2**: Describe NAT gateways and VPCs

## IAM Permissions Required

Create an IAM user or role with these permissions:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "cloudwatch:GetMetricStatistics",
        "cloudwatch:ListMetrics",
        "ec2:DescribeNatGateways",
        "ec2:DescribeVpcs",
        "ec2:DescribeSubnets"
      ],
      "Resource": "*"
    }
  ]
}
```

**Policy Name Suggestion**: `OncallAgentNATGatewayReadOnly`

## Setup Steps

### Step 1: Add Credentials to AWS Secrets Manager

Add these properties to your existing secret: `dev-eks/dev/oncall-agent`

**Using AWS CLI**:
```bash
# Get current secret value
aws secretsmanager get-secret-value \
  --secret-id dev-eks/dev/oncall-agent \
  --region us-east-1 \
  --profile admin \
  --query SecretString \
  --output text > /tmp/current-secret.json

# Edit /tmp/current-secret.json and add:
# "aws-access-key-id": "AKIA...",
# "aws-secret-access-key": "...",
# "aws-region": "us-east-1"

# Update the secret
aws secretsmanager update-secret \
  --secret-id dev-eks/dev/oncall-agent \
  --region us-east-1 \
  --profile admin \
  --secret-string file:///tmp/current-secret.json
```

**Using AWS Console**:
1. Navigate to AWS Secrets Manager
2. Find secret: `dev-eks/dev/oncall-agent`
3. Click "Retrieve secret value" → "Edit"
4. Add key/value pairs:
   - Key: `aws-access-key-id`, Value: `AKIA...`
   - Key: `aws-secret-access-key`, Value: `...`
   - Key: `aws-region`, Value: `us-east-1`
5. Save

### Step 2: Update ExternalSecret (if using External Secrets Operator)

Your ExternalSecret manifest should include:

```yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: oncall-agent-api-secrets
  namespace: crossplane-oncall-agent
spec:
  data:
    - remoteRef:
        key: dev-eks/dev/oncall-agent
        property: anthropic-api-key
      secretKey: anthropic-api-key
    - remoteRef:
        key: dev-eks/dev/oncall-agent
        property: github-token
      secretKey: github-token
    - remoteRef:
        key: dev-eks/dev/oncall-agent
        property: api-keys
      secretKey: api-keys
    # AWS credentials for NAT gateway analysis
    - remoteRef:
        key: dev-eks/dev/oncall-agent
        property: aws-access-key-id
      secretKey: aws-access-key-id
    - remoteRef:
        key: dev-eks/dev/oncall-agent
        property: aws-secret-access-key
      secretKey: aws-secret-access-key
    - remoteRef:
        key: dev-eks/dev/oncall-agent
        property: aws-region
      secretKey: aws-region
  refreshInterval: 1m
  secretStoreRef:
    kind: ClusterSecretStore
    name: aws-cluster-secrets-store
  target:
    creationPolicy: Owner
    name: oncall-agent-api-secrets
```

### Step 3: Verify Deployment Uses Credentials

Your `k8s/api-deployment.yaml` should mount AWS credentials (already updated):

```yaml
env:
  # ... other env vars ...

  # AWS Credentials for NAT Gateway analysis
  - name: AWS_ACCESS_KEY_ID
    valueFrom:
      secretKeyRef:
        name: oncall-agent-api-secrets
        key: aws-access-key-id

  - name: AWS_SECRET_ACCESS_KEY
    valueFrom:
      secretKeyRef:
        name: oncall-agent-api-secrets
        key: aws-secret-access-key

  - name: AWS_REGION
    valueFrom:
      secretKeyRef:
        name: oncall-agent-api-secrets
        key: aws-region
        optional: true
```

### Step 4: Apply Changes

```bash
# If you updated the ExternalSecret manifest
kubectl apply -f your-externalsecret.yaml

# Wait for ExternalSecret to sync (check status)
kubectl get externalsecret oncall-agent-api-secrets -n crossplane-oncall-agent

# Verify the Kubernetes secret was created/updated
kubectl get secret oncall-agent-api-secrets -n crossplane-oncall-agent -o yaml

# Check that aws credentials keys exist
kubectl get secret oncall-agent-api-secrets -n crossplane-oncall-agent -o jsonpath='{.data}' | jq 'keys'

# Should show: aws-access-key-id, aws-secret-access-key, aws-region

# Restart API pods to pick up new credentials
kubectl rollout restart deployment oncall-agent-api -n oncall-agent
```

### Step 5: Verify

```bash
# Check pod logs
kubectl logs -f deployment/oncall-agent-api -n oncall-agent

# You should see:
# "Using AWS credentials from environment variables (KUBERNETES or default)"

# Test NAT query via API
curl -X POST https://oncall-agent.internal.artemishealth.com/query \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-key" \
  -d '{"prompt": "Show me NAT traffic for the last hour"}'
```

## Troubleshooting

### "The config profile (admin) could not be found"
**Solution**: AWS credentials not mounted as environment variables
- Check ExternalSecret synced: `kubectl describe externalsecret ...`
- Check secret has AWS keys: `kubectl get secret ... -o yaml`
- Restart pods: `kubectl rollout restart deployment/oncall-agent-api`

### "Unable to locate credentials"
**Solution**: Environment variables not set
- Verify deployment mounts the secret keys
- Check pod environment: `kubectl exec -it <pod> -- env | grep AWS`

### "Access Denied" when fetching metrics
**Solution**: IAM permissions insufficient
- Verify IAM user/role has CloudWatch:GetMetricStatistics
- Verify IAM user/role has EC2:DescribeNatGateways

## Security Best Practices

1. **Use IAM Role with IRSA** (recommended for production):
   - Instead of access keys, use IAM Roles for Service Accounts (IRSA)
   - Eliminates need to manage credentials
   - Better security posture

2. **Least Privilege**:
   - Only grant CloudWatch:GetMetricStatistics (read-only)
   - Only grant EC2:Describe* (read-only)
   - No write permissions needed

3. **Credential Rotation**:
   - Rotate access keys regularly (every 90 days)
   - Use AWS Secrets Manager rotation for automatic rotation

## Alternative: IRSA (IAM Roles for Service Accounts)

For production, consider using IRSA instead of access keys:

```yaml
# ServiceAccount with IAM role annotation
apiVersion: v1
kind: ServiceAccount
metadata:
  name: oncall-agent-api-sa
  namespace: oncall-agent
  annotations:
    eks.amazonaws.com/role-arn: arn:aws:iam::082902060548:role/OncallAgentNATGatewayRole

# No AWS credentials needed in deployment - role assumed automatically
```

This eliminates the need for AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY entirely.

## Quick Reference

**Required Environment Variables** (in pod):
- `AWS_ACCESS_KEY_ID` - IAM access key
- `AWS_SECRET_ACCESS_KEY` - IAM secret key
- `AWS_REGION` - AWS region (default: us-east-1)

**Required IAM Permissions**:
- `cloudwatch:GetMetricStatistics`
- `cloudwatch:ListMetrics`
- `ec2:DescribeNatGateways`
- `ec2:DescribeVpcs`

**Verification Commands**:
```bash
# Check secret exists and has AWS keys
kubectl get secret oncall-agent-api-secrets -n crossplane-oncall-agent -o jsonpath='{.data}' | jq 'keys'

# Check pod has environment variables
kubectl exec -it deployment/oncall-agent-api -n oncall-agent -- env | grep AWS

# Test NAT query
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Show NAT traffic for the last hour"}'
```
