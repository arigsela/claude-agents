#!/bin/bash
# Build and tag Docker image for On-Call Agent (k3s homelab)

set -e

VERSION=${1:-"latest"}
ECR_REGISTRY="YOUR_AWS_ACCOUNT.dkr.ecr.us-east-2.amazonaws.com"
IMAGE_NAME="oncall-agent"

echo "=========================================="
echo "Building On-Call Agent Docker Image"
echo "=========================================="
echo "Version: $VERSION"
echo ""

# Build image
echo "Building Docker image..."
docker build -t ${IMAGE_NAME}:${VERSION} .

# Tag for ECR
echo "Tagging for ECR..."
docker tag ${IMAGE_NAME}:${VERSION} ${ECR_REGISTRY}/${IMAGE_NAME}:${VERSION}

if [ "$VERSION" != "latest" ]; then
    docker tag ${IMAGE_NAME}:${VERSION} ${ECR_REGISTRY}/${IMAGE_NAME}:latest
fi

echo ""
echo "=========================================="
echo "Build Complete!"
echo "=========================================="
echo ""
echo "Local image: ${IMAGE_NAME}:${VERSION}"
echo "ECR image: ${ECR_REGISTRY}/${IMAGE_NAME}:${VERSION}"
echo ""
echo "Next steps:"
echo "  1. Test locally: docker compose up"
echo "  2. Push to ECR: ./deploy-to-ecr.sh ${VERSION}"
echo ""
