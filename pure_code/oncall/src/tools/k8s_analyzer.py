"""
Kubernetes Analyzer Tools
Custom MCP tools for K8s deployment analysis

These tools are registered as MCP tools and called by the Claude Agent SDK.
They delegate to actual Kubernetes and GitHub MCP servers for data access.
"""

from claude_agent_sdk import tool
from typing import Any, Dict, List
import json
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


# Correlation time windows and confidence scores (minutes)
CORRELATION_IMMEDIATE = 5      # Within 5 min = 1.0 confidence
CORRELATION_HIGH = 15          # Within 15 min = 0.8 confidence
CORRELATION_MEDIUM = 30        # Within 30 min = 0.5 confidence
# Beyond 30 min = 0.2 confidence

CONFIDENCE_IMMEDIATE = 1.0
CONFIDENCE_HIGH = 0.8
CONFIDENCE_MEDIUM = 0.5
CONFIDENCE_LOW = 0.2

# Rollback decision threshold
ROLLBACK_THRESHOLD = 0.8
INVESTIGATE_THRESHOLD = 0.5

# Restart count thresholds for health assessment
RESTART_COUNT_CRITICAL = 10    # Critical threshold
RESTART_COUNT_WARNING = 3      # Warning threshold
RESTART_COUNT_ESCALATION = 10  # Requires escalation

# Rollback scoring weights
ROLLBACK_SCORE_CRITICAL = 0.4
ROLLBACK_SCORE_HIGH = 0.2
ROLLBACK_SCORE_INCIDENT_TYPE = 0.3
ROLLBACK_SCORE_HIGH_RESTARTS = 0.3    # > 10 restarts
ROLLBACK_SCORE_ELEVATED_RESTARTS = 0.2  # > 5 restarts
ROLLBACK_SCORE_DEPLOYMENT = 0.4

# Log tail size for pod logs
DEFAULT_LOG_TAIL_LINES = 100

# Default deployments repository
DEFAULT_DEPLOYMENTS_REPO = "deployments"


@tool("analyze_deployment",
      "Analyze deployment health and recent changes",
      {"deployment_name": str, "namespace": str})
async def analyze_deployment(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Analyzes a Kubernetes deployment for issues.

    This tool provides guidance for using Kubernetes MCP tools to diagnose
    deployment issues. The actual K8s API calls should be made through the
    Kubernetes MCP server tools.

    Checks:
    - Pod status and restart counts
    - Recent K8s events
    - Resource utilization
    - Recent configuration changes

    Args:
        deployment_name: Name of the deployment to analyze
        namespace: K8s namespace (default: 'default')

    Returns:
        Analysis guidance with recommended MCP tool calls
    """
    deployment = args["deployment_name"]
    namespace = args.get("namespace", "default")

    logger.info(f"Analyzing deployment: {deployment} in namespace: {namespace}")

    # Build analysis guidance
    analysis = {
        "deployment": deployment,
        "namespace": namespace,
        "timestamp": datetime.now().isoformat(),
        "recommended_checks": [
            {
                "check": "pod_status",
                "tool": "mcp__kubernetes__list_pods",
                "args": {
                    "namespace": namespace,
                    "label_selector": f"app={deployment}"
                },
                "description": "Get all pods for this deployment and check their status"
            },
            {
                "check": "recent_events",
                "tool": "mcp__kubernetes__get_events",
                "args": {
                    "namespace": namespace,
                    "field_selector": f"involvedObject.name={deployment}"
                },
                "description": "Get recent events related to this deployment"
            },
            {
                "check": "deployment_details",
                "tool": "mcp__kubernetes__describe_deployment",
                "args": {
                    "name": deployment,
                    "namespace": namespace
                },
                "description": "Get deployment spec including replicas, resource limits, and strategy"
            },
            {
                "check": "pod_logs",
                "tool": "mcp__kubernetes__get_logs",
                "args": {
                    "pod_name": f"{deployment}-*",
                    "namespace": namespace,
                    "tail_lines": DEFAULT_LOG_TAIL_LINES
                },
                "description": "Get recent logs from pods to identify errors"
            }
        ],
        "analysis_workflow": [
            "1. Use mcp__kubernetes__list_pods to get pod list and restart counts",
            "2. Use mcp__kubernetes__get_events to check for Warning events",
            "3. Use mcp__kubernetes__get_logs to review error messages",
            "4. Use mcp__kubernetes__describe_deployment to check resource limits",
            "5. Compare current state with expected state (desired replicas vs available)"
        ],
        "health_indicators": {
            "critical": [
                f"restart_count > {RESTART_COUNT_CRITICAL}",
                "available_replicas < desired_replicas",
                "OOMKilled events present"
            ],
            "warning": [
                f"restart_count > {RESTART_COUNT_WARNING}",
                "CPU/memory near limits",
                "Slow startup times"
            ]
        }
    }

    return {
        "content": [{
            "type": "text",
            "text": json.dumps(analysis, indent=2)
        }]
    }


@tool("correlate_events",
      "Correlate K8s events with GitHub deployments",
      {"time_window": str, "service": str, "context": dict})
async def correlate_events(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Correlates Kubernetes events with GitHub deployment activities.

    This tool provides a correlation framework that guides the agent to:
    1. Fetch K8s events using Kubernetes MCP tools
    2. Fetch GitHub workflow runs using GitHub MCP tools
    3. Match timestamps to identify deployment-related incidents

    Args:
        time_window: Time window to analyze (e.g., '1h', '24h', '7d')
        service: Service name to correlate
        context: Optional context dict with 'namespace' and 'deployments_repo' configuration

    Returns:
        Correlation guidance with recommended tool calls
    """
    time_window = args["time_window"]
    service = args["service"]

    # Get context for namespace and repo configuration
    context = args.get("context", {})
    namespace = context.get("namespace", "default")
    deployments_repo = context.get("deployments_repo", DEFAULT_DEPLOYMENTS_REPO)

    logger.info(f"Correlating events for service: {service}, namespace: {namespace}, window: {time_window}")

    # Parse time window to calculate time range
    time_mapping = {
        '1h': 1, '2h': 2, '6h': 6, '12h': 12, '24h': 24,
        '1d': 24, '2d': 48, '7d': 168
    }

    hours = time_mapping.get(time_window, 24)
    start_time = datetime.now() - timedelta(hours=hours)

    correlation_guidance = {
        "service": service,
        "namespace": namespace,
        "time_window": time_window,
        "analysis_period": {
            "start": start_time.isoformat(),
            "end": datetime.now().isoformat(),
            "duration_hours": hours
        },
        "recommended_tool_calls": [
            {
                "step": 1,
                "description": "Fetch K8s events for this service",
                "tool": "mcp__kubernetes__get_events",
                "args": {
                    "namespace": namespace,
                    "field_selector": f"involvedObject.name~{service}",
                    "type": "Warning"
                },
                "extract": ["timestamp", "reason", "message", "count"]
            },
            {
                "step": 2,
                "description": "Fetch recent GitHub workflow runs",
                "tool": "mcp__github__list_workflow_runs",
                "args": {
                    "owner": "artemishealth",
                    "repo": deployments_repo,
                    "workflow_id": "deploy.yml",
                    "status": "completed",
                    "per_page": 20
                },
                "extract": ["id", "created_at", "updated_at", "conclusion", "head_commit"]
            },
            {
                "step": 3,
                "description": "Match events by timestamp proximity",
                "logic": [
                    f"For each K8s event, find GitHub workflows within ±{CORRELATION_MEDIUM} minutes",
                    "Calculate confidence based on time proximity and service name match",
                    f"Confidence = {CONFIDENCE_IMMEDIATE} if within {CORRELATION_IMMEDIATE} min, {CONFIDENCE_HIGH} if within {CORRELATION_HIGH} min, {CONFIDENCE_MEDIUM} if within {CORRELATION_MEDIUM} min"
                ]
            }
        ],
        "correlation_algorithm": {
            "time_proximity_scoring": {
                f"0-{CORRELATION_IMMEDIATE}_minutes": CONFIDENCE_IMMEDIATE,
                f"{CORRELATION_IMMEDIATE}-{CORRELATION_HIGH}_minutes": CONFIDENCE_HIGH,
                f"{CORRELATION_HIGH}-{CORRELATION_MEDIUM}_minutes": CONFIDENCE_MEDIUM,
                f">{CORRELATION_MEDIUM}_minutes": CONFIDENCE_LOW
            },
            "service_name_matching": {
                "exact_match": "+0.2 bonus",
                "partial_match": "+0.1 bonus",
                "no_match": "no bonus"
            }
        },
        "interpretation_guide": {
            "confidence >= 0.9": "Very likely deployment-related (suggest rollback)",
            f"confidence {ROLLBACK_THRESHOLD}-0.89": "Likely deployment-related (investigate further)",
            f"confidence {INVESTIGATE_THRESHOLD}-{ROLLBACK_THRESHOLD - 0.01:.2f}": "Possibly deployment-related (check other factors)",
            f"confidence < {INVESTIGATE_THRESHOLD}": "Unlikely deployment-related (check other causes)"
        }
    }

    return {
        "content": [{
            "type": "text",
            "text": json.dumps(correlation_guidance, indent=2)
        }]
    }


@tool("analyze_cluster_nodes",
      "Analyze cluster nodes, node groups, and resource capacity",
      {"cluster_context": str})
async def analyze_cluster_nodes(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Analyzes Kubernetes cluster nodes including count, node groups/pools, and capacity.

    This tool provides guidance for using Kubernetes MCP tools to query node-level
    information. The actual K8s API calls should be made through the Kubernetes MCP
    server tools.

    Information provided:
    - Node count and status
    - Node groups/pools (from node labels)
    - Node capacity (CPU, memory)
    - Node allocatable resources
    - Node conditions and health

    Args:
        cluster_context: Optional context about the cluster (e.g., 'dev-eks', 'prod-eks')

    Returns:
        Analysis guidance with recommended MCP tool calls for node information
    """
    cluster_context = args.get("cluster_context", "default")

    logger.info(f"Analyzing cluster nodes for context: {cluster_context}")

    analysis = {
        "cluster_context": cluster_context,
        "timestamp": datetime.now().isoformat(),
        "recommended_checks": [
            {
                "check": "list_all_nodes",
                "tool": "mcp__kubernetes__list_nodes",
                "args": {},
                "description": "Get all nodes in the cluster with their status",
                "extract": [
                    "metadata.name",
                    "status.conditions",
                    "status.nodeInfo",
                    "status.capacity",
                    "status.allocatable"
                ]
            },
            {
                "check": "get_node_labels",
                "tool": "mcp__kubernetes__list_nodes",
                "args": {},
                "description": "Get node labels to identify node groups/pools",
                "extract": [
                    "metadata.labels",
                    "metadata.labels['eks.amazonaws.com/nodegroup']",
                    "metadata.labels['node.kubernetes.io/instance-type']",
                    "metadata.labels['topology.kubernetes.io/zone']"
                ]
            },
            {
                "check": "node_details",
                "tool": "mcp__kubernetes__describe_node",
                "args": {
                    "name": "<node-name>"
                },
                "description": "Get detailed information about a specific node including capacity, allocatable resources, and conditions"
            }
        ],
        "analysis_workflow": [
            "1. Use mcp__kubernetes__list_nodes to get all nodes",
            "2. Count total nodes and group by status (Ready, NotReady, etc.)",
            "3. Extract node group/pool information from labels:",
            "   - For EKS: Look for 'eks.amazonaws.com/nodegroup' label",
            "   - For GKE: Look for 'cloud.google.com/gke-nodepool' label",
            "   - For AKS: Look for 'agentpool' label",
            "   - Generic: Look for 'node-role.kubernetes.io/*' labels",
            "4. Summarize capacity per node group (CPU, memory)",
            "5. Check node conditions for health issues",
            "6. Identify instance types from 'node.kubernetes.io/instance-type' label"
        ],
        "data_extraction_guide": {
            "node_count": "Count of items in list_nodes response",
            "node_groups": {
                "EKS": "metadata.labels['eks.amazonaws.com/nodegroup']",
                "GKE": "metadata.labels['cloud.google.com/gke-nodepool']",
                "AKS": "metadata.labels['agentpool']",
                "generic": "metadata.labels matching 'node-role.kubernetes.io/*'"
            },
            "node_capacity": {
                "cpu": "status.capacity.cpu",
                "memory": "status.capacity.memory",
                "pods": "status.capacity.pods"
            },
            "node_allocatable": {
                "cpu": "status.allocatable.cpu",
                "memory": "status.allocatable.memory",
                "pods": "status.allocatable.pods"
            },
            "instance_type": "metadata.labels['node.kubernetes.io/instance-type']",
            "availability_zone": "metadata.labels['topology.kubernetes.io/zone']"
        },
        "response_format": {
            "summary": {
                "total_nodes": "number",
                "ready_nodes": "number",
                "not_ready_nodes": "number"
            },
            "node_groups": [
                {
                    "name": "node-group-name",
                    "node_count": "number",
                    "instance_type": "instance type",
                    "total_capacity": {
                        "cpu": "total CPU cores",
                        "memory": "total memory in Gi"
                    }
                }
            ],
            "individual_nodes": [
                {
                    "name": "node name",
                    "status": "Ready/NotReady",
                    "node_group": "group name",
                    "instance_type": "instance type",
                    "zone": "availability zone",
                    "capacity": {"cpu": "cores", "memory": "Gi"},
                    "allocatable": {"cpu": "cores", "memory": "Gi"}
                }
            ]
        },
        "health_indicators": {
            "healthy": [
                "All nodes in Ready state",
                "No DiskPressure, MemoryPressure, or PIDPressure conditions",
                "Sufficient allocatable resources available"
            ],
            "warning": [
                "Nodes in NotReady state",
                "DiskPressure or MemoryPressure conditions present",
                "Low allocatable resources"
            ]
        }
    }

    return {
        "content": [{
            "type": "text",
            "text": json.dumps(analysis, indent=2)
        }]
    }


@tool("suggest_fix",
      "Suggest remediation based on incident type",
      {"incident_type": str, "severity": str, "context": dict})
async def suggest_fix(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Provides specific remediation steps based on incident analysis.

    This tool combines:
    1. Pre-defined remediation playbooks for common incidents
    2. Severity-based action prioritization
    3. Zeus memory search guidance for past resolutions
    4. Rollback decision logic

    Args:
        incident_type: Type of incident (oom_killed, crashloop, imagepull, etc.)
        severity: Incident severity (critical, high, medium, low)
        context: Additional context about the incident

    Returns:
        Remediation recommendations with prioritized steps and memory search guidance
    """
    incident_type = args["incident_type"]
    severity = args["severity"]
    context = args.get("context", {})

    logger.info(f"Suggesting fix for {incident_type} (severity: {severity})")

    # Remediation playbooks
    playbooks = {
        "oom_killed": {
            "steps": [
                "1. Get current memory limits: kubectl describe deployment <name> -n <namespace>",
                "2. Check memory usage trends: kubectl top pods -n <namespace>",
                "3. Review recent code changes for memory leaks in git history",
                "4. Increase memory limits (e.g., from 512Mi to 1Gi) if justified",
                "5. Consider rollback if issue started after recent deployment"
            ],
            "kubectl_commands": [
                "kubectl describe deployment {service} -n {namespace}",
                "kubectl top pods -l app={service} -n {namespace}",
                "kubectl get events -n {namespace} --field-selector involvedObject.name={service}",
                "kubectl logs {pod} -n {namespace} --previous"
            ],
            "rollback_recommendation": f"HIGH - if deployment correlation confidence > {ROLLBACK_THRESHOLD}"
        },
        "crashloop": {
            "steps": [
                "1. Get pod logs: kubectl logs <pod> -n <namespace> --previous",
                "2. Check deployment configuration: kubectl get deployment <name> -o yaml",
                "3. Verify environment variables and secrets are properly configured",
                "4. Check liveness/readiness probe configuration",
                "5. Review recent image changes in deployment history",
                "6. Rollback to last known good version if deployment-related"
            ],
            "kubectl_commands": [
                "kubectl logs {pod} -n {namespace} --previous --tail=100",
                "kubectl describe pod {pod} -n {namespace}",
                "kubectl get deployment {service} -n {namespace} -o yaml",
                "kubectl rollout history deployment/{service} -n {namespace}"
            ],
            "rollback_recommendation": "HIGH - if deployment occurred within last hour"
        },
        "imagepull": {
            "steps": [
                "1. Verify image tag exists in ECR: aws ecr describe-images",
                "2. Check image pull secrets: kubectl get secrets -n <namespace>",
                "3. Verify ECR registry connectivity from cluster",
                "4. Review image specification in deployment (tag vs digest)",
                "5. Check IAM roles for ECR access (IRSA configuration)"
            ],
            "kubectl_commands": [
                "kubectl describe pod {pod} -n {namespace}",
                "kubectl get secrets -n {namespace}",
                "kubectl get sa -n {namespace}"
            ],
            "rollback_recommendation": "MEDIUM - check if image tag changed in recent deployment"
        },
        "scheduling": {
            "steps": [
                "1. Check node resources: kubectl describe nodes",
                "2. Review pod resource requests in deployment spec",
                "3. Check for node taints/tolerations conflicts",
                "4. Verify PodDisruptionBudget isn't blocking scheduling",
                "5. Consider cluster autoscaling if capacity issue"
            ],
            "kubectl_commands": [
                "kubectl describe nodes",
                "kubectl get pods -n {namespace} -o wide",
                "kubectl describe deployment {service} -n {namespace}",
                "kubectl get pdb -n {namespace}"
            ],
            "rollback_recommendation": "LOW - usually infrastructure issue, not deployment"
        },
        "failed_mount": {
            "steps": [
                "1. Check PVC status: kubectl get pvc -n <namespace>",
                "2. Verify storage class exists and is healthy",
                "3. Check EBS/EFS volume availability",
                "4. Review volume mount configuration in deployment"
            ],
            "kubectl_commands": [
                "kubectl get pvc -n {namespace}",
                "kubectl describe pvc {pvc_name} -n {namespace}",
                "kubectl get sc"
            ],
            "rollback_recommendation": "LOW - usually storage infrastructure issue"
        }
    }

    playbook = playbooks.get(incident_type, {
        "steps": ["Manual investigation required - unknown incident type"],
        "kubectl_commands": [],
        "rollback_recommendation": "UNKNOWN"
    })

    # Build comprehensive recommendation
    recommendations = {
        "incident_type": incident_type,
        "severity": severity,
        "timestamp": datetime.now().isoformat(),
        "remediation_playbook": playbook,
        "severity_actions": _get_severity_actions(severity),
        "immediate_actions": _get_immediate_actions(severity, incident_type),
        "requires_rollback": _calculate_rollback_requirement(severity, incident_type, context),
        "auto_remediation_available": incident_type in playbooks,
        "escalation_required": severity == "critical" and context.get("restart_count", 0) > RESTART_COUNT_ESCALATION
    }

    return {
        "content": [{
            "type": "text",
            "text": json.dumps(recommendations, indent=2)
        }]
    }


def _get_severity_actions(severity: str) -> Dict[str, Any]:
    """Get actions based on severity level"""
    actions = {
        "critical": {
            "response_time": "Immediate (< 5 minutes)",
            "automation_level": "Automated analysis with recommendations",
            "escalation": "Teams notification sent immediately, escalate if not resolved in 15 min",
            "rollback_authority": f"Rollback PR creation with >{ROLLBACK_THRESHOLD} confidence"
        },
        "high": {
            "response_time": "Rapid (< 15 minutes)",
            "automation_level": "Automated analysis with recommendations",
            "escalation": "Escalate if not resolved in 30 min",
            "rollback_authority": "Human approval required for rollback PR"
        },
        "medium": {
            "response_time": "Standard (< 1 hour)",
            "automation_level": "Monitoring and recommendations only",
            "escalation": "Queue for team review",
            "rollback_authority": "Not applicable"
        },
        "low": {
            "response_time": "Best effort",
            "automation_level": "Document and learn",
            "escalation": "None",
            "rollback_authority": "Not applicable"
        }
    }
    return actions.get(severity, actions["low"])


def _get_immediate_actions(severity: str, incident_type: str) -> List[str]:
    """Get immediate actions based on severity and type"""
    if severity == "critical":
        return [
            "Gather diagnostic information immediately",
            "Check deployment correlation",
            "Prepare rollback if deployment-related",
            "Alert on-call team"
        ]
    elif severity == "high":
        return [
            "Collect logs and events",
            "Analyze root cause",
            "Prepare remediation plan",
            "Monitor for escalation"
        ]
    else:
        return [
            "Document incident",
            "Queue for review",
            "Update monitoring if needed"
        ]


def _calculate_rollback_requirement(severity: str, incident_type: str, context: Dict) -> Dict[str, Any]:
    """Calculate if rollback is recommended"""
    # Factors that increase rollback likelihood
    factors = []
    score = 0.0

    # Severity factor
    if severity == "critical":
        score += ROLLBACK_SCORE_CRITICAL
        factors.append(f"Critical severity (+{ROLLBACK_SCORE_CRITICAL})")
    elif severity == "high":
        score += ROLLBACK_SCORE_HIGH
        factors.append(f"High severity (+{ROLLBACK_SCORE_HIGH})")

    # Incident type factor
    if incident_type in ["oom_killed", "crashloop"]:
        score += ROLLBACK_SCORE_INCIDENT_TYPE
        factors.append(f"{incident_type} type (+{ROLLBACK_SCORE_INCIDENT_TYPE})")

    # Restart count factor
    restart_count = context.get("restart_count", 0)
    if restart_count > RESTART_COUNT_CRITICAL:
        score += ROLLBACK_SCORE_HIGH_RESTARTS
        factors.append(f"High restart count {restart_count} (+{ROLLBACK_SCORE_HIGH_RESTARTS})")
    elif restart_count > RESTART_COUNT_WARNING:
        score += ROLLBACK_SCORE_ELEVATED_RESTARTS
        factors.append(f"Elevated restart count {restart_count} (+{ROLLBACK_SCORE_ELEVATED_RESTARTS})")

    # Recent deployment factor (would need correlation confidence from previous step)
    if context.get("deployment_correlation_confidence", 0) > ROLLBACK_THRESHOLD:
        score += ROLLBACK_SCORE_DEPLOYMENT
        factors.append(f"High deployment correlation (+{ROLLBACK_SCORE_DEPLOYMENT})")

    recommendation = "ROLLBACK" if score >= ROLLBACK_THRESHOLD else "INVESTIGATE" if score >= INVESTIGATE_THRESHOLD else "MONITOR"

    return {
        "recommendation": recommendation,
        "confidence": min(score, 1.0),
        "factors": factors,
        "threshold": f"{ROLLBACK_THRESHOLD} for rollback recommendation",
        "requires_approval": score >= ROLLBACK_THRESHOLD and score < 1.0
    }