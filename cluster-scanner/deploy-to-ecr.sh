#!/bin/bash
# Deploy Cluster Scanner to AWS ECR (k3s homelab)
# Builds AMD64 image from M1 Mac and pushes to ECR

set -e

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

# Configuration
ECR_REPO="852893458518.dkr.ecr.us-east-2.amazonaws.com/cluster-scanner"
VERSION="${1:-v1.0.0}"
REGION="us-east-2"

echo "=========================================="
echo "  Deploy Cluster Scanner to ECR"
echo "=========================================="
echo ""
echo "ECR Repository: $ECR_REPO"
echo "Version: $VERSION"
echo "Region: $REGION"
echo ""

# Step 1: Login to ECR
echo -e "${BLUE}Step 1: Logging into ECR...${NC}"
aws ecr get-login-password --region $REGION | \
  docker login --username AWS --password-stdin \
  $(echo $ECR_REPO | cut -d'/' -f1)

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✅ Logged in to ECR${NC}"
else
    echo -e "${RED}❌ ECR login failed${NC}"
    echo "Ensure AWS CLI is configured and you have ECR permissions"
    exit 1
fi
echo ""

# Step 2: Build image for AMD64 (k3s runs x86_64)
echo -e "${BLUE}Step 2: Building Docker image for AMD64 (k3s)...${NC}"
echo "Platform: linux/amd64 (x86_64 for k3s server)"
echo ""

docker buildx build \
  --platform linux/amd64 \
  -t cluster-scanner:$VERSION \
  -f Dockerfile \
  --load \
  .

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✅ Image built successfully${NC}"
else
    echo -e "${RED}❌ Build failed${NC}"
    exit 1
fi
echo ""

# Step 3: Tag for ECR
echo -e "${BLUE}Step 3: Tagging for ECR...${NC}"
docker tag cluster-scanner:$VERSION $ECR_REPO:$VERSION
docker tag cluster-scanner:$VERSION $ECR_REPO:latest

echo -e "${GREEN}✅ Image tagged:${NC}"
echo "   - $ECR_REPO:$VERSION"
echo "   - $ECR_REPO:latest"
echo ""

# Step 4: Push to ECR
echo -e "${BLUE}Step 4: Pushing to ECR...${NC}"
echo "Pushing versioned tag..."
docker push $ECR_REPO:$VERSION

echo "Pushing latest tag..."
docker push $ECR_REPO:latest

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✅ Images pushed to ECR${NC}"
else
    echo -e "${RED}❌ Push failed${NC}"
    exit 1
fi
echo ""

# Step 5: Verify in ECR
echo -e "${BLUE}Step 5: Verifying in ECR...${NC}"
aws ecr describe-images \
  --repository-name cluster-scanner \
  --region $REGION \
  --output table \
  --query 'sort_by(imageDetails,& imagePushedAt)[*].[imageTags[0],imagePushedAt,imageSizeInBytes]' || true

echo ""

# Summary
echo "=========================================="
echo -e "${GREEN}  Deploy Complete!${NC}"
echo "=========================================="
echo ""
echo "Image available at:"
echo "  - $ECR_REPO:$VERSION"
echo "  - $ECR_REPO:latest"
echo ""
echo -e "${YELLOW}Next steps:${NC}"
echo ""
echo "1. Deploy to k3s:"
echo "   kubectl apply -f k8s/"
echo ""
echo "2. Test with a manual job:"
echo "   kubectl create job --from=cronjob/cluster-scanner test-scan -n cluster-scanner"
echo ""
echo "3. Watch logs:"
echo "   kubectl logs -n cluster-scanner -l app=cluster-scanner -f"
echo ""
