#!/bin/bash
# Docker entrypoint for OnCall Agent
# Supports multiple run modes: daemon, api, or both

set -e

# Ensure Claude CLI is in PATH
export PATH="/usr/local/bin:$PATH"

echo "=================================================="
echo "  OnCall Troubleshooting Agent - Container"
echo "=================================================="
echo ""
echo "Run Mode: ${RUN_MODE:-daemon}"
echo ""

# Determine run mode from RUN_MODE env var
RUN_MODE=${RUN_MODE:-daemon}

case "$RUN_MODE" in
  daemon)
    echo "Starting in DAEMON mode (K8s event watcher + orchestrator)"
    echo "Monitoring cluster: ${K8S_CONTEXT:-dev-eks}"
    echo ""
    exec python3 src/integrations/orchestrator.py
    ;;

  api)
    echo "Starting in API mode (HTTP server for n8n integration)"
    echo "API will be available on port ${API_PORT:-8000}"
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
    ;;

  both)
    echo "Starting in BOTH mode (daemon + API server)"
    echo "Daemon: K8s monitoring active"
    echo "API: Available on port ${API_PORT:-8000}"
    echo ""

    # Start orchestrator in background
    python3 src/integrations/orchestrator.py &
    DAEMON_PID=$!
    echo "Daemon started (PID: $DAEMON_PID)"

    # Start API server in foreground
    # Increased timeout for Claude Agent SDK queries (can take 15-30s)
    uvicorn api.api_server:app \
      --host "${API_HOST:-0.0.0.0}" \
      --port "${API_PORT:-8000}" \
      --app-dir /app/src \
      --log-level info \
      --timeout-keep-alive 60 \
      --timeout-graceful-shutdown 30 &
    API_PID=$!
    echo "API server started (PID: $API_PID)"

    # Wait for both processes
    wait -n

    # If one exits, kill the other
    kill $DAEMON_PID $API_PID 2>/dev/null
    exit 1
    ;;

  *)
    echo "ERROR: Invalid RUN_MODE: $RUN_MODE"
    echo "Valid modes: daemon, api, both"
    exit 1
    ;;
esac
