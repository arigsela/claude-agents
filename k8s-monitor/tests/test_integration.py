"""End-to-end integration tests for monitoring pipeline."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path
from datetime import datetime

from src.orchestrator import Monitor
from src.config import Settings
from src.models import EscalationDecision, Finding, IncidentSeverity, Severity, Priority


class TestMonitorIntegration:
    """Integration tests for Monitor orchestrator."""

    def setup_method(self):
        """Set up test fixtures."""
        # Create minimal settings for testing
        self.settings = MagicMock(spec=Settings)
        self.settings.slack_channel = "#test-alerts"
        self.settings.log_level = "INFO"
        self.settings.orchestrator_model = "claude-haiku-4-5-20251001"
        self.settings.github_mcp_path = "/path/to/github"
        self.settings.slack_mcp_path = "/path/to/slack"
        self.settings.github_token = "test-token"
        self.settings.slack_bot_token = "test-bot-token"

    def _mock_client(self):
        """Create a mock client for testing."""
        return AsyncMock()

    def test_monitor_initialization(self):
        """Test monitor initializes with proper state."""
        monitor = Monitor(self.settings)

        assert monitor.cycle_count == 0
        assert monitor.failed_cycles == 0
        assert monitor.last_successful_cycle is None
        assert monitor.last_cycle_status is None

    def test_monitor_status_summary(self):
        """Test status summary generation."""
        monitor = Monitor(self.settings)
        summary = monitor.get_status_summary()

        assert summary["cycle_count"] == 0
        assert summary["failed_cycles"] == 0
        assert summary["last_successful_cycle"] is None
        assert summary["last_cycle_status"] is None
        assert summary["health"] == "healthy"

    @pytest.mark.asyncio
    async def test_healthy_cluster_workflow(self):
        """Test workflow when cluster is healthy (no findings)."""
        monitor = Monitor(self.settings)

        with patch.object(monitor, "initialize_client", new_callable=AsyncMock):
            with patch.object(monitor, "_analyze_cluster", return_value=[]):
                results = await monitor.run_monitoring_cycle()

        assert results["status"] == "healthy"
        assert results["findings"] == []
        assert results["escalation_decision"] is None
        assert results["notifications_sent"] == 0
        assert results["failed_cycles"] == 0
        assert monitor.cycle_count == 1
        assert monitor.failed_cycles == 0

    @pytest.mark.asyncio
    async def test_sev1_incident_workflow(self):
        """Test workflow for SEV-1 incident (P0 down)."""
        monitor = Monitor(self.settings)

        # Mock findings: P0 service down
        finding = Finding(
            severity=Severity.CRITICAL,
            priority=Priority.P0,
            description="2/2 pods in CrashLoopBackOff",
            service="chores-tracker-backend",
            namespace="chores-tracker-backend",
        )

        # Mock escalation decision
        escalation_decision = EscalationDecision(
            severity=IncidentSeverity.SEV_1,
            confidence=95,
            should_notify=True,
            affected_services=["chores-tracker-backend"],
            root_cause="Pod crash",
            immediate_actions=["Restart pod"],
            business_impact="Service down",
            notification_channel="#critical-alerts",
        )

        notification_result = {
            "success": True,
            "incident_id": "INC-20251020-001",
            "message_id": "ts-12345",
        }

        with patch.object(monitor, "initialize_client", new_callable=AsyncMock):
            with patch.object(monitor, "_analyze_cluster", return_value=[finding]):
                with patch.object(monitor, "_assess_escalation", return_value="SEV-1 response"):
                    with patch.object(
                        monitor.escalation_manager,
                        "parse_escalation_response",
                        return_value=escalation_decision,
                    ):
                        with patch.object(
                            monitor, "_send_notification", return_value=notification_result
                        ):
                            results = await monitor.run_monitoring_cycle()

        assert results["status"] == "completed"
        assert len(results["findings"]) == 1
        assert results["notifications_sent"] == 1
        assert results["failed_cycles"] == 0
        assert monitor.failed_cycles == 0

    @pytest.mark.asyncio
    async def test_sev3_known_issue_workflow(self):
        """Test workflow for SEV-3 known issue (no notification)."""
        monitor = Monitor(self.settings)

        # Mock findings: vault unsealing
        finding = Finding(
            severity=Severity.WARNING,
            priority=Priority.P1,
            description="vault pod requires manual unsealing",
            service="vault",
            namespace="vault",
        )

        # Mock escalation decision: SEV-3, no notification needed
        escalation_decision = EscalationDecision(
            severity=IncidentSeverity.SEV_3,
            confidence=80,
            should_notify=False,
            affected_services=["vault"],
            root_cause="Known issue: vault unsealing",
            immediate_actions=["Manual unseal"],
            business_impact="None - expected",
        )

        with patch.object(monitor, "initialize_client", new_callable=AsyncMock):
            with patch.object(monitor, "_analyze_cluster", return_value=[finding]):
                with patch.object(monitor, "_assess_escalation", return_value="SEV-3 response"):
                    with patch.object(
                        monitor.escalation_manager,
                        "parse_escalation_response",
                        return_value=escalation_decision,
                    ):
                        results = await monitor.run_monitoring_cycle()

        assert results["status"] == "completed"
        assert len(results["findings"]) == 1
        assert results["notifications_sent"] == 0
        assert results["failed_cycles"] == 0

    @pytest.mark.asyncio
    async def test_k8s_analyzer_failure_fallback(self):
        """Test fallback behavior when k8s-analyzer fails."""
        monitor = Monitor(self.settings)

        with patch.object(monitor, "initialize_client", new_callable=AsyncMock):
            with patch.object(
                monitor, "_analyze_cluster", side_effect=Exception("API Error")
            ):
                results = await monitor.run_monitoring_cycle()

        assert results["status"] == "failed"
        assert results["phase"] == "k8s-analyzer"
        assert results["error"] == "API Error"
        assert results["findings"] == []
        assert monitor.failed_cycles == 1

    @pytest.mark.asyncio
    async def test_escalation_manager_failure_fallback(self):
        """Test fallback behavior when escalation-manager fails."""
        monitor = Monitor(self.settings)

        finding = Finding(
            severity=Severity.HIGH,
            priority=Priority.P0,
            description="Pod degraded",
            service="service-a",
        )

        with patch.object(monitor, "initialize_client", new_callable=AsyncMock):
            with patch.object(monitor, "_analyze_cluster", return_value=[finding]):
                with patch.object(
                    monitor, "_assess_escalation", side_effect=Exception("Timeout")
                ):
                    results = await monitor.run_monitoring_cycle()

        assert results["status"] == "completed"
        assert len(results["findings"]) == 1
        # Should use conservative fallback
        assert results["escalation_decision"]["should_notify"] is True
        assert results["escalation_decision"]["confidence"] == 50
        assert "conservative" in results["escalation_decision"]["root_cause"].lower()

    @pytest.mark.asyncio
    async def test_slack_notifier_failure_backup(self):
        """Test backup behavior when Slack notification fails."""
        monitor = Monitor(self.settings)

        finding = Finding(
            severity=Severity.CRITICAL,
            priority=Priority.P0,
            description="Service down",
            service="service-a",
        )

        escalation_decision = EscalationDecision(
            severity=IncidentSeverity.SEV_1,
            confidence=95,
            should_notify=True,
            affected_services=["service-a"],
            root_cause="Down",
            immediate_actions=["Fix"],
            business_impact="Down",
        )

        with patch.object(monitor, "initialize_client", new_callable=AsyncMock):
            with patch.object(monitor, "_analyze_cluster", return_value=[finding]):
                with patch.object(monitor, "_assess_escalation", return_value="response"):
                    with patch.object(
                        monitor.escalation_manager,
                        "parse_escalation_response",
                        return_value=escalation_decision,
                    ):
                        with patch.object(
                            monitor, "_send_notification", side_effect=Exception("Slack Error")
                        ):
                            with patch.object(monitor, "_backup_notification") as mock_backup:
                                results = await monitor.run_monitoring_cycle()

        assert results["status"] == "completed"
        assert results["notification_result"]["success"] is False
        assert results["notification_result"]["backed_up"] is True
        assert mock_backup.called

    @pytest.mark.asyncio
    async def test_cycle_counter_increments(self):
        """Test cycle counter increments on each run."""
        monitor = Monitor(self.settings)

        with patch.object(monitor, "initialize_client", new_callable=AsyncMock):
            with patch.object(monitor, "_analyze_cluster", return_value=[]):
                for i in range(5):
                    await monitor.run_monitoring_cycle()
                    assert monitor.cycle_count == i + 1

    @pytest.mark.asyncio
    async def test_failed_cycles_tracking(self):
        """Test failed cycles are tracked."""
        monitor = Monitor(self.settings)

        # Simulate 3 failures
        with patch.object(monitor, "initialize_client", new_callable=AsyncMock):
            mock_analyze = AsyncMock(side_effect=Exception("Error"))
            with patch.object(monitor, "_analyze_cluster", mock_analyze):
                for _ in range(3):
                    await monitor.run_monitoring_cycle()

        assert monitor.failed_cycles == 3

    @pytest.mark.asyncio
    async def test_multiple_findings_aggregation(self):
        """Test multiple findings are properly aggregated."""
        monitor = Monitor(self.settings)

        findings = [
            Finding(
                severity=Severity.CRITICAL,
                priority=Priority.P0,
                description="Pod down",
                service="service-a",
            ),
            Finding(
                severity=Severity.HIGH,
                priority=Priority.P1,
                description="Memory high",
                service="service-b",
            ),
            Finding(
                severity=Severity.WARNING,
                priority=Priority.P2,
                description="Disk warning",
                service="service-c",
            ),
        ]

        escalation_decision = EscalationDecision(
            severity=IncidentSeverity.SEV_1,
            confidence=90,
            should_notify=True,
            affected_services=["service-a", "service-b", "service-c"],
            root_cause="Multiple issues",
            immediate_actions=["Investigate"],
            business_impact="Degraded",
        )

        with patch.object(monitor, "initialize_client", new_callable=AsyncMock):
            with patch.object(monitor, "_analyze_cluster", return_value=findings):
                with patch.object(monitor, "_assess_escalation", return_value="response"):
                    with patch.object(
                        monitor.escalation_manager,
                        "parse_escalation_response",
                        return_value=escalation_decision,
                    ):
                        with patch.object(monitor, "_send_notification", return_value={"success": True}):
                            results = await monitor.run_monitoring_cycle()

        assert len(results["findings"]) == 3
        assert len(results["escalation_decision"]["affected_services"]) == 3


class TestMonitorErrorRecovery:
    """Tests for monitor error recovery and resilience."""

    def setup_method(self):
        """Set up test fixtures."""
        self.settings = MagicMock(spec=Settings)
        self.settings.slack_channel = "#test"
        self.settings.log_level = "INFO"
        self.settings.orchestrator_model = "claude-haiku-4-5-20251001"
        self.settings.github_mcp_path = "/path"
        self.settings.slack_mcp_path = "/path"
        self.settings.github_token = "token"
        self.settings.slack_bot_token = "token"

    @pytest.mark.asyncio
    async def test_graceful_degradation_on_slack_failure(self):
        """Test system continues when Slack is unavailable."""
        monitor = Monitor(self.settings)

        finding = Finding(
            severity=Severity.CRITICAL,
            priority=Priority.P0,
            description="Critical",
            service="critical-service",
        )

        decision = EscalationDecision(
            severity=IncidentSeverity.SEV_1,
            confidence=100,
            should_notify=True,
            affected_services=["critical-service"],
            root_cause="Critical",
            immediate_actions=["Fix"],
            business_impact="Down",
        )

        with patch.object(monitor, "initialize_client", new_callable=AsyncMock):
            with patch.object(monitor, "_analyze_cluster", return_value=[finding]):
                with patch.object(monitor, "_assess_escalation", return_value="response"):
                    with patch.object(
                        monitor.escalation_manager,
                        "parse_escalation_response",
                        return_value=decision,
                    ):
                        with patch.object(
                            monitor, "_send_notification", side_effect=Exception("Slack unreachable")
                        ):
                            with patch.object(monitor, "_backup_notification"):
                                results = await monitor.run_monitoring_cycle()

        # Should complete despite Slack failure
        assert results["status"] == "completed"
        assert results["notification_result"]["success"] is False

    @pytest.mark.asyncio
    async def test_conservative_escalation_on_manager_failure(self):
        """Test uses conservative escalation when manager fails."""
        monitor = Monitor(self.settings)

        findings = [
            Finding(
                severity=Severity.CRITICAL,
                priority=Priority.P0,
                description="Unknown issue",
                service="unknown-service",
            )
        ]

        with patch.object(monitor, "initialize_client", new_callable=AsyncMock):
            with patch.object(monitor, "_analyze_cluster", return_value=findings):
                with patch.object(
                    monitor, "_assess_escalation", side_effect=Exception("Manager crashed")
                ):
                    results = await monitor.run_monitoring_cycle()

        decision = results["escalation_decision"]
        # Conservative: SEV-2, notify, unknown services
        assert decision["should_notify"] is True
        assert decision["confidence"] == 50
        assert "unknown-service" in decision["affected_services"]

    def test_backup_notification_creates_directory(self):
        """Test backup notification creates incidents directory."""
        monitor = Monitor(self.settings)

        decision = EscalationDecision(
            severity=IncidentSeverity.SEV_1,
            confidence=95,
            should_notify=True,
            affected_services=["service"],
            root_cause="Issue",
            immediate_actions=["Fix"],
            business_impact="Down",
        )

        with patch("pathlib.Path.mkdir"):
            with patch("builtins.open", create=True):
                monitor._backup_notification(decision)

    def test_status_summary_health_degraded(self):
        """Test health status degrades after 3 failures."""
        monitor = Monitor(self.settings)
        monitor.failed_cycles = 3

        summary = monitor.get_status_summary()

        assert summary["health"] == "degraded"

    def test_status_summary_health_healthy(self):
        """Test health status is healthy with < 3 failures."""
        monitor = Monitor(self.settings)
        monitor.failed_cycles = 2

        summary = monitor.get_status_summary()

        assert summary["health"] == "healthy"


class TestMonitorCycleReporting:
    """Tests for cycle reporting and state management."""

    def setup_method(self):
        """Set up test fixtures."""
        self.settings = MagicMock(spec=Settings)
        self.settings.slack_channel = "#test"
        self.settings.log_level = "INFO"
        self.settings.orchestrator_model = "claude-haiku-4-5-20251001"
        self.settings.github_mcp_path = "/path"
        self.settings.slack_mcp_path = "/path"
        self.settings.github_token = "token"
        self.settings.slack_bot_token = "token"

    @pytest.mark.asyncio
    async def test_cycle_report_includes_timing(self):
        """Test cycle report includes duration for findings."""
        monitor = Monitor(self.settings)

        # Create a finding to get into the main cycle
        finding = Finding(
            severity=Severity.CRITICAL,
            priority=Priority.P0,
            description="Test",
            service="test",
        )

        decision = EscalationDecision(
            severity=IncidentSeverity.SEV_1,
            confidence=95,
            should_notify=False,
            affected_services=["test"],
            root_cause="Test",
            immediate_actions=["Test"],
            business_impact="Test",
        )

        with patch.object(monitor, "initialize_client", new_callable=AsyncMock):
            with patch.object(monitor, "_analyze_cluster", return_value=[finding]):
                with patch.object(monitor, "_assess_escalation", return_value="response"):
                    with patch.object(
                        monitor.escalation_manager,
                        "parse_escalation_response",
                        return_value=decision,
                    ):
                        results = await monitor.run_monitoring_cycle()

        assert "cycle_duration_seconds" in results
        assert results["cycle_duration_seconds"] >= 0

    @pytest.mark.asyncio
    async def test_cycle_report_includes_cycle_number(self):
        """Test cycle report includes cycle counter."""
        monitor = Monitor(self.settings)

        with patch.object(monitor, "_analyze_cluster", return_value=[]):
            results = await monitor.run_monitoring_cycle()

        assert "cycle_number" in results
        assert results["cycle_number"] == 1

    def test_save_cycle_report(self, tmp_path):
        """Test cycle report is saved to file."""
        monitor = Monitor(self.settings)

        results = {
            "cycle_id": "test_cycle",
            "status": "completed",
            "findings": [],
        }

        report_path = monitor.save_cycle_report(results, tmp_path)

        assert report_path.exists()
        assert report_path.suffix == ".json"

    def test_get_status_summary_complete(self):
        """Test status summary contains all fields."""
        monitor = Monitor(self.settings)
        monitor.cycle_count = 10
        monitor.failed_cycles = 2
        monitor.last_cycle_status = "completed"

        summary = monitor.get_status_summary()

        assert "cycle_count" in summary
        assert "failed_cycles" in summary
        assert "last_successful_cycle" in summary
        assert "last_cycle_status" in summary
        assert "health" in summary
