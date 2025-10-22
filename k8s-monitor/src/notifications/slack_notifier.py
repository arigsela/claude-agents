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

            # Build Slack message
            slack_message = self._format_slack_message(decision, payload)
            channel = payload.get("channel", self.slack_channel or "#infrastructure-alerts")

            self.logger.info(f"📤 Sending Slack message to channel: {channel}")
            self.logger.debug(f"Message preview: {slack_message[:200]}...")

            # Use Slack MCP tool directly
            query = f"""Use the mcp__slack__post_message tool to send this message to {channel}:

{slack_message}

Return the message ID and confirmation."""

            await client.query(query)

            # Receive response from Claude (async generator)
            # Messages are AssistantMessage/SystemMessage objects with content blocks
            response_text = ""
            async for message in client.receive_response():
                # Extract text from message content blocks
                if hasattr(message, 'content'):
                    content_list = message.content
                    if isinstance(content_list, list):
                        for block in content_list:
                            if hasattr(block, 'text'):
                                # TextBlock with text content
                                response_text += block.text
                    elif hasattr(content_list, 'text'):
                        # Single text block
                        response_text += content_list.text
                elif hasattr(message, 'text'):
                    # Direct text attribute
                    response_text += message.text

            response = response_text

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

    def _format_slack_message(self, decision: EscalationDecision, payload: Dict[str, Any]) -> str:
        """Format Slack message according to severity.

        Args:
            decision: Escalation decision
            payload: Notification payload

        Returns:
            Formatted Slack message
        """
        incident_id = payload["incident_id"]
        severity = decision.severity
        emoji = self.severity_emoji.get(decision.severity, "")
        services = payload["affected_services"]
        root_cause = payload.get("root_cause", "Unknown")
        business_impact = payload.get("business_impact", "N/A")
        confidence = payload.get("confidence", 0)
        actions = payload.get("immediate_actions", [])

        # SEV-1 format
        if severity == IncidentSeverity.SEV_1:
            message = f"""{emoji} *CRITICAL INCIDENT* {emoji}
*Severity*: {severity} | *Status*: ACTIVE | *Confidence*: {confidence}%

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

*Incident Summary*
{root_cause}

*Affected Services*
"""
            for service in services:
                message += f"🔴 *{service}*\n"

            message += f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

*Business Impact*
{business_impact}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

*Immediate Actions Required*
"""
            for i, action in enumerate(actions, 1):
                message += f"{i}️⃣ {action}\n"

            message += f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

*Incident ID*: {incident_id}
"""

        # SEV-2 format
        elif severity == IncidentSeverity.SEV_2:
            message = f"""{emoji} *HIGH PRIORITY ALERT* {emoji}
*Severity*: {severity} | *Status*: ACTIVE | *Confidence*: {confidence}%

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

*Alert Summary*
{root_cause}

*Affected Services*
"""
            for service in services:
                message += f"🟡 *{service}*\n"

            message += f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

*Business Impact*
{business_impact}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

*Recommended Actions*
"""
            for i, action in enumerate(actions, 1):
                message += f"{i}️⃣ {action}\n"

            message += f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

*Incident ID*: {incident_id}
"""

        # SEV-3 format (shouldn't happen per escalation policy, but for completeness)
        else:
            message = f"""{emoji} *Infrastructure Notice*
*Severity*: {severity} | *Status*: MONITORING

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

*Notice*
{root_cause}

*Details*
"""
            for service in services:
                message += f"🟢 *{service}*\n"

            message += f"""
*Action Required*
Monitor over next 24 hours

*Incident ID*: {incident_id}
"""

        return message

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
