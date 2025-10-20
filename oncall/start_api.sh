#!/bin/bash
# Start OnCall Agent API Server with environment variables loaded

# Load environment variables
set -a
source .env
set +a

# Start API server with PYTHONPATH
PYTHONPATH=src ./venv/bin/uvicorn api.api_server:app --reload --port 8000 --host 0.0.0.0
