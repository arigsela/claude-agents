#!/bin/bash
# Atlassian (Jira) MCP Server wrapper - runs via Docker
# This runs the sooperset/mcp-atlassian container

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Load environment variables if .env exists
if [ -f "${SCRIPT_DIR}/../.env" ]; then
    set -a
    source "${SCRIPT_DIR}/../.env"
    set +a
fi

# Check if Jira is configured (optional - agent works without Jira)
if [ -z "$JIRA_URL" ]; then
    echo "Warning: JIRA_URL not set - Jira integration disabled" >&2
    echo "The agent will run without Jira ticket management" >&2
    # Exit gracefully - daemon will continue without Jira MCP server
    exit 0
fi

# Verify Docker is running
if ! docker info >/dev/null 2>&1; then
    echo "Error: Docker is not running. Please start Docker Desktop." >&2
    exit 1
fi

# Clean up any existing containers
docker rm -f mcp-atlassian-jira 2>/dev/null || true

# Run Atlassian MCP server in Docker
# stdio mode is required for MCP protocol communication
docker run --rm -i \
    --name mcp-atlassian-jira \
    -e JIRA_URL="$JIRA_URL" \
    -e JIRA_USERNAME="$JIRA_USERNAME" \
    -e JIRA_API_TOKEN="$JIRA_API_TOKEN" \
    -e READ_ONLY_MODE="${JIRA_READ_ONLY:-false}" \
    ghcr.io/sooperset/mcp-atlassian:latest
