#!/bin/bash
# Deploy OnCall CrewAI agents to AWS ECR (k3s homelab)
# Builds AMD64 images from M1 Mac and pushes to ECR
#
# Usage:
#   ./deploy-to-ecr.sh                    # Deploy all 3 services (v1.0.0)
#   ./deploy-to-ecr.sh v1.1.0             # Deploy all with version
#   ./deploy-to-ecr.sh v1.1.0 orchestrator  # Deploy only orchestrator
#   ./deploy-to-ecr.sh v1.1.0 k8s-agent     # Deploy only k8s agent
#   ./deploy-to-ecr.sh v1.1.0 github-agent  # Deploy only github agent
#   ./deploy-to-ecr.sh v1.1.0 frontend      # Deploy only frontend

set -e

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

# Configuration
ECR_REGISTRY="852893458518.dkr.ecr.us-east-2.amazonaws.com"
VERSION="${1:-v1.0.0}"
SERVICE_FILTER="${2:-all}"
REGION="us-east-2"

# Service definitions: name|ecr-repo|dockerfile
SERVICES=(
  "orchestrator|crewai-orchestrator|docker/Dockerfile.orchestrator"
  "k8s-agent|crewai-k8s-agent|docker/Dockerfile.k8s-agent"
  "github-agent|crewai-github-agent|docker/Dockerfile.github-agent"
  "frontend|crewai-frontend|docker/Dockerfile.frontend"
)

echo "=========================================="
echo "  Deploy OnCall CrewAI Agents to ECR"
echo "=========================================="
echo ""
echo "ECR Registry: $ECR_REGISTRY"
echo "Version:      $VERSION"
echo "Service:      $SERVICE_FILTER"
echo "Region:       $REGION"
echo ""

# Validate service filter
if [[ "$SERVICE_FILTER" != "all" && "$SERVICE_FILTER" != "orchestrator" && \
      "$SERVICE_FILTER" != "k8s-agent" && "$SERVICE_FILTER" != "github-agent" && \
      "$SERVICE_FILTER" != "frontend" ]]; then
    echo -e "${RED}Invalid service: $SERVICE_FILTER${NC}"
    echo "Valid options: all, orchestrator, k8s-agent, github-agent"
    exit 1
fi

# Step 1: Login to ECR
echo -e "${BLUE}Step 1: Logging into ECR...${NC}"
aws ecr get-login-password --region $REGION | \
  docker login --username AWS --password-stdin $ECR_REGISTRY

if [ $? -eq 0 ]; then
    echo -e "${GREEN}Logged in to ECR${NC}"
else
    echo -e "${RED}ECR login failed${NC}"
    echo "Ensure AWS CLI is configured and you have ECR permissions"
    exit 1
fi
echo ""

# Step 2: Ensure ECR repositories exist
echo -e "${BLUE}Step 2: Ensuring ECR repositories exist...${NC}"
for entry in "${SERVICES[@]}"; do
    IFS='|' read -r name repo dockerfile <<< "$entry"

    if [[ "$SERVICE_FILTER" != "all" && "$SERVICE_FILTER" != "$name" ]]; then
        continue
    fi

    aws ecr describe-repositories --repository-names "$repo" --region $REGION > /dev/null 2>&1 || \
        aws ecr create-repository --repository-name "$repo" --region $REGION --image-scanning-configuration scanOnPush=true > /dev/null 2>&1
    echo "  $repo: OK"
done
echo ""

# Step 3: Build, tag, and push each service
BUILT=()
for entry in "${SERVICES[@]}"; do
    IFS='|' read -r name repo dockerfile <<< "$entry"

    if [[ "$SERVICE_FILTER" != "all" && "$SERVICE_FILTER" != "$name" ]]; then
        continue
    fi

    ECR_IMAGE="$ECR_REGISTRY/$repo"

    echo -e "${BLUE}Building: $name${NC}"
    echo "  Dockerfile: $dockerfile"
    echo "  Image:      $ECR_IMAGE:$VERSION"
    echo "  Platform:   linux/amd64 (cross-compile for k3s)"
    echo ""

    docker buildx build \
      --platform linux/amd64 \
      -t "$repo:$VERSION" \
      -f "$dockerfile" \
      --load \
      .

    if [ $? -eq 0 ]; then
        echo -e "${GREEN}Built: $name${NC}"
    else
        echo -e "${RED}Build failed: $name${NC}"
        exit 1
    fi

    # Tag for ECR
    docker tag "$repo:$VERSION" "$ECR_IMAGE:$VERSION"
    docker tag "$repo:$VERSION" "$ECR_IMAGE:latest"

    # Push
    echo "  Pushing $ECR_IMAGE:$VERSION..."
    docker push "$ECR_IMAGE:$VERSION"
    echo "  Pushing $ECR_IMAGE:latest..."
    docker push "$ECR_IMAGE:latest"

    if [ $? -eq 0 ]; then
        echo -e "${GREEN}Pushed: $name${NC}"
    else
        echo -e "${RED}Push failed: $name${NC}"
        exit 1
    fi

    BUILT+=("$ECR_IMAGE:$VERSION")
    echo ""
done

# Service definitions with K8s deployment names: name|k8s-deployment
# (must match SERVICES order above)
get_deploy_name() {
    case "$1" in
        orchestrator) echo "crewai-orchestrator" ;;
        k8s-agent)    echo "k8s-agent-a2a" ;;
        github-agent) echo "github-agent-a2a" ;;
        frontend)     echo "crewai-frontend" ;;
    esac
}

NAMESPACE="oncall-crewai"

# Step 4: Rolling restart deployments
echo -e "${BLUE}Step 4: Rolling out deployments in $NAMESPACE...${NC}"
ROLLOUT_OK=true
for entry in "${SERVICES[@]}"; do
    IFS='|' read -r name repo dockerfile <<< "$entry"

    if [[ "$SERVICE_FILTER" != "all" && "$SERVICE_FILTER" != "$name" ]]; then
        continue
    fi

    deploy_name="$(get_deploy_name "$name")"
    echo -e "  ${YELLOW}Restarting: $deploy_name${NC}"
    if kubectl rollout restart deployment/"$deploy_name" -n "$NAMESPACE" 2>/dev/null; then
        echo -e "  ${GREEN}Rollout triggered: $deploy_name${NC}"
    else
        echo -e "  ${RED}Rollout failed: $deploy_name (is kubectl configured?)${NC}"
        ROLLOUT_OK=false
    fi
done
echo ""

# Step 5: Wait for rollouts to complete
if $ROLLOUT_OK; then
    echo -e "${BLUE}Step 5: Waiting for rollouts to complete...${NC}"
    for entry in "${SERVICES[@]}"; do
        IFS='|' read -r name repo dockerfile <<< "$entry"

        if [[ "$SERVICE_FILTER" != "all" && "$SERVICE_FILTER" != "$name" ]]; then
            continue
        fi

        deploy_name="$(get_deploy_name "$name")"
        echo -n "  Waiting for $deploy_name... "
        if kubectl rollout status deployment/"$deploy_name" -n "$NAMESPACE" --timeout=120s 2>/dev/null; then
            echo -e "${GREEN}ready${NC}"
        else
            echo -e "${RED}timed out${NC}"
        fi
    done
    echo ""
fi

# Summary
echo "=========================================="
echo -e "${GREEN}  Deploy Complete!${NC}"
echo "=========================================="
echo ""
echo "Images deployed:"
for img in "${BUILT[@]}"; do
    echo "  - $img"
done
echo ""
echo "Pod status:"
kubectl get pods -n "$NAMESPACE" -o wide 2>/dev/null || echo "  (kubectl not available)"
echo ""
