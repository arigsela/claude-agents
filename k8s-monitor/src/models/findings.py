"""Data models for cluster findings and escalation decisions."""

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class Severity(str, Enum):
    """Severity levels for issues."""

    CRITICAL = "critical"
    HIGH = "high"
    WARNING = "warning"
    INFO = "info"


class Priority(str, Enum):
    """Priority tiers from services.txt."""

    P0 = "P0"  # Critical production service
    P1 = "P1"  # Important service
    P2 = "P2"  # Secondary service
    P3 = "P3"  # Nice-to-have service


class Finding(BaseModel):
    """A single finding from cluster analysis."""

    severity: Severity = Field(..., description="Severity level")
    priority: Optional[Priority] = Field(
        default=None, description="Priority tier (P0-P3)"
    )
    description: str = Field(..., description="Human-readable issue description")
    service: Optional[str] = Field(default=None, description="Affected service name")
    namespace: Optional[str] = Field(default=None, description="Affected namespace")
    pod: Optional[str] = Field(default=None, description="Affected pod name")
    recommendation: Optional[str] = Field(
        default=None, description="Recommended remediation action"
    )
    raw_output: Optional[str] = Field(
        default=None, description="Raw output from kubectl/logs"
    )

    model_config = ConfigDict(use_enum_values=True)

    def __str__(self) -> str:
        """String representation of finding."""
        location = f"{self.namespace}/{self.pod}" if self.pod else (
            self.namespace or self.service or "unknown"
        )
        return f"[{self.severity.upper()}] {self.description} ({location})"


class IncidentSeverity(str, Enum):
    """Incident severity levels for escalation."""

    SEV_1 = "SEV-1"  # CRITICAL - Immediate notification
    SEV_2 = "SEV-2"  # HIGH - Immediate notification
    SEV_3 = "SEV-3"  # MEDIUM - Business hours notification
    SEV_4 = "SEV-4"  # LOW - Log only, no notification


class EscalationDecision(BaseModel):
    """Escalation decision from escalation-manager subagent."""

    severity: IncidentSeverity = Field(..., description="Incident severity level")
    confidence: int = Field(
        default=100, description="Confidence percentage (0-100)", ge=0, le=100
    )
    should_notify: bool = Field(..., description="Whether notification is required")
    affected_services: List[str] = Field(
        default_factory=list, description="List of affected service names"
    )
    root_cause: Optional[str] = Field(
        default=None, description="Root cause analysis summary"
    )
    immediate_actions: List[str] = Field(
        default_factory=list, description="Immediate remediation steps"
    )
    business_impact: Optional[str] = Field(
        default=None, description="Business impact assessment"
    )
    notification_channel: Optional[str] = Field(
        default=None, description="Target Slack channel for notification"
    )
    enriched_payload: Optional[Dict[str, Any]] = Field(
        default=None, description="Enriched JSON payload for slack-notifier"
    )

    model_config = ConfigDict(use_enum_values=True)

    def __str__(self) -> str:
        """String representation of decision."""
        notify_status = "NOTIFY" if self.should_notify else "NO NOTIFICATION"
        return f"[{self.severity}] {notify_status} (confidence: {self.confidence}%)"
