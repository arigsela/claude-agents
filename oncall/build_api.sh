#!/bin/bash
# Build Docker image for OnCall Agent API
# Supports multi-platform builds for deployment

set -e

GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

echo "=================================================="
echo "  OnCall Agent API - Docker Build"
echo "=================================================="
echo ""

# Get version from args or default
VERSION=${1:-latest}
IMAGE_NAME="oncall-agent"
IMAGE_TAG="${IMAGE_NAME}:${VERSION}"

echo -e "${BLUE}Building image: ${IMAGE_TAG}${NC}"
echo "Platform: linux/amd64 (for EKS deployment)"
echo ""

# Build for AMD64 (EKS platform)
# Use buildx for cross-platform support
docker buildx build \
  --platform linux/amd64 \
  -t ${IMAGE_TAG} \
  -t ${IMAGE_NAME}:latest \
  -f Dockerfile \
  --load \
  .

if [ $? -eq 0 ]; then
    echo ""
    echo -e "${GREEN}✅ Build successful!${NC}"
    echo ""
    echo "Image tags created:"
    echo "  - ${IMAGE_TAG}"
    echo "  - ${IMAGE_NAME}:latest"
    echo ""
    echo "Next steps:"
    echo ""
    echo "1. Test locally:"
    echo "   docker run --rm -e RUN_MODE=api -p 8000:8000 ${IMAGE_TAG}"
    echo ""
    echo "2. Test with docker-compose:"
    echo "   docker compose up oncall-agent-api"
    echo ""
    echo "3. Push to registry:"
    echo "   docker tag ${IMAGE_TAG} YOUR_ECR_REPO/oncall-agent:${VERSION}"
    echo "   docker push YOUR_ECR_REPO/oncall-agent:${VERSION}"
    echo ""
else
    echo "❌ Build failed"
    exit 1
fi
