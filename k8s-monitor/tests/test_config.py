"""Tests for configuration management."""

from pathlib import Path

import pytest

from src.config import Settings


class TestSettings:
    """Tests for Settings class."""

    def test_settings_from_env(self, monkeypatch):
        """Test loading settings from environment variables."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-12345")
        monkeypatch.setenv("K3S_CONTEXT", "test-context")
        monkeypatch.setenv("MONITORING_INTERVAL_HOURS", "2")

        settings = Settings()

        assert settings.anthropic_api_key == "sk-test-12345"
        assert settings.k3s_context == "test-context"
        assert settings.monitoring_interval_hours == 2

    def test_settings_defaults(self):
        """Test default settings values."""
        settings = Settings(anthropic_api_key="sk-test-key")

        assert settings.k3s_context == "default"
        assert settings.monitoring_interval_hours == 1
        assert settings.log_level == "INFO"
        assert settings.orchestrator_model == "claude-sonnet-4-5-20250929"
        assert settings.k8s_analyzer_model == "claude-haiku-4-5-20251001"

    def test_settings_required_api_key(self):
        """Test that ANTHROPIC_API_KEY is required."""
        # Should raise ValidationError if API key not provided
        with pytest.raises(Exception):  # pydantic ValidationError
            Settings()

    def test_settings_custom_paths(self):
        """Test custom path configuration."""
        settings = Settings(
            anthropic_api_key="sk-test",
            services_file=Path("custom/services.txt"),
            github_mcp_path=Path("custom/github/index.js"),
        )

        assert settings.services_file == Path("custom/services.txt")
        assert settings.github_mcp_path == Path("custom/github/index.js")

    def test_validate_paths_raises_on_missing_kubeconfig(self, monkeypatch):
        """Test path validation for missing kubeconfig."""
        # Set a non-existent kubeconfig path
        monkeypatch.setenv("KUBECONFIG", "/nonexistent/kubeconfig")

        settings = Settings(anthropic_api_key="sk-test-key")

        # validate_all() should raise FileNotFoundError for missing kubeconfig
        with pytest.raises(FileNotFoundError):
            settings.validate_all()

    def test_validate_api_keys_raises_on_missing_key(self):
        """Test API key validation."""
        settings = Settings(anthropic_api_key="")

        with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
            settings.validate_api_keys()

    def test_case_insensitive_env_vars(self, monkeypatch):
        """Test case-insensitive environment variable loading."""
        monkeypatch.setenv("anthropic_api_key", "sk-lowercase")
        monkeypatch.setenv("K3S_CONTEXT", "uppercase-context")

        settings = Settings()

        assert settings.anthropic_api_key == "sk-lowercase"
        assert settings.k3s_context == "uppercase-context"

    def test_optional_tokens(self):
        """Test that GitHub and Slack tokens are optional."""
        settings = Settings(anthropic_api_key="sk-test")

        assert settings.github_token is None
        assert settings.slack_bot_token is None
        assert settings.slack_channel is None

    def test_model_configuration(self):
        """Test custom model configuration."""
        settings = Settings(
            anthropic_api_key="sk-test",
            orchestrator_model="custom-orchestrator",
            k8s_analyzer_model="custom-analyzer",
        )

        assert settings.orchestrator_model == "custom-orchestrator"
        assert settings.k8s_analyzer_model == "custom-analyzer"
        # Other models should have defaults
        assert settings.escalation_manager_model == "claude-sonnet-4-5-20250929"
