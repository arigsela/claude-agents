"""Test suite for ConversationFormatter functionality."""

import pytest
from datetime import datetime

from src.sessions.conversation_formatter import ConversationFormatter


@pytest.fixture
def formatter():
    """Create a ConversationFormatter instance."""
    return ConversationFormatter()


@pytest.fixture
def sample_k8s_data():
    """Sample Kubernetes cluster state data."""
    return {
        "node_count": 5,
        "pod_count": 42,
        "healthy_pods": 40,
        "namespace_count": 8,
        "critical_issues": [
            "OOMKilled pods in default namespace",
            "Node node-3 experiencing high CPU",
            "PersistentVolume storage is 85% full"
        ],
        "warnings": [
            "Deployment replicas mismatch in kube-system",
            "High memory usage on 2 nodes",
            "Stale pods in eviction queue"
        ]
    }


class TestConversationFormatterBasics:
    """Test basic formatting functionality."""

    def test_format_cluster_state_message(self, formatter, sample_k8s_data):
        """Test formatting cluster state into conversation message."""
        message = formatter.format_cluster_state_message(1, sample_k8s_data)

        assert "Monitoring Cycle #1" in message
        assert "Current Cluster State" in message
        assert "**Nodes**: 5" in message
        assert "**Pods**: 40/42 healthy (2 failed/pending)" in message
        assert "**Namespaces**: 8" in message
        assert "Critical Issues (3)" in message
        assert "OOMKilled pods" in message
        assert "Warnings (3)" in message
        assert "Analysis Request" in message

    def test_format_with_previous_summary(self, formatter, sample_k8s_data):
        """Test formatting with reference to previous cycle."""
        previous = "Cluster was stable with 41/42 pods healthy."
        message = formatter.format_cluster_state_message(2, sample_k8s_data, previous)

        assert "Monitoring Cycle #2" in message
        assert "Previous Cycle Summary" in message
        assert "Cluster was stable" in message

    def test_format_no_issues(self, formatter):
        """Test formatting when there are no issues."""
        clean_state = {
            "node_count": 3,
            "pod_count": 10,
            "healthy_pods": 10,
            "namespace_count": 2,
            "critical_issues": [],
            "warnings": []
        }

        message = formatter.format_cluster_state_message(1, clean_state)

        assert "Critical Issues (0)" in message
        assert "Warnings (0)" in message

    def test_format_issues_truncation(self, formatter):
        """Test that issue list is truncated if too many."""
        many_issues = [f"Issue {i}" for i in range(10)]
        formatted = formatter._format_issues(many_issues, max_display=5)

        # Should show first 5 and indicator
        assert "Issue 0" in formatted
        assert "Issue 4" in formatted
        assert "... and 5 more" in formatted
        # Should not show issue 5 directly
        assert "Issue 5" not in formatted

    def test_format_analysis_summary(self, formatter):
        """Test extracting structured summary from analysis."""
        analysis = "The cluster is experiencing memory pressure. Multiple pods are OOMKilled." * 50

        summary = formatter.format_analysis_summary(analysis, max_length=100)

        assert "full_analysis" in summary
        assert "summary" in summary
        assert "timestamp" in summary
        assert "length" in summary
        assert "was_truncated" in summary
        assert summary["was_truncated"] is True
        assert len(summary["summary"]) <= 104  # 100 + "..."


class TestTrendAnalysis:
    """Test trend analysis formatting."""

    def test_format_trend_analysis_message(self, formatter, sample_k8s_data):
        """Test trend analysis message formatting."""
        trend_metrics = {
            "trend_direction": "degrading",
            "issue_frequency": 2.5,
            "resolved_count": 1
        }

        message = formatter.format_trend_analysis_message(
            10, sample_k8s_data, trend_metrics, previous_cycles=5
        )

        assert "Trend Analysis" in message
        assert "Cycle #10" in message
        assert "Last 5 cycles" in message
        assert "degrading" in message
        assert "2.5" in message
        assert "1 issues resolved" in message

    def test_trend_with_stable_direction(self, formatter, sample_k8s_data):
        """Test trend message with stable trend."""
        trend_metrics = {
            "trend_direction": "stable",
            "issue_frequency": 1.0,
            "resolved_count": 0
        }

        message = formatter.format_trend_analysis_message(
            5, sample_k8s_data, trend_metrics
        )

        assert "stable" in message


class TestActionItemExtraction:
    """Test extracting action items from analysis."""

    def test_extract_action_items(self, formatter):
        """Test extracting actionable recommendations."""
        analysis = """
The cluster needs immediate attention.
We should restart the affected pods.
Must increase the persistent volume size.
You must implement network policies.
We recommend adding node autoscaling.
        """

        items = formatter.extract_action_items(analysis)

        assert len(items) > 0
        assert any("restart" in item["action_text"].lower() for item in items)
        assert any("volume size" in item["action_text"].lower() for item in items)
        assert any(item["confidence"] == "high" for item in items)

    def test_extract_with_custom_keywords(self, formatter):
        """Test extraction with custom keywords."""
        analysis = "Please check the logs. Verify cluster health."

        items = formatter.extract_action_items(
            analysis,
            keywords=["check", "verify"]
        )

        assert len(items) >= 1
        assert any("check" in item["action_text"].lower() for item in items)

    def test_extract_empty_analysis(self, formatter):
        """Test extraction from empty analysis."""
        items = formatter.extract_action_items("")

        assert items == []

    def test_extract_limit(self, formatter):
        """Test that extracted items are limited."""
        analysis = "\n".join([f"Line {i}: should do something" for i in range(20)])

        items = formatter.extract_action_items(analysis)

        assert len(items) <= 10


class TestConversationContextSummary:
    """Test conversation context summary generation."""

    def test_format_context_summary(self, formatter):
        """Test formatting conversation context summary."""
        messages = [
            {"role": "user", "content": "Cycle 1 data"},
            {"role": "assistant", "content": "Cycle 1 analysis: Everything is nominal."},
            {"role": "user", "content": "Cycle 2 data"},
            {"role": "assistant", "content": "Cycle 2 analysis: CPU usage trending up."},
        ]

        summary = formatter.format_conversation_context_summary(messages)

        assert "Conversation Context Summary" in summary
        assert "Total Messages**: 4" in summary
        assert "2 user" in summary
        assert "2 assistant" in summary
        assert "2 monitoring cycles" in summary

    def test_context_summary_empty(self, formatter):
        """Test summary with empty message history."""
        summary = formatter.format_conversation_context_summary([])

        assert "No conversation history" in summary

    def test_context_summary_single_message(self, formatter):
        """Test summary with just one message."""
        messages = [{"role": "user", "content": "Initial state"}]

        summary = formatter.format_conversation_context_summary(messages)

        assert "Total Messages**: 1" in summary


class TestMessageValidation:
    """Test message format validation."""

    def test_validate_correct_message(self, formatter):
        """Test validation of correctly formatted message."""
        msg = {"role": "user", "content": "Test content"}

        assert formatter.validate_message_format(msg) is True

    def test_validate_missing_role(self, formatter):
        """Test validation fails when role is missing."""
        msg = {"content": "Test content"}

        assert formatter.validate_message_format(msg) is False

    def test_validate_missing_content(self, formatter):
        """Test validation fails when content is missing."""
        msg = {"role": "user"}

        assert formatter.validate_message_format(msg) is False

    def test_validate_invalid_role(self, formatter):
        """Test validation fails with invalid role."""
        msg = {"role": "invalid", "content": "Test"}

        assert formatter.validate_message_format(msg) is False

    def test_validate_invalid_content_type(self, formatter):
        """Test validation fails when content is not string."""
        msg = {"role": "user", "content": 123}

        assert formatter.validate_message_format(msg) is False

    def test_validate_not_dict(self, formatter):
        """Test validation fails when input is not dict."""
        assert formatter.validate_message_format("not a dict") is False
        assert formatter.validate_message_format(None) is False

    def test_validate_assistant_message(self, formatter):
        """Test validation of assistant message."""
        msg = {"role": "assistant", "content": "Analysis result"}

        assert formatter.validate_message_format(msg) is True

    def test_validate_system_message(self, formatter):
        """Test validation of system message."""
        msg = {"role": "system", "content": "System prompt"}

        assert formatter.validate_message_format(msg) is True


class TestMessageSanitization:
    """Test message content sanitization."""

    def test_sanitize_null_characters(self, formatter):
        """Test removal of null characters."""
        content = "Safe content\x00with null"
        sanitized = formatter.sanitize_message_content(content)

        assert "\x00" not in sanitized
        assert "Safe content" in sanitized

    def test_sanitize_length_limit(self, formatter):
        """Test truncation of long content."""
        long_content = "x" * 20000
        sanitized = formatter.sanitize_message_content(long_content, max_length=100)

        assert len(sanitized) <= 120  # 100 + "[... truncated ...]"
        assert "[... truncated ...]" in sanitized

    def test_sanitize_normal_content(self, formatter):
        """Test that normal content is unchanged."""
        content = "This is normal content with no issues."
        sanitized = formatter.sanitize_message_content(content)

        assert sanitized == content

    def test_sanitize_multiline_content(self, formatter):
        """Test sanitization of multiline content."""
        content = "Line 1\nLine 2\nLine 3"
        sanitized = formatter.sanitize_message_content(content)

        assert sanitized == content


class TestIntegration:
    """Integration tests combining multiple components."""

    def test_full_formatting_cycle(self, formatter, sample_k8s_data):
        """Test a complete formatting cycle."""
        # Format initial state
        msg1 = formatter.format_cluster_state_message(1, sample_k8s_data)
        assert "Monitoring Cycle #1" in msg1

        # Create analysis
        analysis = "Cluster has 3 critical issues. Recommend immediate action."

        # Extract summary
        summary = formatter.format_analysis_summary(analysis)
        assert "critical issues" in summary["full_analysis"]

        # Use summary in next cycle
        msg2 = formatter.format_cluster_state_message(
            2, sample_k8s_data, summary["summary"]
        )
        assert "Previous Cycle Summary" in msg2

    def test_message_validation_in_history(self, formatter):
        """Test validating messages in conversation history."""
        history = [
            {"role": "user", "content": "Valid message"},
            {"role": "assistant", "content": "Valid response"},
            {"role": "invalid", "content": "Invalid message"},
        ]

        valid_count = sum(1 for msg in history if formatter.validate_message_format(msg))
        assert valid_count == 2

    def test_extract_and_format_actions(self, formatter):
        """Test extracting actions and formatting them."""
        analysis = "We must fix the OOM issue. Should increase memory limits."
        actions = formatter.extract_action_items(analysis)

        formatted_actions = "\n".join(
            f"- {action['action_text']} ({action['confidence']})"
            for action in actions
        )

        assert "OOM" in formatted_actions
        assert "memory" in formatted_actions
