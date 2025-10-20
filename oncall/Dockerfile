# Multi-stage build for On-Call Troubleshooting Agent
# Using Python base (no Node.js needed - API uses Anthropic SDK directly)
FROM python:3.11-slim AS base

# Install AWS CLI
RUN apt-get update && apt-get install -y \
    curl \
    unzip \
    && ARCH=$(dpkg --print-architecture) \
    && if [ "$ARCH" = "arm64" ]; then \
        curl "https://awscli.amazonaws.com/awscli-exe-linux-aarch64.zip" -o "awscliv2.zip"; \
       else \
        curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"; \
       fi \
    && unzip awscliv2.zip \
    && ./aws/install \
    && rm -rf aws awscliv2.zip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy Python requirements
COPY requirements.txt .

# Install Python dependencies in virtual environment
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY src/ ./src/
COPY config/ ./config/

# Set Python path
ENV PYTHONPATH=/app/src

# Create logs directory
RUN mkdir -p /app/logs

# Note: Claude CLI no longer needed - API mode now uses Anthropic SDK directly
# (same as daemon mode - no CLI dependencies)

# Set default run mode (can be overridden)
ENV RUN_MODE=daemon

# Health check - different based on mode
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD if [ "$RUN_MODE" = "api" ]; then \
        curl -f http://localhost:8000/health || exit 1; \
      else \
        python3 -c "import sys; sys.exit(0)"; \
      fi

# Entrypoint script to handle different modes
COPY docker-entrypoint.sh /app/
RUN chmod +x /app/docker-entrypoint.sh

ENTRYPOINT ["/app/docker-entrypoint.sh"]
