"""Tests for data models."""

from src.models import Finding, Priority, Severity


class TestFinding:
    """Tests for Finding model."""

    def test_create_finding(self):
        """Test creating a Finding instance."""
        finding = Finding(
            severity=Severity.CRITICAL,
            priority=Priority.P0,
            description="Pod in CrashLoopBackOff",
            service="chores-tracker-backend",
            namespace="chores-tracker-backend",
            pod="chores-tracker-backend-7d8f9c5b4-x7k2p",
            recommendation="Check pod logs for OOMKilled errors",
        )

        assert finding.severity == Severity.CRITICAL
        assert finding.priority == Priority.P0
        assert finding.service == "chores-tracker-backend"
        assert finding.namespace == "chores-tracker-backend"

    def test_finding_string_representation(self):
        """Test Finding string representation."""
        finding = Finding(
            severity=Severity.HIGH,
            priority=Priority.P1,
            description="High memory usage detected",
            namespace="mysql",
            pod="mysql-9b7c3a2d1-l2m3n",
        )

        result = str(finding)

        assert "HIGH" in result
        assert "High memory usage" in result
        assert "mysql-9b7c3a2d1-l2m3n" in result

    def test_finding_minimal(self):
        """Test Finding with minimal required fields."""
        finding = Finding(
            severity=Severity.WARNING,
            description="Informational issue detected",
        )

        assert finding.severity == Severity.WARNING
        assert finding.priority is None
        assert finding.service is None
        assert finding.namespace is None

    def test_severity_enum_values(self):
        """Test Severity enum values."""
        assert Severity.CRITICAL.value == "critical"
        assert Severity.HIGH.value == "high"
        assert Severity.WARNING.value == "warning"
        assert Severity.INFO.value == "info"

    def test_priority_enum_values(self):
        """Test Priority enum values."""
        assert Priority.P0.value == "P0"
        assert Priority.P1.value == "P1"
        assert Priority.P2.value == "P2"
        assert Priority.P3.value == "P3"

    def test_finding_with_raw_output(self):
        """Test Finding with raw kubectl output."""
        kubectl_output = "NAME                    READY   STATUS             RESTARTS\nchores-tracker-backend-7d8f9c5b4-x7k2p   0/1     CrashLoopBackOff   5"

        finding = Finding(
            severity=Severity.CRITICAL,
            description="Pod in CrashLoopBackOff",
            raw_output=kubectl_output,
        )

        assert finding.raw_output is not None
        assert "CrashLoopBackOff" in finding.raw_output

    def test_finding_model_config(self):
        """Test Finding model configuration."""
        finding = Finding(
            severity=Severity.CRITICAL,
            priority=Priority.P0,
            description="Test issue",
        )

        # Test that enum values are used in output
        finding_dict = finding.model_dump()
        assert finding_dict["severity"] == "critical"
        assert finding_dict["priority"] == "P0"
