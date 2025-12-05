#!/bin/bash
# RAG MCP Server Entrypoint
#
# Modes:
#   server  - Run MCP server (stdio or http mode)
#   sync    - Run content sync job
#   shell   - Start interactive shell
#
# Examples:
#   docker run rag-mcp-server server
#   docker run rag-mcp-server sync --config /app/config/sync.yaml
#   docker run -it rag-mcp-server shell

set -e

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Wait for Qdrant to be ready
wait_for_qdrant() {
    local max_attempts=30
    local attempt=1

    log_info "Waiting for Qdrant at ${RAG_QDRANT_URL}..."

    while [ $attempt -le $max_attempts ]; do
        if curl -sf "${RAG_QDRANT_URL}" > /dev/null 2>&1; then
            log_info "Qdrant is ready"
            return 0
        fi

        log_warn "Attempt $attempt/$max_attempts - Qdrant not ready, waiting..."
        sleep 2
        attempt=$((attempt + 1))
    done

    log_error "Qdrant failed to become ready after $max_attempts attempts"
    return 1
}

# Run MCP server
run_server() {
    log_info "Starting RAG MCP Server..."
    log_info "Qdrant URL: ${RAG_QDRANT_URL}"
    log_info "Default collection: ${RAG_DEFAULT_COLLECTION}"
    log_info "Log level: ${RAG_LOG_LEVEL}"

    # Wait for Qdrant if not in stdio-only mode
    if [ "${RAG_MCP_MODE}" != "stdio" ]; then
        wait_for_qdrant || exit 1
    fi

    exec python -m src.server "$@"
}

# Run sync job
run_sync() {
    log_info "Starting RAG Sync Job..."

    wait_for_qdrant || exit 1

    exec python -m src.sync.sync_job "$@"
}

# Health check endpoint
run_healthcheck() {
    curl -sf "${RAG_QDRANT_URL}" > /dev/null 2>&1
    exit $?
}

# Main entrypoint
case "${1:-server}" in
    server)
        shift || true
        run_server "$@"
        ;;
    sync)
        shift || true
        run_sync "$@"
        ;;
    healthcheck)
        run_healthcheck
        ;;
    shell|bash|sh)
        exec /bin/bash
        ;;
    python)
        shift || true
        exec python "$@"
        ;;
    *)
        # If first arg doesn't match a mode, assume it's a command
        exec "$@"
        ;;
esac
