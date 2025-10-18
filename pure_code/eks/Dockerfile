# Multi-stage build for EKS Monitoring Agent
# Requires: Python 3.10+, Node.js (for MCP servers), Docker (for Atlassian MCP)

FROM python:3.11-slim AS base

# Install system dependencies: curl, unzip, Node.js, Docker CLI
RUN apt-get update && apt-get install -y \
    curl \
    unzip \
    ca-certificates \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js 20.x (required for Kubernetes and GitHub MCP servers)
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Install Docker CLI (required for Atlassian MCP server)
RUN install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc \
    && chmod a+r /etc/apt/keyrings/docker.asc \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian bookworm stable" \
      > /etc/apt/sources.list.d/docker.list \
    && apt-get update \
    && apt-get install -y docker-ce-cli \
    && rm -rf /var/lib/apt/lists/*

# Install AWS CLI (for EKS authentication)
RUN ARCH=$(dpkg --print-architecture) \
    && if [ "$ARCH" = "arm64" ]; then \
        curl "https://awscli.amazonaws.com/awscli-exe-linux-aarch64.zip" -o "awscliv2.zip"; \
       else \
        curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"; \
       fi \
    && unzip awscliv2.zip \
    && ./aws/install \
    && rm -rf aws awscliv2.zip

WORKDIR /app

# Copy Python requirements
COPY requirements.txt .

# Install Python dependencies
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --no-cache-dir -r requirements.txt

# Copy agent configuration and code
COPY .claude/ ./.claude/
COPY bin/ ./bin/
COPY monitor_daemon.py .
COPY .env.example .

# Ensure MCP server wrappers are executable
RUN chmod +x bin/*.sh

# Ensure hooks are executable
RUN chmod +x .claude/hooks/*.py

# Set Python path
ENV PYTHONPATH=/app

# Create necessary directories
RUN mkdir -p /tmp/eks-monitoring-reports \
    && mkdir -p /tmp/logs

# Expose port for future HTTP API mode (not yet implemented)
# EXPOSE 8000

# Health check - verify daemon is running
HEALTHCHECK --interval=60s --timeout=10s --start-period=90s --retries=3 \
  CMD ps aux | grep -q "[m]onitor_daemon.py" || exit 1

# Default command - run monitoring daemon
CMD ["python", "monitor_daemon.py"]
