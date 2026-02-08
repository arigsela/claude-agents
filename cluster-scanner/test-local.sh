#!/bin/bash
# Local Docker testing for Cluster Scanner
# Pulls secrets from K8s, port-forwards oncall-agent-api, runs container locally.
#
# Usage:
#   ./test-local.sh              # Build + run in Docker
#   ./test-local.sh --no-build   # Run without rebuilding

set -e

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "=========================================="
echo "  Cluster Scanner — Local Docker Test"
echo "=========================================="
echo ""

# Step 1: Pull secrets from K8s cluster
echo -e "${BLUE}Step 1: Pulling secrets from cluster...${NC}"
ANTHROPIC_API_KEY=$(kubectl get secret -n cluster-scanner cluster-scanner-secrets -o jsonpath='{.data.anthropic-api-key}' | base64 -d 2>/dev/null)
ONCALL_API_KEY=$(kubectl get secret -n cluster-scanner cluster-scanner-secrets -o jsonpath='{.data.oncall-api-key}' | base64 -d 2>/dev/null)
SLACK_BOT_TOKEN=$(kubectl get secret -n cluster-scanner cluster-scanner-secrets -o jsonpath='{.data.slack-bot-token}' | base64 -d 2>/dev/null)

MISSING=0
for VAR in ANTHROPIC_API_KEY ONCALL_API_KEY SLACK_BOT_TOKEN; do
    if [ -z "${!VAR}" ]; then
        echo -e "${RED}  Missing: $VAR${NC}"
        MISSING=1
    else
        echo -e "${GREEN}  $VAR: ***${!VAR: -4}${NC}"
    fi
done

if [ $MISSING -eq 1 ]; then
    echo ""
    echo -e "${RED}Could not pull secrets from cluster-scanner namespace.${NC}"
    echo "Ensure ExternalSecret has synced: kubectl get externalsecret -n cluster-scanner"
    exit 1
fi
echo ""

# Step 2: Check port-forward to oncall-agent-api
echo -e "${BLUE}Step 2: Checking oncall-agent-api connectivity...${NC}"
if curl -s --max-time 3 "http://localhost:8000/health" > /dev/null 2>&1; then
    echo -e "${GREEN}  oncall-agent-api reachable on localhost:8000${NC}"
else
    echo -e "${YELLOW}  oncall-agent-api not reachable. Starting port-forward...${NC}"
    kubectl port-forward -n oncall-agent svc/oncall-agent-api 8000:80 &
    PF_PID=$!
    sleep 3

    if curl -s --max-time 3 "http://localhost:8000/health" > /dev/null 2>&1; then
        echo -e "${GREEN}  Port-forward started (PID $PF_PID)${NC}"
    else
        echo -e "${RED}  Failed to reach oncall-agent-api even after port-forward.${NC}"
        kill $PF_PID 2>/dev/null || true
        exit 1
    fi
fi
echo ""

# Step 3: Build Docker image
if [ "$1" != "--no-build" ]; then
    echo -e "${BLUE}Step 3: Building Docker image...${NC}"
    docker build -t cluster-scanner:local -f Dockerfile . 2>&1 | tail -5
    echo ""
else
    echo -e "${BLUE}Step 3: Skipping build (--no-build)${NC}"
    echo ""
fi

# Step 4: Run container
echo -e "${BLUE}Step 4: Running cluster-scanner container...${NC}"
echo "  ONCALL_API_URL: http://host.docker.internal:8000"
echo "  SLACK_CHANNEL:  #test-alerts"
echo "  MODEL:          haiku (via --model flag)"
echo ""

docker run --rm \
    -e ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" \
    -e ONCALL_API_KEY="$ONCALL_API_KEY" \
    -e SLACK_BOT_TOKEN="$SLACK_BOT_TOKEN" \
    -e ONCALL_API_URL="http://host.docker.internal:8000" \
    -e SLACK_CHANNEL="#test-alerts" \
    cluster-scanner:local

EXIT_CODE=$?

echo ""
if [ $EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN}✅ Local test passed${NC}"
else
    echo -e "${RED}❌ Local test failed (exit code: $EXIT_CODE)${NC}"
fi

# Cleanup port-forward if we started it
if [ -n "$PF_PID" ]; then
    kill $PF_PID 2>/dev/null || true
    echo "Port-forward stopped."
fi

exit $EXIT_CODE
