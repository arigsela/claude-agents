# RAG MCP Server Dockerfile
#
# Multi-stage build for minimal production image.
# Supports both MCP server and sync job modes.
#
# Build:
#   docker build -t rag-mcp-server:latest .
#
# Run MCP Server (stdio mode):
#   docker run -it rag-mcp-server:latest server
#
# Run Sync Job:
#   docker run -v ./config:/app/config rag-mcp-server:latest sync --config /app/config/sync.yaml

# =============================================================================
# Stage 1: Builder - Install dependencies
# =============================================================================
FROM python:3.11-slim as builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Pre-download the embedding model (cache in image)
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5')"

# =============================================================================
# Stage 2: Runtime - Minimal production image
# =============================================================================
FROM python:3.11-slim as runtime

# Labels
LABEL org.opencontainers.image.title="RAG MCP Server"
LABEL org.opencontainers.image.description="MCP server for RAG with Qdrant or PostgreSQL+pgvector backend"
LABEL org.opencontainers.image.version="1.0.0"

# Create non-root user
RUN groupadd -r ragmcp && useradd -r -g ragmcp ragmcp

WORKDIR /app

# Install runtime dependencies
# - git: for sync job cloning
# - curl: for health checks and Qdrant connectivity
# - postgresql-client: for pgvector backend connectivity (pg_isready)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy fastembed model cache from builder
COPY --from=builder /root/.cache/huggingface /home/ragmcp/.cache/huggingface

# Copy application code
COPY src/ ./src/
COPY config/ ./config/

# Copy entrypoint and ensure it's executable
COPY --chmod=755 docker-entrypoint.sh /usr/local/bin/

# Create directories for runtime
RUN mkdir -p /app/cache /app/playbooks && \
    chown -R ragmcp:ragmcp /app /home/ragmcp

# Switch to non-root user
USER ragmcp

# Environment defaults
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    RAG_QDRANT_URL=http://qdrant:6333 \
    RAG_DEFAULT_COLLECTION=default \
    RAG_LOG_LEVEL=INFO

# Health check for HTTP mode
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8003/health 2>/dev/null || exit 0

# Default port for HTTP mode
EXPOSE 8003

# Entrypoint handles mode selection
ENTRYPOINT ["docker-entrypoint.sh"]

# Default command: run MCP server
CMD ["server"]
