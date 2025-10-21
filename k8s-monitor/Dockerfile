# Stage: Python runtime with kubectl
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    wget \
    gnupg \
    ca-certificates \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

# Install kubectl
RUN curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl" && \
    chmod +x kubectl && \
    mv kubectl /usr/local/bin/

# Install Claude Code CLI (required for Claude Agent SDK)
RUN npm install -g @anthropic-ai/claude-code

# Create MCP server directories (will be populated at runtime or during deployment)
RUN mkdir -p /app/mcp-servers/github/dist && \
    mkdir -p /app/mcp-servers/slack/dist

# Copy Python requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code (NOT .env - users should provide their own)
COPY .claude/ .claude/
COPY docs/ docs/
COPY src/ src/
COPY tests/ tests/

# Copy .env.example as reference (but don't use as default)
COPY .env.example /app/.env.example

# Create logs directory
RUN mkdir -p logs/incidents

# Set Python path
ENV PYTHONPATH=/app:$PYTHONPATH

# Health check
HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import sys; sys.exit(0)" || exit 1

# Default entrypoint
ENTRYPOINT ["python", "-m"]
CMD ["src.main"]
