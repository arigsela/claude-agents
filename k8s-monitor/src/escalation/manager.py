"""Escalation manager for determining incident severity and notification requirements."""

import json
import logging
import re
from typing import Any, Dict, List, Optional

from src.models import EscalationDecision, Finding, IncidentSeverity


class EscalationManager:
    """Manages incident escalation and severity classification."""

    def __init__(self):
        """Initialize escalation manager."""
        self.logger = logging.getLogger(__name__)

        # Service criticality mapping (from services.txt context)
        self.p0_services = {
            "chores-tracker-backend",
            "chores-tracker-frontend",
            "mysql",
            "n8n",
            "postgresql",
            "nginx-ingress",
            "oncall-agent",
        }

        self.p1_services = {
            "vault",
            "external-secrets-operator",
            "cert-manager",
            "ecr-credentials-sync",
            "crossplane",
        }

        # Known issues that shouldn't trigger escalation
        self.known_issues = {
            "vault": ["unsealing required", "manual unseal", "pod restart"],
            "chores-tracker-backend": ["slow startup", "5-6 minutes"],
        }

        # Max downtime tolerances (in minutes)
        self.max_downtime = {
            "P0": 0,  # 0 minutes - immediate escalation
            "P1": 5,  # 5-15 minutes, normalize to 5
            "P2": 60,  # 1 hour
            "P3": float("inf"),  # No limit
        }

    def classify_findings(self, findings: List[Finding]) -> IncidentSeverity:
        """Classify overall incident severity from findings.

        Args:
            findings: List of findings from k8s-analyzer

        Returns:
            Overall incident severity level
        """
        if not findings:
            return IncidentSeverity.SEV_4

        # Check for P0 critical issues
        p0_findings = [f for f in findings if self._is_p0_service(f.service)]
        p1_findings = [f for f in findings if self._is_p1_service(f.service)]

        # SEV-1: P0 service completely unavailable
        if any(
            "CrashLoopBackOff" in (f.description or "")
            and "all" in (f.description or "").lower()
            for f in p0_findings
        ):
            return IncidentSeverity.SEV_1

        # SEV-1: Data layer unavailable
        if any(
            f.service in ["mysql", "postgresql"]
            and "unavailable" in (f.description or "").lower()
            for f in p0_findings
        ):
            return IncidentSeverity.SEV_1

        # SEV-1: Ingress down
        if any(
            f.service == "nginx-ingress"
            and "down" in (f.description or "").lower()
            for f in p0_findings
        ):
            return IncidentSeverity.SEV_1

        # SEV-2: P1 service unavailable or P0 degraded
        if p1_findings or (p0_findings and len(p0_findings) < 3):
            return IncidentSeverity.SEV_2

        # SEV-3: P2 issues or P0/P1 warnings
        p2_findings = [
            f
            for f in findings
            if not self._is_p0_service(f.service)
            and not self._is_p1_service(f.service)
        ]
        if p2_findings or any("warning" in (f.description or "").lower() for f in findings):
            return IncidentSeverity.SEV_3

        # SEV-4: No critical issues
        return IncidentSeverity.SEV_4

    def should_notify(
        self, severity: IncidentSeverity, findings: List[Finding]
    ) -> bool:
        """Determine if notification should be sent.

        Args:
            severity: Classified incident severity
            findings: List of findings for context

        Returns:
            True if notification required, False otherwise
        """
        # SEV-1 and SEV-2 always require notification
        if severity in [IncidentSeverity.SEV_1, IncidentSeverity.SEV_2]:
            return True

        # SEV-3: Notify only if not a known issue
        if severity == IncidentSeverity.SEV_3:
            for finding in findings:
                if self._is_known_issue(finding):
                    return False
            return True

        # SEV-4: Never notify
        return False

    def get_notification_channel(self, severity: IncidentSeverity) -> Optional[str]:
        """Get target Slack channel for severity level.

        Args:
            severity: Incident severity

        Returns:
            Slack channel name or ID
        """
        channel_map = {
            IncidentSeverity.SEV_1: "#critical-alerts",
            IncidentSeverity.SEV_2: "#infrastructure-alerts",
            IncidentSeverity.SEV_3: "#infrastructure-alerts",
            IncidentSeverity.SEV_4: None,
        }
        return channel_map.get(severity)

    def parse_escalation_response(self, response: str) -> EscalationDecision:
        """Parse escalation-manager subagent response.

        Args:
            response: Raw markdown response from escalation-manager

        Returns:
            Parsed escalation decision
        """
        self.logger.debug(f"Parsing escalation response: {response[:200]}...")

        # Extract severity from response
        severity = self._extract_severity(response)

        # Extract notification decision
        should_notify = self._extract_notification_decision(response)

        # Extract affected services
        affected_services = self._extract_affected_services(response)

        # Extract JSON payload if present
        enriched_payload = self._extract_json_payload(response)

        # Extract immediate actions
        immediate_actions = self._extract_actions(response)

        # Extract root cause
        root_cause = self._extract_section(response, "Root Cause Analysis")

        # Extract business impact
        business_impact = self._extract_section(response, "Business Impact Statement")

        # Determine confidence
        confidence = self._extract_confidence(response)

        # Create decision object
        decision = EscalationDecision(
            severity=severity,
            confidence=confidence,
            should_notify=should_notify,
            affected_services=affected_services,
            root_cause=root_cause,
            immediate_actions=immediate_actions,
            business_impact=business_impact,
            notification_channel=self.get_notification_channel(severity),
            enriched_payload=enriched_payload,
        )

        self.logger.info(f"Escalation decision: {decision}")
        return decision

    # Private helper methods

    def _is_p0_service(self, service: Optional[str]) -> bool:
        """Check if service is P0 criticality."""
        if not service:
            return False
        return service.lower() in {s.lower() for s in self.p0_services}

    def _is_p1_service(self, service: Optional[str]) -> bool:
        """Check if service is P1 criticality."""
        if not service:
            return False
        return service.lower() in {s.lower() for s in self.p1_services}

    def _is_known_issue(self, finding: Finding) -> bool:
        """Check if finding matches a known issue."""
        if not finding.service:
            return False

        service_lower = finding.service.lower()
        description_lower = (finding.description or "").lower()

        # Check against known issues map
        if service_lower in self.known_issues:
            for keyword in self.known_issues[service_lower]:
                if keyword.lower() in description_lower:
                    return True

        return False

    def _extract_severity(self, response: str) -> IncidentSeverity:
        """Extract severity level from response."""
        # Look for SEV-1, SEV-2, etc.
        match = re.search(r"SEV[_-]([1-4])", response, re.IGNORECASE)
        if match:
            sev_num = match.group(1)
            return IncidentSeverity[f"SEV_{sev_num}"]

        # Default to SEV-4 if not found
        return IncidentSeverity.SEV_4

    def _extract_notification_decision(self, response: str) -> bool:
        """Extract YES/NO notification decision."""
        # Look for "NOTIFY: YES" or "NOTIFY: ✅ YES"
        if re.search(r"NOTIFY[:\s]+✅?\s*YES", response, re.IGNORECASE):
            return True
        if re.search(r"NOTIFY[:\s]+❌?\s*NO", response, re.IGNORECASE):
            return False

        # Default: if SEV-1 or SEV-2, notify; otherwise don't
        severity = self._extract_severity(response)
        return severity in [IncidentSeverity.SEV_1, IncidentSeverity.SEV_2]

    def _extract_affected_services(self, response: str) -> List[str]:
        """Extract list of affected service names."""
        services = []

        # Look for patterns like "- **service-name** (P0"
        pattern = r"[-*]\s+\*\*([^*]+)\*\*\s+\(P[0-3]"
        matches = re.finditer(pattern, response)

        for match in matches:
            service_name = match.group(1).strip()
            services.append(service_name)

        return services

    def _extract_confidence(self, response: str) -> int:
        """Extract confidence percentage."""
        # Look for patterns like "**Confidence**: HIGH (95%)" or "Confidence: 95%"
        # Try parentheses format (with or without markdown bold)
        match = re.search(
            r"\*?\*?Confidence\*?\*?[:\s]+[A-Z]+\s*\((\d+)%\)",
            response,
            re.IGNORECASE,
        )
        if match:
            return int(match.group(1))

        # Try direct percentage format
        match = re.search(
            r"\*?\*?Confidence\*?\*?[:\s]+(\d+)%", response, re.IGNORECASE
        )
        if match:
            return int(match.group(1))

        # Default to 100%
        return 100

    def _extract_actions(self, response: str) -> List[str]:
        """Extract immediate action steps."""
        actions = []

        # Look for numbered list items
        pattern = r"^\s*\d+\.\s+(.+?)(?=\n\s*\d+\.|$)"
        matches = re.finditer(pattern, response, re.MULTILINE | re.DOTALL)

        for match in matches:
            action = match.group(1).strip()
            if action and len(action) < 500:  # Reasonable action length
                actions.append(action)

        return actions

    def _extract_section(self, response: str, section_name: str) -> Optional[str]:
        """Extract content from a markdown section."""
        # Look for section header and capture until next header or end
        pattern = f"^#+\\s+{re.escape(section_name)}.*?(?=^#+|\\Z)"
        match = re.search(pattern, response, re.MULTILINE | re.IGNORECASE | re.DOTALL)

        if match:
            section_content = match.group(0)
            # Remove the header line
            lines = section_content.split("\n")[1:]
            content = "\n".join(lines).strip()
            return content if content else None

        return None

    def _extract_json_payload(self, response: str) -> Optional[Dict[str, Any]]:
        """Extract JSON payload from markdown code block."""
        # Look for JSON code blocks
        pattern = r"```(?:json)?\s*(\{.*?\})\s*```"
        match = re.search(pattern, response, re.DOTALL)

        if match:
            try:
                json_text = match.group(1)
                return json.loads(json_text)
            except json.JSONDecodeError:
                self.logger.warning("Failed to parse JSON payload")
                return None

        return None
