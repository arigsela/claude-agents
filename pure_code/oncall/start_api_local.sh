#!/bin/bash
# Start API server locally with venv and env vars

set -e

# Activate venv
source venv/bin/activate

# Load env vars
set -a
source .env
set +a

# Start server
python -m uvicorn api.api_server:app \
    --host 0.0.0.0 \
    --port 8000 \
    --app-dir src \
    --log-level info
