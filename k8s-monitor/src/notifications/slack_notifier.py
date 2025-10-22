"""Slack notification manager for incident alerts."""

import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from claude_agent_sdk import ClaudeSDKClient

from src.models import EscalationDecision, IncidentSeverity
from src.config.settings import settings


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
        """Send Slack notification using Slack API or fallback to Bash.

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

            # Skip MCP tool - it's not available in Claude Agent SDK
            # Go directly to Slack API via curl
            self.logger.info("Using direct Slack API call (MCP tool not available in this environment)")
            result = await self._send_via_bash(slack_message, channel, incident_id)

            return result

        except Exception as e:
            self.logger.error(f"Error sending Slack notification: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "severity": decision.severity,
            }

    async def _send_via_mcp(
        self, client: ClaudeSDKClient, message: str, channel: str, incident_id: str
    ) -> Dict[str, Any]:
        """Try to send via Slack MCP tool.

        Args:
            client: ClaudeSDKClient instance
            message: Slack message text
            channel: Target channel
            incident_id: Incident ID for tracking

        Returns:
            Result dictionary
        """
        try:
            query = f"""Use the mcp__slack__post_message tool to send this message to {channel}:

{message}

CRITICAL: After sending, you MUST report back the exact message timestamp (ts) value from the Slack API response.
The response format should include: "Message sent successfully. Message ID: <timestamp>"
Example: "Message sent successfully. Message ID: 1234567890.123456"

If the tool returns a JSON response, extract the "ts" field and report it explicitly."""

            await client.query(query)

            response_text = ""
            async for message_obj in client.receive_response():
                if hasattr(message_obj, 'content'):
                    content_list = message_obj.content
                    if isinstance(content_list, list):
                        for block in content_list:
                            if hasattr(block, 'text'):
                                response_text += block.text
                    elif hasattr(content_list, 'text'):
                        response_text += content_list.text
                elif hasattr(message_obj, 'text'):
                    response_text += message_obj.text

            self.logger.info(f"Slack MCP response: {response_text[:500]}...")
            return self._parse_slack_response(response_text, incident_id)

        except Exception as e:
            self.logger.warning(f"MCP Slack send failed: {e}")
            return {"success": False, "error": str(e), "incident_id": incident_id}

    async def _send_via_bash(
        self, message: str, channel: str, incident_id: str
    ) -> Dict[str, Any]:
        """Send via direct Slack API using curl in Bash.

        Args:
            message: Slack message text
            channel: Target channel (e.g., '#oncall-agent')
            incident_id: Incident ID for tracking

        Returns:
            Result dictionary
        """
        import subprocess
        import json

        try:
            slack_token = settings.slack_bot_token
            if not slack_token:
                self.logger.error("SLACK_BOT_TOKEN not configured in settings")
                return {
                    "success": False,
                    "error": "SLACK_BOT_TOKEN not configured",
                    "incident_id": incident_id,
                }

            self.logger.info(f"Sending message to {channel} via Slack API (curl)")
            self.logger.info(f"Message length: {len(message)} chars")

            # Create JSON payload separately to avoid shell escaping issues
            payload = json.dumps({
                "channel": channel,
                "text": message
            })

            self.logger.info(f"Payload length: {len(payload)} chars")
            self.logger.info(f"Payload preview: {payload[:200]}...")
            self.logger.info(f"Using token: {slack_token[:15]}...")  # Log truncated for security

            # Use Slack Web API to post message
            cmd = [
                "curl",
                "-X", "POST",
                "-H", "Content-type: application/json",
                "-H", f"Authorization: Bearer {slack_token}",
                "--data", payload,
                "https://slack.com/api/chat.postMessage"
            ]

            self.logger.info(f"Executing curl command to Slack API")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

            self.logger.info(f"Curl return code: {result.returncode}")
            self.logger.info(f"Curl stdout: {result.stdout[:500]}")
            if result.stderr:
                self.logger.info(f"Curl stderr: {result.stderr[:500]}")

            if result.returncode == 0 and result.stdout:
                try:
                    response_json = json.loads(result.stdout)
                    if response_json.get("ok"):
                        self.logger.info(f"✅ Slack message sent successfully to {channel}")
                        self.logger.info(f"   Message TS: {response_json.get('ts')}")
                        return {
                            "success": True,
                            "incident_id": incident_id,
                            "message_id": response_json.get("ts"),
                            "channel": channel,
                            "timestamp": str(datetime.now().isoformat()),
                        }
                    else:
                        error_msg = response_json.get("error", "Unknown error")
                        self.logger.error(f"❌ Slack API error: {error_msg}")
                        self.logger.debug(f"   Full response: {response_json}")
                        return {
                            "success": False,
                            "error": error_msg,
                            "incident_id": incident_id,
                        }
                except json.JSONDecodeError as e:
                    self.logger.error(f"Invalid JSON response from Slack: {result.stdout}")
                    self.logger.error(f"JSON decode error: {e}")
                    return {
                        "success": False,
                        "error": "Invalid response from Slack API",
                        "incident_id": incident_id,
                    }
            else:
                self.logger.error(f"❌ Curl command failed")
                self.logger.error(f"   Return code: {result.returncode}")
                self.logger.error(f"   Stdout: {result.stdout}")
                self.logger.error(f"   Stderr: {result.stderr}")
                return {
                    "success": False,
                    "error": f"Curl failed: {result.stderr or result.stdout}",
                    "incident_id": incident_id,
                }

        except Exception as e:
            self.logger.error(f"Error sending via Bash/curl: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "incident_id": incident_id,
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
            # Extract service issues from actions for context
            service_issues = self._extract_service_issues_from_actions(actions, services)

            for service in services:
                issue = service_issues.get(service, "Service unavailable or degraded")
                message += f"🔴 *{service}*: {issue}\n"

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
            # Extract service issues from actions for context
            service_issues = self._extract_service_issues_from_actions(actions, services)

            for service in services:
                issue = service_issues.get(service, "Service degraded or at risk")
                message += f"🟡 *{service}*: {issue}\n"

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

        Handles both:
        - Text responses from MCP Slack tool
        - JSON responses from direct Slack API calls

        Args:
            response: Raw response from slack-notifier or Slack API
            incident_id: Generated incident ID

        Returns:
            Parsed result dictionary
        """
        import json

        success = False
        message_id = None
        channel = None

        # Try to parse as JSON first (from direct Slack API calls)
        try:
            response_json = json.loads(response)
            if response_json.get("ok"):
                success = True
                message_id = response_json.get("ts")
                channel = response_json.get("channel")
            else:
                # Slack API returned error
                self.logger.debug(f"Slack API error: {response_json.get('error')}")
                success = False
        except (json.JSONDecodeError, ValueError):
            # Not JSON, try text parsing (from MCP tool)
            # Check for success indicators
            if re.search(r"successfully|delivered|sent|✅|message\s+(?:posted|sent)", response, re.IGNORECASE):
                success = True

            # Try to extract message ID from text response
            # Pattern 1: "Message ID: 1234567890.123456"
            message_match = re.search(r"message\s+(?:id|ts)[:\s]+(\d+\.\d+)", response, re.IGNORECASE)
            if message_match:
                message_id = message_match.group(1)
            else:
                # Pattern 2: "ts: 1234567890.123456" or generic "1234567890.123456"
                ts_match = re.search(r"(?:ts|timestamp)[:\s]+(\d+\.\d+)", response, re.IGNORECASE)
                if ts_match:
                    message_id = ts_match.group(1)

            # Extract channel - only match channel-like patterns (#channel or @user)
            # Avoid capturing random words like "the"
            channel_match = re.search(r"(?:in|to|channel)\s+([#@]\S+)", response, re.IGNORECASE)
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

    def _extract_service_issues_from_actions(
        self, actions: List[str], services: List[str]
    ) -> Dict[str, str]:
        """Extract service-specific issues from immediate action descriptions.

        Args:
            actions: List of immediate action descriptions
            services: List of affected service names

        Returns:
            Dictionary mapping service names to their specific issues
        """
        service_issues = {}

        for action in actions:
            action_lower = action.lower()

            # Look for each service in the action text
            for service in services:
                service_lower = service.lower()

                if service_lower in action_lower:
                    # Try to extract the issue description
                    # Patterns like "MySQL ... - CrashLoopBackOff" or "mysql: pod not ready"

                    # Pattern 1: "**Service** - Issue description"
                    match = re.search(
                        rf"\*\*{re.escape(service)}\*\*[^-]*-\s*(.+?)(?:\n|$|,)",
                        action,
                        re.IGNORECASE
                    )
                    if match:
                        issue = match.group(1).strip()
                        # Clean up the issue (remove extra details after commas)
                        issue = issue.split(',')[0].strip()
                        service_issues[service] = issue
                        continue

                    # Pattern 2: "service (namespace) - Issue"
                    match = re.search(
                        rf"{re.escape(service)}\s*\([^)]+\)\s*-\s*(.+?)(?:\n|$|,)",
                        action,
                        re.IGNORECASE
                    )
                    if match:
                        issue = match.group(1).strip()
                        service_issues[service] = issue
                        continue

                    # Pattern 3: Look for common issue keywords after service name
                    keywords = [
                        "CrashLoopBackOff", "ImagePullBackOff", "OOMKilled",
                        "pending", "not ready", "unavailable", "degraded",
                        "restarts", "down", "offline", "failing"
                    ]

                    for keyword in keywords:
                        if keyword.lower() in action_lower:
                            # Extract a snippet around the keyword
                            start_idx = action_lower.find(keyword.lower())
                            snippet = action[max(0, start_idx-20):start_idx+len(keyword)+30]
                            service_issues[service] = keyword
                            break

        return service_issues
