#!/bin/bash
# Build the homelab-agent image (AMD64, from Apple Silicon) and push to ECR.
#
# Usage:
#   ./deploy-to-ecr.sh            # tag v0.1.0
#   ./deploy-to-ecr.sh v0.2.0     # explicit tag
set -e

ECR_REGISTRY="852893458518.dkr.ecr.us-east-2.amazonaws.com"
REPO="homelab-agent"
VERSION="${1:-v0.1.0}"
REGION="us-east-2"

echo "==> Logging into ECR ($REGION)"
aws ecr get-login-password --region "$REGION" | \
  docker login --username AWS --password-stdin "$ECR_REGISTRY"

echo "==> Ensuring ECR repository exists: $REPO"
aws ecr describe-repositories --repository-names "$REPO" --region "$REGION" >/dev/null 2>&1 || \
  aws ecr create-repository --repository-name "$REPO" --region "$REGION" \
    --image-scanning-configuration scanOnPush=true >/dev/null

echo "==> Building and pushing $ECR_REGISTRY/$REPO:$VERSION (linux/amd64)"
docker buildx build --platform linux/amd64 \
  -t "$ECR_REGISTRY/$REPO:$VERSION" \
  -t "$ECR_REGISTRY/$REPO:latest" \
  --push .

echo "==> Done: $ECR_REGISTRY/$REPO:$VERSION"
echo "    Reference this tag in arigsela/kubernetes base-apps/kagent/agents/homelab-agent.yaml (spec.byo.deployment.image)"
