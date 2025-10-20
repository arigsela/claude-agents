#!/bin/bash
# Docker entrypoint for OnCall Agent API Server

set -e

# Ensure Claude CLI is in PATH
export PATH="/usr/local/bin:$PATH"

echo "=================================================="
echo "  OnCall Troubleshooting Agent - API Server"
echo "=================================================="
echo ""
echo "Starting API server for n8n integration"
echo "API will be available on port ${API_PORT:-8000}"
echo "Monitoring cluster: ${K8S_CONTEXT:-dev-eks}"
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
