#!/bin/bash
# Kubernetes MCP Server wrapper - Python-based implementation

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Debug logging to stderr
echo "[K8S-MCP] Starting Kubernetes MCP server..." >&2
echo "[K8S-MCP] Script dir: $SCRIPT_DIR" >&2
echo "[K8S-MCP] Project dir: $PROJECT_DIR" >&2

# Load environment variables if .env exists
if [ -f "$PROJECT_DIR/.env" ]; then
    set -a
    source "$PROJECT_DIR/.env"
    set +a
    echo "[K8S-MCP] Loaded .env" >&2
fi

# Export KUBECONFIG if set
if [ -n "$KUBECONFIG" ]; then
    export KUBECONFIG
    echo "[K8S-MCP] Using KUBECONFIG: $KUBECONFIG" >&2
fi

# Export KUBE_CONTEXT if set (kubectl will use this)
if [ -n "$KUBE_CONTEXT" ]; then
    export KUBE_CONTEXT
    echo "[K8S-MCP] Using KUBE_CONTEXT: $KUBE_CONTEXT" >&2
    # Set kubectl context
    kubectl config use-context "$KUBE_CONTEXT" >/dev/null 2>&1
fi

# Activate venv and run Python MCP server
cd "$PROJECT_DIR"

# Find Python in venv
if [ -f "venv/bin/python" ]; then
    PYTHON="venv/bin/python"
    echo "[K8S-MCP] Found Python at: $PYTHON" >&2
elif [ -f "venv/bin/python3" ]; then
    PYTHON="venv/bin/python3"
    echo "[K8S-MCP] Found Python at: $PYTHON" >&2
else
    echo "[K8S-MCP] Error: Python venv not found at $PROJECT_DIR/venv" >&2
    exit 1
fi

# Verify MCP server script exists
if [ ! -f "bin/kubernetes-mcp-server.py" ]; then
    echo "[K8S-MCP] Error: MCP server script not found at bin/kubernetes-mcp-server.py" >&2
    exit 1
fi

echo "[K8S-MCP] Running: $PYTHON bin/kubernetes-mcp-server.py" >&2

# Log to file for debugging
LOG_FILE="/tmp/k8s-mcp-wrapper.log"
echo "=== $(date) ===" >> "$LOG_FILE"
echo "Executing: $PYTHON bin/kubernetes-mcp-server.py" >> "$LOG_FILE"

# Run the MCP server
exec "$PYTHON" bin/kubernetes-mcp-server.py 2>> "$LOG_FILE"
