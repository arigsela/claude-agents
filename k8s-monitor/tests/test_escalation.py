"""Tests for escalation management."""

import pytest

from src.escalation import EscalationManager
from src.models import EscalationDecision, Finding, IncidentSeverity, Priority, Severity


class TestEscalationClassification:
    """Tests for severity classification."""

    def setup_method(self):
        """Set up test fixtures."""
        self.manager = EscalationManager()

    def test_classify_p0_down_to_sev1(self):
        """Test P0 service down → SEV-1."""
        findings = [
            Finding(
                severity=Severity.CRITICAL,
                priority=Priority.P0,
                description="2/2 pods in CrashLoopBackOff - all instances down",
                service="chores-tracker-backend",
                namespace="chores-tracker-backend",
            )
        ]

        severity = self.manager.classify_findings(findings)

        assert severity == IncidentSeverity.SEV_1

    def test_classify_mysql_unavailable_to_sev1(self):
        """Test MySQL unavailable → SEV-1 (data layer)."""
        findings = [
            Finding(
                severity=Severity.CRITICAL,
                priority=Priority.P0,
                description="mysql pod unavailable - data layer unreachable",
                service="mysql",
                namespace="mysql",
            )
        ]

        severity = self.manager.classify_findings(findings)

        assert severity == IncidentSeverity.SEV_1

    def test_classify_nginx_ingress_down_to_sev1(self):
        """Test nginx-ingress down → SEV-1 (no external access)."""
        findings = [
            Finding(
                severity=Severity.CRITICAL,
                priority=Priority.P0,
                description="nginx-ingress all pods down",
                service="nginx-ingress",
                namespace="ingress-nginx",
            )
        ]

        severity = self.manager.classify_findings(findings)

        assert severity == IncidentSeverity.SEV_1

    def test_classify_p0_degraded_to_sev2(self):
        """Test P0 service degraded → SEV-2."""
        findings = [
            Finding(
                severity=Severity.HIGH,
                priority=Priority.P0,
                description="1/2 pods running, 1 pending",
                service="chores-tracker-backend",
                namespace="chores-tracker-backend",
            )
        ]

        severity = self.manager.classify_findings(findings)

        assert severity == IncidentSeverity.SEV_2

    def test_classify_p1_issue_to_sev2(self):
        """Test P1 service issue → SEV-2."""
        findings = [
            Finding(
                severity=Severity.HIGH,
                priority=Priority.P1,
                description="vault pod restarted, manual unseal required",
                service="vault",
                namespace="vault",
            )
        ]

        severity = self.manager.classify_findings(findings)

        assert severity == IncidentSeverity.SEV_2

    def test_classify_p2_issue_to_sev3(self):
        """Test P2 service issue → SEV-3."""
        findings = [
            Finding(
                severity=Severity.WARNING,
                priority=Priority.P2,
                description="Support service degraded",
                service="support-service",
                namespace="support",
            )
        ]

        severity = self.manager.classify_findings(findings)

        assert severity == IncidentSeverity.SEV_3

    def test_classify_no_findings_to_sev4(self):
        """Test no findings → SEV-4."""
        findings = []

        severity = self.manager.classify_findings(findings)

        assert severity == IncidentSeverity.SEV_4

    def test_classify_healthy_cluster_to_sev4(self):
        """Test healthy cluster with no findings → SEV-4."""
        # Healthy cluster means no P0/P1 findings, only info messages
        findings = []

        severity = self.manager.classify_findings(findings)

        assert severity == IncidentSeverity.SEV_4


class TestNotificationDecision:
    """Tests for notification decision logic."""

    def setup_method(self):
        """Set up test fixtures."""
        self.manager = EscalationManager()

    def test_sev1_should_notify(self):
        """Test SEV-1 always requires notification."""
        findings = []
        should_notify = self.manager.should_notify(IncidentSeverity.SEV_1, findings)

        assert should_notify is True

    def test_sev2_should_notify(self):
        """Test SEV-2 always requires notification."""
        findings = []
        should_notify = self.manager.should_notify(IncidentSeverity.SEV_2, findings)

        assert should_notify is True

    def test_sev3_should_notify_if_not_known_issue(self):
        """Test SEV-3 notifies unless known issue."""
        findings = [
            Finding(
                severity=Severity.WARNING,
                description="P1 service issue",
                service="unknown-service",
            )
        ]
        should_notify = self.manager.should_notify(IncidentSeverity.SEV_3, findings)

        assert should_notify is True

    def test_sev3_skip_notify_for_vault_unseal(self):
        """Test SEV-3 skips notification for vault manual unseal (known issue)."""
        findings = [
            Finding(
                severity=Severity.WARNING,
                priority=Priority.P1,
                description="vault pod requires manual unsealing",
                service="vault",
            )
        ]
        should_notify = self.manager.should_notify(IncidentSeverity.SEV_3, findings)

        assert should_notify is False

    def test_sev3_skip_notify_for_slow_startup(self):
        """Test SEV-3 skips notification for chores-tracker slow startup."""
        findings = [
            Finding(
                severity=Severity.WARNING,
                priority=Priority.P0,
                description="chores-tracker-backend slow startup (5-6 minutes)",
                service="chores-tracker-backend",
            )
        ]
        should_notify = self.manager.should_notify(IncidentSeverity.SEV_3, findings)

        assert should_notify is False

    def test_sev4_never_notify(self):
        """Test SEV-4 never requires notification."""
        findings = []
        should_notify = self.manager.should_notify(IncidentSeverity.SEV_4, findings)

        assert should_notify is False


class TestNotificationChannel:
    """Tests for notification channel selection."""

    def setup_method(self):
        """Set up test fixtures."""
        self.manager = EscalationManager()

    def test_sev1_critical_alerts_channel(self):
        """Test SEV-1 sends to #critical-alerts."""
        channel = self.manager.get_notification_channel(IncidentSeverity.SEV_1)

        assert channel == "#critical-alerts"

    def test_sev2_infrastructure_alerts_channel(self):
        """Test SEV-2 sends to #infrastructure-alerts."""
        channel = self.manager.get_notification_channel(IncidentSeverity.SEV_2)

        assert channel == "#infrastructure-alerts"

    def test_sev3_infrastructure_alerts_channel(self):
        """Test SEV-3 sends to #infrastructure-alerts."""
        channel = self.manager.get_notification_channel(IncidentSeverity.SEV_3)

        assert channel == "#infrastructure-alerts"

    def test_sev4_no_channel(self):
        """Test SEV-4 has no notification channel."""
        channel = self.manager.get_notification_channel(IncidentSeverity.SEV_4)

        assert channel is None


class TestEscalationParsing:
    """Tests for parsing escalation-manager responses."""

    def setup_method(self):
        """Set up test fixtures."""
        self.manager = EscalationManager()

    def test_parse_sev1_critical(self):
        """Test parsing SEV-1 critical response."""
        response = """
## Incident Escalation Decision

**Severity Level**: SEV-1 (CRITICAL)
**Confidence**: HIGH (95%)
**NOTIFY**: ✅ YES - IMMEDIATE

**Affected Services**:
- **chores-tracker-backend** (P0 - Business Critical)
  - Status: UNAVAILABLE

**Immediate Actions**:
1. Rollback deployment abc123def
2. Verify pod restart
3. Monitor for 5-6 minutes
"""
        decision = self.manager.parse_escalation_response(response)

        assert decision.severity == IncidentSeverity.SEV_1
        assert decision.should_notify is True
        assert decision.confidence == 95
        assert "chores-tracker-backend" in decision.affected_services

    def test_parse_sev4_known_issue(self):
        """Test parsing SEV-4 known issue response."""
        response = """
## Incident Escalation Decision

**Severity Level**: SEV-4 (INFORMATIONAL)
**NOTIFY**: ❌ NO

**Reason**: vault pod restart requiring manual unseal is EXPECTED behavior.
"""
        decision = self.manager.parse_escalation_response(response)

        assert decision.severity == IncidentSeverity.SEV_4
        assert decision.should_notify is False

    def test_parse_with_json_payload(self):
        """Test parsing response with enriched JSON payload."""
        response = '''
## Incident Escalation Decision

**Severity Level**: SEV-2 (HIGH)
**NOTIFY**: ✅ YES

**Affected Services**:
- **mysql** (P0 - Business Critical)

**Enriched Payload**:
```json
{
  "severity": "SEV-2",
  "title": "Database High Memory Usage",
  "affected_services": ["mysql"],
  "immediate_actions": ["Scale up memory limits"]
}
```
'''
        decision = self.manager.parse_escalation_response(response)

        assert decision.severity == IncidentSeverity.SEV_2
        assert decision.enriched_payload is not None
        assert decision.enriched_payload["severity"] == "SEV-2"

    def test_parse_with_immediate_actions(self):
        """Test extracting immediate actions from response."""
        response = """
**Immediate Actions**:
1. Increase memory limits to 512Mi
2. Restart the pod
3. Monitor logs for OOMKilled events
"""
        decision = self.manager.parse_escalation_response(response)

        assert len(decision.immediate_actions) > 0
        assert any("memory" in action.lower() for action in decision.immediate_actions)

    def test_parse_default_confidence(self):
        """Test parsing without explicit confidence defaults to 100%."""
        response = """
## Incident Escalation Decision

**Severity Level**: SEV-2
**NOTIFY**: ✅ YES
"""
        decision = self.manager.parse_escalation_response(response)

        assert decision.confidence == 100


class TestServiceCriticality:
    """Tests for service criticality checking."""

    def setup_method(self):
        """Set up test fixtures."""
        self.manager = EscalationManager()

    def test_p0_services(self):
        """Test P0 service recognition."""
        assert self.manager._is_p0_service("chores-tracker-backend") is True
        assert self.manager._is_p0_service("mysql") is True
        assert self.manager._is_p0_service("nginx-ingress") is True

    def test_p1_services(self):
        """Test P1 service recognition."""
        assert self.manager._is_p1_service("vault") is True
        assert self.manager._is_p1_service("cert-manager") is True
        assert self.manager._is_p1_service("external-secrets-operator") is True

    def test_unknown_service(self):
        """Test unknown service is neither P0 nor P1."""
        assert self.manager._is_p0_service("unknown-service") is False
        assert self.manager._is_p1_service("unknown-service") is False

    def test_none_service(self):
        """Test None service returns False."""
        assert self.manager._is_p0_service(None) is False
        assert self.manager._is_p1_service(None) is False


class TestKnownIssues:
    """Tests for known issue detection."""

    def setup_method(self):
        """Set up test fixtures."""
        self.manager = EscalationManager()

    def test_vault_unsealing_is_known_issue(self):
        """Test vault manual unseal is recognized as known issue."""
        finding = Finding(
            severity=Severity.WARNING,
            description="vault pod requires manual unsealing",
            service="vault",
        )
        assert self.manager._is_known_issue(finding) is True

    def test_chores_slow_startup_is_known_issue(self):
        """Test chores-tracker slow startup is recognized as known issue."""
        finding = Finding(
            severity=Severity.WARNING,
            description="chores-tracker-backend slow startup (5-6 minutes)",
            service="chores-tracker-backend",
        )
        assert self.manager._is_known_issue(finding) is True

    def test_actual_issue_not_known(self):
        """Test actual issue is not marked as known."""
        finding = Finding(
            severity=Severity.CRITICAL,
            description="chores-tracker-backend CrashLoopBackOff",
            service="chores-tracker-backend",
        )
        assert self.manager._is_known_issue(finding) is False

    def test_none_service_not_known_issue(self):
        """Test None service cannot be known issue."""
        finding = Finding(
            severity=Severity.WARNING,
            description="some issue",
            service=None,
        )
        assert self.manager._is_known_issue(finding) is False


class TestEscalationDecision:
    """Tests for EscalationDecision model."""

    def test_create_escalation_decision(self):
        """Test creating escalation decision."""
        decision = EscalationDecision(
            severity=IncidentSeverity.SEV_1,
            confidence=95,
            should_notify=True,
            affected_services=["chores-tracker-backend"],
            immediate_actions=[
                "Rollback deployment",
                "Monitor pod restart",
            ],
        )

        assert decision.severity == IncidentSeverity.SEV_1
        assert decision.confidence == 95
        assert decision.should_notify is True
        assert len(decision.affected_services) == 1

    def test_escalation_decision_string_representation(self):
        """Test string representation of decision."""
        decision = EscalationDecision(
            severity=IncidentSeverity.SEV_2,
            should_notify=True,
            confidence=90,
        )

        result = str(decision)

        assert "SEV-2" in result
        assert "NOTIFY" in result
        assert "90%" in result
