"""Slack notification manager for incident alerts."""

import logging
import re
from datetime import datetime
from typing import Any, Dict, Optional

from claude_agent_sdk import ClaudeSDKClient

from src.models import EscalationDecision, IncidentSeverity


class SlackNotifier:
    """Manages Slack notifications for incidents."""

    def __init__(self, slack_channel: Optional[str] = None):
        """Initialize Slack notifier.

        Args:
            slack_channel: Target Slack channel (overrides default)
        """
        self.logger = logging.getLogger(__name__)
        self.slack_channel = slack_channel
        self.incident_counter = 0

        # Emoji mapping by severity
        self.severity_emoji = {
            IncidentSeverity.SEV_1: "🚨",
            IncidentSeverity.SEV_2: "⚠️",
            IncidentSeverity.SEV_3: "ℹ️",
            IncidentSeverity.SEV_4: "✅",
        }

        # Color codes for Slack messages (hex)
        self.severity_color = {
            IncidentSeverity.SEV_1: "#FF0000",  # Red
            IncidentSeverity.SEV_2: "#FFA500",  # Orange
            IncidentSeverity.SEV_3: "#FFD700",  # Gold
            IncidentSeverity.SEV_4: "#00AA00",  # Green
        }

    async def send_notification(
        self, client: ClaudeSDKClient, decision: EscalationDecision
    ) -> Dict[str, Any]:
        """Send Slack notification using slack-notifier subagent.

        Args:
            client: ClaudeSDKClient instance
            decision: Escalation decision with notification payload

        Returns:
            Dictionary with delivery confirmation
        """
        if not decision.should_notify:
            self.logger.info(f"Skipping notification for {decision.severity} (should_notify=False)")
            return {
                "success": False,
                "reason": "Notification not required for this severity",
                "severity": decision.severity,
            }

        self.logger.info(f"Sending {decision.severity} notification to Slack")

        try:
            # Generate incident ID
            incident_id = self._generate_incident_id()

            # Prepare payload for slack-notifier
            payload = self._prepare_notification_payload(decision, incident_id)

            # Query slack-notifier subagent
            query = self._build_slack_query(payload, decision)

            await client.query(query)

            # Receive response from slack-notifier
            response = await client.receive_response()

            self.logger.debug(f"Slack notifier response: {response[:300]}...")

            # Parse response
            result = self._parse_slack_response(response, incident_id)

            return result

        except Exception as e:
            self.logger.error(f"Error sending Slack notification: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "severity": decision.severity,
            }

    def format_message_preview(self, decision: EscalationDecision) -> str:
        """Generate a preview of the Slack message format.

        Args:
            decision: Escalation decision

        Returns:
            Formatted message preview
        """
        emoji = self.severity_emoji.get(decision.severity, "")
        services = ", ".join(decision.affected_services[:3])
        if len(decision.affected_services) > 3:
            services += f" +{len(decision.affected_services) - 3} more"

        return (
            f"{emoji} *{decision.severity}* | "
            f"Services: {services} | "
            f"Notify: {'YES' if decision.should_notify else 'NO'}"
        )

    # Private helper methods

    def _generate_incident_id(self) -> str:
        """Generate unique incident ID."""
        self.incident_counter += 1
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"INC-{timestamp}-{self.incident_counter:03d}"

    def _prepare_notification_payload(
        self, decision: EscalationDecision, incident_id: str
    ) -> Dict[str, Any]:
        """Prepare notification payload for slack-notifier.

        Args:
            decision: Escalation decision
            incident_id: Generated incident ID

        Returns:
            Prepared payload dictionary
        """
        payload = {
            "incident_id": incident_id,
            "severity": decision.severity,
            "confidence": decision.confidence,
            "affected_services": decision.affected_services,
            "root_cause": decision.root_cause,
            "immediate_actions": decision.immediate_actions,
            "business_impact": decision.business_impact,
            "channel": decision.notification_channel or self.slack_channel,
        }

        # Include enriched payload if available
        if decision.enriched_payload:
            payload["enriched_data"] = decision.enriched_payload

        return payload

    def _build_slack_query(self, payload: Dict[str, Any], decision: EscalationDecision) -> str:
        """Build query for slack-notifier subagent.

        Args:
            payload: Notification payload
            decision: Escalation decision

        Returns:
            Query string for subagent
        """
        channel = payload.get("channel", "#infrastructure-alerts")
        severity = decision.severity
        services = ", ".join(payload["affected_services"])

        query = f"""Use the slack-notifier subagent to send a {severity} alert to {channel}:

Incident ID: {payload['incident_id']}
Severity: {severity}
Confidence: {payload['confidence']}%
Affected Services: {services}
Root Cause: {payload.get('root_cause', 'Unknown')}
Business Impact: {payload.get('business_impact', 'N/A')}

Immediate Actions:
{chr(10).join(f'• {action}' for action in payload['immediate_actions'])}

Format the message appropriately for {severity} level with clear formatting, emojis, and actionable steps."""

        return query

    def _parse_slack_response(self, response: str, incident_id: str) -> Dict[str, Any]:
        """Parse slack-notifier response.

        Args:
            response: Raw response from slack-notifier
            incident_id: Generated incident ID

        Returns:
            Parsed result dictionary
        """
        success = False
        message_id = None

        # Check for success indicators
        if re.search(r"successfully|delivered|sent|✅|message\s+(?:posted|sent)", response, re.IGNORECASE):
            success = True

        # Try to extract message ID
        message_match = re.search(r"message\s+(?:id|ts)[:\s]+([^\s]+)", response, re.IGNORECASE)
        if message_match:
            message_id = message_match.group(1)

        # Extract channel if mentioned
        channel_match = re.search(r"(?:in|to)\s+[#@]?([^\s]+)", response, re.IGNORECASE)
        channel = channel_match.group(1) if channel_match else None

        result = {
            "success": success,
            "incident_id": incident_id,
            "message_id": message_id,
            "channel": channel,
            "timestamp": datetime.now().isoformat(),
        }

        # Add raw response for debugging
        if not success:
            result["raw_response"] = response[:500]

        self.logger.info(f"Slack notification result: {result}")
        return result
