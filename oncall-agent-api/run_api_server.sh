#!/bin/bash
# Run API Server for OnCall Agent
# This script sets up the environment correctly and starts the FastAPI server

set -e

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "=================================================="
echo "  OnCall Agent API Server"
echo "=================================================="
echo ""

# Get the directory of this script
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Check if .env exists
if [ ! -f .env ]; then
    echo -e "${YELLOW}⚠️  Warning: .env file not found${NC}"
    echo "   Creating from .env.example..."
    if [ -f .env.example ]; then
        cp .env.example .env
        echo "   ✅ Created .env - please edit it with your API keys"
        echo ""
    else
        echo "   ❌ .env.example not found"
        echo ""
    fi
fi

# Load environment variables
if [ -f .env ]; then
    export $(cat .env | grep -v '^#' | xargs)
fi

# Set PYTHONPATH to include src directory
export PYTHONPATH="${SCRIPT_DIR}/src:${PYTHONPATH}"

# Check required environment variables
MISSING_VARS=()
if [ -z "$ANTHROPIC_API_KEY" ]; then
    MISSING_VARS+=("ANTHROPIC_API_KEY")
fi

if [ ${#MISSING_VARS[@]} -gt 0 ]; then
    echo -e "${YELLOW}⚠️  Warning: Missing required environment variables:${NC}"
    for var in "${MISSING_VARS[@]}"; do
        echo "   - $var"
    done
    echo ""
    echo "The API server may fail to initialize without these variables."
    echo "Press Ctrl+C to cancel, or Enter to continue anyway..."
    read -r
fi

# Get port from args or default to 8000
PORT=${1:-8000}

echo -e "${GREEN}✅ Environment configured${NC}"
echo "   PYTHONPATH: ${PYTHONPATH}"
echo "   Port: ${PORT}"
echo ""

echo "Starting API server..."
echo "   - Swagger UI: http://localhost:${PORT}/docs"
echo "   - Health check: http://localhost:${PORT}/health"
echo ""
echo "Press Ctrl+C to stop"
echo ""

# Run uvicorn with proper module path
python -m uvicorn api.api_server:app --reload --port "$PORT" --app-dir ./src
