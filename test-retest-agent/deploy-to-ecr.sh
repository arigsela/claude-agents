#!/bin/bash
# ==============================================================================
# Build & Push Docker Images to AWS ECR
# ==============================================================================
#
# USAGE:
#   ./deploy-to-ecr.sh                    # Uses git SHA as version tag
#   ./deploy-to-ecr.sh --version 1.0.0    # Uses specified version tag
#
# WHAT IT DOES:
# 1. Logs in to AWS ECR (Elastic Container Registry)
# 2. Builds each service image for linux/amd64 (K8s nodes run AMD64)
# 3. Pushes with both :version and :latest tags
#
# PREREQUISITES:
# - AWS CLI configured with ECR push permissions
# - Docker with buildx support (for cross-platform builds on Apple Silicon)
# ==============================================================================

set -euo pipefail

# ECR registry — update this to match your AWS account and region
ECR_REGISTRY="852893458518.dkr.ecr.us-east-2.amazonaws.com"
REGION="us-east-2"

# Parse arguments
VERSION=""
while [[ $# -gt 0 ]]; do
    case $1 in
        --version) VERSION="$2"; shift 2 ;;
        *) echo "Unknown argument: $1"; exit 1 ;;
    esac
done

# Default to git SHA if no version specified
if [ -z "$VERSION" ]; then
    VERSION=$(git rev-parse --short HEAD 2>/dev/null || echo "latest")
fi

echo "=== Building images with version: $VERSION ==="

# Login to ECR
aws ecr get-login-password --region "$REGION" | \
    docker login --username AWS --password-stdin "$ECR_REGISTRY"

# Services to build: (image-name dockerfile-path)
SERVICES=(
    "test-retest-agent-orchestrator:docker/Dockerfile.orchestrator"
    "test-retest-agent-test-sub-agent:docker/Dockerfile.test-sub-agent"
)

for service_spec in "${SERVICES[@]}"; do
    IFS=':' read -r IMAGE_NAME DOCKERFILE <<< "$service_spec"
    REPO="$ECR_REGISTRY/$IMAGE_NAME"

    echo ""
    echo "--- Building $IMAGE_NAME ---"

    # Create ECR repo if it doesn't exist
    aws ecr describe-repositories --repository-names "$IMAGE_NAME" --region "$REGION" 2>/dev/null || \
        aws ecr create-repository --repository-name "$IMAGE_NAME" --region "$REGION"

    # Build for linux/amd64 (even on Apple Silicon Macs)
    docker buildx build \
        --platform linux/amd64 \
        -f "$DOCKERFILE" \
        -t "$REPO:$VERSION" \
        -t "$REPO:latest" \
        --push \
        .

    echo "Pushed: $REPO:$VERSION"
done

echo ""
echo "=== All images pushed successfully ==="

