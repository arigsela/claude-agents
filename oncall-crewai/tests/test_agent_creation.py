"""Tests for agent creation -- verifying roles, goals, tools, and parameters.

Ensures that agent identity and configuration match expected values.
Catches accidental prompt changes, removed tools, or missing parameters.
"""

from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def mock_k8s_config():
    """Prevent real kubernetes config loading."""
    with patch("k8s_agent.tools.config") as mock_config:
        mock_config.load_incluster_config.side_effect = Exception("not in cluster")
        mock_config.load_kube_config.return_value = None
        yield mock_config


@pytest.fixture
def mock_env(monkeypatch):
    """Set required env vars for agent creation."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setenv("ANTHROPIC_MODEL", "anthropic/claude-sonnet-4-5-20250929")


class TestK8sAgentCreation:
    """Tests for K8s agent identity and configuration."""

    def test_agent_has_correct_role(self, mock_env):
        from k8s_agent.agent import create_k8s_agent
        from k8s_agent.prompts import K8S_AGENT_ROLE

        agent = create_k8s_agent()
        assert agent.role == K8S_AGENT_ROLE

    def test_agent_has_correct_goal(self, mock_env):
        from k8s_agent.agent import create_k8s_agent
        from k8s_agent.prompts import K8S_AGENT_GOAL

        agent = create_k8s_agent()
        assert agent.goal == K8S_AGENT_GOAL

    def test_agent_has_7_tools(self, mock_env):
        from k8s_agent.agent import create_k8s_agent

        agent = create_k8s_agent()
        assert len(agent.tools) == 7

    def test_agent_has_correct_tool_names(self, mock_env):
        from k8s_agent.agent import create_k8s_agent

        agent = create_k8s_agent()
        tool_names = {t.name for t in agent.tools}
        expected = {
            "list_namespaces",
            "list_pods",
            "get_pod_logs",
            "get_pod_events",
            "get_deployment_status",
            "list_services",
            "analyze_service_health",
        }
        assert tool_names == expected

    def test_agent_cache_disabled(self, mock_env):
        from k8s_agent.agent import create_k8s_agent

        agent = create_k8s_agent()
        assert agent.cache is False

    def test_agent_has_max_execution_time(self, mock_env):
        from k8s_agent.agent import create_k8s_agent

        agent = create_k8s_agent()
        assert agent.max_execution_time == 300

    def test_agent_has_max_rpm(self, mock_env):
        from k8s_agent.agent import create_k8s_agent

        agent = create_k8s_agent()
        assert agent.max_rpm == 30

    def test_agent_has_reasoning_enabled(self, mock_env):
        from k8s_agent.agent import create_k8s_agent

        agent = create_k8s_agent()
        assert agent.reasoning is True

    def test_agent_has_fingerprint(self, mock_env):
        from k8s_agent.agent import create_k8s_agent

        agent = create_k8s_agent()
        assert agent.fingerprint is not None

    def test_agent_respects_context_window(self, mock_env):
        from k8s_agent.agent import create_k8s_agent

        agent = create_k8s_agent()
        assert agent.respect_context_window is True

    def test_agent_has_step_callback(self, mock_env):
        from k8s_agent.agent import create_k8s_agent

        agent = create_k8s_agent()
        assert agent.step_callback is not None


class TestGitHubAgentCreation:
    """Tests for GitHub agent identity and configuration."""

    def test_agent_has_correct_role(self, mock_env):
        from github_agent.agent import create_github_agent
        from github_agent.prompts import GITHUB_AGENT_ROLE

        agent = create_github_agent()
        assert agent.role == GITHUB_AGENT_ROLE

    def test_agent_has_correct_goal(self, mock_env):
        from github_agent.agent import create_github_agent
        from github_agent.prompts import GITHUB_AGENT_GOAL

        agent = create_github_agent()
        assert agent.goal == GITHUB_AGENT_GOAL

    def test_agent_has_5_tools(self, mock_env):
        from github_agent.agent import create_github_agent

        agent = create_github_agent()
        assert len(agent.tools) == 5

    def test_agent_has_correct_tool_names(self, mock_env):
        from github_agent.agent import create_github_agent

        agent = create_github_agent()
        tool_names = {t.name for t in agent.tools}
        expected = {
            "search_recent_deployments",
            "get_gitops_file",
            "list_gitops_directory",
            "create_remediation_pr",
            "create_document_pr",
        }
        assert tool_names == expected

    def test_agent_has_max_execution_time(self, mock_env):
        from github_agent.agent import create_github_agent

        agent = create_github_agent()
        assert agent.max_execution_time == 300

    def test_agent_has_max_rpm(self, mock_env):
        from github_agent.agent import create_github_agent

        agent = create_github_agent()
        assert agent.max_rpm == 30

    def test_agent_has_fingerprint(self, mock_env):
        from github_agent.agent import create_github_agent

        agent = create_github_agent()
        assert agent.fingerprint is not None

    def test_agent_respects_context_window(self, mock_env):
        from github_agent.agent import create_github_agent

        agent = create_github_agent()
        assert agent.respect_context_window is True

    def test_agent_has_step_callback(self, mock_env):
        from github_agent.agent import create_github_agent

        agent = create_github_agent()
        assert agent.step_callback is not None


class TestInvokeValidation:
    """Tests for input validation in invoke() functions."""

    def test_k8s_invoke_rejects_empty_query(self, mock_env):
        from k8s_agent.agent import invoke

        with pytest.raises(ValueError, match="Query cannot be empty"):
            invoke(query="", context_id="test")

    def test_k8s_invoke_rejects_whitespace_query(self, mock_env):
        from k8s_agent.agent import invoke

        with pytest.raises(ValueError, match="Query cannot be empty"):
            invoke(query="   ", context_id="test")

    def test_github_invoke_rejects_empty_query(self, mock_env):
        from github_agent.agent import invoke

        with pytest.raises(ValueError, match="Query cannot be empty"):
            invoke(query="", context_id="test")


class TestSharedModels:
    """Tests for Pydantic output models and guardrails."""

    def test_k8s_diagnosis_model_defaults(self):
        from shared.models import K8sDiagnosisOutput

        output = K8sDiagnosisOutput()
        assert output.service == ""
        assert output.priority == ""
        assert output.remediation_steps == []

    def test_gitops_output_model_defaults(self):
        from shared.models import GitOpsOutput

        output = GitOpsOutput()
        assert output.action == ""
        assert output.pr_url == ""

    def test_k8s_guardrail_rejects_short_output(self):
        from unittest.mock import Mock

        from shared.models import validate_k8s_diagnosis

        result = Mock()
        result.raw = "short"
        ok, msg = validate_k8s_diagnosis(result)
        assert ok is False
        assert "too short" in msg

    def test_k8s_guardrail_accepts_long_output(self):
        from unittest.mock import Mock

        from shared.models import validate_k8s_diagnosis

        result = Mock()
        result.raw = "A" * 100
        ok, _ = validate_k8s_diagnosis(result)
        assert ok is True

    def test_gitops_guardrail_rejects_short_output(self):
        from unittest.mock import Mock

        from shared.models import validate_gitops_output

        result = Mock()
        result.raw = "x"
        ok, msg = validate_gitops_output(result)
        assert ok is False
        assert "too short" in msg

    def test_gitops_guardrail_accepts_valid_output(self):
        from unittest.mock import Mock

        from shared.models import validate_gitops_output

        result = Mock()
        result.raw = "Listed the directory contents of base-apps/chores-tracker/"
        ok, _ = validate_gitops_output(result)
        assert ok is True


class TestObservability:
    """Tests for observability callbacks and helpers."""

    def test_timed_invoke_decorator(self):
        from shared.observability import timed_invoke

        @timed_invoke
        def sample_func(x):
            return x * 2

        assert sample_func(5) == 10

    def test_timed_invoke_propagates_exceptions(self):
        from shared.observability import timed_invoke

        @timed_invoke
        def failing_func():
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError, match="boom"):
            failing_func()

    def test_log_token_usage_no_crash_on_missing(self):
        from unittest.mock import Mock

        from shared.observability import log_token_usage

        result = Mock(spec=[])  # No token_usage attribute
        # Should not raise
        log_token_usage(result, agent_name="test")


class TestA2AUtils:
    """Tests for shared A2A utility functions."""

    def test_extract_text_part(self):
        from unittest.mock import Mock

        from a2a.types import TextPart

        from shared.a2a_utils import extract_user_input

        msg = Mock()
        msg.parts = [TextPart(text="hello world")]
        assert extract_user_input(msg) == "hello world"

    def test_extract_default_on_empty(self):
        from unittest.mock import Mock

        from shared.a2a_utils import extract_user_input

        msg = Mock()
        msg.parts = []
        assert extract_user_input(msg, default="fallback") == "fallback"

    def test_extract_default_on_none(self):
        from shared.a2a_utils import extract_user_input

        assert extract_user_input(None, default="fallback") == "fallback"
