"""Shared configuration for oncall-crewai multi-agent system."""

import os


def get_env(key: str, default: str = "") -> str:
    """Get environment variable with default."""
    return os.getenv(key, default)


def get_env_int(key: str, default: int = 0) -> int:
    """Get integer environment variable with default."""
    return int(os.getenv(key, str(default)))


def get_env_bool(key: str, default: bool = False) -> bool:
    """Get boolean environment variable with default."""
    return os.getenv(key, str(default)).lower() in ("true", "1", "yes")


# LLM Configuration
ANTHROPIC_API_KEY = get_env("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = get_env("ANTHROPIC_MODEL", "anthropic/claude-sonnet-4-5-20250929")

# Agent Service URLs (for orchestrator to discover A2A agents)
K8S_AGENT_URL = get_env("K8S_AGENT_URL", "http://k8s-agent-a2a:8080")
GITHUB_AGENT_URL = get_env("GITHUB_AGENT_URL", "http://github-agent-a2a:8080")

# API Configuration
API_HOST = get_env("API_HOST", "0.0.0.0")
API_PORT = get_env_int("API_PORT", 8000)
API_KEYS = [k.strip() for k in get_env("API_KEYS", "").split(",") if k.strip()]
CORS_ORIGINS = get_env("CORS_ORIGINS", "*")

# JWT / User Authentication
JWT_SECRET = get_env("JWT_SECRET", "dev-secret-change-in-production")
JWT_EXPIRY_HOURS = get_env_int("JWT_EXPIRY_HOURS", 24)
USERS_DB_PATH = get_env("USERS_DB_PATH", "/data/users.db")

# Logging & Observability
AGENT_LOG_LEVEL = get_env("AGENT_LOG_LEVEL", "INFO")
LOG_FORMAT = get_env("LOG_FORMAT", "text")  # "text" or "json" (use "json" in K8s)

# CrewAI Configuration
CREWAI_VERBOSE = get_env_bool("CREWAI_VERBOSE", default=False)

# GitHub Configuration
GITHUB_TOKEN = get_env("GITHUB_TOKEN")
GITHUB_ORG = get_env("GITHUB_ORG", "arigsela")
GITOPS_REPO = get_env("GITOPS_REPO", "arigsela/kubernetes")
GITOPS_BASE_PATH = get_env("GITOPS_BASE_PATH", "base-apps/")
GITOPS_BASE_BRANCH = get_env("GITOPS_BASE_BRANCH", "main")
DOCS_REPO = get_env("DOCS_REPO", "arigsela/claude-agents")
