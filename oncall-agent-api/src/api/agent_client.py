"""
Anthropic SDK Agent Client
Simplified agent implementation using Anthropic SDK directly (like daemon mode)
"""

import json
import logging
import os
from typing import Any

from anthropic import Anthropic

from api.custom_tools import (
    analyze_service_health,
    analyze_zeus_refreshes,
    check_ecr_image,
    check_nat_gateway_metrics,
    check_network_traffic,
    check_secrets_manager,
    correlate_deployment_with_incidents,
    correlate_nat_spike_with_zeus_jobs,
    find_zeus_jobs_by_client,
    find_zeus_jobs_during_timeframe,
    get_cost_anomalies,
    get_daily_costs,
    get_deployment_status,
    get_ec2_costs_by_tags,
    get_pod_events,
    get_pod_logs,
    get_recent_commits,
    get_resource_usage_trends,
    get_zeus_job_details,
    list_namespaces,
    list_pods,
    list_services,
    query_datadog_metrics,
    search_recent_deployments,
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
        self.model = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929")

        # Initialize incident memory store (optional - graceful fallback)
        self.memory_store = None
        try:
            from memory import IncidentMemoryStore

            self.memory_store = IncidentMemoryStore()
            memory_stats = self.memory_store.get_stats()
            logger.info(
                f"Incident memory initialized: {memory_stats.get('total_incidents', 0)} incidents stored"
            )
        except ImportError as e:
            logger.warning(f"Incident memory not available (lancedb not installed): {e}")
        except Exception as e:
            logger.warning(f"Failed to initialize incident memory: {e}")

        # Define available tools for Anthropic API
        self.tools = self._define_tools()

        # System prompt
        self.system_prompt = self._get_system_prompt()

        logger.info("OnCallAgentClient initialized with Anthropic SDK")
        logger.info(f"Model: {self.model}")
        logger.info(f"Tools available: {len(self.tools)}")

    def _get_system_prompt(self) -> str:
        """Get system prompt for the agent."""
        return """You are an on-call agent for Ari's K3s homelab (GitOps: github.com/arigsela/kubernetes, ArgoCD apps in base-apps/).

**Your Mission**: Diagnose Kubernetes incidents and provide actionable remediation steps.

**CRITICAL SERVICES (P0 - customer-facing)**:
- chores-tracker-backend (ns: chores-tracker-backend): FastAPI, 2 replicas, **5-6min startup is NORMAL**, depends on mysql+vault+ecr-auth
- chores-tracker-frontend (ns: chores-tracker-frontend): HTMX UI, depends on backend+nginx-ingress
- mysql (ns: mysql): **Single replica, data loss risk**, S3 backups, needs vault for password
- n8n (ns: n8n): **Runs THIS agent's Slack bot!**, depends on postgresql+vault
- postgresql (ns: postgresql): **Single replica, n8n memory loss risk**
- nginx-ingress (ns: ingress-nginx): **Platform-wide outage if down**
- oncall-agent (ns: oncall-agent): This service

**INFRASTRUCTURE (P1)**:
- vault (ns: vault): **Manual unseal required after pod restart**: `kubectl exec -n vault vault-0 -- vault operator unseal`, single replica
- external-secrets (ns: external-secrets): Syncs from vault
- cert-manager (ns: cert-manager): Let's Encrypt, pfSense->Route53 DNS
- ecr-auth (ns: ecr-auth): CronJob syncs ECR creds every 12h to kube-system
- crossplane (ns: crossplane-system): AWS IaC (P2)

**KNOWN ISSUES**:
1. chores-tracker-backend: 5-6min startup=NORMAL (slow Python init), only alert if >6min
2. Vault unsealing: Required after every pod restart, manual procedure above
3. Single replicas: mysql (customer data risk, S3 backups), postgresql (n8n memory loss), vault
4. ImagePullBackOff on ECR: Check ecr-auth cronjob last run, check vault unsealed

**DEPENDENCIES (use when troubleshooting)**:
- mysql down -> chores-tracker-backend down (P0)
- vault sealed -> ALL services can't get secrets (P1)
- n8n down -> Slack bot broken (P0)
- nginx-ingress down -> Platform-wide outage (P0)
- postgresql down -> n8n broken, conversation history lost (P0)

**GITOPS WORKFLOW**:
1. Code change -> GitHub Actions -> ECR push
2. PR to kubernetes repo -> update base-apps/{service}/deployment.yaml
3. Merge -> ArgoCD auto-sync -> rolling update
Correlation: Pod restart loops (5+) -> Check recent ArgoCD sync, GitHub PR, ECR push

**Available Tools**:

**Kubernetes Tools**:
- list_namespaces: Discover namespaces by service name pattern (USE THIS FIRST!)
- list_pods: List pods in a namespace with status and restart counts
- get_pod_logs: Retrieve recent logs from a pod
- get_pod_events: Get K8s events for troubleshooting
- get_deployment_status: Check deployment replica status
- list_services: List Services with their label selectors (can filter by specific labels)

**GitHub Tools**:
- search_recent_deployments: Find recent GitHub Actions workflow runs
- get_recent_commits: Get recent code changes

**AWS Tools**:
- check_secrets_manager: Verify AWS secrets exist
- check_ecr_image: Check if container images are available

**Incident Memory Tools**:
- search_past_incidents: Search for similar past incidents. Use when user asks:
  * "Have we seen this error before?"
  * "What was the root cause of past [error_type] incidents?"
  * "Show me similar incidents"
  * "Is this a recurring issue?"

- store_incident: Save an incident to memory for future reference. Use when user asks:
  * "Remember this incident"
  * "Save this issue"
  * "Store this for later"
  * "Add this to the knowledge base"

**When to Use Incident Memory**:
- ALWAYS search incident memory when investigating a new issue
- Include memory search results in your analysis
- Reference past remediation steps when recommending solutions
- Compare current symptoms with historical patterns
- Store incidents when user explicitly asks to remember them
- When storing, include: service, namespace, error_type, root_cause, and remediation_steps

**Composite Analysis**:
- analyze_service_health: Comprehensive service health check
- correlate_deployment_with_incidents: Link K8s issues to deployments

**TROUBLESHOOTING WORKFLOW**:
1. list_namespaces(pattern=service) to discover namespaces (NO {service}-{env} pattern, single prod)
2. list_pods in namespace -> check restart counts
3. get_pod_logs + get_pod_events for diagnosis
4. search_past_incidents to check for similar historical issues
5. Check service catalog for known issues FIRST
6. search_recent_deployments for GitOps correlation
7. Provide remediation with priority (P0/P1/P2), exact commands, GitOps context

**KEY**: Check known issues BEFORE alerting. Vault unsealing is frequent. chores-tracker slow startup is normal. Single replicas have risks. All escalations -> Slack to Ari.
"""

    def _define_tools(self) -> list[dict[str, Any]]:
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
                            "description": "Optional pattern to filter namespaces (e.g., 'chores' will match 'chores-tracker-backend', 'chores-tracker-frontend'). Leave empty to list all namespaces.",
                        }
                    },
                    "required": [],
                },
            },
            {
                "name": "list_pods",
                "description": "List pods in a Kubernetes namespace with status, restarts, and container details",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "namespace": {
                            "type": "string",
                            "description": "Kubernetes namespace (e.g., 'chores-tracker-backend', 'n8n', 'vault')",
                        },
                        "label_selector": {
                            "type": "string",
                            "description": "Optional label selector for filtering (e.g., 'app=chores-tracker-backend')",
                        },
                    },
                    "required": ["namespace"],
                },
            },
            {
                "name": "get_pod_logs",
                "description": "Get logs from a Kubernetes pod",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "namespace": {"type": "string", "description": "Kubernetes namespace"},
                        "pod_name": {"type": "string", "description": "Name of the pod"},
                        "container": {
                            "type": "string",
                            "description": "Optional container name for multi-container pods",
                        },
                        "tail_lines": {
                            "type": "integer",
                            "description": "Number of recent log lines to retrieve (default: 100)",
                        },
                    },
                    "required": ["namespace", "pod_name"],
                },
            },
            {
                "name": "get_pod_events",
                "description": "Get Kubernetes events for troubleshooting a pod or namespace",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "namespace": {"type": "string", "description": "Kubernetes namespace"},
                        "pod_name": {
                            "type": "string",
                            "description": "Optional pod name to filter events",
                        },
                    },
                    "required": ["namespace"],
                },
            },
            {
                "name": "get_deployment_status",
                "description": "Get status of a Kubernetes deployment including replica counts and conditions",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "namespace": {"type": "string", "description": "Kubernetes namespace"},
                        "deployment_name": {
                            "type": "string",
                            "description": "Name of the deployment",
                        },
                    },
                    "required": ["namespace", "deployment_name"],
                },
            },
            {
                "name": "list_services",
                "description": "List Kubernetes Services with their label selectors. Useful for checking Service selector configurations and identifying services using problematic labels like 'app.kubernetes.io/version'",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "namespace": {
                            "type": "string",
                            "description": "Kubernetes namespace (optional - omit to search all namespaces)",
                        },
                        "service_name": {
                            "type": "string",
                            "description": "Specific service name to inspect (optional)",
                        },
                        "check_label": {
                            "type": "string",
                            "description": "Specific label key to check in selectors (e.g., 'app.kubernetes.io/version'). If provided, only returns services using this label in their selector.",
                        },
                    },
                    "required": [],
                },
            },
            {
                "name": "search_recent_deployments",
                "description": "Search for recent GitHub Actions workflow runs to correlate with incidents",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "repo_name": {
                            "type": "string",
                            "description": "GitHub repository in format 'org/repo' (e.g., 'arigsela/chores-tracker')",
                        },
                        "hours_back": {
                            "type": "integer",
                            "description": "Hours to look back (default: 24)",
                        },
                        "workflow_name": {
                            "type": "string",
                            "description": "Optional workflow name filter",
                        },
                    },
                    "required": ["repo_name"],
                },
            },
            {
                "name": "analyze_service_health",
                "description": "Comprehensive health analysis combining pods, deployment, and events for a service",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "service_name": {
                            "type": "string",
                            "description": "Name of the service to analyze",
                        },
                        "namespace": {"type": "string", "description": "Kubernetes namespace"},
                    },
                    "required": ["service_name", "namespace"],
                },
            },
            {
                "name": "check_nat_gateway_metrics",
                "description": "Check AWS NAT gateway traffic metrics for spikes, historical analysis, or correlation with workloads. Use when user asks about NAT traffic, Datadog NAT alerts, network bandwidth, or Zeus refresh job uploads.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "time_window_hours": {
                            "type": "integer",
                            "description": "Hours to look back for traffic analysis (1-168, default: 1). Use 24 for daily analysis, 168 for weekly trends.",
                        },
                        "nat_gateway_id": {
                            "type": "string",
                            "description": "NAT gateway ID. Not applicable for k3s homelab - this tool is disabled.",
                        },
                    },
                    "required": [],
                },
            },
            {
                "name": "find_zeus_jobs_during_timeframe",
                "description": "Find Zeus refresh jobs running during a specific time window. Use to discover which client data uploads were happening at a particular time. Returns job metadata and log analysis showing upload destinations.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "start_time": {
                            "type": "string",
                            "description": "Start of time window in ISO 8601 format (e.g., '2025-10-16T02:00:00Z')",
                        },
                        "end_time": {
                            "type": "string",
                            "description": "End of time window in ISO 8601 format (e.g., '2025-10-16T03:00:00Z')",
                        },
                        "namespace": {
                            "type": "string",
                            "description": "Optional specific namespace to search (default: searches devmatt, devzeus, devjason)",
                        },
                    },
                    "required": ["start_time", "end_time"],
                },
            },
            {
                "name": "correlate_nat_spike_with_zeus_jobs",
                "description": "PRIMARY TOOL for NAT spike investigation. Correlates a NAT gateway traffic spike with Zeus refresh jobs to identify the root cause. Automatically fetches NAT metrics, finds jobs, analyzes logs, and provides confidence-scored assessment. Use this for queries like 'What caused the NAT spike at 2am?'",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "spike_timestamp": {
                            "type": "string",
                            "description": "Timestamp of the spike. Accepts ISO 8601 format (e.g., '2025-10-16T02:00:00Z') or relative time (e.g., '2am' for 02:00 today)",
                        },
                        "time_window_minutes": {
                            "type": "integer",
                            "description": "Correlation window in minutes (default: 30). Jobs within ±this many minutes of spike will be analyzed.",
                        },
                    },
                    "required": ["spike_timestamp"],
                },
            },
            {
                "name": "query_datadog_metrics",
                "description": "Query Datadog metrics for Kubernetes pods, containers, or services. Use for CPU, memory, network, or custom application metrics over time. Helpful for identifying trends, memory leaks, and correlating with incidents. Use when user asks about performance 'over time' or historical patterns.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "metric": {
                            "type": "string",
                            "description": "Metric name (e.g., 'kubernetes.cpu.usage', 'kubernetes.memory.rss', 'kubernetes.network.tx_bytes')",
                        },
                        "namespace": {"type": "string", "description": "Kubernetes namespace"},
                        "pod_name": {
                            "type": "string",
                            "description": "Optional pod name for filtering to specific pod",
                        },
                        "time_window_hours": {
                            "type": "integer",
                            "description": "Hours to look back (default: 1, max: 168 for 1 week)",
                        },
                        "aggregation": {
                            "type": "string",
                            "description": "Aggregation function: avg, max, min, sum (default: avg)",
                        },
                    },
                    "required": ["metric", "namespace"],
                },
            },
            {
                "name": "get_resource_usage_trends",
                "description": "Get CPU and memory usage trends for a service over time. Use to identify memory leaks, resource exhaustion, or performance degradation patterns. Automatically queries multiple metrics (CPU, memory RSS, working set) for comprehensive analysis.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "namespace": {"type": "string", "description": "Kubernetes namespace"},
                        "pod_name": {
                            "type": "string",
                            "description": "Optional pod name for filtering",
                        },
                        "time_window_hours": {
                            "type": "integer",
                            "description": "Hours to look back (default: 24 for daily trends, use 168 for weekly)",
                        },
                    },
                    "required": ["namespace"],
                },
            },
            {
                "name": "check_network_traffic",
                "description": "Check network traffic patterns for pods. Use to identify traffic spikes, correlate with NAT gateway usage, or investigate network errors. Returns TX/RX bytes and error rates with totals in GB for easy analysis.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "namespace": {"type": "string", "description": "Kubernetes namespace"},
                        "pod_name": {
                            "type": "string",
                            "description": "Optional pod name for filtering",
                        },
                        "time_window_hours": {
                            "type": "integer",
                            "description": "Hours to look back (default: 1)",
                        },
                    },
                    "required": ["namespace"],
                },
            },
            {
                "name": "analyze_zeus_refreshes",
                "description": "Comprehensive analysis of Zeus refresh jobs combining Kubernetes + Datadog logs + metrics. Use when user asks about Zeus refreshes, data uploads, client refreshes, or Databricks jobs. Returns job status, duration, client names, resource usage (CPU/memory/network), errors, and Databricks job IDs.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "hours_back": {
                            "type": "integer",
                            "description": "Number of hours to look back (default: 1)",
                        },
                        "client_name": {
                            "type": "string",
                            "description": "Optional filter by client name",
                        },
                        "status": {
                            "type": "string",
                            "description": "Optional filter by status (Running, Succeeded, Failed)",
                        },
                        "include_logs": {
                            "type": "boolean",
                            "description": "Whether to enrich with Datadog logs (default: true)",
                        },
                        "include_metrics": {
                            "type": "boolean",
                            "description": "Whether to enrich with Datadog metrics (default: true)",
                        },
                    },
                    "required": [],
                },
            },
            {
                "name": "get_zeus_job_details",
                "description": "Get detailed information about a specific Zeus refresh job including logs, metrics, errors, and Databricks job details.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "job_name": {
                            "type": "string",
                            "description": "Name of the Zeus job (e.g., 'zeus-refresh-abc-12345')",
                        },
                        "namespace": {
                            "type": "string",
                            "description": "Namespace where the job runs (e.g., 'qa', 'devmatt')",
                        },
                        "include_logs": {
                            "type": "boolean",
                            "description": "Whether to include Datadog logs (default: true)",
                        },
                        "include_metrics": {
                            "type": "boolean",
                            "description": "Whether to include metrics (default: true)",
                        },
                    },
                    "required": ["job_name", "namespace"],
                },
            },
            {
                "name": "find_zeus_jobs_by_client",
                "description": "Find all Zeus refresh jobs for a specific client. Use when user asks about refreshes for a particular client or customer.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "client_name": {
                            "type": "string",
                            "description": "Client name to search for (e.g., 'ABC Corp', 'acme')",
                        },
                        "hours_back": {
                            "type": "integer",
                            "description": "Number of hours to look back (default: 24)",
                        },
                        "status": {
                            "type": "string",
                            "description": "Optional filter by status (Running, Succeeded, Failed)",
                        },
                    },
                    "required": ["client_name"],
                },
            },
            {
                "name": "get_cost_anomalies",
                "description": "Detect AWS cost anomalies using ML-based AWS Cost Anomaly Detection service. Use when user asks about cost spikes, unusual spending, or cost anomalies.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "days_back": {
                            "type": "integer",
                            "description": "Number of days to look back (1-90, default: 7)",
                        },
                        "min_impact": {
                            "type": "number",
                            "description": "Minimum dollar impact threshold in USD (default: 10.0)",
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Maximum anomalies to return (1-100, default: 50)",
                        },
                    },
                    "required": [],
                },
            },
            {
                "name": "get_daily_costs",
                "description": "Get daily AWS cost breakdown by service, account, or region. Use when user asks about cost trends, service-level spending, or cost analysis over time.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "days_back": {
                            "type": "integer",
                            "description": "Number of days to analyze (1-365, default: 30)",
                        },
                        "group_by": {
                            "type": "string",
                            "description": "Dimension to group by: SERVICE (default), LINKED_ACCOUNT, REGION, or USAGE_TYPE",
                        },
                        "granularity": {
                            "type": "string",
                            "description": "Time granularity: DAILY (default) or MONTHLY",
                        },
                    },
                    "required": [],
                },
            },
            {
                "name": "get_ec2_costs_by_tags",
                "description": "Get EC2 costs broken down by specific tags to identify which infrastructure components are most expensive. Use when user asks about EC2 costs by node groups, Karpenter pools, Databricks workers, or other tag-based cost analysis. IMPORTANT: Our infrastructure includes: (1) Kubernetes node groups (eks:nodegroup-name), (2) Karpenter node pools (karpenter.sh/nodepool), (3) Databricks workers (Refresh-Id tag).",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "days_back": {
                            "type": "integer",
                            "description": "Number of days to analyze (1-365, default: 15)",
                        },
                        "tag_keys": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of tag keys to group by. Default: ['karpenter.sh/nodepool', 'eks:nodegroup-name', 'Refresh-Id']. Common infrastructure tags: 'karpenter.sh/nodepool' (Karpenter pools), 'eks:nodegroup-name' (EKS node groups), 'Refresh-Id' (Databricks workers), 'eks:cluster-name', 'Name', 'Environment', 'Team'",
                        },
                        "service_filter": {
                            "type": "string",
                            "description": "AWS service to filter. Default: 'Amazon Elastic Compute Cloud - Compute' for EC2 instances",
                        },
                    },
                    "required": [],
                },
            },
            {
                "name": "search_past_incidents",
                "description": "Search the incident memory store for similar past incidents. Use when user asks about past incidents, historical issues, or wants to see if similar problems have occurred before.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "service": {
                            "type": "string",
                            "description": "Service name to search for (e.g., 'chores-tracker-backend'). Required.",
                        },
                        "namespace": {
                            "type": "string",
                            "description": "Kubernetes namespace filter (optional)",
                        },
                        "error_type": {
                            "type": "string",
                            "description": "Error type filter (e.g., 'OOMKilled', 'CrashLoopBackOff'). Optional.",
                        },
                        "error_message": {
                            "type": "string",
                            "description": "Error message for better semantic matching. Optional.",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Max results (default: 5, max: 10)",
                        },
                    },
                    "required": ["service"],
                },
            },
            {
                "name": "store_incident",
                "description": "Store an incident in memory for future reference. Use when user asks to 'remember this incident', 'save this issue', 'store this for later', or after analyzing an issue that should be remembered for future troubleshooting.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "service": {
                            "type": "string",
                            "description": "Service name (e.g., 'chores-tracker-backend', 'n8n'). Required.",
                        },
                        "namespace": {
                            "type": "string",
                            "description": "Kubernetes namespace (e.g., 'chores-tracker-backend', 'n8n'). Required.",
                        },
                        "error_type": {
                            "type": "string",
                            "description": "Error type (e.g., 'CreateContainerConfigError', 'OOMKilled', 'CrashLoopBackOff'). Required.",
                        },
                        "root_cause": {
                            "type": "string",
                            "description": "Root cause analysis - what caused the issue. Required.",
                        },
                        "remediation_steps": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of steps to fix the issue. Required.",
                        },
                        "severity": {
                            "type": "string",
                            "enum": ["critical", "high", "medium", "low"],
                            "description": "Severity level. Default: 'medium'",
                        },
                        "summary": {
                            "type": "string",
                            "description": "Brief summary of the incident (optional)",
                        },
                    },
                    "required": [
                        "service",
                        "namespace",
                        "error_type",
                        "root_cause",
                        "remediation_steps",
                    ],
                },
            },
        ]

    async def query(
        self,
        prompt: str,
        conversation_history: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        """
        Send a query to Claude and handle tool calls.

        Args:
            prompt: User query
            conversation_history: Optional list of prior conversation messages
                for multi-turn context. Each entry is {"role": "user"|"assistant", "content": "..."}

        Returns:
            Dictionary with response text and metadata
        """
        messages = []
        if conversation_history:
            messages.extend(conversation_history)
        messages.append({"role": "user", "content": prompt})

        logger.info(f"Sending query to Anthropic API: {prompt[:100]}...")
        logger.debug(f"Tools being sent: {json.dumps(self.tools, indent=2)}")

        # Initial API call
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=self.system_prompt,
                messages=messages,
                tools=self.tools,
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
            messages.append({"role": "assistant", "content": response.content})

            # Execute tools and collect results
            tool_results = []
            for tool_call in tool_calls:
                tool_name = tool_call.name
                tool_input = tool_call.input

                logger.info(f"Executing tool: {tool_name}")
                logger.debug(f"Tool input: {tool_input}")

                # Execute the tool
                result = await self._execute_tool(tool_name, tool_input)

                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_call.id,
                        "content": json.dumps(result),
                    }
                )

            # Add tool results to conversation
            messages.append({"role": "user", "content": tool_results})

            # Get next response from Claude
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=self.system_prompt,
                messages=messages,
                tools=self.tools,
            )

        # Extract final text response
        final_text = ""
        for block in response.content:
            if hasattr(block, "text"):
                final_text += block.text

        logger.info("Query completed successfully")

        return {
            "response": final_text,
            "usage": {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            },
            "stop_reason": response.stop_reason,
        }

    async def _execute_tool(self, tool_name: str, tool_input: dict[str, Any]) -> dict[str, Any]:
        """
        Execute a tool by name.

        Args:
            tool_name: Name of the tool to execute
            tool_input: Input parameters for the tool

        Returns:
            Tool execution result
        """
        # Map tool names to functions
        tool_map = {
            "list_namespaces": list_namespaces,
            "list_pods": list_pods,
            "get_pod_logs": get_pod_logs,
            "get_pod_events": get_pod_events,
            "get_deployment_status": get_deployment_status,
            "list_services": list_services,
            "search_recent_deployments": search_recent_deployments,
            "get_recent_commits": get_recent_commits,
            "check_secrets_manager": check_secrets_manager,
            "check_ecr_image": check_ecr_image,
            "analyze_service_health": analyze_service_health,
            "correlate_deployment_with_incidents": correlate_deployment_with_incidents,
            "check_nat_gateway_metrics": check_nat_gateway_metrics,
            "find_zeus_jobs_during_timeframe": find_zeus_jobs_during_timeframe,
            "correlate_nat_spike_with_zeus_jobs": correlate_nat_spike_with_zeus_jobs,
            "query_datadog_metrics": query_datadog_metrics,
            "get_resource_usage_trends": get_resource_usage_trends,
            "check_network_traffic": check_network_traffic,
            "analyze_zeus_refreshes": analyze_zeus_refreshes,
            "get_zeus_job_details": get_zeus_job_details,
            "find_zeus_jobs_by_client": find_zeus_jobs_by_client,
            "get_cost_anomalies": get_cost_anomalies,
            "get_daily_costs": get_daily_costs,
            "get_ec2_costs_by_tags": get_ec2_costs_by_tags,
            "search_past_incidents": self._search_past_incidents,
            "store_incident": self._store_incident,
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

    async def _search_past_incidents(self, tool_input: dict[str, Any]) -> dict[str, Any]:
        """
        Search for similar past incidents in the memory store.

        Args:
            tool_input: Dictionary containing:
                - service (required): Service name to search
                - namespace (optional): Namespace filter
                - error_type (optional): Error type filter
                - error_message (optional): Error message for semantic matching
                - limit (optional): Max results (default 5, max 10)

        Returns:
            Dictionary with search results or error status
        """
        # Check if memory store is available
        if self.memory_store is None:
            return {
                "status": "unavailable",
                "message": "Incident memory is not available. The lancedb library may not be installed.",
                "incidents_found": 0,
                "incidents": [],
            }

        # Extract and validate parameters
        service = tool_input.get("service")
        if not service:
            return {
                "status": "error",
                "message": "Service parameter is required",
                "incidents_found": 0,
                "incidents": [],
            }

        namespace = tool_input.get("namespace", "")
        error_type = tool_input.get("error_type", "")
        error_message = tool_input.get("error_message", "")
        limit = min(tool_input.get("limit", 5), 10)  # Cap at 10

        logger.info(
            f"Searching past incidents: service={service}, "
            f"namespace={namespace or 'any'}, error_type={error_type or 'any'}"
        )

        try:
            # Search for similar incidents
            similar_incidents = self.memory_store.find_similar(
                service=service,
                namespace=namespace or service,  # Use service as fallback for namespace
                error_type=error_type,
                error_message=error_message,
                limit=limit,
            )

            if not similar_incidents:
                return {
                    "status": "success",
                    "query": {
                        "service": service,
                        "namespace": namespace or "any",
                        "error_type": error_type or "any",
                    },
                    "incidents_found": 0,
                    "summary": f"No similar past incidents found for {service}.",
                    "incidents": [],
                }

            # Format results for Claude
            incidents_data = []
            for similar in similar_incidents:
                incident = similar.incident
                incidents_data.append(
                    {
                        "id": incident.id,
                        "timestamp": incident.timestamp.isoformat(),
                        "service": incident.service,
                        "namespace": incident.namespace,
                        "error_type": incident.error_type,
                        "severity": incident.severity,
                        "root_cause": incident.root_cause,
                        "remediation_steps": incident.remediation_steps,
                        "resolution_outcome": incident.resolution_outcome,
                        "similarity_score": similar.similarity_score,
                        "match_reasons": similar.match_reasons,
                    }
                )

            # Generate summary for Claude
            top_incident = similar_incidents[0]
            summary_parts = [
                f"Found {len(similar_incidents)} similar past incident(s) for {service}."
            ]

            if error_type:
                summary_parts.append(f"Filtering by error type: {error_type}.")

            summary_parts.append(
                f"Top match (similarity: {top_incident.similarity_score:.0%}): "
                f"{top_incident.incident.error_type} in {top_incident.incident.namespace}. "
                f"Root cause: {top_incident.incident.root_cause[:100]}..."
            )

            return {
                "status": "success",
                "query": {
                    "service": service,
                    "namespace": namespace or "any",
                    "error_type": error_type or "any",
                },
                "incidents_found": len(similar_incidents),
                "summary": " ".join(summary_parts),
                "incidents": incidents_data,
            }

        except Exception as e:
            logger.error(f"Error searching past incidents: {e}", exc_info=True)
            return {
                "status": "error",
                "message": f"Failed to search incident memory: {str(e)}",
                "incidents_found": 0,
                "incidents": [],
            }

    async def _store_incident(self, tool_input: dict[str, Any]) -> dict[str, Any]:
        """
        Store an incident in the memory store for future reference.

        Args:
            tool_input: Dictionary containing:
                - service (required): Service name
                - namespace (required): Kubernetes namespace
                - error_type (required): Error type
                - root_cause (required): Root cause analysis
                - remediation_steps (required): List of remediation steps
                - severity (optional): Severity level (default: medium)
                - summary (optional): Brief summary

        Returns:
            Dictionary with store result
        """
        # Check if memory store is available
        if self.memory_store is None:
            return {
                "status": "unavailable",
                "message": "Incident memory is not available. The lancedb library may not be installed.",
                "stored": False,
            }

        # Extract and validate required parameters
        service = tool_input.get("service")
        namespace = tool_input.get("namespace")
        error_type = tool_input.get("error_type")
        root_cause = tool_input.get("root_cause")
        remediation_steps = tool_input.get("remediation_steps", [])

        # Validate required fields
        missing_fields = []
        if not service:
            missing_fields.append("service")
        if not namespace:
            missing_fields.append("namespace")
        if not error_type:
            missing_fields.append("error_type")
        if not root_cause:
            missing_fields.append("root_cause")
        if not remediation_steps:
            missing_fields.append("remediation_steps")

        if missing_fields:
            return {
                "status": "error",
                "message": f"Missing required fields: {', '.join(missing_fields)}",
                "stored": False,
            }

        # Extract optional parameters
        severity = tool_input.get("severity", "medium")
        summary = tool_input.get("summary", root_cause[:200] if root_cause else "")
        cluster = os.getenv("K8S_CONTEXT", "default")  # Use configured cluster

        logger.info(
            f"Storing incident: service={service}, namespace={namespace}, "
            f"error_type={error_type}, severity={severity}"
        )

        try:
            # Store the incident
            incident_id = self.memory_store.store_incident(
                service=service,
                namespace=namespace,
                cluster=cluster,
                error_type=error_type,
                root_cause=root_cause,
                remediation_steps=remediation_steps,
                severity=severity,
                summary=summary,
                llm_model=self.model,
            )

            logger.info(f"Successfully stored incident {incident_id[:8]}...")

            return {
                "status": "success",
                "stored": True,
                "incident_id": incident_id,
                "message": f"Incident stored successfully. ID: {incident_id[:8]}...",
                "details": {
                    "service": service,
                    "namespace": namespace,
                    "error_type": error_type,
                    "severity": severity,
                    "remediation_steps_count": len(remediation_steps),
                },
            }

        except Exception as e:
            logger.error(f"Error storing incident: {e}", exc_info=True)
            return {
                "status": "error",
                "message": f"Failed to store incident: {str(e)}",
                "stored": False,
            }
