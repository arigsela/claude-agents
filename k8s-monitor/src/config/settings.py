"""Pydantic settings for k8s-monitor configuration."""

import logging
from pathlib import Path
from typing import Optional

from pydantic import ConfigDict, Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env file."""

    # API Keys (Required)
    anthropic_api_key: str = Field(
        ..., description="Anthropic API key for Claude access"
    )
    github_token: Optional[str] = Field(
        default=None, description="GitHub personal access token for GitHub MCP"
    )
    slack_bot_token: Optional[str] = Field(
        default=None, description="Slack bot token for Slack MCP"
    )

    # Slack Configuration (Optional)
    slack_enabled: bool = Field(
        default=True, description="Enable Slack notifications (set to false to disable)"
    )
    slack_channel: Optional[str] = Field(
        default=None, description="Slack channel ID for alerts (e.g., C01234567)"
    )

    # Kubernetes Configuration
    kubeconfig: Optional[str] = Field(
        default=None,
        description="Path to kubeconfig file (resolved at runtime)",
    )
    k3s_context: str = Field(default="default", description="K3s context name")

    # Model Configuration (Cost Optimization)
    # ⚠️ IMPORTANT: These settings are NO LONGER USED
    # All models are HARDCODED in src/orchestrator/monitor.py to ensure Haiku usage
    # These fields are kept for backward compatibility only
    # To change models, edit the HARDCODED constants in monitor.py, not these fields
    orchestrator_model: str = Field(
        default="claude-haiku-4-5-20251001",
        description="[DEPRECATED] Model hardcoded in monitor.py - not used",
    )
    k8s_analyzer_model: str = Field(
        default="claude-haiku-4-5-20251001",
        description="[DEPRECATED] Model hardcoded in monitor.py - not used",
    )
    escalation_manager_model: str = Field(
        default="claude-haiku-4-5-20251001",
        description="[DEPRECATED] Model hardcoded in monitor.py - not used",
    )
    slack_notifier_model: str = Field(
        default="claude-haiku-4-5-20251001",
        description="[DEPRECATED] Model hardcoded in monitor.py - not used",
    )
    github_reviewer_model: str = Field(
        default="claude-haiku-4-5-20251001",
        description="[DEPRECATED] Model hardcoded in monitor.py - not used",
    )

    # Monitoring Settings
    monitoring_interval_minutes: int = Field(
        default=60, description="Minutes between monitoring cycles"
    )
    log_level: str = Field(default="INFO", description="Logging level")

    # File Paths
    services_file: Path = Field(
        default=Path("docs/reference/services.txt"),
        description="Path to service criticality mapping file",
    )
    github_mcp_path: Path = Field(
        default=Path("mcp-servers/github/dist/index.js"),
        description="Path to GitHub MCP server executable",
    )
    slack_mcp_path: Path = Field(
        default=Path("mcp-servers/slack/dist/index.js"),
        description="Path to Slack MCP server executable",
    )

    model_config = ConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore",
    )

    def validate_paths(self) -> None:
        """Validate required paths exist and resolve kubeconfig intelligently.

        This method handles kubeconfig path resolution for both local, Docker, and in-cluster execution:
        - If running in-cluster (ServiceAccount tokens detected), use in-cluster auth
        - If KUBECONFIG env var is set, try it first
        - If that path doesn't exist, fall back to ~/.kube/config
        - This allows a single .env file to work in all contexts
        """
        # Check if running in-cluster (Kubernetes ServiceAccount available)
        in_cluster_ca = Path("/var/run/secrets/kubernetes.io/serviceaccount/ca.crt")
        in_cluster_token = Path("/var/run/secrets/kubernetes.io/serviceaccount/token")

        if in_cluster_ca.exists() and in_cluster_token.exists():
            # Running in-cluster: use None to signal in-cluster auth
            self.kubeconfig = None
            logger = logging.getLogger(__name__)
            logger.info("Running in-cluster: using Kubernetes ServiceAccount authentication")
            # Validate services file
            if self.services_file and not self.services_file.exists():
                raise FileNotFoundError(f"Services file not found at {self.services_file}")
            return

        # Resolve kubeconfig intelligently for local/Docker execution
        kubeconfig_path = None

        # Try the configured path first (could be from env var or default)
        if self.kubeconfig:
            candidate = Path(self.kubeconfig)
            if candidate.exists():
                kubeconfig_path = candidate

        # Fall back to home directory if configured path doesn't exist
        if not kubeconfig_path:
            home_kubeconfig = Path.home() / ".kube" / "config"
            if home_kubeconfig.exists():
                kubeconfig_path = home_kubeconfig

        # Raise error if no valid kubeconfig found
        if not kubeconfig_path:
            configured = self.kubeconfig or "not set"
            home_path = Path.home() / ".kube" / "config"
            raise FileNotFoundError(
                f"Kubeconfig not found. Tried: {configured}, {home_path}"
            )

        # Update kubeconfig to the resolved path
        self.kubeconfig = str(kubeconfig_path)

        # Validate services file
        if self.services_file and not self.services_file.exists():
            raise FileNotFoundError(f"Services file not found at {self.services_file}")

    def validate_api_keys(self) -> None:
        """Validate required API keys are set."""
        if not self.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY environment variable is required")

    def validate_all(self) -> None:
        """Run all validations."""
        self.validate_api_keys()
        self.validate_paths()


# Global settings instance - loaded from .env and environment variables
settings = Settings()
