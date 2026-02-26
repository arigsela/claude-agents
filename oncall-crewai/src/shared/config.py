"""Shared configuration for oncall-crewai multi-agent system."""

import os
from pathlib import Path

import yaml


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

# Agent Log Level
AGENT_LOG_LEVEL = get_env("AGENT_LOG_LEVEL", "INFO")

# GitHub Configuration
GITHUB_TOKEN = get_env("GITHUB_TOKEN")
GITHUB_ORG = get_env("GITHUB_ORG", "arigsela")
GITOPS_REPO = get_env("GITOPS_REPO", "arigsela/kubernetes")
GITOPS_BASE_PATH = get_env("GITOPS_BASE_PATH", "base-apps/")
GITOPS_BASE_BRANCH = get_env("GITOPS_BASE_BRANCH", "main")
DOCS_REPO = get_env("DOCS_REPO", "arigsela/claude-agents")


def load_service_catalog() -> dict:
    """Load service catalog from YAML file.

    Searches for service_mapping.yaml in:
    1. config/ relative to the project root
    2. /app/config/ (container path)
    """
    search_paths = [
        Path(__file__).parent.parent.parent / "config" / "service_mapping.yaml",
        Path("/app/config/service_mapping.yaml"),
    ]

    for path in search_paths:
        if path.exists():
            with open(path) as f:
                data = yaml.safe_load(f)
            return data.get("service_mappings", {})

    return {}
