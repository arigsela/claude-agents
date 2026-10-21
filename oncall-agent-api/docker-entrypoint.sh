#!/bin/bash
# Docker entrypoint for OnCall Agent API
# Starts the FastAPI server for n8n/external integrations

set -e

echo "=================================================="
echo "  OnCall Troubleshooting Agent API - Container"
echo "=================================================="
echo ""
echo "API Mode: HTTP server for troubleshooting queries"
echo "API will be available on port ${API_PORT:-8000}"
echo "K8s Auth: ${K8S_CONTEXT:-in-cluster}"
echo ""

# Use exec to replace shell process with uvicorn
# Increased timeout for Claude Agent SDK queries (can take 15-30s)
exec uvicorn api.api_server:app \
  --host "${API_HOST:-0.0.0.0}" \
  --port "${API_PORT:-8000}" \
  --app-dir /app/src \
  --log-level info \
  --timeout-keep-alive 60 \
  --timeout-graceful-shutdown 30
