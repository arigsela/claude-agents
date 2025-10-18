#!/bin/bash
# Entry point for On-Call Agent that handles PYTHONPATH correctly

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Set PYTHONPATH to include src directory
export PYTHONPATH="${PYTHONPATH}:${SCRIPT_DIR}/src"

# Activate virtual environment if not already activated
if [ -z "$VIRTUAL_ENV" ]; then
    source "${SCRIPT_DIR}/venv/bin/activate"
fi

# Run the agent with all arguments passed through
cd "${SCRIPT_DIR}"
python3 src/agent/oncall_agent.py "$@"
