# ==============================================================================
# Shared Configuration — Environment Variables & Constants
# ==============================================================================
#
# WHY ENVIRONMENT VARIABLES?
# Following the 12-Factor App methodology, all configuration comes from
# environment variables. This means the same Docker image works in any
# environment (local dev, staging, production) — only the env vars change.
#
# HOW IT WORKS:
# os.getenv("VAR_NAME", "default") reads from the environment with a fallback.
# In Kubernetes, these come from ConfigMaps (non-sensitive) and Secrets (sensitive).
# In local dev, they come from docker-compose.yml or a .env file.
# ==============================================================================

import os

# --- LLM CONFIGURATION ---
# The model identifier for CrewAI's LLM calls.
# Format: "provider/model-name" (CrewAI's LiteLLM integration handles routing).
# Anthropic models: anthropic/claude-sonnet-4-5-20250929, anthropic/claude-haiku-4-5-20251001
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "anthropic/claude-sonnet-4-5-20250929")

# The raw API key — injected from Vault in production, .env locally.
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# --- SERVICE CONFIGURATION ---
# Project name used for logging, service discovery, and identification.
PROJECT_NAME = os.getenv("PROJECT_NAME", "dnd-agent")

# Display name shown in the shared frontend UI dropdown (auto-discovery).
DISPLAY_NAME = os.getenv("ORCHESTRATOR_DISPLAY_NAME", PROJECT_NAME)

# Human-readable description shown as tooltip/subtitle in the frontend (auto-discovery).
DESCRIPTION = os.getenv("ORCHESTRATOR_DESCRIPTION", "")

# Ports for each service. These must match the Dockerfile EXPOSE and K8s service definitions.
ORCHESTRATOR_PORT = int(os.getenv("ORCHESTRATOR_PORT", "8000"))
SUB_AGENT_PORT = int(os.getenv("SUB_AGENT_PORT", "8080"))

# --- INTER-SERVICE AUTHENTICATION ---
# Comma-separated list of valid API keys for service-to-service communication.
# The orchestrator uses these to authenticate with sub-agents via A2A protocol.
# In production, injected from Vault. Empty string = dev mode (no auth required).
API_KEYS = [k.strip() for k in os.getenv("API_KEYS", "").split(",") if k.strip()]

# --- SUB-AGENT URLS ---
# The orchestrator needs to know where sub-agents are running.
# In K8s, these use internal DNS: http://<service>.<namespace>.svc:<port>
# In Docker Compose, these use the service name: http://<service>:<port>
SUB_AGENT_URL = os.getenv(
    "SUB_AGENT_URL",
    f"http://dnd-character-agent:{SUB_AGENT_PORT}"
)

# --- LOGGING ---
# "json" for Kubernetes (structured, parseable by log aggregators like Loki)
# "text" for local development (human-readable with timestamps)
LOG_FORMAT = os.getenv("LOG_FORMAT", "text")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

