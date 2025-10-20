#!/bin/bash
# GitHub MCP Server wrapper - Python-based implementation

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Debug logging to stderr
echo "[GITHUB-MCP] Starting GitHub MCP server..." >&2

# Load environment variables if .env exists
if [ -f "$PROJECT_DIR/.env" ]; then
    set -a
    source "$PROJECT_DIR/.env"
    set +a
fi

# Verify GitHub token is set (for future use)
if [ -z "$GITHUB_PERSONAL_ACCESS_TOKEN" ]; then
    echo "[GITHUB-MCP] Warning: GITHUB_PERSONAL_ACCESS_TOKEN not set" >&2
fi

# Export token for potential use
export GITHUB_PERSONAL_ACCESS_TOKEN

# Activate venv and run Python MCP server
cd "$PROJECT_DIR"

# Find Python in venv
if [ -f "venv/bin/python" ]; then
    PYTHON="venv/bin/python"
elif [ -f "venv/bin/python3" ]; then
    PYTHON="venv/bin/python3"
else
    echo "[GITHUB-MCP] Error: Python venv not found at $PROJECT_DIR/venv" >&2
    exit 1
fi

# Verify MCP server script exists
if [ ! -f "bin/github-mcp-server.py" ]; then
    echo "[GITHUB-MCP] Error: MCP server script not found at bin/github-mcp-server.py" >&2
    exit 1
fi

echo "[GITHUB-MCP] Running: $PYTHON bin/github-mcp-server.py" >&2

# Run the MCP server
exec "$PYTHON" bin/github-mcp-server.py
