#!/bin/bash
# Build and tag Docker image for EKS Monitoring Agent

set -e

VERSION=${1:-"latest"}
ECR_REGISTRY="082902060548.dkr.ecr.us-east-1.amazonaws.com"
IMAGE_NAME="eks-monitoring-agent"

echo "=========================================="
echo "Building EKS Monitoring Agent Docker Image"
echo "=========================================="
echo "Version: $VERSION"
echo "Platform: linux/arm64 (Mac ARM)"
echo ""

# Build image
echo "Building Docker image..."
docker build --platform linux/arm64 -t ${IMAGE_NAME}:${VERSION} .

# Tag for local use
echo "Tagging for local use..."
docker tag ${IMAGE_NAME}:${VERSION} ${IMAGE_NAME}:local

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
echo "Local images:"
echo "  - ${IMAGE_NAME}:${VERSION}"
echo "  - ${IMAGE_NAME}:local"
echo ""
echo "ECR image:"
echo "  - ${ECR_REGISTRY}/${IMAGE_NAME}:${VERSION}"
if [ "$VERSION" != "latest" ]; then
    echo "  - ${ECR_REGISTRY}/${IMAGE_NAME}:latest"
fi
echo ""
echo "Next steps:"
echo "  1. Test locally: docker compose up"
echo "  2. View logs: docker compose logs -f"
echo "  3. Deploy to ECR: ./deploy-to-ecr.sh ${VERSION}"
echo ""
echo "To test manually:"
echo "  docker run -it --rm \\"
echo "    -v ~/.kube/config:/root/.kube/config:ro \\"
echo "    -v /var/run/docker.sock:/var/run/docker.sock \\"
echo "    -e ANTHROPIC_API_KEY=\$ANTHROPIC_API_KEY \\"
echo "    -e GITHUB_PERSONAL_ACCESS_TOKEN=\$GITHUB_PERSONAL_ACCESS_TOKEN \\"
echo "    ${IMAGE_NAME}:local"
echo ""
