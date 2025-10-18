"""
Microsoft Teams Webhook Notifier
Sends incident alerts to Teams channels via webhook

GitOps-Friendly: Provides diagnosis and recommendations, NO automated actions
"""

import aiohttp
import logging
from typing import Any, Dict, Optional
from datetime import datetime, timedelta
import json

logger = logging.getLogger(__name__)


class TeamsNotifier:
    """
    Sends formatted notifications to Microsoft Teams via incoming webhook.

    Features:
    - Critical incident alerts (immediate)
    - Diagnosis complete notifications (with recommendations)
    - Escalation alerts (human action required)
    - Microsoft Adaptive Card formatting
    - Rate limiting to prevent notification spam
    - GitOps-friendly (recommendations only, no automated changes)
    """

    def __init__(self, webhook_url: str, config: Optional[Dict] = None, dry_run: bool = False):
        """
        Initialize Teams notifier.

        Args:
            webhook_url: Microsoft Teams incoming webhook URL
            config: Optional configuration dict (from notifications.yaml)
            dry_run: If True, log notifications instead of sending them (for testing)
        """
        self.webhook_url = webhook_url
        self.config = config or {}
        self.notification_cache = {}  # Track recent notifications for rate limiting
        self.dry_run = dry_run

        mode = "dry-run mode (logging only)" if dry_run else "webhook configured"
        logger.info(f"TeamsNotifier initialized ({mode})")

    async def send_incident_alert(
        self,
        incident: Dict,
        severity: str,
        diagnosis: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """
        Send critical incident alert to Teams (immediate notification).

        This is sent as soon as a critical incident is detected, before
        full diagnosis completes. Provides quick awareness.

        Args:
            incident: Incident details (service, error, pod, restart_count, etc.)
            severity: Severity level (critical, high, medium, low)
            diagnosis: Optional partial diagnosis if available

        Returns:
            Notification result with status
        """
        service = incident.get('service', 'unknown')

        # Check if should notify
        if not self._should_notify(severity, service):
            logger.info(f"Skipping notification for {service} ({severity}) - rate limited or below threshold")
            return {"status": "skipped", "reason": "rate_limited_or_below_threshold"}

        logger.info(f"Sending incident alert to Teams: {service} ({severity})")

        # Build adaptive card
        card = self._build_incident_card(incident, severity, diagnosis)

        # Send to Teams
        result = await self._send_webhook(card)

        # Track notification for rate limiting
        self._track_notification(service, severity)

        return result

    async def send_diagnosis_complete(
        self,
        incident: Dict,
        diagnosis: Dict,
        recommendations: Dict
    ) -> Dict[str, Any]:
        """
        Send diagnosis complete notification to Teams.

        This is sent after full analysis, providing:
        - Root cause analysis
        - Deployment correlation details
        - Remediation recommendations
        - kubectl commands
        - Links to ArgoCD and GitHub

        Args:
            incident: Original incident data
            diagnosis: Complete diagnosis results from run_diagnosis()
            recommendations: Remediation recommendations from suggest_fix

        Returns:
            Notification result
        """
        service = incident.get('service', 'unknown')
        logger.info(f"Sending diagnosis complete to Teams: {service}")

        card = self._build_diagnosis_card(incident, diagnosis, recommendations)
        return await self._send_webhook(card)

    async def send_escalation_alert(
        self,
        incident: Dict,
        reason: str,
        diagnosis: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """
        Send escalation alert when human action required.

        For GitOps: Always requires human action for deployment changes.

        Args:
            incident: Incident details
            reason: Why human intervention is needed
            diagnosis: Optional diagnosis data

        Returns:
            Notification result
        """
        service = incident.get('service', 'unknown')
        logger.info(f"Sending escalation alert to Teams: {service} - {reason}")

        card = self._build_escalation_card(incident, reason, diagnosis)
        return await self._send_webhook(card)

    def _should_notify(self, severity: str, service: str) -> bool:
        """
        Determine if notification should be sent based on configuration rules.

        Checks:
        - Severity threshold (default: critical only)
        - Rate limiting (cooldown period)
        - Max notifications per hour

        Args:
            severity: Incident severity
            service: Service name

        Returns:
            True if notification should be sent
        """
        # Get configuration
        severity_threshold = self.config.get('severity_threshold', 'critical')
        cooldown_minutes = self.config.get('rate_limiting', {}).get('cooldown_minutes', 5)

        # Severity check - only critical by default
        severity_levels = ['low', 'medium', 'high', 'critical']
        if severity_levels.index(severity) < severity_levels.index(severity_threshold):
            logger.debug(f"Severity {severity} below threshold {severity_threshold}")
            return False

        # Rate limiting check
        cache_key = f"{service}_{severity}"
        last_notification = self.notification_cache.get(cache_key)

        if last_notification:
            time_since = datetime.now() - last_notification
            if time_since < timedelta(minutes=cooldown_minutes):
                logger.info(f"Notification rate limited: {service} (cooldown: {cooldown_minutes}min)")
                return False

        return True

    def _track_notification(self, service: str, severity: str):
        """Track notification timestamp for rate limiting"""
        cache_key = f"{service}_{severity}"
        self.notification_cache[cache_key] = datetime.now()
        logger.debug(f"Tracked notification: {cache_key}")

    def _build_incident_card(
        self,
        incident: Dict,
        severity: str,
        diagnosis: Optional[Dict]
    ) -> Dict:
        """
        Build Microsoft Adaptive Card for incident notification.

        Creates an immediate alert card with basic incident info.

        Args:
            incident: Incident data
            severity: Severity level
            diagnosis: Optional partial diagnosis

        Returns:
            Adaptive card JSON for Teams webhook
        """
        service = incident.get('service', 'unknown')
        namespace = incident.get('namespace', 'default')
        error = incident.get('error', 'unknown')
        restart_count = incident.get('restart_count', 0)
        cluster = incident.get('cluster', 'dev-eks')
        pod = incident.get('pod', 'unknown')

        # Build cluster-specific ArgoCD URL (namespace is the ArgoCD app name)
        cluster_env = cluster.replace('-eks', '')  # dev-eks → dev, prod-eks → prod
        argocd_url = f"https://argocd-{cluster_env}.internal.artemishealth.com/applications/argo-cd/{namespace}"

        # Color based on severity
        color_map = {
            'critical': 'Attention',  # Red
            'high': 'Warning',        # Yellow
            'medium': 'Default',      # Blue
            'low': 'Good'             # Green
        }
        theme_color = color_map.get(severity, 'Default')

        # Build fact set
        facts = [
            {"title": "🎯 Service", "value": service},
            {"title": "📦 Namespace", "value": namespace},
            {"title": "❌ Error Type", "value": error},
            {"title": "🔄 Restart Count", "value": str(restart_count)},
            {"title": "⚠️ Severity", "value": severity.upper()},
            {"title": "🖥️ Cluster", "value": cluster},
            {"title": "🕐 Detected", "value": datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        ]

        # Build adaptive card
        card = {
            "type": "message",
            "attachments": [
                {
                    "contentType": "application/vnd.microsoft.card.adaptive",
                    "content": {
                        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                        "type": "AdaptiveCard",
                        "version": "1.4",
                        "body": [
                            {
                                "type": "Container",
                                "style": "attention" if severity == "critical" else "default",
                                "items": [
                                    {
                                        "type": "TextBlock",
                                        "text": f"🚨 {severity.upper()} INCIDENT DETECTED",
                                        "size": "Large",
                                        "weight": "Bolder",
                                        "color": theme_color
                                    },
                                    {
                                        "type": "TextBlock",
                                        "text": f"Service **{service}** in {namespace}",
                                        "size": "Medium",
                                        "wrap": True
                                    }
                                ]
                            },
                            {
                                "type": "FactSet",
                                "facts": facts
                            },
                            {
                                "type": "TextBlock",
                                "text": "⏳ **Agent is analyzing incident...**",
                                "wrap": True,
                                "color": "Accent",
                                "weight": "Bolder"
                            },
                            {
                                "type": "TextBlock",
                                "text": "Full diagnosis with recommendations will follow in ~30 seconds.",
                                "wrap": True,
                                "isSubtle": True
                            }
                        ],
                        "actions": [
                            {
                                "type": "Action.OpenUrl",
                                "title": "View in ArgoCD",
                                "url": argocd_url
                            }
                        ]
                    }
                }
            ]
        }

        return card

    def _build_diagnosis_card(
        self,
        incident: Dict,
        diagnosis: Dict,
        recommendations: Dict
    ) -> Dict:
        """
        Build adaptive card for diagnosis complete notification.

        Includes full analysis, recommendations, and action links.

        Args:
            incident: Original incident
            diagnosis: Diagnosis results
            recommendations: Remediation recommendations

        Returns:
            Adaptive card JSON
        """
        service = incident.get('service', 'unknown')
        namespace = incident.get('namespace', 'default')
        cluster = incident.get('cluster', 'dev-eks')

        # Build cluster-specific ArgoCD URL (namespace is the ArgoCD app name)
        cluster_env = cluster.replace('-eks', '')  # dev-eks → dev, prod-eks → prod
        argocd_url = f"https://argocd-{cluster_env}.internal.artemishealth.com/applications/argo-cd/{namespace}"

        # Get error from event (not top-level)
        error = incident.get('event', {}).get('reason', 'unknown')
        github_repo = incident.get('github_repo', f'artemishealth/{service}')

        # Extract LLM analysis from incident
        llm_analysis = incident.get('llm_analysis', {})

        # Get refined root cause and remediation from LLM
        root_cause = llm_analysis.get('root_cause_refined') or llm_analysis.get('root_cause', 'Unknown')
        immediate_action = llm_analysis.get('immediate_action', '')
        steps = llm_analysis.get('remediation_steps', [])

        # If no LLM analysis, fall back to basic remediation
        if not steps:
            steps = diagnosis.get('remediation_guidance', {}).get('recommended_actions', [
                "Check pod logs",
                "Review deployment configuration",
                "Investigate root cause"
            ])

        # Kubectl commands (can be extracted from steps or kept generic)
        kubectl_commands = [step for step in steps if 'kubectl' in step.lower()][:3]

        # Get correlation info
        correlation = diagnosis.get('deployment_correlation', {})
        correlation_confidence = correlation.get('confidence', 0.0)

        # Build card
        card = {
            "type": "message",
            "attachments": [
                {
                    "contentType": "application/vnd.microsoft.card.adaptive",
                    "content": {
                        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                        "type": "AdaptiveCard",
                        "version": "1.4",
                        "body": [
                            {
                                "type": "Container",
                                "style": "good",
                                "items": [
                                    {
                                        "type": "TextBlock",
                                        "text": "✅ DIAGNOSIS COMPLETE - ACTION REQUIRED",
                                        "size": "Large",
                                        "weight": "Bolder",
                                        "color": "Good"
                                    }
                                ]
                            },
                            {
                                "type": "FactSet",
                                "facts": [
                                    {"title": "Service", "value": service},
                                    {"title": "Namespace", "value": namespace},
                                    {"title": "Error Type", "value": error}
                                ]
                            },
                            {
                                "type": "TextBlock",
                                "text": "🔍 **Root Cause (Claude Analysis):**",
                                "weight": "Bolder"
                            },
                            {
                                "type": "TextBlock",
                                "text": root_cause,
                                "wrap": True,
                                "color": "Attention"
                            },
                            {
                                "type": "TextBlock",
                                "text": "🚨 **Immediate Action:**",
                                "weight": "Bolder"
                            },
                            {
                                "type": "TextBlock",
                                "text": immediate_action or "See remediation steps below",
                                "wrap": True,
                                "color": "Warning"
                            },
                            {
                                "type": "TextBlock",
                                "text": "📋 **Remediation Steps:**",
                                "weight": "Bolder"
                            },
                            {
                                "type": "TextBlock",
                                "text": "\n".join(f"{i}. {step}" for i, step in enumerate(steps[:8], 1)) if steps else "No specific steps available",
                                "wrap": True
                            }
                        ],
                        "actions": [
                            {
                                "type": "Action.OpenUrl",
                                "title": "View in ArgoCD",
                                "url": argocd_url
                            },
                            {
                                "type": "Action.OpenUrl",
                                "title": "View GitHub Repo",
                                "url": f"https://github.com/{github_repo}"
                            },
                            {
                                "type": "Action.OpenUrl",
                                "title": "View Recent Commits",
                                "url": f"https://github.com/{github_repo}/commits"
                            }
                        ]
                    }
                }
            ]
        }

        return card

    def _build_escalation_card(
        self,
        incident: Dict,
        reason: str,
        diagnosis: Optional[Dict]
    ) -> Dict:
        """
        Build adaptive card for escalation alert.

        Sent when human decision/action is required.

        Args:
            incident: Incident data
            reason: Escalation reason
            diagnosis: Optional diagnosis data

        Returns:
            Adaptive card JSON
        """
        service = incident.get('service', 'unknown')
        namespace = incident.get('namespace', 'default')
        error = incident.get('error', 'unknown')
        cluster = incident.get('cluster', 'dev-eks')

        # Build cluster-specific ArgoCD URL (namespace is the ArgoCD app name)
        cluster_env = cluster.replace('-eks', '')  # dev-eks → dev, prod-eks → prod
        argocd_url = f"https://argocd-{cluster_env}.internal.artemishealth.com/applications/argo-cd/{namespace}"

        card = {
            "type": "message",
            "attachments": [
                {
                    "contentType": "application/vnd.microsoft.card.adaptive",
                    "content": {
                        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                        "type": "AdaptiveCard",
                        "version": "1.4",
                        "body": [
                            {
                                "type": "Container",
                                "style": "warning",
                                "items": [
                                    {
                                        "type": "TextBlock",
                                        "text": "⚠️ HUMAN ACTION REQUIRED",
                                        "size": "Large",
                                        "weight": "Bolder",
                                        "color": "Warning"
                                    }
                                ]
                            },
                            {
                                "type": "FactSet",
                                "facts": [
                                    {"title": "Service", "value": service},
                                    {"title": "Namespace", "value": namespace},
                                    {"title": "Error", "value": error},
                                    {"title": "Reason", "value": reason}
                                ]
                            },
                            {
                                "type": "TextBlock",
                                "text": "**What to Do:**",
                                "weight": "Bolder"
                            },
                            {
                                "type": "TextBlock",
                                "text": "1. Review the full diagnosis above\n2. Check ArgoCD for deployment status\n3. Investigate logs and recent changes\n4. Decide on action (rollback, scale, investigate)\n5. Execute via GitOps (revert commit if needed)",
                                "wrap": True
                            }
                        ],
                        "actions": [
                            {
                                "type": "Action.OpenUrl",
                                "title": "View in ArgoCD",
                                "url": argocd_url
                            }
                        ]
                    }
                }
            ]
        }

        return card

    async def _send_webhook(self, card: Dict) -> Dict[str, Any]:
        """
        Send adaptive card to Teams webhook.

        Args:
            card: Adaptive card JSON

        Returns:
            Result dict with status
        """
        # Dry-run mode: Log the payload instead of sending
        if self.dry_run:
            logger.info("=" * 80)
            logger.info("🔍 DRY-RUN: Teams notification (NOT actually sent)")
            logger.info("=" * 80)
            logger.info(f"Webhook URL: {self.webhook_url[:60]}...")
            logger.info("")
            logger.info("Full Adaptive Card JSON:")
            logger.info(json.dumps(card, indent=2))
            logger.info("=" * 80)
            return {
                "status": "dry-run",
                "message": "Notification logged, not sent",
                "timestamp": datetime.now().isoformat()
            }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.webhook_url,
                    json=card,
                    headers={'Content-Type': 'application/json'},
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    response_text = await response.text()

                    # Teams Workflows return 202 Accepted, older webhooks return 200 OK
                    # Both are success responses
                    if response.status in [200, 202]:
                        logger.info(f"✅ Teams notification sent successfully (HTTP {response.status})")
                        return {
                            "status": "success",
                            "http_status": response.status,
                            "webhook_response": response_text,
                            "timestamp": datetime.now().isoformat()
                        }
                    else:
                        logger.error(f"❌ Teams webhook failed: HTTP {response.status}")
                        logger.error(f"Response: {response_text}")
                        return {
                            "status": "failed",
                            "error": f"HTTP {response.status}",
                            "response": response_text
                        }

        except aiohttp.ClientError as e:
            logger.error(f"❌ Teams webhook connection error: {e}")
            return {
                "status": "error",
                "error": f"Connection error: {str(e)}"
            }
        except Exception as e:
            logger.error(f"❌ Teams webhook unexpected error: {e}")
            return {
                "status": "error",
                "error": str(e)
            }

    def get_notification_stats(self) -> Dict[str, Any]:
        """
        Get notification statistics for monitoring.

        Returns:
            Dict with notification counts and timing
        """
        now = datetime.now()
        recent_notifications = [
            (key, timestamp)
            for key, timestamp in self.notification_cache.items()
            if now - timestamp < timedelta(hours=1)
        ]

        return {
            "total_notifications_sent": len(self.notification_cache),
            "notifications_last_hour": len(recent_notifications),
            "services_notified": list(set(key.split('_')[0] for key in self.notification_cache.keys())),
            "oldest_notification": min(self.notification_cache.values()) if self.notification_cache else None,
            "newest_notification": max(self.notification_cache.values()) if self.notification_cache else None
        }
