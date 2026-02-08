#!/bin/bash
# Local testing for Cluster Scanner
# Requires: oncall-agent-api port-forwarded, Slack bot token, Anthropic key

set -e

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo "=========================================="
echo "  Cluster Scanner — Local Test"
echo "=========================================="
echo ""

# Check required env vars
MISSING=0
for VAR in ANTHROPIC_API_KEY ONCALL_API_KEY SLACK_BOT_TOKEN; do
    if [ -z "${!VAR}" ]; then
        echo -e "${RED}Missing: $VAR${NC}"
        MISSING=1
    fi
done

if [ $MISSING -eq 1 ]; then
    echo ""
    echo "Set required env vars or source a .env file:"
    echo "  export ANTHROPIC_API_KEY=sk-ant-..."
    echo "  export ONCALL_API_KEY=your-api-key"
    echo "  export SLACK_BOT_TOKEN=xoxb-..."
    echo ""
    echo "Or: source .env"
    exit 1
fi

# Defaults for local testing
export ONCALL_API_URL="${ONCALL_API_URL:-http://localhost:8000}"
export SLACK_CHANNEL="${SLACK_CHANNEL:-#test-alerts}"
export ANTHROPIC_MODEL="${ANTHROPIC_MODEL:-claude-haiku-4-5-20251001}"

echo "Configuration:"
echo "  ONCALL_API_URL: $ONCALL_API_URL"
echo "  SLACK_CHANNEL:  $SLACK_CHANNEL"
echo "  MODEL:          $ANTHROPIC_MODEL"
echo ""

# Check oncall-agent-api is reachable
echo -e "${BLUE}Checking oncall-agent-api connectivity...${NC}"
if curl -s --max-time 5 "$ONCALL_API_URL/health" > /dev/null 2>&1; then
    echo -e "${GREEN}✅ oncall-agent-api reachable${NC}"
else
    echo -e "${YELLOW}⚠️  oncall-agent-api not reachable at $ONCALL_API_URL${NC}"
    echo ""
    echo "Start port-forward in another terminal:"
    echo "  kubectl port-forward -n oncall-agent svc/oncall-agent-api 8000:80"
    echo ""
    echo "Or set ONCALL_API_URL to the correct address."
    exit 1
fi
echo ""

# Ensure Ralph memories directory exists
mkdir -p .ralph/agent
if [ ! -f ".ralph/agent/memories.md" ]; then
    echo "# Cluster Scanner Memories" > .ralph/agent/memories.md
fi

# Initialize git if needed
if [ ! -d ".git" ]; then
    echo -e "${BLUE}Initializing git repo...${NC}"
    git init
    git add -A
    git commit -m "Local test init"
fi

# Run Ralph
echo -e "${BLUE}Starting Ralph orchestration...${NC}"
echo ""
ralph run -c ralph.yml --max-iterations 20

echo ""
echo -e "${GREEN}✅ Local test complete${NC}"
