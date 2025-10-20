#!/bin/bash

# K3s Monitor Startup Script
# This script sets up the environment and starts the monitoring agent

set -e

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}=== K3s Monitor Startup ===${NC}"

# Check if we're in the right directory
if [ ! -f "src/main.py" ]; then
    echo -e "${RED}Error: src/main.py not found. Are you in the k8s-monitor directory?${NC}"
    exit 1
fi

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo -e "${RED}Error: Virtual environment not found. Please create it first:${NC}"
    echo "python3 -m venv venv"
    exit 1
fi

# Activate virtual environment
echo -e "${BLUE}Activating virtual environment...${NC}"
source venv/bin/activate

# Check if .env exists
if [ ! -f ".env" ]; then
    echo -e "${RED}Error: .env file not found. Please create it:${NC}"
    echo "cp .env.example .env"
    echo "# Then edit .env with your API keys"
    exit 1
fi

# Validate required environment variables
echo -e "${BLUE}Validating configuration...${NC}"

if grep -q "your_anthropic_api_key_here" .env; then
    echo -e "${RED}Error: ANTHROPIC_API_KEY not configured in .env${NC}"
    exit 1
fi

if grep -q "/path/to/your/k3s/kubeconfig" .env; then
    echo -e "${RED}Error: KUBECONFIG path not configured in .env${NC}"
    exit 1
fi

# Check kubectl access
echo -e "${BLUE}Checking kubectl access...${NC}"
if ! kubectl get nodes > /dev/null 2>&1; then
    echo -e "${RED}Error: Cannot access Kubernetes cluster. Check KUBECONFIG and K3S_CONTEXT.${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Configuration valid${NC}"

# Create logs directory if it doesn't exist
mkdir -p logs/incidents

# Run the monitor
echo -e "${BLUE}Starting K3s Monitor...${NC}"
echo -e "${GREEN}Press Ctrl+C to stop${NC}"
echo ""

cd "$(dirname "$0")"
export PYTHONPATH="${PYTHONPATH}:$(pwd)"
python -c "
import sys
sys.path.insert(0, '.')
from src.main import main
import asyncio
asyncio.run(main())
"
