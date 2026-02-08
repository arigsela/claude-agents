#!/bin/bash
# Cluster Scanner Entrypoint
# Initializes git repo if needed (PVC mount may overwrite .git),
# ensures Ralph memory directory exists, and runs the scan cycle.

set -e

echo "=== Cluster Scanner Starting ==="
echo "Timestamp: $(date -u +%Y-%m-%dT%H:%M:%SZ)"

# PVC mount at /app/.ralph may overwrite the .git directory
# Re-initialize if needed
if [ ! -d "/app/.git" ]; then
    echo "Initializing git repository..."
    cd /app
    git init
    git config user.email "cluster-scanner@homelab"
    git config user.name "Cluster Scanner"
    git add -A
    git commit -m "Re-init after PVC mount"
fi

# Ensure Ralph memories directory exists (persisted via PVC)
mkdir -p /app/.ralph/agent
if [ ! -f "/app/.ralph/agent/memories.md" ]; then
    echo "# Cluster Scanner Memories" > /app/.ralph/agent/memories.md
    echo "" >> /app/.ralph/agent/memories.md
    echo "Initialized memories file."
fi

# Default model to Haiku for cost optimization
export ANTHROPIC_MODEL="${ANTHROPIC_MODEL:-claude-haiku-4-5-20251001}"
echo "Model: $ANTHROPIC_MODEL"
echo "oncall-agent-api: $ONCALL_API_URL"
echo "Slack channel: $SLACK_CHANNEL"
echo ""

# Run Ralph orchestration
ralph run -c ralph.yml --max-iterations 20

EXIT_CODE=$?

echo ""
echo "=== Cluster Scanner Complete ==="
echo "Exit code: $EXIT_CODE"
echo "Timestamp: $(date -u +%Y-%m-%dT%H:%M:%SZ)"

exit $EXIT_CODE
