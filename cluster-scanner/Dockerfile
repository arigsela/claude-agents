FROM node:20-slim

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends git curl ca-certificates xz-utils && \
    rm -rf /var/lib/apt/lists/*

# Install Claude Code CLI
RUN npm install -g @anthropic-ai/claude-code

# Install Ralph CLI (downloads pre-built binary from GitHub releases)
RUN npm install -g @ralph-orchestrator/ralph-cli

WORKDIR /app

# Copy project files
COPY ralph.yml CLAUDE.md PROMPT.md ./
COPY docs/ ./docs/
COPY entrypoint.sh ./

RUN chmod +x entrypoint.sh

# Initialize git repo (Ralph requires git)
RUN git init && \
    git config user.email "cluster-scanner@homelab" && \
    git config user.name "Cluster Scanner" && \
    git add -A && \
    git commit -m "Initial cluster-scanner setup"

ENTRYPOINT ["/app/entrypoint.sh"]
