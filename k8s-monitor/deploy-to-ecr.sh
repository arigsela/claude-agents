#!/bin/bash

# Deploy K8s Monitor to AWS ECR
# Usage: ./deploy-to-ecr.sh [VERSION]
# Example: ./deploy-to-ecr.sh v0.0.1

set -e

# Configuration
AWS_ACCOUNT_ID="YOUR_AWS_ACCOUNT"
AWS_REGION="us-east-2"
ECR_REGISTRY="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
IMAGE_NAME="k8s-monitor"
IMAGE_REPO="${ECR_REGISTRY}/${IMAGE_NAME}"

# Get version from argument or use default
VERSION="${1:-v0.0.1}"

# Validate version format
if [[ ! $VERSION =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "❌ Invalid version format: $VERSION"
  echo "   Expected format: vX.Y.Z (e.g., v0.0.1)"
  exit 1
fi

# Full image URI
IMAGE_URI="${IMAGE_REPO}:${VERSION}"
LATEST_URI="${IMAGE_REPO}:latest"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🚀 K8s Monitor ECR Deployment"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "AWS Account:    $AWS_ACCOUNT_ID"
echo "Region:         $AWS_REGION"
echo "ECR Registry:   $ECR_REGISTRY"
echo "Image:          $IMAGE_NAME"
echo "Version:        $VERSION"
echo "Image URI:      $IMAGE_URI"
echo "Latest URI:     $LATEST_URI"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Step 1: Build Docker image
echo ""
echo "📦 Step 1: Building Docker image..."
docker build \
  --no-cache \
  --tag "${IMAGE_URI}" \
  --tag "${LATEST_URI}" \
  --file Dockerfile \
  .

if [ $? -eq 0 ]; then
  echo "✅ Docker image built successfully"
  docker images | grep "${IMAGE_NAME}" | head -2
else
  echo "❌ Docker build failed"
  exit 1
fi

# Step 2: Authenticate with ECR
echo ""
echo "🔐 Step 2: Authenticating with AWS ECR..."
aws ecr get-login-password --region "${AWS_REGION}" | \
  docker login --username AWS --password-stdin "${ECR_REGISTRY}"

if [ $? -eq 0 ]; then
  echo "✅ Successfully authenticated with ECR"
else
  echo "❌ ECR authentication failed"
  echo "   Make sure AWS credentials are configured (aws configure)"
  exit 1
fi

# Step 3: Push image to ECR
echo ""
echo "📤 Step 3: Pushing image to ECR..."
echo "   Pushing ${IMAGE_URI}..."
docker push "${IMAGE_URI}"

if [ $? -eq 0 ]; then
  echo "✅ Image pushed successfully"
else
  echo "❌ Failed to push versioned image"
  exit 1
fi

echo "   Pushing ${LATEST_URI}..."
docker push "${LATEST_URI}"

if [ $? -eq 0 ]; then
  echo "✅ Latest tag pushed successfully"
else
  echo "❌ Failed to push latest tag"
  exit 1
fi

# Summary
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ Deployment Complete!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "🎯 Next Steps:"
echo ""
echo "1. Update Kubernetes deployment with new image:"
echo "   kubectl set image deployment/k8s-monitor \\"
echo "     k8s-monitor=${IMAGE_URI} \\"
echo "     -n k8s-monitor"
echo ""
echo "2. Or update deployment manifest and apply:"
echo "   kubectl apply -f k8s/deployment.yaml"
echo ""
echo "3. Verify deployment:"
echo "   kubectl rollout status deployment/k8s-monitor -n k8s-monitor"
echo ""
echo "4. Check logs:"
echo "   kubectl logs -f deployment/k8s-monitor -n k8s-monitor"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
