#!/bin/bash
# Build and tag Docker image for On-Call Agent

set -e

VERSION=${1:-"latest"}
ECR_REGISTRY="082902060548.dkr.ecr.us-east-1.amazonaws.com"
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
echo "  1. Test locally: docker run -it --rm ${IMAGE_NAME}:${VERSION}"
echo "  2. Or use docker-compose: docker-compose up"
echo ""
echo "To push to ECR:"
echo "  1. Login: aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin ${ECR_REGISTRY}"
echo "  2. Push: docker push ${ECR_REGISTRY}/${IMAGE_NAME}:${VERSION}"
echo ""
