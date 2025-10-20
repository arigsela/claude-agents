#!/bin/bash

# K3s Monitor - Run Once (for testing)
# This script runs a single monitoring cycle immediately

set -e

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}=== K3s Monitor - Single Cycle ===${NC}"

# Check if we're in the right directory
if [ ! -f "src/main.py" ]; then
    echo -e "${RED}Error: src/main.py not found. Are you in the k8s-monitor directory?${NC}"
    exit 1
fi

# Activate virtual environment
echo -e "${BLUE}Activating virtual environment...${NC}"
source venv/bin/activate

# Check if .env exists
if [ ! -f ".env" ]; then
    echo -e "${RED}Error: .env file not found.${NC}"
    exit 1
fi

# Create logs directory
mkdir -p logs/incidents

# Run single cycle
echo -e "${BLUE}Running single monitoring cycle...${NC}"
echo ""

cd "$(dirname "$0")"
export PYTHONPATH="${PYTHONPATH}:$(pwd)"

# Run using python module syntax (same as Docker)
python -m src.main

echo -e "${GREEN}✓ Cycle complete!${NC}"
echo -e "${BLUE}View logs:${NC} tail -f logs/k8s-monitor.log"
echo -e "${BLUE}View report:${NC} ls -lt logs/cycle_*.json | head -1"
