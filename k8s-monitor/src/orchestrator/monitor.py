"""Main monitoring orchestrator using Claude Agent SDK."""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions

from src.config import Settings
from src.escalation import EscalationManager
from src.models import EscalationDecision, Finding
from src.notifications import SlackNotifier
from src.utils.parsers import parse_k8s_analyzer_output
from src.utils.model_inspector import ModelInspector

# HARDCODED MODELS - NO VARIABLES, NO SUBSTITUTION
# All models set to Haiku for cost optimization (~12x cheaper than Sonnet)
ORCHESTRATOR_MODEL = "claude-haiku-4-5-20251001"
K8S_ANALYZER_MODEL = "claude-haiku-4-5-20251001"
ESCALATION_MANAGER_MODEL = "claude-haiku-4-5-20251001"
SLACK_NOTIFIER_MODEL = "claude-haiku-4-5-20251001"
GITHUB_REVIEWER_MODEL = "claude-haiku-4-5-20251001"


class Monitor:
    """Orchestrator that coordinates subagents for cluster monitoring."""

    def __init__(self, settings: Settings):
        """Initialize monitor with configuration.

        Args:
            settings: Settings instance with all configuration
        """
        self.settings = settings
        self.logger = logging.getLogger(__name__)
        self.cycle_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.escalation_manager = EscalationManager()
        self.slack_notifier = SlackNotifier(slack_channel=self.settings.slack_channel)
        # State tracking for error recovery
        self.cycle_count = 0
        self.last_successful_cycle: Optional[datetime] = None
        self.last_cycle_status: Optional[str] = None
        self.failed_cycles = 0

    async def initialize_client(self) -> ClaudeSDKClient:
        """Initialize Claude Agent SDK client with MCP servers and subagents.

        Returns:
            Initialized ClaudeSDKClient instance
        """
        self.logger.info("=" * 80)
        self.logger.info("CLAUDE AGENT SDK INITIALIZATION - HARDCODED HAIKU MODELS")
        self.logger.info("=" * 80)
        self.logger.info(f"Initializing ClaudeSDKClient for cycle {self.cycle_id}")
        self.logger.info(f"🤖 ORCHESTRATOR MODEL: {ORCHESTRATOR_MODEL}")
        self.logger.info(f"📊 K8S_ANALYZER MODEL: {K8S_ANALYZER_MODEL}")
        self.logger.info(f"🚨 ESCALATION_MANAGER MODEL: {ESCALATION_MANAGER_MODEL}")
        self.logger.info(f"💬 SLACK_NOTIFIER MODEL: {SLACK_NOTIFIER_MODEL}")
        self.logger.info(f"🔍 GITHUB_REVIEWER MODEL: {GITHUB_REVIEWER_MODEL}")
        self.logger.info("=" * 80)

        # Configure MCP servers
        mcp_servers = {
            "github": {
                "type": "stdio",
                "command": "node",
                "args": [str(self.settings.github_mcp_path)],
                "env": {"GITHUB_TOKEN": self.settings.github_token or ""},
            },
            "slack": {
                "type": "stdio",
                "command": "node",
                "args": [str(self.settings.slack_mcp_path)],
                "env": {
                    "SLACK_BOT_TOKEN": self.settings.slack_bot_token or "",
                    "SLACK_DEFAULT_CHANNEL": self.settings.slack_channel or "",
                },
            },
        }

        # Configure Claude Agent SDK options with HARDCODED Haiku model
        # NOTE: Removed setting_sources=["project"] because it was causing SDK to load
        # conflicting agent definitions that override our hardcoded Haiku models!
        # The SDK has internal defaults that prefer Sonnet, so we must NOT load project files
        options = ClaudeAgentOptions(
            # DO NOT load .claude/ project files - they conflict with hardcoding!
            # setting_sources=["project"],  # DISABLED - causes Sonnet override
            # MCP Servers for GitHub and Slack integration
            mcp_servers=mcp_servers,
            # Tools available to orchestrator
            allowed_tools=[
                "Bash",
                "Read",
                "Grep",
                "Glob",
                "mcp__github__*",
                "mcp__slack__*",
            ],
            # Use Claude Code preset
            system_prompt={"type": "preset", "preset": "claude_code"},
            # Auto-approve kubectl and file reads
            permission_mode="acceptEdits",
            # HARDCODED Model - Haiku for cost optimization
            model=ORCHESTRATOR_MODEL,
        )

        # Create orchestrator client
        client = ClaudeSDKClient(options=options)

        # Connect to the client
        await client.connect()

        self.logger.info("✅ ClaudeSDKClient initialized successfully with HARDCODED Haiku models")

        # INSPECTION: Log which models the SDK actually loaded
        inspector = ModelInspector(logger=self.logger)
        detected_models = await inspector.inspect_client_initialization(client)
        self.logger.info(f"🔍 SDK Model Detection: {detected_models}")

        return client

    async def run_monitoring_cycle(self) -> dict[str, Any]:
        """Run a complete monitoring cycle with comprehensive error handling.

        Returns:
            Results dictionary with findings and decisions
        """
        self.cycle_count += 1
        cycle_start = datetime.now()
        self.logger.info(
            f"Starting monitoring cycle {self.cycle_id} (cycle #{self.cycle_count})"
        )

        try:
            client = await self.initialize_client()

            # Phase 1: Analyze cluster health
            self.logger.info("Phase 1: Running k8s-analyzer subagent")
            try:
                k8s_results = await self._analyze_cluster(client)
            except Exception as e:
                self.logger.error(f"CRITICAL: k8s-analyzer failed: {e}", exc_info=True)
                self.failed_cycles += 1
                return {
                    "cycle_id": self.cycle_id,
                    "cycle_number": self.cycle_count,
                    "status": "failed",
                    "phase": "k8s-analyzer",
                    "error": str(e),
                    "findings": [],
                    "failed_cycles": self.failed_cycles,
                }

            if not k8s_results:
                self.logger.info("No issues detected in cluster")
                self.last_successful_cycle = datetime.now()
                self.last_cycle_status = "healthy"
                return {
                    "cycle_id": self.cycle_id,
                    "cycle_number": self.cycle_count,
                    "status": "healthy",
                    "findings": [],
                    "escalation_decision": None,
                    "notifications_sent": 0,
                    "failed_cycles": self.failed_cycles,
                }

            # Phase 2: Assess severity using escalation manager
            self.logger.info("Phase 2: Running escalation-manager subagent")
            try:
                escalation_response = await self._assess_escalation(client, k8s_results)
                escalation_decision = self.escalation_manager.parse_escalation_response(
                    escalation_response
                )
            except Exception as e:
                self.logger.error(
                    f"escalation-manager failed: {e}, using conservative default (always notify)",
                    exc_info=True,
                )
                # Fallback: conservative default
                escalation_decision = EscalationDecision(
                    severity="SEV-2",
                    confidence=50,
                    should_notify=True,
                    affected_services=[f.service or "unknown" for f in k8s_results],
                    root_cause="Unable to assess escalation, conservative default",
                    immediate_actions=["Manual review required"],
                    business_impact="Potential incident detected",
                )
                self.logger.warning(f"Using fallback escalation decision: {escalation_decision}")

            # Phase 3: Send Slack notifications if required
            notifications_sent = 0
            notification_result = None
            if escalation_decision.should_notify:
                self.logger.info("Phase 3: Running slack-notifier subagent")
                try:
                    notification_result = await self._send_notification(
                        client, escalation_decision
                    )
                    if notification_result and notification_result.get("success"):
                        notifications_sent = 1
                        self.logger.info(f"Notification sent: {notification_result}")
                    else:
                        self.logger.warning(
                            f"Notification delivery failed: {notification_result}"
                        )
                except Exception as e:
                    self.logger.error(
                        f"slack-notifier failed: {e}, notification backed up to file",
                        exc_info=True,
                    )
                    # Fallback: Save to file for retry
                    notification_result = {
                        "success": False,
                        "error": str(e),
                        "backed_up": True,
                        "severity": str(escalation_decision.severity),
                    }
                    self._backup_notification(escalation_decision)
            else:
                self.logger.info("Phase 3: Notification not required for this severity")

            # Mark cycle as successful
            self.last_successful_cycle = datetime.now()
            self.last_cycle_status = "completed"
            self.failed_cycles = 0  # Reset on success

            cycle_duration = (datetime.now() - cycle_start).total_seconds()
            self.logger.info(f"Cycle completed in {cycle_duration:.2f} seconds")

            return {
                "cycle_id": self.cycle_id,
                "cycle_number": self.cycle_count,
                "status": "completed",
                "findings": [f.model_dump() for f in k8s_results],
                "escalation_decision": escalation_decision.model_dump()
                if isinstance(escalation_decision, EscalationDecision)
                else escalation_decision,
                "notification_result": notification_result,
                "notifications_sent": notifications_sent,
                "cycle_duration_seconds": cycle_duration,
                "failed_cycles": self.failed_cycles,
            }

        except Exception as e:
            self.logger.error(f"Unexpected error in monitoring cycle: {e}", exc_info=True)
            self.failed_cycles += 1
            return {
                "cycle_id": self.cycle_id,
                "cycle_number": self.cycle_count,
                "status": "error",
                "error": str(e),
                "findings": [],
                "failed_cycles": self.failed_cycles,
            }

    async def _analyze_cluster(self, client: ClaudeSDKClient) -> list[dict[str, Any]]:
        """Invoke k8s-analyzer subagent to check cluster health.

        Args:
            client: ClaudeSDKClient instance

        Returns:
            List of findings from analysis
        """
        try:
            self.logger.info("Invoking k8s-analyzer subagent")
            self.logger.info(f"📊 Configured model: {K8S_ANALYZER_MODEL}")
            self.logger.info(f"📊 Settings model: {self.settings.k8s_analyzer_model}")

            # Query orchestrator to use k8s-analyzer subagent
            query = "Use the k8s-analyzer subagent to check the K3s cluster health. Analyze pod status, node conditions, recent events, and service health."

            await client.query(query)

            # Receive response from k8s-analyzer (iterate over async generator)
            response_text = ""
            response_model = None
            async for message in client.receive_response():
                self.logger.debug(f"Received message type: {type(message).__name__}")

                # Try to extract model from message
                if hasattr(message, 'model'):
                    response_model = message.model
                    self.logger.info(f"🔍 Response message model: {response_model}")

                # AssistantMessage has a 'content' list of TextBlock/ToolUseBlock objects
                if hasattr(message, 'content'):
                    content_list = message.content
                    if isinstance(content_list, list):
                        for block in content_list:
                            if hasattr(block, 'text'):
                                # TextBlock with text content
                                response_text += block.text
                                self.logger.debug(f"  Extracted {len(block.text)} chars from TextBlock")
                            elif hasattr(block, '__class__') and 'ToolUse' in block.__class__.__name__:
                                # ToolUseBlock - skip for now
                                pass

            self.logger.debug(f"k8s-analyzer response: {response_text}")
            if response_model:
                self.logger.info(f"✅ k8s-analyzer used model: {response_model}")
            else:
                self.logger.warning(f"⚠️ Could not detect model used by k8s-analyzer")

            # Parse the response
            findings = parse_k8s_analyzer_output(response_text)

            self.logger.info(f"Found {len(findings)} issues in cluster analysis")
            if len(findings) == 0:
                self.logger.warning(f"Parser returned 0 findings. Response length: {len(response_text)} chars. First 500 chars: {response_text[:500]}")
            return findings

        except Exception as e:
            self.logger.error(f"Error in cluster analysis: {e}", exc_info=True)
            raise

    async def _assess_escalation(
        self, client: ClaudeSDKClient, findings: list[Finding]
    ) -> str:
        """Invoke escalation-manager subagent to assess incident severity.

        Args:
            client: ClaudeSDKClient instance
            findings: List of findings from k8s-analyzer

        Returns:
            Raw response from escalation-manager
        """
        try:
            self.logger.info("Invoking escalation-manager subagent")
            self.logger.info(f"🚨 Using model: {self.settings.escalation_manager_model}")

            # Prepare findings summary for escalation-manager
            findings_summary = "\n".join(
                [f"- {f.service}: {f.description}" for f in findings]
            )

            # Query orchestrator to use escalation-manager subagent
            query = f"""Use the escalation-manager subagent to assess incident severity based on these findings:

{findings_summary}

Determine the SEV level (SEV-1 through SEV-4) and whether notification is required."""

            await client.query(query)

            # Receive response from escalation-manager (iterate over async generator)
            response_text = ""
            async for message in client.receive_response():
                # AssistantMessage has a 'content' list of TextBlock/ToolUseBlock objects
                if hasattr(message, 'content'):
                    content_list = message.content
                    if isinstance(content_list, list):
                        for block in content_list:
                            if hasattr(block, 'text'):
                                # TextBlock with text content
                                response_text += block.text

            self.logger.debug(f"escalation-manager response: {response_text[:500]}...")

            return response_text

        except Exception as e:
            self.logger.error(f"Error in escalation assessment: {e}", exc_info=True)
            raise

    async def _send_notification(
        self, client: ClaudeSDKClient, decision: EscalationDecision
    ) -> Optional[Dict[str, Any]]:
        """Send Slack notification using slack-notifier subagent.

        Args:
            client: ClaudeSDKClient instance
            decision: Escalation decision with notification details

        Returns:
            Notification result dictionary or None if skipped
        """
        try:
            self.logger.info(f"Sending {decision.severity} notification to Slack")
            self.logger.info(f"💬 Using model: {self.settings.slack_notifier_model}")

            # Use SlackNotifier to send the notification
            notification_result = await self.slack_notifier.send_notification(
                client, decision
            )

            self.logger.info(f"Notification result: {notification_result}")
            return notification_result

        except Exception as e:
            self.logger.error(f"Error sending notification: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "severity": str(decision.severity),
            }

    def _backup_notification(self, decision: EscalationDecision) -> None:
        """Backup failed notification to file for retry.

        Args:
            decision: Escalation decision that failed to send
        """
        backup_dir = Path("logs/incidents")
        backup_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = backup_dir / f"backup_{timestamp}_{decision.severity}.json"

        try:
            with open(backup_file, "w") as f:
                json.dump(decision.model_dump(), f, indent=2)
            self.logger.info(f"Notification backed up to {backup_file}")
        except Exception as e:
            self.logger.error(f"Failed to backup notification: {e}", exc_info=True)

    def save_cycle_report(
        self, results: dict[str, Any], output_dir: Optional[Path] = None
    ) -> Path:
        """Save monitoring cycle results to JSON report.

        Args:
            results: Results dictionary from monitoring cycle
            output_dir: Output directory for report (defaults to logs/)

        Returns:
            Path to saved report file
        """
        if output_dir is None:
            output_dir = Path("logs")

        output_dir.mkdir(parents=True, exist_ok=True)

        report_path = output_dir / f"cycle_{self.cycle_id}.json"

        with open(report_path, "w") as f:
            json.dump(results, f, indent=2, default=str)

        self.logger.info(f"Cycle report saved to {report_path}")
        return report_path

    def get_status_summary(self) -> Dict[str, Any]:
        """Get current monitor status summary.

        Returns:
            Dictionary with current monitor state
        """
        return {
            "cycle_count": self.cycle_count,
            "failed_cycles": self.failed_cycles,
            "last_successful_cycle": (
                self.last_successful_cycle.isoformat()
                if self.last_successful_cycle
                else None
            ),
            "last_cycle_status": self.last_cycle_status,
            "health": "healthy" if self.failed_cycles < 3 else "degraded",
        }
