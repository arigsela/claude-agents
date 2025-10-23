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
from src.utils.cycle_history import CycleHistory

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
        # Cycle history for trend analysis
        self.cycle_history = CycleHistory(
            history_dir=Path("logs"),
            max_history_cycles=5,
            max_history_hours=24,
        )
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

        # Configure MCP servers (optional - only if available)
        mcp_servers = {}

        # GitHub MCP server (optional)
        if Path(self.settings.github_mcp_path).exists():
            mcp_servers["github"] = {
                "type": "stdio",
                "command": "node",
                "args": [str(self.settings.github_mcp_path)],
                "env": {"GITHUB_TOKEN": self.settings.github_token or ""},
            }
        else:
            self.logger.warning(f"GitHub MCP server not found at {self.settings.github_mcp_path}")

        # Slack MCP server (optional)
        if Path(self.settings.slack_mcp_path).exists():
            slack_channel_for_mcp = self.settings.slack_channel or ""
            self.logger.info(f"🎯 Slack MCP Configuration: SLACK_DEFAULT_CHANNEL={slack_channel_for_mcp}")
            mcp_servers["slack"] = {
                "type": "stdio",
                "command": "node",
                "args": [str(self.settings.slack_mcp_path)],
                "env": {
                    "SLACK_BOT_TOKEN": self.settings.slack_bot_token or "",
                    "SLACK_DEFAULT_CHANNEL": slack_channel_for_mcp,
                },
            }
        else:
            self.logger.warning(f"Slack MCP server not found at {self.settings.slack_mcp_path}")

        # Configure Claude Agent SDK with programmatic agent definitions
        # Per SDK docs: Programmatic agents take precedence and allow full control
        # https://docs.claude.com/en/api/agent-sdk/subagents

        # Load agent prompts from .md files
        k8s_analyzer_prompt = self._load_agent_prompt("k8s-analyzer")

        # SKILLS INTEGRATION: Manually append skill content to k8s-analyzer
        # Since Claude Agent SDK doesn't auto-load skills, we include them in the prompt
        skill_content = self._load_skill_content("k8s-failure-patterns")
        if skill_content:
            # Add explicit instructions to use the skill knowledge
            skill_usage_instructions = """

## IMPORTANT: Using the K8s Failure Patterns Knowledge

When you encounter pod failures, YOU MUST:
1. **Identify the failure type** (CrashLoopBackOff, ImagePullBackOff, OOMKilled, etc.)
2. **Reference "Common Causes"** from the k8s-failure-patterns knowledge below
3. **Include "Investigation Steps"** with specific kubectl commands from the skill
4. **Apply service-specific known issues** if relevant (vault unsealing, slow startups, etc.)

The skill knowledge is provided below for your reference.
"""
            k8s_analyzer_prompt += skill_usage_instructions + "\n\n" + skill_content
            self.logger.info("✅ Loaded k8s-failure-patterns skill into k8s-analyzer prompt")

        escalation_manager_prompt = self._load_agent_prompt("escalation-manager")
        github_reviewer_prompt = self._load_agent_prompt("github-reviewer")
        slack_notifier_prompt = self._load_agent_prompt("slack-notifier")

        # Define agents programmatically with explicit Haiku model
        from claude_agent_sdk.types import AgentDefinition

        agents_config = {
            "k8s-analyzer": AgentDefinition(
                description="Use PROACTIVELY for Kubernetes cluster health checks. MUST BE USED every monitoring cycle.",
                prompt=k8s_analyzer_prompt,
                tools=["Bash", "Read", "Grep"],
                model="haiku",
            ),
            "escalation-manager": AgentDefinition(
                description="Assess incident severity and determine notification requirements based on service criticality.",
                prompt=escalation_manager_prompt,
                tools=["Read"],
                model="haiku",
            ),
            "github-reviewer": AgentDefinition(
                description="Correlate cluster issues with recent GitHub commits for deployment context.",
                prompt=github_reviewer_prompt,
                tools=["Read", "Bash"],  # GitHub tool via bash commands
                model="haiku",
            ),
            "slack-notifier": AgentDefinition(
                description="Format and deliver Slack alerts for critical incidents.",
                prompt=slack_notifier_prompt,
                tools=["Bash"],  # Slack tool via bash commands
                model="haiku",
            ),
        }

        options = ClaudeAgentOptions(
            # Pass agents programmatically (recommended per SDK docs)
            agents=agents_config,
            # Load filesystem settings for skills discovery
            # This enables .claude/skills/*.md files to be auto-discovered
            setting_sources=["project"],
            # MCP Servers (optional - only if available)
            mcp_servers=mcp_servers if mcp_servers else None,
            # Tools available to orchestrator (None = all tools including MCP tools)
            # Important: Must allow MCP tools like mcp__slack__post_message
            allowed_tools=None,  # Allow all tools including MCP
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
            # Load previous cycles for trend analysis
            previous_cycles = self.cycle_history.load_recent_cycles()
            self.logger.info(f"Loaded {len(previous_cycles)} previous cycles for context")

            client = await self.initialize_client()

            # Phase 1: Analyze cluster health
            self.logger.info("Phase 1: Running k8s-analyzer subagent")
            try:
                k8s_results = await self._analyze_cluster(client, previous_cycles)
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
            # Detect recurring issues for better context
            recurring_analysis = self.cycle_history.detect_recurring_issues(
                k8s_results, previous_cycles
            )
            self.logger.info(f"Trend analysis: {recurring_analysis}")

            try:
                escalation_response = await self._assess_escalation(
                    client, k8s_results, recurring_analysis
                )
                escalation_decision = self.escalation_manager.parse_escalation_response(
                    escalation_response
                )
            except Exception as e:
                self.logger.error(
                    f"escalation-manager failed: {e}, using conservative default (always notify)",
                    exc_info=True,
                )
                # Fallback: conservative default
                # Extract service names, handling both Finding objects and dicts
                affected_services = []
                for f in k8s_results:
                    service = f.service if hasattr(f, 'service') else f.get('service')
                    if service:
                        affected_services.append(service)
                    else:
                        affected_services.append("unknown")

                escalation_decision = EscalationDecision(
                    severity="SEV-2",
                    confidence=50,
                    should_notify=True,
                    affected_services=affected_services,
                    root_cause="Unable to assess escalation, conservative default",
                    immediate_actions=["Manual review required"],
                    business_impact="Potential incident detected",
                )
                self.logger.warning(f"Using fallback escalation decision: {escalation_decision}")

            # Phase 3: Send Slack notifications if required and enabled
            notifications_sent = 0
            notification_result = None

            if not self.settings.slack_enabled:
                self.logger.info("Phase 3: Slack notifications disabled in settings")
            elif escalation_decision.should_notify:
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
                "trend_analysis": recurring_analysis,
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

    async def _analyze_cluster(
        self, client: ClaudeSDKClient, previous_cycles: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Invoke k8s-analyzer subagent to check cluster health.

        Args:
            client: ClaudeSDKClient instance
            previous_cycles: List of previous cycle reports for trend analysis

        Returns:
            List of findings from analysis
        """
        try:
            self.logger.info("Invoking k8s-analyzer subagent")
            self.logger.info(f"📊 Configured model: {K8S_ANALYZER_MODEL}")
            self.logger.info(f"📊 Settings model: {self.settings.k8s_analyzer_model}")

            # Format previous cycle history for context
            history_summary = self.cycle_history.format_history_summary(previous_cycles)

            # Run kubectl commands directly via orchestrator's Bash tool (with auto-approval)
            # This bypasses permission issues with subagents
            self.logger.info("Gathering cluster data via direct kubectl commands...")

            kubectl_commands = [
                ("pods", "kubectl get pods --all-namespaces -o wide"),
                ("events", "kubectl get events --all-namespaces --sort-by='.lastTimestamp' | tail -100"),
                ("nodes", "kubectl get nodes -o wide"),
                ("deployments", "kubectl get deployments --all-namespaces"),
                ("ingress", "kubectl get ingress --all-namespaces"),
            ]

            kubectl_output = {}
            for cmd_name, cmd in kubectl_commands:
                try:
                    self.logger.debug(f"Executing: {cmd}")
                    # Using subprocess instead of SDK to avoid permission issues
                    import subprocess
                    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
                    kubectl_output[cmd_name] = result.stdout
                    if result.returncode != 0:
                        self.logger.warning(f"kubectl {cmd_name} failed: {result.stderr}")
                except Exception as e:
                    self.logger.error(f"Error running kubectl {cmd_name}: {e}")
                    kubectl_output[cmd_name] = f"Error: {str(e)}"

            # Build analysis prompt for Claude with actual kubectl data AND historical context
            query = f"""Analyze this Kubernetes cluster data and identify all issues:

## KUBECTL OUTPUT (CURRENT STATE)

### Pods (all namespaces)
{kubectl_output.get('pods', 'ERROR')}

### Events (recent)
{kubectl_output.get('events', 'ERROR')}

### Nodes
{kubectl_output.get('nodes', 'ERROR')}

### Deployments
{kubectl_output.get('deployments', 'ERROR')}

### Ingress
{kubectl_output.get('ingress', 'ERROR')}

{history_summary}

## YOUR TASK

Analyze the above kubectl output and identify:
1. MySQL pod status in mysql namespace
2. PostgreSQL pod status in postgresql namespace
3. Any pods with: CrashLoopBackOff, ImagePullBackOff, OOMKilled, Pending, Failed
4. Any error/warning events
5. Node issues: NotReady, MemoryPressure, DiskPressure

**IMPORTANT**: Use the previous cycle history to:
- Identify NEW issues (not seen before)
- Identify RECURRING issues (appeared in previous cycles)
- Identify RESOLVED issues (were present, now fixed)
- Detect WORSENING TRENDS (same service failing repeatedly)

## CRITICAL FINDINGS FORMAT

For EACH issue found, create this format:

## FINDINGS

1. **[Service Name]** - [Issue Type] [🆕 NEW / 🔁 RECURRING / ⚠️ WORSENING]
   - Namespace: [namespace]
   - Pod Status: [status]
   - Details: [specific details from kubectl output]
   - Severity: P0/P1/P2/P3
   - History: [First seen in cycle X / Recurring for Y cycles / etc.]

If no issues are found, respond with:
## FINDINGS
No critical issues detected."""

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

            # Save full response to file for skill verification
            response_file = Path("logs") / f"k8s_analyzer_response_{self.cycle_id}.txt"
            response_file.write_text(response_text)
            self.logger.info(f"💾 Full k8s-analyzer response saved to: {response_file}")

            # Check if skill was loaded by looking for skill references
            skill_loaded = "k8s-failure-patterns" in response_text.lower() or \
                          "skill" in response_text.lower() and "pattern" in response_text.lower()
            if skill_loaded:
                self.logger.info(f"🎯 SKILL DETECTED: k8s-failure-patterns skill was referenced in response")
            else:
                self.logger.info(f"📝 No explicit skill reference detected (skill may still have been loaded)")

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
        self,
        client: ClaudeSDKClient,
        findings: list[Finding],
        recurring_analysis: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Invoke escalation-manager subagent to assess incident severity.

        Args:
            client: ClaudeSDKClient instance
            findings: List of findings from k8s-analyzer
            recurring_analysis: Optional trend analysis from cycle history

        Returns:
            Raw response from escalation-manager
        """
        try:
            self.logger.info("Invoking escalation-manager subagent")
            self.logger.info(f"🚨 Using model: {self.settings.escalation_manager_model}")

            # Prepare findings summary for escalation-manager
            findings_summary_parts = []
            for f in findings:
                # Handle both Finding objects and dicts
                service = f.service if hasattr(f, 'service') else f.get('service', 'unknown')
                description = f.description if hasattr(f, 'description') else f.get('description', '')
                if service or description:
                    findings_summary_parts.append(f"- {service}: {description}")
            findings_summary = "\n".join(findings_summary_parts)

            # Add trend context if available
            trend_context = ""
            if recurring_analysis:
                # Filter out None values from lists
                new_issues = [s for s in recurring_analysis.get('new_issues', []) if s]
                recurring_issues = [s for s in recurring_analysis.get('recurring_issues', []) if s]
                resolved_issues = [s for s in recurring_analysis.get('resolved_issues', []) if s]
                worsening_trends = [s for s in recurring_analysis.get('worsening_trends', []) if s]

                trend_context = f"""

## TREND ANALYSIS

- 🆕 New Issues: {', '.join(new_issues) or 'None'}
- 🔁 Recurring Issues: {', '.join(recurring_issues) or 'None'}
- ✅ Resolved Issues: {', '.join(resolved_issues) or 'None'}
- ⚠️ Worsening Trends: {', '.join(worsening_trends) or 'None'}

**Note**: Worsening trends (services failing repeatedly) should increase severity."""

            # Query orchestrator to use escalation-manager subagent
            query = f"""Use the escalation-manager subagent to assess incident severity based on these findings:

## CURRENT FINDINGS

{findings_summary}
{trend_context}

Determine the SEV level (SEV-1 through SEV-4) and whether notification is required.
**IMPORTANT**: Consider trend analysis when assessing severity - recurring/worsening issues warrant higher severity."""

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

    def _load_agent_prompt(self, agent_name: str) -> str:
        """Load agent system prompt from .md file.

        Args:
            agent_name: Name of the agent (e.g., 'k8s-analyzer')

        Returns:
            Agent's system prompt (text after YAML frontmatter)
        """
        agent_file = Path(".claude/agents") / f"{agent_name}.md"

        if not agent_file.exists():
            raise FileNotFoundError(f"Agent file not found: {agent_file}")

        with open(agent_file, "r") as f:
            content = f.read()

        # Extract content after YAML frontmatter (after second ---)
        parts = content.split("---", 2)
        if len(parts) < 3:
            raise ValueError(f"Invalid agent file format: {agent_file}")

        # Return everything after the frontmatter
        return parts[2].strip()

    def _load_skill_content(self, skill_name: str) -> Optional[str]:
        """Load skill content from .claude/skills/ directory.

        Args:
            skill_name: Name of the skill (e.g., 'k8s-failure-patterns')

        Returns:
            Skill content (text after YAML frontmatter) or None if not found
        """
        skill_file = Path(".claude/skills") / f"{skill_name}.md"

        if not skill_file.exists():
            self.logger.warning(f"Skill file not found: {skill_file}")
            return None

        try:
            with open(skill_file, "r") as f:
                content = f.read()

            # Extract content after YAML frontmatter (after second ---)
            parts = content.split("---", 2)
            if len(parts) < 3:
                self.logger.warning(f"Invalid skill file format: {skill_file}")
                return None

            # Return everything after the frontmatter, prefixed with a header
            skill_content = parts[2].strip()
            return f"---\n\n# SKILL: {skill_name}\n\n{skill_content}"

        except Exception as e:
            self.logger.error(f"Failed to load skill {skill_name}: {e}")
            return None
