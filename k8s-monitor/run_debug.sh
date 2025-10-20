#!/bin/bash

# K3s Monitor - Debug Mode (shows full subagent responses)
# This script runs a single monitoring cycle with verbose output

set -e

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${BLUE}=== K3s Monitor - DEBUG MODE ===${NC}"

# Check if we're in the right directory
if [ ! -f "src/main.py" ]; then
    echo -e "${RED}Error: src/main.py not found. Are you in the k8s-monitor directory?${NC}"
    exit 1
fi

# Activate virtual environment
echo -e "${BLUE}Activating virtual environment...${NC}"
source venv/bin/activate

# Create logs directory
mkdir -p logs/incidents

# Run single cycle with DEBUG logging
echo -e "${BLUE}Running single monitoring cycle (DEBUG MODE)...${NC}"
echo -e "${YELLOW}This will show full k8s-analyzer output${NC}"
echo ""

cd "$(dirname "$0")"
export PYTHONPATH="${PYTHONPATH}:$(pwd)"

python -c "
import sys
import asyncio
import logging

sys.path.insert(0, '.')

from src.config import Settings
from src.orchestrator import Monitor

async def run_debug():
    # Set up DEBUG logging
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[logging.StreamHandler(sys.stdout)]
    )
    logger = logging.getLogger(__name__)

    logger.info('=' * 80)
    logger.info('DEBUG MODE: Will show full k8s-analyzer response')
    logger.info('=' * 80)

    logger.info('Loading configuration...')
    settings = Settings()
    settings.validate_all()

    logger.info('Initializing monitor...')
    monitor = Monitor(settings)

    logger.info('Starting monitoring cycle...')
    results = await monitor.run_monitoring_cycle()

    # Print results
    print()
    print('=' * 80)
    print('MONITORING CYCLE RESULTS:')
    print('=' * 80)
    print(f'Status: {results.get(\"status\")}')
    print(f'Cycle ID: {results.get(\"cycle_id\")}')
    print(f'Findings: {len(results.get(\"findings\", []))}')

    if results.get('findings'):
        print()
        print('FINDINGS DETECTED:')
        for i, finding in enumerate(results.get('findings', []), 1):
            print(f'{i}. Service: {finding.get(\"service\")}')
            print(f'   Severity: {finding.get(\"severity\")}')
            print(f'   Description: {finding.get(\"description\")}')
            print()

    if results.get('escalation_decision'):
        print(f'Severity: {results[\"escalation_decision\"].get(\"severity\")}')
        print(f'Should Notify: {results[\"escalation_decision\"].get(\"should_notify\")}')

    print(f'Notifications Sent: {results.get(\"notifications_sent\", 0)}')
    print('=' * 80)

    # Save report
    report_path = monitor.save_cycle_report(results)
    print(f'Full report saved to: {report_path}')
    print()

asyncio.run(run_debug())
"

echo -e "${GREEN}✓ Debug cycle complete!${NC}"
echo -e "${BLUE}Check logs above for full k8s-analyzer response${NC}"
