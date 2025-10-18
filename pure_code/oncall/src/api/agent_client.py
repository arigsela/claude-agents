"""
Anthropic SDK Agent Client
Simplified agent implementation using Anthropic SDK directly (like daemon mode)
"""

import os
import logging
from typing import Dict, List, Any, Optional
from anthropic import Anthropic
import json

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
    check_network_traffic
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
        self.model = "claude-sonnet-4-5-20250929"

        # Define available tools for Anthropic API
        self.tools = self._define_tools()

        # System prompt
        self.system_prompt = self._get_system_prompt()

        logger.info("OnCallAgentClient initialized with Anthropic SDK")
        logger.info(f"Model: {self.model}")
        logger.info(f"Tools available: {len(self.tools)}")

    def _get_system_prompt(self) -> str:
        """Get system prompt for the agent."""
        return """You are an expert on-call troubleshooting agent for Kubernetes clusters.

**Your Mission**: Diagnose Kubernetes incidents and provide actionable remediation steps.

**Available Tools**:
You have access to these tools using direct Python APIs (kubernetes, PyGithub, boto3):

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
- check_nat_gateway_metrics: Check NAT gateway traffic and detect spikes

**Datadog Tools**:
- query_datadog_metrics: Query infrastructure metrics over time (CPU, memory, network)
- get_resource_usage_trends: Get CPU/memory trends to identify leaks or degradation
- check_network_traffic: Check network traffic patterns and correlate with NAT

**Composite Analysis**:
- analyze_service_health: Comprehensive service health check
- correlate_deployment_with_incidents: Link K8s issues to deployments

**NAT Gateway Analysis**:
Use check_nat_gateway_metrics when user asks about:
- NAT gateway traffic or spikes
- Network bandwidth usage
- Datadog NAT alerts
- Why NAT egress is high
- Zeus refresh job uploads

The tool will automatically check CloudWatch metrics and can be combined with
pod/job analysis to correlate traffic with workloads like Zeus refresh jobs.

**IMPORTANT - Zeus Job Namespaces**:
Zeus refresh jobs run in ENVIRONMENT-BASED namespaces, NOT "zeus-*" namespaces:
- preprod, qa, prod (main environments)
- devmatt, devjeff (dev user environments)
- merlindev1-5, merlinqa (Merlin environments)

When correlating NAT spikes, the agent searches these 11 namespaces for Zeus jobs.

**CRITICAL - VPC Endpoint Traffic Does NOT Use NAT Gateway**:
The following services use VPC PrivateLink/Endpoints and DO NOT cause NAT traffic:
- S3 (Gateway VPC endpoint configured)
- ECR (Interface VPC endpoints configured)
- Databricks (PrivateLink configured)
- AWS Secrets Manager (Interface VPC endpoint)
- Other AWS services with VPC endpoints

**What DOES Cause NAT Gateway Traffic**:
Only traffic to EXTERNAL (non-AWS) services goes through NAT:
- MEG (Member Eligibility Gateway) - External vendor SaaS
- Confluent Cloud Kafka - us-east-1.aws.confluent.cloud (external SaaS)
- Snowflake - External data warehouse (if applicable)
- Other third-party APIs not in AWS

When analyzing NAT spikes, focus on external vendor destinations, NOT S3/Databricks.

**CRITICAL: Namespace Discovery Pattern**:
When asked about a service (e.g., "artemis-auth", "proteus", "hermes"):
1. FIRST use list_namespaces with pattern={service_name} to discover namespaces
   Example: list_namespaces(pattern="artemis-auth") finds "artemis-auth-dev", "artemis-auth-preprod", etc.
2. THEN check pods in each discovered namespace with list_pods
3. Avoid assuming namespace names - always discover them first

**Common Namespace Patterns**:
- Services typically have namespaces like: {service}-dev, {service}-preprod, {service}-staging, {service}-production
- Example: "artemis-auth" service → artemis-auth-dev, artemis-auth-preprod namespaces
- Example: "proteus" service → proteus-dev, proteus-preprod namespaces

**When to Use Datadog Tools**:
Use Datadog tools when user asks about:
- Performance "over time" or historical trends
- Memory leaks or gradual resource increases
- CPU/memory usage before or after deployments
- Correlating current incidents with historical patterns
- Network traffic patterns or spikes over time
- Comparing resource usage across time periods

**Datadog + Kubernetes Combined Analysis**:
1. Use list_pods to identify current pod issues (restarts, failures)
2. Use query_datadog_metrics to check historical CPU/memory leading up to issue
3. Use get_resource_usage_trends for comprehensive memory leak analysis
4. Use get_pod_logs to see error messages
5. Use search_recent_deployments to correlate with code changes
6. Use check_network_traffic to correlate pod traffic with NAT spikes
7. Provide remediation based on combined K8s + Datadog analysis

**Troubleshooting Workflow**:
1. Use list_namespaces to discover where the service is deployed
2. Use list_pods in each discovered namespace to check pod status
3. If issues found, use get_pod_logs and get_pod_events for details
4. Use Datadog tools to check historical metrics if investigating trends
5. Use search_recent_deployments to check for recent changes
6. Correlate timing of incidents with deployments and metric changes
7. Provide specific, actionable remediation steps

**Key Guidelines**:
- ALWAYS start with list_namespaces when asked about a service
- Check pods in ALL discovered namespaces for that service
- Use get_pod_events to understand what K8s is reporting
- Use Datadog for historical analysis (not real-time - use list_pods for that)
- Correlate incidents with recent deployments AND metric trends
- Provide clear, step-by-step remediation
- Be specific (exact commands, pod names, namespaces)
"""

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
                            "description": "Optional pattern to filter namespaces (e.g., 'artemis-auth' will match 'artemis-auth-dev', 'artemis-auth-preprod'). Leave empty to list all namespaces."
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
                            "description": "Kubernetes namespace (e.g., 'preprod', 'proteus-dev')"
                        },
                        "label_selector": {
                            "type": "string",
                            "description": "Optional label selector for filtering (e.g., 'app=proteus')"
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
                            "description": "GitHub repository in format 'org/repo' (e.g., 'artemishealth/proteus')"
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
                "name": "check_nat_gateway_metrics",
                "description": "Check AWS NAT gateway traffic metrics for spikes, historical analysis, or correlation with workloads. Use when user asks about NAT traffic, Datadog NAT alerts, network bandwidth, or Zeus refresh job uploads.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "time_window_hours": {
                            "type": "integer",
                            "description": "Hours to look back for traffic analysis (1-168, default: 1). Use 24 for daily analysis, 168 for weekly trends."
                        },
                        "nat_gateway_id": {
                            "type": "string",
                            "description": "NAT gateway ID (default: nat-07eb006676096fcd3 for dev-eks us-east-1c). Omit to use default dev-eks NAT."
                        }
                    },
                    "required": []
                }
            },
            {
                "name": "find_zeus_jobs_during_timeframe",
                "description": "Find Zeus refresh jobs running during a specific time window. Use to discover which client data uploads were happening at a particular time. Returns job metadata and log analysis showing upload destinations.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "start_time": {
                            "type": "string",
                            "description": "Start of time window in ISO 8601 format (e.g., '2025-10-16T02:00:00Z')"
                        },
                        "end_time": {
                            "type": "string",
                            "description": "End of time window in ISO 8601 format (e.g., '2025-10-16T03:00:00Z')"
                        },
                        "namespace": {
                            "type": "string",
                            "description": "Optional specific namespace to search (default: searches devmatt, devzeus, devjason)"
                        }
                    },
                    "required": ["start_time", "end_time"]
                }
            },
            {
                "name": "correlate_nat_spike_with_zeus_jobs",
                "description": "PRIMARY TOOL for NAT spike investigation. Correlates a NAT gateway traffic spike with Zeus refresh jobs to identify the root cause. Automatically fetches NAT metrics, finds jobs, analyzes logs, and provides confidence-scored assessment. Use this for queries like 'What caused the NAT spike at 2am?'",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "spike_timestamp": {
                            "type": "string",
                            "description": "Timestamp of the spike. Accepts ISO 8601 format (e.g., '2025-10-16T02:00:00Z') or relative time (e.g., '2am' for 02:00 today)"
                        },
                        "time_window_minutes": {
                            "type": "integer",
                            "description": "Correlation window in minutes (default: 30). Jobs within ±this many minutes of spike will be analyzed."
                        }
                    },
                    "required": ["spike_timestamp"]
                }
            },
            {
                "name": "query_datadog_metrics",
                "description": "Query Datadog metrics for Kubernetes pods, containers, or services. Use for CPU, memory, network, or custom application metrics over time. Helpful for identifying trends, memory leaks, and correlating with incidents. Use when user asks about performance 'over time' or historical patterns.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "metric": {
                            "type": "string",
                            "description": "Metric name (e.g., 'kubernetes.cpu.usage', 'kubernetes.memory.rss', 'kubernetes.network.tx_bytes')"
                        },
                        "namespace": {
                            "type": "string",
                            "description": "Kubernetes namespace"
                        },
                        "pod_name": {
                            "type": "string",
                            "description": "Optional pod name for filtering to specific pod"
                        },
                        "time_window_hours": {
                            "type": "integer",
                            "description": "Hours to look back (default: 1, max: 168 for 1 week)"
                        },
                        "aggregation": {
                            "type": "string",
                            "description": "Aggregation function: avg, max, min, sum (default: avg)"
                        }
                    },
                    "required": ["metric", "namespace"]
                }
            },
            {
                "name": "get_resource_usage_trends",
                "description": "Get CPU and memory usage trends for a service over time. Use to identify memory leaks, resource exhaustion, or performance degradation patterns. Automatically queries multiple metrics (CPU, memory RSS, working set) for comprehensive analysis.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "namespace": {
                            "type": "string",
                            "description": "Kubernetes namespace"
                        },
                        "pod_name": {
                            "type": "string",
                            "description": "Optional pod name for filtering"
                        },
                        "time_window_hours": {
                            "type": "integer",
                            "description": "Hours to look back (default: 24 for daily trends, use 168 for weekly)"
                        }
                    },
                    "required": ["namespace"]
                }
            },
            {
                "name": "check_network_traffic",
                "description": "Check network traffic patterns for pods. Use to identify traffic spikes, correlate with NAT gateway usage, or investigate network errors. Returns TX/RX bytes and error rates with totals in GB for easy analysis.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "namespace": {
                            "type": "string",
                            "description": "Kubernetes namespace"
                        },
                        "pod_name": {
                            "type": "string",
                            "description": "Optional pod name for filtering"
                        },
                        "time_window_hours": {
                            "type": "integer",
                            "description": "Hours to look back (default: 1)"
                        }
                    },
                    "required": ["namespace"]
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
            "check_network_traffic": check_network_traffic
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
