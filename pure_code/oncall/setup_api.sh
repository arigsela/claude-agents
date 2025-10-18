#!/bin/bash
# Setup script for OnCall Agent API
# Installs dependencies and verifies setup

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo "=================================================="
echo "  OnCall Agent API - Setup"
echo "=================================================="
echo ""

# Get the directory of this script
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Check for virtual environment
if [ -z "$VIRTUAL_ENV" ]; then
    echo -e "${YELLOW}⚠️  No virtual environment detected${NC}"
    echo ""
    echo "Recommended: Activate your virtual environment first"
    echo "  source venv/bin/activate"
    echo ""
    echo "Or press Enter to continue with system Python..."
    read -r
fi

# Step 1: Install dependencies
echo -e "${GREEN}Step 1: Installing dependencies...${NC}"
pip install fastapi uvicorn[standard] python-multipart

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✅ FastAPI dependencies installed${NC}"
else
    echo -e "${RED}❌ Failed to install dependencies${NC}"
    exit 1
fi
echo ""

# Step 2: Verify environment variables
echo -e "${GREEN}Step 2: Checking environment variables...${NC}"

if [ ! -f .env ]; then
    echo -e "${YELLOW}⚠️  .env file not found${NC}"
    if [ -f .env.example ]; then
        cp .env.example .env
        echo "   Created .env from .env.example"
        echo "   Please edit .env and add your API keys"
    fi
else
    echo "✅ .env file found"
fi

# Check required variables
source .env 2>/dev/null || true

if [ -z "$ANTHROPIC_API_KEY" ]; then
    echo -e "${YELLOW}⚠️  ANTHROPIC_API_KEY not set in .env${NC}"
else
    echo "✅ ANTHROPIC_API_KEY is set"
fi

if [ -z "$GITHUB_TOKEN" ]; then
    echo -e "${YELLOW}⚠️  GITHUB_TOKEN not set in .env${NC}"
else
    echo "✅ GITHUB_TOKEN is set"
fi

echo ""

# Step 3: Validate API code
echo -e "${GREEN}Step 3: Validating API code...${NC}"
export PYTHONPATH="${SCRIPT_DIR}/src:${PYTHONPATH}"

python validate_api.py

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✅ API validation passed${NC}"
else
    echo -e "${RED}❌ API validation failed${NC}"
    exit 1
fi
echo ""

# Step 4: Instructions
echo "=================================================="
echo -e "${GREEN}✅ Setup Complete!${NC}"
echo "=================================================="
echo ""
echo "Next steps:"
echo ""
echo "1. Start the API server:"
echo "   ./run_api_server.sh"
echo ""
echo "2. Test the API:"
echo "   curl http://localhost:8000/health"
echo ""
echo "3. View interactive docs:"
echo "   open http://localhost:8000/docs"
echo ""
echo "4. Send a query:"
echo '   curl -X POST http://localhost:8000/query \'
echo '     -H "Content-Type: application/json" \'
echo '     -d '"'"'{"prompt": "What services are you monitoring?"}'"'"
echo ""
