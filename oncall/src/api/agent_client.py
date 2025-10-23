"""
Anthropic SDK Agent Client
Simplified agent implementation using Anthropic SDK directly (like daemon mode)
"""

import os
import logging
from typing import Dict, List, Any, Optional
from anthropic import Anthropic
import json
from pathlib import Path

from api.custom_tools import (
    list_namespaces,
    list_pods,
    get_pod_logs,
    get_pod_events,
    get_deployment_status,
    list_services,
    search_recent_deployments,
    get_recent_commits,
    check_secrets_manager,
    check_ecr_image,
    analyze_service_health,
    correlate_deployment_with_incidents,
    check_nat_gateway_metrics,
    find_zeus_jobs_during_timeframe,
    correlate_nat_spike_with_zeus_jobs,
    query_datadog_metrics,
    get_resource_usage_trends,
    check_network_traffic,
    generate_skill_document
)

logger = logging.getLogger(__name__)


class OnCallAgentClient:
    """
    OnCall Agent using Anthropic SDK directly.

    This implementation mirrors the daemon mode's approach using direct Anthropic API
    calls with tool calling, avoiding the Claude CLI dependency.
    """

    def __init__(self):
        """Initialize the agent with Anthropic client and tools."""
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY environment variable not set")

        self.client = Anthropic(api_key=api_key)
        self.model = "claude-haiku-4-5-20251001"

        # Define available tools for Anthropic API
        self.tools = self._define_tools()

        # System prompt
        self.system_prompt = self._get_system_prompt()

        logger.info("OnCallAgentClient initialized with Anthropic SDK")
        logger.info(f"Model: {self.model}")
        logger.info(f"Tools available: {len(self.tools)}")

    def _load_skill_content(self, skill_name: str) -> Optional[str]:
        """
        Load skill content from .claude/skills/ directory.

        Args:
            skill_name: Name of the skill (e.g., 'k8s-failure-patterns')

        Returns:
            Skill content (text after YAML frontmatter) or None if not found
        """
        # Look for skill in project root .claude/skills/
        skill_file = Path(".claude/skills") / f"{skill_name}.md"

        if not skill_file.exists():
            logger.warning(f"Skill file not found: {skill_file}")
            return None

        try:
            with open(skill_file, "r") as f:
                content = f.read()

            # Extract content after YAML frontmatter (after second ---)
            parts = content.split("---", 2)
            if len(parts) < 3:
                logger.warning(f"Invalid skill file format: {skill_file}")
                return None

            skill_content = parts[2].strip()
            logger.info(f"✅ Loaded skill: {skill_name} ({len(skill_content)} chars)")
            return f"---\n\n# SKILL: {skill_name}\n\n{skill_content}"

        except Exception as e:
            logger.error(f"Failed to load skill {skill_name}: {e}")
            return None

    def _get_system_prompt(self) -> str:
        """Get system prompt for the agent with skills integration."""
        # Base system prompt
        base_prompt = """You are an on-call agent for Ari's K3s homelab (GitOps: github.com/arigsela/kubernetes, ArgoCD apps in base-apps/).

**CRITICAL SERVICES (P0 - customer-facing)**:
- chores-tracker-backend (ns: chores-tracker-backend): FastAPI, 2 replicas, **5-6min startup is NORMAL**, depends on mysql+vault+ecr-auth
- chores-tracker-frontend (ns: chores-tracker-frontend): HTMX UI, depends on backend+nginx-ingress
- mysql (ns: mysql): **Single replica, data loss risk**, S3 backups, needs vault for password
- n8n (ns: n8n): **Runs THIS agent's Slack bot!**, depends on postgresql+vault
- postgresql (ns: postgresql): **Single replica, n8n memory loss risk**
- nginx-ingress (ns: ingress-nginx): **Platform-wide outage if down**
- oncall-agent (ns: oncall-agent): This service, 2 replicas

**INFRASTRUCTURE (P1)**:
- vault (ns: vault): **Manual unseal required after pod restart**: `kubectl exec -n vault vault-0 -- vault operator unseal`, single replica
- external-secrets (ns: external-secrets): Syncs from vault
- cert-manager (ns: cert-manager): Let's Encrypt, pfSense→Route53 DNS
- ecr-auth (ns: ecr-auth): CronJob syncs ECR creds every 12h to kube-system, account: 852893458518.dkr.ecr.us-east-2.amazonaws.com
- crossplane (ns: crossplane-system): AWS IaC (P2)

**KNOWN ISSUES**:
1. chores-tracker-backend: 5-6min startup=NORMAL (slow Python init), only alert if >6min
2. Vault unsealing: Required after every pod restart, manual procedure above
3. Single replicas: mysql (customer data risk, S3 backups), postgresql (n8n memory loss), vault
4. ImagePullBackOff on ECR: Check ecr-auth cronjob last run, check vault unsealed

**DEPENDENCIES (use when troubleshooting)**:
- mysql down → chores-tracker-backend down (P0)
- vault sealed → ALL services can't get secrets (P1)
- n8n down → Slack bot broken (P0)
- nginx-ingress down → Platform-wide outage (P0)
- postgresql down → n8n broken, conversation history lost (P0)

**GITOPS WORKFLOW**:
1. Code change → GitHub Actions → ECR push
2. PR to kubernetes repo → update base-apps/{service}/deployment.yaml
3. Merge → ArgoCD auto-sync → rolling update
Correlation: Pod restart loops (5+) → Check recent ArgoCD sync, GitHub PR, ECR push

**TROUBLESHOOTING WORKFLOW**:
1. list_namespaces(pattern=service) to discover namespaces (NO {service}-{env} pattern, single prod)
2. list_pods in namespace → check restart counts
3. get_pod_logs + get_pod_events for diagnosis
4. Check service catalog for known issues FIRST
5. search_recent_deployments for GitOps correlation
6. Provide remediation with priority (P0/P1/P2), exact commands, GitOps context

**TOOLS**: list_namespaces, list_pods, get_pod_logs, get_pod_events, get_deployment_status, list_services, search_recent_deployments, get_recent_commits, check_secrets_manager, check_ecr_image, analyze_service_health, correlate_deployment_with_incidents

**KEY**: Check known issues BEFORE alerting. Vault unsealing is frequent. chores-tracker slow startup is normal. Single replicas have risks. All escalations → Slack to Ari.
"""

        # Load skills and append to prompt
        skills_to_load = ["k8s-failure-patterns", "homelab-runbooks", "incident-reporter"]

        for skill_name in skills_to_load:
            skill_content = self._load_skill_content(skill_name)
            if skill_content:
                base_prompt += "\n\n" + skill_content

        # Add explicit instructions for using skills
        skills_instructions = """

## IMPORTANT: Using Skills Knowledge

When troubleshooting Kubernetes issues, YOU MUST:
1. **Identify the failure type** from k8s-failure-patterns (CrashLoopBackOff, ImagePullBackOff, OOMKilled, etc.)
2. **Reference "Common Causes"** from the skill knowledge for the specific failure type
3. **Include "Investigation Steps"** with specific kubectl commands from the skills
4. **Apply runbook procedures** from homelab-runbooks for known scenarios:
   - Vault unsealing
   - ECR authentication issues
   - MySQL troubleshooting
   - chores-tracker slow startup checks
   - ArgoCD deployment correlation
5. **Cite which skill you're using** in your response (e.g., "According to the homelab-runbooks...")

## IMPORTANT: Generating Incident Reports

After investigating a significant incident (P0/P1 severity), YOU MUST generate an incident report using the incident-reporter skill:

1. **Gather investigation data** as you troubleshoot (logs, events, commands, findings)
2. **Structure the data** with these fields:
   - timestamp (ISO format)
   - severity (critical/high/medium/low)
   - summary (1-2 sentence description)
   - affected_resources (list of pods/deployments/services)
   - investigation_steps (chronological list with commands and findings)
   - root_cause (clear RCA)
   - remediation_actions (what was done to fix it)
   - recommendations (how to prevent recurrence)
3. **Call generate_skill_document** tool with:
   - skill_name: "incident-reporter"
   - template_name: "k8s_incident_report"
   - data: Your structured investigation data
4. **Return the file path** to the user so they can attach it to Slack/Teams

The incident report will be saved to /tmp/oncall-reports/ and can be attached to notifications.

The skills knowledge provided above contains detailed troubleshooting procedures. Use them!
"""

        base_prompt += skills_instructions

        return base_prompt

    def _define_tools(self) -> List[Dict[str, Any]]:
        """Define tools in Anthropic API format."""
        return [
            {
                "name": "list_namespaces",
                "description": "List all namespaces in the cluster, optionally filtered by a pattern. Use this FIRST when asked about a service to discover which namespaces contain that service.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "pattern": {
                            "type": "string",
                            "description": "Optional pattern to filter namespaces (e.g., 'chores-tracker' will match 'chores-tracker-backend', 'chores-tracker-frontend'). Leave empty to list all namespaces."
                        }
                    },
                    "required": []
                }
            },
            {
                "name": "list_pods",
                "description": "List pods in a Kubernetes namespace with status, restarts, and container details",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "namespace": {
                            "type": "string",
                            "description": "Kubernetes namespace (e.g., 'mysql', 'chores-tracker-backend')"
                        },
                        "label_selector": {
                            "type": "string",
                            "description": "Optional label selector for filtering (e.g., 'app=chores-tracker')"
                        }
                    },
                    "required": ["namespace"]
                }
            },
            {
                "name": "get_pod_logs",
                "description": "Get logs from a Kubernetes pod",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "namespace": {
                            "type": "string",
                            "description": "Kubernetes namespace"
                        },
                        "pod_name": {
                            "type": "string",
                            "description": "Name of the pod"
                        },
                        "container": {
                            "type": "string",
                            "description": "Optional container name for multi-container pods"
                        },
                        "tail_lines": {
                            "type": "integer",
                            "description": "Number of recent log lines to retrieve (default: 100)"
                        }
                    },
                    "required": ["namespace", "pod_name"]
                }
            },
            {
                "name": "get_pod_events",
                "description": "Get Kubernetes events for troubleshooting a pod or namespace",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "namespace": {
                            "type": "string",
                            "description": "Kubernetes namespace"
                        },
                        "pod_name": {
                            "type": "string",
                            "description": "Optional pod name to filter events"
                        }
                    },
                    "required": ["namespace"]
                }
            },
            {
                "name": "get_deployment_status",
                "description": "Get status of a Kubernetes deployment including replica counts and conditions",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "namespace": {
                            "type": "string",
                            "description": "Kubernetes namespace"
                        },
                        "deployment_name": {
                            "type": "string",
                            "description": "Name of the deployment"
                        }
                    },
                    "required": ["namespace", "deployment_name"]
                }
            },
            {
                "name": "list_services",
                "description": "List Kubernetes Services with their label selectors. Useful for checking Service selector configurations and identifying services using problematic labels like 'app.kubernetes.io/version'",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "namespace": {
                            "type": "string",
                            "description": "Kubernetes namespace (optional - omit to search all namespaces)"
                        },
                        "service_name": {
                            "type": "string",
                            "description": "Specific service name to inspect (optional)"
                        },
                        "check_label": {
                            "type": "string",
                            "description": "Specific label key to check in selectors (e.g., 'app.kubernetes.io/version'). If provided, only returns services using this label in their selector."
                        }
                    },
                    "required": []
                }
            },
            {
                "name": "search_recent_deployments",
                "description": "Search for recent GitHub Actions workflow runs to correlate with incidents",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "repo_name": {
                            "type": "string",
                            "description": "GitHub repository in format 'org/repo' (e.g., 'arigsela/kubernetes')"
                        },
                        "hours_back": {
                            "type": "integer",
                            "description": "Hours to look back (default: 24)"
                        },
                        "workflow_name": {
                            "type": "string",
                            "description": "Optional workflow name filter"
                        }
                    },
                    "required": ["repo_name"]
                }
            },
            {
                "name": "analyze_service_health",
                "description": "Comprehensive health analysis combining pods, deployment, and events for a service",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "service_name": {
                            "type": "string",
                            "description": "Name of the service to analyze"
                        },
                        "namespace": {
                            "type": "string",
                            "description": "Kubernetes namespace"
                        }
                    },
                    "required": ["service_name", "namespace"]
                }
            },
            {
                "name": "generate_skill_document",
                "description": "Generate a formatted document (incident report, runbook, status report) from a skill template. Use this to create professional documentation after troubleshooting incidents.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "skill_name": {
                            "type": "string",
                            "description": "Name of the skill containing the template (e.g., 'incident-reporter')"
                        },
                        "template_name": {
                            "type": "string",
                            "description": "Name of the template to use (e.g., 'k8s_incident_report')"
                        },
                        "data": {
                            "type": "object",
                            "description": "Dictionary of data to populate the template with (timestamp, severity, summary, affected_resources, etc.)"
                        },
                        "output_filename": {
                            "type": "string",
                            "description": "Optional custom filename for the output document"
                        }
                    },
                    "required": ["skill_name", "template_name", "data"]
                }
            }
        ]

    async def query(self, prompt: str) -> Dict[str, Any]:
        """
        Send a query to Claude and handle tool calls.

        Args:
            prompt: User query

        Returns:
            Dictionary with response text and metadata
        """
        messages = [{"role": "user", "content": prompt}]

        logger.info(f"Sending query to Anthropic API: {prompt[:100]}...")
        logger.debug(f"Tools being sent: {json.dumps(self.tools, indent=2)}")

        # Initial API call
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=self.system_prompt,
                messages=messages,
                tools=self.tools
            )
        except Exception as e:
            logger.error(f"Anthropic API error: {e}")
            logger.error(f"Tool definitions: {json.dumps(self.tools, indent=2)}")
            raise

        # Handle tool calls in a loop
        while response.stop_reason == "tool_use":
            # Extract tool calls
            tool_calls = [block for block in response.content if block.type == "tool_use"]

            logger.info(f"Claude requested {len(tool_calls)} tool calls")

            # Add assistant message to conversation
            messages.append({
                "role": "assistant",
                "content": response.content
            })

            # Execute tools and collect results
            tool_results = []
            for tool_call in tool_calls:
                tool_name = tool_call.name
                tool_input = tool_call.input

                logger.info(f"Executing tool: {tool_name}")
                logger.debug(f"Tool input: {tool_input}")

                # Execute the tool
                result = await self._execute_tool(tool_name, tool_input)

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_call.id,
                    "content": json.dumps(result)
                })

            # Add tool results to conversation
            messages.append({
                "role": "user",
                "content": tool_results
            })

            # Get next response from Claude
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=self.system_prompt,
                messages=messages,
                tools=self.tools
            )

        # Extract final text response
        final_text = ""
        for block in response.content:
            if hasattr(block, 'text'):
                final_text += block.text

        logger.info("Query completed successfully")

        return {
            "response": final_text,
            "usage": {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens
            },
            "stop_reason": response.stop_reason
        }

    async def _execute_tool(self, tool_name: str, tool_input: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute a tool by name.

        Args:
            tool_name: Name of the tool to execute
            tool_input: Input parameters for the tool

        Returns:
            Tool execution result
        """
        # Map tool names to functions (K3s homelab tools + skills)
        tool_map = {
            "list_namespaces": list_namespaces,
            "list_pods": list_pods,
            "get_pod_logs": get_pod_logs,
            "get_pod_events": get_pod_events,
            "get_deployment_status": get_deployment_status,
            "list_services": list_services,
            "search_recent_deployments": search_recent_deployments,
            "analyze_service_health": analyze_service_health,
            "generate_skill_document": generate_skill_document,
        }

        if tool_name not in tool_map:
            return {"error": f"Unknown tool: {tool_name}"}

        try:
            # Execute the tool
            result = await tool_map[tool_name](tool_input)
            return result
        except Exception as e:
            logger.error(f"Tool execution error ({tool_name}): {e}", exc_info=True)
            return {"error": str(e)}
