#!/bin/bash
# Deploy EKS Monitoring Agent to AWS ECR
# Builds multi-platform image and pushes to ECR for EKS deployment

set -e

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

# Configuration
ECR_REGISTRY="082902060548.dkr.ecr.us-east-1.amazonaws.com"
REPO_NAME="eks-monitoring-agent"
ECR_REPO="${ECR_REGISTRY}/${REPO_NAME}"
VERSION="${1:-v1.0.0}"
REGION="us-east-1"
AWS_PROFILE="${AWS_PROFILE:-admin}"

echo "=========================================="
echo "  Deploy EKS Monitoring Agent to ECR"
echo "=========================================="
echo ""
echo "ECR Repository: $ECR_REPO"
echo "Version: $VERSION"
echo "Region: $REGION"
echo "AWS Profile: $AWS_PROFILE"
echo ""

# Step 1: Ensure ECR repository exists
echo -e "${BLUE}Step 1: Checking ECR repository...${NC}"
if ! aws ecr describe-repositories \
  --repository-names $REPO_NAME \
  --region $REGION \
  --profile $AWS_PROFILE \
  --output table 2>/dev/null; then
    echo ""
    echo -e "${YELLOW}Repository doesn't exist. Creating...${NC}"
    aws ecr create-repository \
      --repository-name $REPO_NAME \
      --region $REGION \
      --profile $AWS_PROFILE \
      --image-scanning-configuration scanOnPush=true \
      --output table
    echo -e "${GREEN}✅ Repository created${NC}"
else
    echo -e "${GREEN}✅ Repository exists${NC}"
fi
echo ""

# Step 2: Login to ECR
echo -e "${BLUE}Step 2: Logging into ECR...${NC}"
aws ecr get-login-password --region $REGION --profile $AWS_PROFILE | \
  docker login --username AWS --password-stdin $ECR_REGISTRY

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✅ Logged in to ECR${NC}"
else
    echo -e "${RED}❌ ECR login failed${NC}"
    echo "Ensure AWS CLI is configured with profile: $AWS_PROFILE"
    exit 1
fi
echo ""

# Step 3: Build image for AMD64 (EKS nodes are x86_64)
echo -e "${BLUE}Step 3: Building Docker image for AMD64 (EKS)...${NC}"
echo "Platform: linux/amd64 (x86_64 for EKS instances)"
echo "This may take 5-10 minutes for the first build..."
echo ""

# Use buildx for cross-platform build from M1 Mac
echo "Using docker buildx for cross-platform AMD64 build..."
docker buildx build \
  --platform linux/amd64 \
  -t ${REPO_NAME}:${VERSION} \
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

# Step 4: Tag for ECR
echo -e "${BLUE}Step 4: Tagging for ECR...${NC}"
docker tag ${REPO_NAME}:${VERSION} ${ECR_REPO}:${VERSION}
docker tag ${REPO_NAME}:${VERSION} ${ECR_REPO}:latest

echo -e "${GREEN}✅ Image tagged:${NC}"
echo "   - ${ECR_REPO}:${VERSION}"
echo "   - ${ECR_REPO}:latest"
echo ""

# Step 5: Push to ECR
echo -e "${BLUE}Step 5: Pushing to ECR...${NC}"
echo "Pushing versioned tag..."
docker push ${ECR_REPO}:${VERSION}

echo "Pushing latest tag..."
docker push ${ECR_REPO}:latest

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✅ Images pushed to ECR${NC}"
else
    echo -e "${RED}❌ Push failed${NC}"
    exit 1
fi
echo ""

# Step 6: Verify in ECR
echo -e "${BLUE}Step 6: Verifying in ECR...${NC}"
aws ecr describe-images \
  --repository-name $REPO_NAME \
  --region $REGION \
  --profile $AWS_PROFILE \
  --output table \
  --query 'sort_by(imageDetails,& imagePushedAt)[-5:].[imageTags[0],imagePushedAt,imageSizeInBytes]' || true

echo ""

# Summary
echo "=========================================="
echo -e "${GREEN}  Deploy Complete!${NC}"
echo "=========================================="
echo ""
echo "Image available at:"
echo "  - ${ECR_REPO}:${VERSION}"
echo "  - ${ECR_REPO}:latest"
echo ""
echo -e "${YELLOW}Next steps:${NC}"
echo ""
echo "1. Update Kubernetes manifests with new image:"
echo ""
echo "   ${BLUE}k8s/deployment.yaml:${NC}"
echo "   image: ${ECR_REPO}:${VERSION}"
echo ""
echo "2. Deploy to EKS:"
echo "   kubectl apply -f k8s/"
echo ""
echo "3. Verify deployment:"
echo "   kubectl get pods -n eks-monitoring"
echo "   kubectl logs -f deployment/eks-monitoring-agent -n eks-monitoring"
echo ""
echo "4. Check MCP server connectivity:"
echo "   kubectl logs deployment/eks-monitoring-agent -n eks-monitoring | grep 'MCP'"
echo ""
echo -e "${BLUE}Repository URL for GitHub:${NC}"
echo "https://github.com/artemishealth/eks-monitoring-agent"
echo ""
