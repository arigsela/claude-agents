"""Pytest fixtures and configuration."""

import os
from pathlib import Path

import pytest

from src.config import Settings


@pytest.fixture
def test_settings():
    """Create test settings with minimal configuration."""
    # Set up minimal environment for testing
    os.environ["ANTHROPIC_API_KEY"] = "sk-test-key-12345"

    settings = Settings(
        anthropic_api_key="sk-test-key-12345",
        github_token="test-token",
        slack_bot_token="xoxb-test-token",
        slack_channel="C123456789",
        kubeconfig=Path.home() / ".kube" / "config",
        k3s_context="default",
        orchestrator_model="claude-sonnet-4-5-20250929",
        k8s_analyzer_model="claude-haiku-4-5-20251001",
        escalation_manager_model="claude-sonnet-4-5-20250929",
        slack_notifier_model="claude-haiku-4-5-20251001",
        github_reviewer_model="claude-sonnet-4-5-20250929",
        monitoring_interval_hours=1,
        log_level="INFO",
    )

    return settings


@pytest.fixture
def mock_kubectl_output():
    """Mock kubectl output for testing."""
    return {
        "pods_healthy": """NAMESPACE              NAME                                  READY   STATUS    RESTARTS
        chores-tracker-backend    chores-tracker-backend-7d8f9c5b4-x7k2p   1/1     Running   0
        chores-tracker-backend    chores-tracker-backend-7d8f9c5b4-y9k3p   1/1     Running   0
        chores-tracker-frontend   chores-tracker-frontend-5f1a2b3c-a1b2c   1/1     Running   0
        mysql                     mysql-9b7c3a2d1-l2m3n                  1/1     Running   0
        """,
        "pods_with_issues": """NAMESPACE           NAME                                    READY   STATUS             RESTARTS
        chores-tracker-backend    chores-tracker-backend-7d8f9c5b4-x7k2p   0/1     CrashLoopBackOff   5 (2m ago)
        chores-tracker-backend    chores-tracker-backend-7d8f9c5b4-y9k3p   0/1     CrashLoopBackOff   5 (2m ago)
        mysql                     mysql-9b7c3a2d1-l2m3n                  1/1     Running            0
        """,
        "events_warning": """NAMESPACE         LAST SEEN   TYPE      REASON              OBJECT
        chores-tracker-backend    2m ago      Warning   OOMKilled           pod/chores-tracker-backend-7d8f9c5b4-x7k2p
        chores-tracker-backend    5m ago      Warning   BackOff             pod/chores-tracker-backend-7d8f9c5b4-x7k2p
        """,
        "nodes_healthy": """NAME       STATUS   ROLES         AGE   VERSION
        k8s-master-1   Ready    control-plane   30d   v1.28.0
        k8s-node-1     Ready    worker          30d   v1.28.0
        k8s-node-2     Ready    worker          30d   v1.28.0
        """,
    }
