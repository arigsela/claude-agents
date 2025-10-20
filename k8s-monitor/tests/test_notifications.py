"""Tests for Slack notification management."""

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from src.notifications import SlackNotifier
from src.models import EscalationDecision, IncidentSeverity


class TestSlackNotifierInitialization:
    """Tests for SlackNotifier initialization."""

    def test_init_with_default_channel(self):
        """Test initialization with default channel."""
        notifier = SlackNotifier()

        assert notifier.slack_channel is None
        assert notifier.incident_counter == 0
        assert len(notifier.severity_emoji) == 4
        assert len(notifier.severity_color) == 4

    def test_init_with_custom_channel(self):
        """Test initialization with custom channel."""
        notifier = SlackNotifier(slack_channel="#custom-alerts")

        assert notifier.slack_channel == "#custom-alerts"

    def test_severity_emoji_mapping(self):
        """Test severity emoji mapping is correct."""
        notifier = SlackNotifier()

        assert notifier.severity_emoji[IncidentSeverity.SEV_1] == "🚨"
        assert notifier.severity_emoji[IncidentSeverity.SEV_2] == "⚠️"
        assert notifier.severity_emoji[IncidentSeverity.SEV_3] == "ℹ️"
        assert notifier.severity_emoji[IncidentSeverity.SEV_4] == "✅"

    def test_severity_color_mapping(self):
        """Test severity color mapping is correct."""
        notifier = SlackNotifier()

        assert notifier.severity_color[IncidentSeverity.SEV_1] == "#FF0000"  # Red
        assert notifier.severity_color[IncidentSeverity.SEV_2] == "#FFA500"  # Orange
        assert notifier.severity_color[IncidentSeverity.SEV_3] == "#FFD700"  # Gold
        assert notifier.severity_color[IncidentSeverity.SEV_4] == "#00AA00"  # Green


class TestIncidentIdGeneration:
    """Tests for incident ID generation."""

    def test_generate_incident_id_format(self):
        """Test incident ID follows correct format."""
        notifier = SlackNotifier()
        incident_id = notifier._generate_incident_id()

        # Format: INC-YYYYMMDD_HHMMSS-NNN
        parts = incident_id.split("-")
        assert len(parts) == 3
        assert parts[0] == "INC"
        assert len(parts[1]) == 15  # YYYYMMDD_HHMMSS
        assert parts[1][8] == "_"
        assert parts[2].isdigit()
        assert len(parts[2]) == 3

    def test_incident_id_counter_increments(self):
        """Test incident counter increments."""
        notifier = SlackNotifier()
        assert notifier.incident_counter == 0

        id1 = notifier._generate_incident_id()
        assert notifier.incident_counter == 1

        id2 = notifier._generate_incident_id()
        assert notifier.incident_counter == 2

        # Counter part should differ
        assert id1.split("-")[2] != id2.split("-")[2]

    def test_incident_id_uniqueness(self):
        """Test generated incident IDs are unique."""
        notifier = SlackNotifier()
        ids = [notifier._generate_incident_id() for _ in range(10)]

        # All IDs should be unique
        assert len(set(ids)) == 10


class TestNotificationPayloadPreparation:
    """Tests for notification payload preparation."""

    def setup_method(self):
        """Set up test fixtures."""
        self.notifier = SlackNotifier(slack_channel="#test-channel")

    def test_prepare_payload_basic(self):
        """Test basic payload preparation."""
        decision = EscalationDecision(
            severity=IncidentSeverity.SEV_1,
            confidence=95,
            should_notify=True,
            affected_services=["service-a", "service-b"],
            root_cause="Database connection pool exhausted",
            immediate_actions=["Restart pod", "Scale up replicas"],
            business_impact="Users cannot access dashboard",
        )

        payload = self.notifier._prepare_notification_payload(decision, "INC-12345")

        assert payload["incident_id"] == "INC-12345"
        assert payload["severity"] == IncidentSeverity.SEV_1
        assert payload["confidence"] == 95
        assert payload["affected_services"] == ["service-a", "service-b"]
        assert payload["root_cause"] == "Database connection pool exhausted"
        assert payload["channel"] == "#test-channel"

    def test_prepare_payload_with_enriched_data(self):
        """Test payload preparation with enriched data."""
        enriched = {
            "pod_count": 3,
            "memory_usage": "85%",
            "restart_count": 5,
        }
        decision = EscalationDecision(
            severity=IncidentSeverity.SEV_2,
            confidence=80,
            should_notify=True,
            affected_services=["service-a"],
            enriched_payload=enriched,
        )

        payload = self.notifier._prepare_notification_payload(decision, "INC-67890")

        assert payload["enriched_data"] == enriched

    def test_prepare_payload_overrides_channel(self):
        """Test payload uses decision's notification channel if provided."""
        decision = EscalationDecision(
            severity=IncidentSeverity.SEV_1,
            confidence=100,
            should_notify=True,
            affected_services=["service-a"],
            notification_channel="#critical-override",
        )

        payload = self.notifier._prepare_notification_payload(decision, "INC-99999")

        assert payload["channel"] == "#critical-override"

    def test_prepare_payload_defaults_to_notifier_channel(self):
        """Test payload uses notifier's channel if decision doesn't specify."""
        decision = EscalationDecision(
            severity=IncidentSeverity.SEV_2,
            confidence=90,
            should_notify=True,
            affected_services=["service-a"],
            notification_channel=None,
        )

        payload = self.notifier._prepare_notification_payload(decision, "INC-55555")

        assert payload["channel"] == "#test-channel"


class TestSlackQueryBuilding:
    """Tests for Slack query building."""

    def setup_method(self):
        """Set up test fixtures."""
        self.notifier = SlackNotifier(slack_channel="#alerts")

    def test_build_query_includes_incident_id(self):
        """Test query includes incident ID."""
        payload = {
            "incident_id": "INC-12345",
            "severity": IncidentSeverity.SEV_1,
            "confidence": 95,
            "affected_services": ["service-a"],
            "channel": "#alerts",
            "root_cause": "Pod crash",
            "business_impact": "Users affected",
            "immediate_actions": ["Action 1"],
        }
        decision = EscalationDecision(
            severity=IncidentSeverity.SEV_1,
            confidence=95,
            should_notify=True,
            affected_services=["service-a"],
            root_cause="Pod crash",
            business_impact="Users affected",
            immediate_actions=["Action 1"],
        )

        query = self.notifier._build_slack_query(payload, decision)

        assert "INC-12345" in query
        assert "slack-notifier" in query.lower()

    def test_build_query_includes_channel(self):
        """Test query includes target channel."""
        payload = {
            "incident_id": "INC-TEST",
            "severity": IncidentSeverity.SEV_2,
            "confidence": 80,
            "affected_services": ["mysql"],
            "channel": "#infrastructure-alerts",
            "root_cause": "High memory",
            "business_impact": "Slow responses",
            "immediate_actions": ["Scale up"],
        }
        decision = EscalationDecision(
            severity=IncidentSeverity.SEV_2,
            confidence=80,
            should_notify=True,
            affected_services=["mysql"],
            root_cause="High memory",
            business_impact="Slow responses",
            immediate_actions=["Scale up"],
        )

        query = self.notifier._build_slack_query(payload, decision)

        assert "#infrastructure-alerts" in query

    def test_build_query_includes_severity(self):
        """Test query includes severity level."""
        payload = {
            "incident_id": "INC-SEV",
            "severity": IncidentSeverity.SEV_1,
            "confidence": 100,
            "affected_services": ["postgres"],
            "channel": "#critical",
            "root_cause": "Data loss risk",
            "business_impact": "Critical",
            "immediate_actions": ["Immediate restart"],
        }
        decision = EscalationDecision(
            severity=IncidentSeverity.SEV_1,
            confidence=100,
            should_notify=True,
            affected_services=["postgres"],
            root_cause="Data loss risk",
            business_impact="Critical",
            immediate_actions=["Immediate restart"],
        )

        query = self.notifier._build_slack_query(payload, decision)

        assert "SEV-1" in query or "SEV_1" in query

    def test_build_query_includes_affected_services(self):
        """Test query includes all affected services."""
        payload = {
            "incident_id": "INC-SVCS",
            "severity": IncidentSeverity.SEV_2,
            "confidence": 90,
            "affected_services": ["service-a", "service-b", "service-c"],
            "channel": "#alerts",
            "root_cause": "Network issue",
            "business_impact": "Partial outage",
            "immediate_actions": ["Check network"],
        }
        decision = EscalationDecision(
            severity=IncidentSeverity.SEV_2,
            confidence=90,
            should_notify=True,
            affected_services=["service-a", "service-b", "service-c"],
            root_cause="Network issue",
            business_impact="Partial outage",
            immediate_actions=["Check network"],
        )

        query = self.notifier._build_slack_query(payload, decision)

        assert "service-a" in query
        assert "service-b" in query
        assert "service-c" in query

    def test_build_query_includes_immediate_actions(self):
        """Test query includes immediate actions."""
        payload = {
            "incident_id": "INC-ACTIONS",
            "severity": IncidentSeverity.SEV_3,
            "confidence": 75,
            "affected_services": ["logging"],
            "channel": "#alerts",
            "root_cause": "Disk space low",
            "business_impact": "Logs not persisted",
            "immediate_actions": ["Clear old logs", "Increase volume", "Monitor disk"],
        }
        decision = EscalationDecision(
            severity=IncidentSeverity.SEV_3,
            confidence=75,
            should_notify=True,
            affected_services=["logging"],
            root_cause="Disk space low",
            business_impact="Logs not persisted",
            immediate_actions=["Clear old logs", "Increase volume", "Monitor disk"],
        )

        query = self.notifier._build_slack_query(payload, decision)

        assert "Clear old logs" in query
        assert "Increase volume" in query
        assert "Monitor disk" in query


class TestSlackResponseParsing:
    """Tests for Slack response parsing."""

    def setup_method(self):
        """Set up test fixtures."""
        self.notifier = SlackNotifier()

    def test_parse_success_response(self):
        """Test parsing successful delivery response."""
        response = """
The Slack message has been successfully delivered to #infrastructure-alerts.

Message ID: ts-1234567890.123456
Timestamp: 2024-10-20T10:30:45Z
Status: ✅ Successfully posted
"""
        result = self.notifier._parse_slack_response(response, "INC-12345")

        assert result["success"] is True
        assert result["incident_id"] == "INC-12345"
        assert result["message_id"] is not None

    def test_parse_failure_response(self):
        """Test parsing failed delivery response."""
        response = """
Failed to send message: Channel not found.
Error: The specified channel does not exist.
"""
        result = self.notifier._parse_slack_response(response, "INC-12345")

        assert result["success"] is False
        assert result["incident_id"] == "INC-12345"
        assert "raw_response" in result

    def test_parse_message_id_extraction(self):
        """Test message ID extraction from response."""
        response = "Message ts: 1234567890.123456 posted successfully"
        result = self.notifier._parse_slack_response(response, "INC-MSG-ID")

        assert result["message_id"] == "1234567890.123456"

    def test_parse_channel_extraction(self):
        """Test channel extraction from response."""
        response = "Successfully sent to #critical-alerts channel"
        result = self.notifier._parse_slack_response(response, "INC-CH-TEST")

        assert result["channel"] is not None

    def test_parse_response_includes_timestamp(self):
        """Test parsed response includes timestamp."""
        response = "Message delivered successfully"
        result = self.notifier._parse_slack_response(response, "INC-TS-TEST")

        assert "timestamp" in result
        assert result["timestamp"] is not None

    def test_parse_response_with_checkmark(self):
        """Test parsing response with checkmark emoji."""
        response = "✅ Message successfully delivered to #alerts"
        result = self.notifier._parse_slack_response(response, "INC-CHECK")

        assert result["success"] is True

    def test_parse_response_with_sent_keyword(self):
        """Test parsing response with 'sent' keyword."""
        response = "Alert has been sent to Slack channel #infrastructure-alerts"
        result = self.notifier._parse_slack_response(response, "INC-SENT")

        assert result["success"] is True


class TestMessagePreviewFormatting:
    """Tests for message preview formatting."""

    def setup_method(self):
        """Set up test fixtures."""
        self.notifier = SlackNotifier()

    def test_format_sev1_preview(self):
        """Test SEV-1 message preview format."""
        decision = EscalationDecision(
            severity=IncidentSeverity.SEV_1,
            confidence=100,
            should_notify=True,
            affected_services=["service-a", "service-b"],
        )

        preview = self.notifier.format_message_preview(decision)

        assert "🚨" in preview
        assert "SEV-1" in preview or "SEV_1" in preview
        assert "service-a" in preview
        assert "YES" in preview

    def test_format_sev2_preview(self):
        """Test SEV-2 message preview format."""
        decision = EscalationDecision(
            severity=IncidentSeverity.SEV_2,
            confidence=90,
            should_notify=True,
            affected_services=["service-a"],
        )

        preview = self.notifier.format_message_preview(decision)

        assert "⚠️" in preview
        assert "SEV-2" in preview or "SEV_2" in preview

    def test_format_sev3_preview(self):
        """Test SEV-3 message preview format."""
        decision = EscalationDecision(
            severity=IncidentSeverity.SEV_3,
            confidence=75,
            should_notify=True,
            affected_services=["service-a"],
        )

        preview = self.notifier.format_message_preview(decision)

        assert "ℹ️" in preview
        assert "SEV-3" in preview or "SEV_3" in preview

    def test_format_sev4_preview(self):
        """Test SEV-4 message preview format."""
        decision = EscalationDecision(
            severity=IncidentSeverity.SEV_4,
            confidence=50,
            should_notify=False,
            affected_services=[],
        )

        preview = self.notifier.format_message_preview(decision)

        assert "✅" in preview
        assert "SEV-4" in preview or "SEV_4" in preview
        assert "NO" in preview

    def test_format_preview_with_multiple_services(self):
        """Test preview formatting with multiple affected services."""
        decision = EscalationDecision(
            severity=IncidentSeverity.SEV_1,
            confidence=95,
            should_notify=True,
            affected_services=["service-a", "service-b", "service-c", "service-d"],
        )

        preview = self.notifier.format_message_preview(decision)

        # First 3 services should be shown
        assert "service-a" in preview
        assert "service-b" in preview
        assert "service-c" in preview
        # Should indicate "+1 more"
        assert "+1 more" in preview or "+1" in preview

    def test_format_preview_with_skip_notification(self):
        """Test preview when notification skipped."""
        decision = EscalationDecision(
            severity=IncidentSeverity.SEV_4,
            confidence=80,
            should_notify=False,
            affected_services=["service-a"],
        )

        preview = self.notifier.format_message_preview(decision)

        assert "NO" in preview


class TestSendNotificationIntegration:
    """Integration tests for send_notification method."""

    def setup_method(self):
        """Set up test fixtures."""
        self.notifier = SlackNotifier(slack_channel="#test-alerts")

    @pytest.mark.asyncio
    async def test_send_notification_skipped_when_not_required(self):
        """Test notification skipped when should_notify=False."""
        decision = EscalationDecision(
            severity=IncidentSeverity.SEV_4,
            confidence=50,
            should_notify=False,
            affected_services=[],
        )

        client = AsyncMock()
        result = await self.notifier.send_notification(client, decision)

        assert result["success"] is False
        assert "not required" in result["reason"].lower()
        # Client should not be called
        assert not client.query.called

    @pytest.mark.asyncio
    async def test_send_notification_calls_client_query(self):
        """Test send_notification calls client.query."""
        decision = EscalationDecision(
            severity=IncidentSeverity.SEV_1,
            confidence=95,
            should_notify=True,
            affected_services=["service-a"],
            root_cause="Pod crash",
            immediate_actions=["Restart pod"],
            business_impact="Service down",
        )

        client = AsyncMock()
        client.receive_response = AsyncMock(
            return_value="✅ Message successfully delivered to #test-alerts"
        )

        result = await self.notifier.send_notification(client, decision)

        assert client.query.called
        assert client.receive_response.called

    @pytest.mark.asyncio
    async def test_send_notification_returns_success(self):
        """Test send_notification returns successful result."""
        decision = EscalationDecision(
            severity=IncidentSeverity.SEV_2,
            confidence=90,
            should_notify=True,
            affected_services=["mysql"],
            root_cause="High memory",
            immediate_actions=["Scale up"],
            business_impact="Slow queries",
        )

        client = AsyncMock()
        client.receive_response = AsyncMock(
            return_value="✅ Successfully posted to #infrastructure-alerts\nMessage ID: ts-12345"
        )

        result = await self.notifier.send_notification(client, decision)

        assert result["success"] is True
        assert result["incident_id"] is not None
        assert "INC-" in result["incident_id"]

    @pytest.mark.asyncio
    async def test_send_notification_handles_exception(self):
        """Test send_notification handles exceptions gracefully."""
        decision = EscalationDecision(
            severity=IncidentSeverity.SEV_1,
            confidence=100,
            should_notify=True,
            affected_services=["postgres"],
            root_cause="Connection lost",
            immediate_actions=["Restart"],
            business_impact="Data layer down",
        )

        client = AsyncMock()
        client.query = AsyncMock(side_effect=Exception("API Error"))

        result = await self.notifier.send_notification(client, decision)

        assert result["success"] is False
        assert "error" in result
        assert "API Error" in result["error"]

    @pytest.mark.asyncio
    async def test_send_notification_includes_incident_id(self):
        """Test sent notification includes incident ID in response."""
        decision = EscalationDecision(
            severity=IncidentSeverity.SEV_3,
            confidence=75,
            should_notify=True,
            affected_services=["logging"],
            root_cause="Disk low",
            immediate_actions=["Clean up"],
            business_impact="No logs",
        )

        client = AsyncMock()
        client.receive_response = AsyncMock(
            return_value="Message delivered successfully"
        )

        result = await self.notifier.send_notification(client, decision)

        assert "incident_id" in result
        assert result["incident_id"].startswith("INC-")


class TestSlackNotifierLogging:
    """Tests for logging behavior."""

    def setup_method(self):
        """Set up test fixtures."""
        self.notifier = SlackNotifier()

    def test_notifier_has_logger(self):
        """Test notifier is properly configured with logger."""
        assert self.notifier.logger is not None
        assert self.notifier.logger.name == "src.notifications.slack_notifier"

    @pytest.mark.asyncio
    async def test_logging_on_skipped_notification(self):
        """Test logging when notification is skipped."""
        decision = EscalationDecision(
            severity=IncidentSeverity.SEV_4,
            should_notify=False,
            affected_services=[],
        )

        client = AsyncMock()

        with patch.object(self.notifier.logger, "info") as mock_log:
            await self.notifier.send_notification(client, decision)
            assert mock_log.called

    @pytest.mark.asyncio
    async def test_logging_on_notification_sent(self):
        """Test logging when notification is sent."""
        decision = EscalationDecision(
            severity=IncidentSeverity.SEV_1,
            confidence=100,
            should_notify=True,
            affected_services=["service-a"],
            root_cause="Crash",
            immediate_actions=["Restart"],
            business_impact="Down",
        )

        client = AsyncMock()
        client.receive_response = AsyncMock(return_value="✅ Sent")

        with patch.object(self.notifier.logger, "info") as mock_log:
            await self.notifier.send_notification(client, decision)
            assert mock_log.called


class TestSlackNotifierEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def setup_method(self):
        """Set up test fixtures."""
        self.notifier = SlackNotifier()

    def test_format_preview_with_no_services(self):
        """Test preview formatting with no affected services."""
        decision = EscalationDecision(
            severity=IncidentSeverity.SEV_4,
            confidence=50,
            should_notify=False,
            affected_services=[],
        )

        preview = self.notifier.format_message_preview(decision)

        assert preview is not None
        assert isinstance(preview, str)

    def test_format_preview_with_empty_service_names(self):
        """Test preview with only empty strings in service names (edge case)."""
        decision = EscalationDecision(
            severity=IncidentSeverity.SEV_2,
            confidence=80,
            should_notify=True,
            affected_services=[""],
        )

        # Should not crash and produce valid output
        preview = self.notifier.format_message_preview(decision)
        assert preview is not None
        assert "SEV-2" in preview or "SEV_2" in preview

    def test_payload_with_very_long_root_cause(self):
        """Test payload preparation with very long root cause."""
        long_cause = "A" * 1000
        decision = EscalationDecision(
            severity=IncidentSeverity.SEV_1,
            confidence=95,
            should_notify=True,
            affected_services=["service-a"],
            root_cause=long_cause,
            immediate_actions=["Action"],
            business_impact="Impact",
        )

        payload = self.notifier._prepare_notification_payload(decision, "INC-LONG")

        assert payload["root_cause"] == long_cause

    def test_incident_id_generation_rapid_calls(self):
        """Test incident ID generation with rapid successive calls."""
        notifier = SlackNotifier()
        ids = []

        for _ in range(100):
            ids.append(notifier._generate_incident_id())

        # All should be unique
        assert len(set(ids)) == 100

    @pytest.mark.asyncio
    async def test_send_notification_with_enriched_payload(self):
        """Test send_notification handles enriched payload correctly."""
        enriched = {
            "cluster": "dev-eks",
            "namespace": "production",
            "pod_count": 5,
            "memory_usage": "92%",
        }
        decision = EscalationDecision(
            severity=IncidentSeverity.SEV_2,
            confidence=85,
            should_notify=True,
            affected_services=["app"],
            root_cause="OOM",
            immediate_actions=["Scale"],
            business_impact="Slow",
            enriched_payload=enriched,
        )

        client = AsyncMock()
        client.receive_response = AsyncMock(return_value="✅ Sent")

        result = await self.notifier.send_notification(client, decision)

        # Should successfully handle enriched payload
        assert result["success"] is True
