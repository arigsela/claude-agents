"""
Custom Tools for OnCall Agent API
Uses direct Python libraries (kubernetes, PyGithub, boto3) instead of CLI commands

These are plain async functions (not decorated) for use with Anthropic SDK tool calling.
"""

import logging
import os
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from github import Github
from kubernetes import client, config

from tools.datadog_integrator import DatadogIntegrator

logger = logging.getLogger(__name__)


# ============================================================
# Kubernetes Tools (using kubernetes Python library)
# ============================================================


def _get_k8s_client():
    """Get initialized Kubernetes client"""
    try:
        config.load_incluster_config()
        logger.info("Loaded in-cluster Kubernetes config")
    except Exception:
        try:
            config.load_kube_config()
            logger.info("Loaded kubeconfig from file")
        except Exception as e:
            logger.error(f"Failed to load Kubernetes config: {e}")
            raise
    return client.CoreV1Api(), client.AppsV1Api()


async def list_namespaces(args: dict[str, Any]) -> dict[str, Any]:
    """List all namespaces in the cluster, optionally filtered by pattern."""
    pattern = args.get("pattern", "")

    try:
        v1, _ = _get_k8s_client()

        all_namespaces = v1.list_namespace()

        result = {"pattern": pattern, "namespaces": []}

        for ns in all_namespaces.items:
            ns_name = ns.metadata.name

            # If pattern provided, filter by it
            if pattern:
                if pattern.lower() in ns_name.lower():
                    result["namespaces"].append(
                        {
                            "name": ns_name,
                            "status": ns.status.phase,
                            "created": ns.metadata.creation_timestamp.isoformat(),
                        }
                    )
            else:
                result["namespaces"].append(
                    {
                        "name": ns_name,
                        "status": ns.status.phase,
                        "created": ns.metadata.creation_timestamp.isoformat(),
                    }
                )

        result["count"] = len(result["namespaces"])
        return result

    except Exception as e:
        logger.error(f"Error listing namespaces: {e}")
        return {"error": str(e), "pattern": pattern}


async def list_pods(args: dict[str, Any]) -> dict[str, Any]:
    """List pods in a Kubernetes namespace."""
    namespace = args.get("namespace")
    label_selector = args.get("label_selector", "")

    try:
        v1, _ = _get_k8s_client()

        pods = v1.list_namespaced_pod(namespace=namespace, label_selector=label_selector)

        result = {"namespace": namespace, "count": len(pods.items), "pods": []}

        for pod in pods.items:
            pod_info = {
                "name": pod.metadata.name,
                "status": pod.status.phase,
                "ready": sum(1 for c in pod.status.container_statuses or [] if c.ready),
                "total_containers": len(pod.spec.containers),
                "restarts": sum(c.restart_count for c in pod.status.container_statuses or []),
                "node": pod.spec.node_name,
                "created": pod.metadata.creation_timestamp.isoformat(),
            }

            # Add container status details
            if pod.status.container_statuses:
                pod_info["containers"] = []
                for container in pod.status.container_statuses:
                    container_info = {
                        "name": container.name,
                        "ready": container.ready,
                        "restarts": container.restart_count,
                        "state": {},
                    }

                    # Get current state
                    if container.state.running:
                        container_info["state"]["running"] = {
                            "started_at": container.state.running.started_at.isoformat()
                        }
                    elif container.state.waiting:
                        container_info["state"]["waiting"] = {
                            "reason": container.state.waiting.reason or "",
                            "message": container.state.waiting.message or "",
                        }
                    elif container.state.terminated:
                        container_info["state"]["terminated"] = {
                            "exit_code": container.state.terminated.exit_code,
                            "reason": container.state.terminated.reason or "",
                            "message": container.state.terminated.message or "",
                        }

                    pod_info["containers"].append(container_info)

            result["pods"].append(pod_info)

        return result

    except Exception as e:
        logger.error(f"Error listing pods: {e}")
        return {"error": str(e), "namespace": namespace}


async def get_pod_logs(args: dict[str, Any]) -> dict[str, Any]:
    """Get logs from a Kubernetes pod."""
    namespace = args.get("namespace")
    pod_name = args.get("pod_name")
    container = args.get("container", "")
    tail_lines = args.get("tail_lines", 100)

    try:
        v1, _ = _get_k8s_client()

        logs = v1.read_namespaced_pod_log(
            name=pod_name,
            namespace=namespace,
            container=container if container else None,
            tail_lines=tail_lines,
        )

        return {
            "pod": pod_name,
            "namespace": namespace,
            "container": container or "default",
            "tail_lines": tail_lines,
            "logs": logs,
        }

    except Exception as e:
        logger.error(f"Error getting pod logs: {e}")
        return {"error": str(e), "pod": pod_name, "namespace": namespace}


async def get_pod_events(args: dict[str, Any]) -> dict[str, Any]:
    """Get Kubernetes events for troubleshooting."""
    namespace = args.get("namespace")
    pod_name = args.get("pod_name", "")

    try:
        v1, _ = _get_k8s_client()

        events = v1.list_namespaced_event(namespace=namespace)

        result = {"namespace": namespace, "events": []}

        for event in events.items:
            # Filter by pod name if specified
            if pod_name and event.involved_object.name != pod_name:
                continue

            event_info = {
                "type": event.type,
                "reason": event.reason,
                "message": event.message,
                "object": {"kind": event.involved_object.kind, "name": event.involved_object.name},
                "count": event.count,
                "first_seen": event.first_timestamp.isoformat() if event.first_timestamp else None,
                "last_seen": event.last_timestamp.isoformat() if event.last_timestamp else None,
            }

            result["events"].append(event_info)

        # Sort by last seen, most recent first
        result["events"].sort(key=lambda x: x["last_seen"] or "", reverse=True)

        return result

    except Exception as e:
        logger.error(f"Error getting events: {e}")
        return {"error": str(e), "namespace": namespace}


async def get_deployment_status(args: dict[str, Any]) -> dict[str, Any]:
    """Get status of a Kubernetes deployment."""
    namespace = args.get("namespace")
    deployment_name = args.get("deployment_name", "")

    try:
        _, apps_v1 = _get_k8s_client()

        if deployment_name:
            deployment = apps_v1.read_namespaced_deployment(
                name=deployment_name, namespace=namespace
            )
            deployments = [deployment]
        else:
            deployment_list = apps_v1.list_namespaced_deployment(namespace=namespace)
            deployments = deployment_list.items

        result = {"namespace": namespace, "deployments": []}

        for dep in deployments:
            dep_info = {
                "name": dep.metadata.name,
                "replicas": {
                    "desired": dep.spec.replicas,
                    "ready": dep.status.ready_replicas or 0,
                    "available": dep.status.available_replicas or 0,
                    "unavailable": dep.status.unavailable_replicas or 0,
                },
                "conditions": [],
            }

            if dep.status.conditions:
                for condition in dep.status.conditions:
                    dep_info["conditions"].append(
                        {
                            "type": condition.type,
                            "status": condition.status,
                            "reason": condition.reason or "",
                            "message": condition.message or "",
                        }
                    )

            result["deployments"].append(dep_info)

        return result

    except Exception as e:
        logger.error(f"Error getting deployment status: {e}")
        return {"error": str(e), "namespace": namespace, "deployment": deployment_name}


async def list_services(args: dict[str, Any]) -> dict[str, Any]:
    """List Kubernetes Services with their label selectors.

    This tool retrieves Service definitions and inspects their selectors,
    which is useful for identifying services that may have issues with
    label selector configurations (e.g., using version labels).

    Args:
        namespace: Target namespace (optional - if not provided, lists across all namespaces)
        service_name: Specific service name to inspect (optional)
        check_label: Specific label key to check in selectors (e.g., "app.kubernetes.io/version")

    Returns:
        Dictionary with service information including selectors
    """
    namespace = args.get("namespace", "")
    service_name = args.get("service_name", "")
    check_label = args.get("check_label", "")

    try:
        v1, _ = _get_k8s_client()

        result = {"services": [], "total_count": 0, "filtered_count": 0}

        # Add query context to result
        if namespace:
            result["namespace"] = namespace
        else:
            result["scope"] = "all-namespaces"

        if check_label:
            result["filtered_by_label"] = check_label

        # Determine query scope
        if namespace and service_name:
            # Specific service in specific namespace
            service = v1.read_namespaced_service(name=service_name, namespace=namespace)
            services = [service]
        elif namespace:
            # All services in specific namespace
            service_list = v1.list_namespaced_service(namespace=namespace)
            services = service_list.items
        else:
            # All services across all namespaces
            service_list = v1.list_service_for_all_namespaces()
            services = service_list.items

        result["total_count"] = len(services)

        # Process each service
        for svc in services:
            service_info = {
                "name": svc.metadata.name,
                "namespace": svc.metadata.namespace,
                "type": svc.spec.type,
                "cluster_ip": svc.spec.cluster_ip,
                "selector": svc.spec.selector or {},
                "ports": [],
            }

            # Extract port information
            if svc.spec.ports:
                for port in svc.spec.ports:
                    service_info["ports"].append(
                        {
                            "name": port.name or "",
                            "protocol": port.protocol,
                            "port": port.port,
                            "target_port": str(port.target_port) if port.target_port else "",
                        }
                    )

            # If checking for specific label, filter results
            if check_label:
                if check_label in service_info["selector"]:
                    service_info["label_issue"] = {
                        "problematic_label": check_label,
                        "value": service_info["selector"][check_label],
                        "warning": f"Service selector uses '{check_label}' which may cause routing issues during deployments",
                    }
                    result["services"].append(service_info)
                    result["filtered_count"] += 1
            else:
                # No filter, include all services
                result["services"].append(service_info)
                result["filtered_count"] += 1

        # Add analysis summary if checking for specific label
        if check_label and result["filtered_count"] > 0:
            result["analysis"] = {
                "issue": f"Found {result['filtered_count']} service(s) using '{check_label}' in selector",
                "impact": "Services using version labels in selectors won't route traffic to new versions during rolling updates",
                "recommendation": "Update service selectors to use stable labels like 'app.kubernetes.io/name' or 'app.kubernetes.io/instance' instead",
            }
        elif check_label and result["filtered_count"] == 0:
            result["analysis"] = {
                "status": "healthy",
                "message": f"No services found using '{check_label}' in selector - good practice!",
            }

        return result

    except Exception as e:
        logger.error(f"Error listing services: {e}")
        return {"error": str(e), "namespace": namespace or "all", "service_name": service_name}


# ============================================================
# GitHub Tools (using PyGithub)
# ============================================================


def _get_github_client():
    """Get initialized GitHub client"""
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        raise ValueError("GITHUB_TOKEN not set")
    return Github(token)


async def search_recent_deployments(args: dict[str, Any]) -> dict[str, Any]:
    """Search for recent GitHub Actions deployments."""
    repo_name = args.get("repo_name")
    hours_back = args.get("hours_back", 24)
    workflow_name = args.get("workflow_name", "")

    try:
        gh = _get_github_client()
        repo = gh.get_repo(repo_name)

        since = datetime.now() - timedelta(hours=hours_back)

        runs = repo.get_workflow_runs(created=f">={since.isoformat()}")

        result = {"repository": repo_name, "hours_back": hours_back, "deployments": []}

        for run in runs[:10]:  # Limit to 10 most recent
            # Filter by workflow name if specified
            if workflow_name and workflow_name.lower() not in run.name.lower():
                continue

            run_info = {
                "id": run.id,
                "name": run.name,
                "status": run.status,
                "conclusion": run.conclusion,
                "created_at": run.created_at.isoformat(),
                "updated_at": run.updated_at.isoformat(),
                "head_branch": run.head_branch,
                "head_sha": run.head_sha[:8],
                "url": run.html_url,
            }

            result["deployments"].append(run_info)

        return result

    except Exception as e:
        logger.error(f"Error searching deployments: {e}")
        return {"error": str(e), "repository": repo_name}


async def get_recent_commits(args: dict[str, Any]) -> dict[str, Any]:
    """Get recent commits from a GitHub repository."""
    repo_name = args.get("repo_name")
    branch = args.get("branch", "main")
    limit = args.get("limit", 5)

    try:
        gh = _get_github_client()
        repo = gh.get_repo(repo_name)

        commits = repo.get_commits(sha=branch)

        result = {"repository": repo_name, "branch": branch, "commits": []}

        for commit in list(commits[:limit]):
            commit_info = {
                "sha": commit.sha[:8],
                "message": commit.commit.message.split("\n")[0],  # First line only
                "author": commit.commit.author.name,
                "date": commit.commit.author.date.isoformat(),
                "url": commit.html_url,
            }

            result["commits"].append(commit_info)

        return result

    except Exception as e:
        logger.error(f"Error getting commits: {e}")
        return {"error": str(e), "repository": repo_name}


# ============================================================
# AWS Tools (using boto3)
# ============================================================


async def check_secrets_manager(args: dict[str, Any]) -> dict[str, Any]:
    """Check if a secret exists in AWS Secrets Manager."""
    secret_name = args.get("secret_name")
    region = args.get("region", "us-east-1")

    try:
        import boto3

        secrets_client = boto3.client("secretsmanager", region_name=region)

        try:
            response = secrets_client.describe_secret(SecretId=secret_name)

            return {
                "exists": True,
                "name": response["Name"],
                "arn": response["ARN"],
                "last_changed": (
                    response.get("LastChangedDate", "").isoformat()
                    if response.get("LastChangedDate")
                    else None
                ),
                "region": region,
            }
        except secrets_client.exceptions.ResourceNotFoundException:
            return {"exists": False, "name": secret_name, "region": region}

    except Exception as e:
        logger.error(f"Error checking secret: {e}")
        return {"error": str(e), "secret_name": secret_name}


async def check_ecr_image(args: dict[str, Any]) -> dict[str, Any]:
    """Check if a container image exists in ECR."""
    repository = args.get("repository")
    tag = args.get("tag", "latest")
    region = args.get("region", "us-east-1")

    try:
        import boto3

        ecr_client = boto3.client("ecr", region_name=region)

        try:
            response = ecr_client.describe_images(
                repositoryName=repository, imageIds=[{"imageTag": tag}]
            )

            if response["imageDetails"]:
                image = response["imageDetails"][0]
                return {
                    "exists": True,
                    "repository": repository,
                    "tag": tag,
                    "digest": image.get("imageDigest", "")[:16],
                    "size_mb": round(image.get("imageSizeInBytes", 0) / 1024 / 1024, 2),
                    "pushed_at": (
                        image.get("imagePushedAt", "").isoformat()
                        if image.get("imagePushedAt")
                        else None
                    ),
                    "region": region,
                }
            else:
                return {"exists": False, "repository": repository, "tag": tag, "region": region}

        except ecr_client.exceptions.ImageNotFoundException:
            return {"exists": False, "repository": repository, "tag": tag, "region": region}

    except Exception as e:
        logger.error(f"Error checking ECR image: {e}")
        return {"error": str(e), "repository": repository}


# ============================================================
# Analysis Tools (combining multiple data sources)
# ============================================================


async def analyze_service_health(args: dict[str, Any]) -> dict[str, Any]:
    """Comprehensive health analysis of a Kubernetes service."""
    service_name = args.get("service_name")
    namespace = args.get("namespace")

    try:
        result = {
            "service": service_name,
            "namespace": namespace,
            "timestamp": datetime.now().isoformat(),
            "health_score": "unknown",
            "issues": [],
        }

        # 1. Check pods
        pods_data = await list_pods(
            {"namespace": namespace, "label_selector": f"app={service_name}"}
        )
        result["pods"] = pods_data

        # 2. Check deployment
        deployment_data = await get_deployment_status(
            {"namespace": namespace, "deployment_name": service_name}
        )
        result["deployment"] = deployment_data

        # 3. Check events for issues
        events_data = await get_pod_events({"namespace": namespace, "pod_name": ""})

        # Filter events related to this service
        service_events = [
            e
            for e in events_data.get("events", [])
            if service_name in e.get("object", {}).get("name", "")
        ]
        result["recent_events"] = service_events[:10]

        # 4. Analyze health
        if pods_data.get("error"):
            result["health_score"] = "error"
            result["issues"].append(f"Failed to query pods: {pods_data['error']}")
        else:
            # Check for unhealthy pods
            total_pods = pods_data.get("count", 0)
            unhealthy_pods = [
                p
                for p in pods_data.get("pods", [])
                if p["status"] != "Running" or p["ready"] < p["total_containers"]
            ]

            if unhealthy_pods:
                result["health_score"] = "unhealthy"
                result["issues"].append(f"{len(unhealthy_pods)}/{total_pods} pods unhealthy")
            else:
                result["health_score"] = "healthy"

        # Check for high restart counts
        high_restart_pods = [p for p in pods_data.get("pods", []) if p.get("restarts", 0) > 3]

        if high_restart_pods:
            result["issues"].append(f"{len(high_restart_pods)} pods with high restart counts")

        # Check for warning events
        warning_events = [e for e in service_events if e.get("type") == "Warning"]
        if warning_events:
            result["issues"].append(f"{len(warning_events)} warning events in last 10 minutes")

        return result

    except Exception as e:
        logger.error(f"Error analyzing service health: {e}")
        return {"error": str(e), "service": service_name, "namespace": namespace}


async def correlate_deployment_with_incidents(args: dict[str, Any]) -> dict[str, Any]:
    """Correlate recent K8s incidents with GitHub deployments."""
    service_name = args.get("service_name")
    namespace = args.get("namespace")
    github_repo = args.get("github_repo")

    try:
        result = {"service": service_name, "namespace": namespace, "correlation": "none"}

        # Get recent events
        events_data = await get_pod_events({"namespace": namespace, "pod_name": ""})
        service_events = [
            e
            for e in events_data.get("events", [])
            if service_name in e.get("object", {}).get("name", "") and e.get("type") == "Warning"
        ]

        if not service_events:
            result["correlation"] = "no_recent_incidents"
            return result

        # Get recent deployments
        deployments = await search_recent_deployments({"repo_name": github_repo, "hours_back": 6})

        if deployments.get("error") or not deployments.get("deployments"):
            result["recent_deployments"] = []
            return result

        result["recent_deployments"] = deployments["deployments"]

        # Check for failed deployments
        failed_deployments = [
            d for d in deployments["deployments"] if d.get("conclusion") == "failure"
        ]

        if failed_deployments and service_events:
            result["correlation"] = "likely_related"
            result["analysis"] = (
                f"Found {len(failed_deployments)} failed deployments and "
                f"{len(service_events)} warning events - incidents may be related to deployment"
            )
        elif deployments["deployments"] and service_events:
            result["correlation"] = "possible"
            result["analysis"] = (
                "Recent deployments detected. Check timing correlation between "
                "deployment and incidents"
            )

        return result

    except Exception as e:
        logger.error(f"Error correlating deployment: {e}")
        return {"error": str(e), "service": service_name}


# ============================================================
# NAT Gateway Tools (using boto3 CloudWatch + NATGatewayAnalyzer)
# ============================================================


async def check_nat_gateway_metrics(args: dict[str, Any]) -> dict[str, Any]:
    """
    Check AWS NAT gateway traffic metrics for recent spikes or historical analysis.

    Supports multiple NAT gateways (multi-AZ deployments). When NAT_GATEWAY_IDS
    contains multiple comma-separated IDs, fetches and aggregates metrics from all.

    Use this when user asks about:
    - NAT gateway traffic or spikes
    - Network bandwidth usage
    - Datadog NAT alerts
    - Why NAT egress is high

    Args:
        time_window_hours: Hours to look back (1-168, default: 1)
        nat_gateway_id: Specific NAT gateway ID (optional - if not provided, queries all configured gateways)
        all_gateways: If true, always query all configured gateways (default: true when multiple configured)

    Returns:
        Traffic metrics with spike detection and human-readable summary
    """
    from tools.nat_gateway_analyzer import get_analyzer, DEFAULT_NAT_GATEWAY_IDS

    time_window_hours = args.get("time_window_hours", 1)
    specific_gateway = args.get("nat_gateway_id")
    query_all = args.get("all_gateways", len(DEFAULT_NAT_GATEWAY_IDS) > 1)

    try:
        analyzer = get_analyzer()

        # If specific gateway requested or only one configured, use single-gateway mode
        if specific_gateway or (not query_all and len(DEFAULT_NAT_GATEWAY_IDS) == 1):
            gateway_id = specific_gateway or DEFAULT_NAT_GATEWAY_IDS[0] if DEFAULT_NAT_GATEWAY_IDS else ""
            if not gateway_id:
                return {
                    "error": "No NAT gateway ID configured. Set NAT_GATEWAY_IDS environment variable.",
                    "time_window_hours": time_window_hours,
                }

            metrics = analyzer.fetch_nat_metrics(
                nat_gateway_id=gateway_id, time_window_hours=time_window_hours
            )
            summary = analyzer.format_metrics_for_llm(metrics)

            return {
                "summary": summary,
                "metrics": metrics.to_dict(),
                "spikes_count": len(metrics.spikes_detected),
                "total_egress_gb": round(metrics.total_bytes_out / (1024**3), 3),
                "mode": "single_gateway",
            }

        # Multi-gateway mode - fetch and aggregate from all configured gateways
        aggregated = analyzer.fetch_all_nat_metrics(time_window_hours=time_window_hours)
        summary = analyzer.format_aggregated_metrics_for_llm(aggregated)

        return {
            "summary": summary,
            "metrics": aggregated.to_dict(),
            "spikes_count": len(aggregated.all_spikes),
            "total_egress_gb": round(aggregated.total_bytes_out / (1024**3), 3),
            "gateway_count": len(aggregated.nat_gateway_ids),
            "mode": "multi_gateway",
        }

    except ValueError as e:
        logger.warning(f"Validation error in NAT metrics query: {e}")
        return {
            "error": str(e),
            "time_window_hours": time_window_hours,
        }
    except Exception as e:
        logger.error(f"Error fetching NAT metrics: {e}")
        return {
            "error": f"Failed to fetch NAT gateway metrics: {str(e)}",
        }


async def find_zeus_jobs_during_timeframe(args: dict[str, Any]) -> dict[str, Any]:
    """
    Find Zeus refresh jobs running during a specific time window, including log analysis.

    Use this when user asks about:
    - Which Zeus jobs were running at a specific time
    - What refresh operations happened recently
    - Which clients had refreshes during a period

    Args:
        start_time: Start of time window (ISO format)
        end_time: End of time window (ISO format)
        namespace: Optional specific namespace (default: searches all Zeus namespaces)

    Returns:
        List of Zeus refresh jobs with metadata and log analysis
    """
    from datetime import datetime

    from tools.zeus_job_correlator import get_correlator

    start_time_str = args.get("start_time")
    end_time_str = args.get("end_time")
    namespace = args.get("namespace")

    try:
        # Parse timestamps
        start_time = datetime.fromisoformat(start_time_str.replace("Z", "+00:00"))
        end_time = datetime.fromisoformat(end_time_str.replace("Z", "+00:00"))

        correlator = get_correlator()

        # Find jobs
        jobs = correlator.find_refresh_jobs(
            start_time=start_time, end_time=end_time, namespace=namespace
        )

        if not jobs:
            return {
                "jobs_found": 0,
                "time_window": {"start": start_time_str, "end": end_time_str},
                "message": "No Zeus refresh jobs found during this time window",
            }

        # Analyze logs for each job
        results = []
        for job in jobs:
            job_dict = job.to_dict()

            # Get log analysis
            log_analysis = correlator.analyze_job_logs(
                job_name=job.job_name, namespace=job.namespace, tail_lines=1000
            )

            job_dict["log_analysis"] = log_analysis.to_dict()

            results.append(job_dict)

        # Format summary
        summary = f"Found {len(jobs)} Zeus refresh jobs:\n"
        for idx, job in enumerate(jobs, 1):
            summary += f"\n{idx}. {job.job_name}\n"
            summary += f"   Client: {job.client_name or 'Unknown'}\n"
            summary += f"   Type: {job.refresh_type or 'Unknown'}\n"
            summary += f"   Status: {job.status}\n"
            summary += (
                f"   Duration: {job.duration_minutes:.1f} min\n"
                if job.duration_minutes
                else "   Duration: Running\n"
            )

        return {
            "jobs_found": len(jobs),
            "time_window": {"start": start_time_str, "end": end_time_str},
            "summary": summary,
            "jobs": results,
        }

    except ValueError as e:
        logger.warning(f"Invalid timestamp format: {e}")
        return {
            "error": f"Invalid timestamp format. Use ISO 8601: {str(e)}",
            "start_time": start_time_str,
            "end_time": end_time_str,
        }
    except Exception as e:
        logger.error(f"Error finding Zeus jobs: {e}")
        return {"error": f"Failed to find Zeus jobs: {str(e)}"}


async def correlate_nat_spike_with_zeus_jobs(args: dict[str, Any]) -> dict[str, Any]:
    """
    Correlate a NAT gateway traffic spike with Zeus refresh jobs to identify the cause.

    This is the primary correlation tool that combines NAT metrics with Zeus job discovery.

    Use this when user asks:
    - "What caused the NAT spike at {time}?"
    - "Why did NAT traffic spike?"
    - Investigating Datadog NAT alerts

    Args:
        spike_timestamp: Timestamp of the spike (ISO format or relative like "2am")
        time_window_minutes: Correlation window in minutes (default: 30)

    Returns:
        Complete correlation with NAT metrics, Zeus jobs, log analysis, and confidence scoring
    """
    from datetime import datetime, timedelta

    from tools.zeus_job_correlator import get_correlator

    from tools.nat_gateway_analyzer import get_analyzer

    spike_timestamp_str = args.get("spike_timestamp")
    time_window_minutes = args.get("time_window_minutes", 30)

    try:
        # Parse spike timestamp
        # Handle relative times like "2am" -> convert to today 02:00:00
        if spike_timestamp_str.lower().endswith("am") or spike_timestamp_str.lower().endswith("pm"):
            # Simple hour parsing (e.g., "2am" -> 02:00)
            hour_match = re.match(r"(\d+)(am|pm)", spike_timestamp_str.lower())
            if hour_match:
                hour = int(hour_match.group(1))
                am_pm = hour_match.group(2)
                if am_pm == "pm" and hour != 12:
                    hour += 12
                elif am_pm == "am" and hour == 12:
                    hour = 0

                spike_timestamp = datetime.now(UTC).replace(
                    hour=hour, minute=0, second=0, microsecond=0
                )
            else:
                spike_timestamp = datetime.fromisoformat(spike_timestamp_str.replace("Z", "+00:00"))
        else:
            spike_timestamp = datetime.fromisoformat(spike_timestamp_str.replace("Z", "+00:00"))

        # Step 1: Verify spike exists in NAT metrics
        nat_analyzer = get_analyzer()

        # Fetch metrics for ±1 hour around spike
        nat_metrics = nat_analyzer.fetch_nat_metrics(
            time_window_hours=2,
            start_time=spike_timestamp - timedelta(hours=1),
            end_time=spike_timestamp + timedelta(hours=1),
        )

        # Find the specific spike
        spike_confirmed = any(
            abs(datetime.fromisoformat(s["timestamp"]) - spike_timestamp).total_seconds() < 300
            for s in nat_metrics.spikes_detected
        )

        # Step 2: Find Zeus jobs during correlation window
        correlator = get_correlator()
        jobs = correlator.find_refresh_jobs(
            start_time=spike_timestamp - timedelta(minutes=time_window_minutes),
            end_time=spike_timestamp + timedelta(minutes=time_window_minutes),
        )

        # Step 3: Analyze logs for each job
        log_analyses = {}
        for job in jobs:
            log_analysis = correlator.analyze_job_logs(job.job_name, job.namespace)
            log_analyses[job.job_name] = log_analysis

        # Step 4: Correlate jobs with spike timing
        correlated_jobs = correlator.correlate_jobs_with_spike(
            spike_timestamp=spike_timestamp, jobs=jobs, time_window_minutes=time_window_minutes
        )

        # Step 5: NEW - Get Datadog pod network metrics for correlation window
        logger.info("Querying Datadog for pod-level network traffic during spike window...")

        # Get unique namespaces from correlated jobs
        job_namespaces = list({job.namespace for job in jobs}) if jobs else []

        # Also check common Zeus namespaces
        zeus_namespaces = ["preprod", "qa", "prod", "devmatt", "devjeff", "devjason"]
        all_namespaces = list(set(job_namespaces + zeus_namespaces))

        datadog_network_data = {}
        high_traffic_pods = []

        # Query Datadog for network traffic in relevant namespaces
        for ns in all_namespaces[:5]:  # Limit to 5 namespaces to avoid too many API calls
            try:
                network_result = await check_network_traffic(
                    {
                        "namespace": ns,
                        "time_window_hours": max(2, time_window_minutes // 30),  # At least 2 hours
                    }
                )

                if network_result.get("summary", {}).get("totals"):
                    totals = network_result["summary"]["totals"]
                    datadog_network_data[ns] = totals

                    # Flag high traffic pods (>1GB TX)
                    if totals.get("tx_gb", 0) > 1.0:
                        high_traffic_pods.append(
                            {
                                "namespace": ns,
                                "tx_gb": totals["tx_gb"],
                                "rx_gb": totals.get("rx_gb", 0),
                            }
                        )
                        logger.info(
                            f"  → High traffic detected in {ns}: {totals['tx_gb']:.2f} GB TX"
                        )

            except Exception as e:
                logger.warning(f"Could not get Datadog metrics for {ns}: {e}")

        # Calculate Datadog total across namespaces
        total_datadog_tx_gb = sum(data.get("tx_gb", 0) for data in datadog_network_data.values())

        logger.info(
            f"✓ Datadog pod network data: {len(datadog_network_data)} namespaces, {total_datadog_tx_gb:.2f} GB total TX"
        )

        # Step 6: Format for LLM with enhanced Datadog correlation
        spike_info = {
            "timestamp": spike_timestamp.isoformat(),
            "bytes_gb": nat_metrics.total_bytes_out / (1024**3),
            "nat_gateway_id": nat_metrics.nat_gateway_id,
            "spike_confirmed": spike_confirmed,
        }

        formatted_output = correlator.format_correlation_for_llm(
            spike_info=spike_info, correlated_jobs=correlated_jobs, log_analyses=log_analyses
        )

        # Add Datadog network analysis to output
        if datadog_network_data:
            datadog_summary = "\n\n## DATADOG POD-LEVEL NETWORK ANALYSIS\n\n"
            datadog_summary += f"Total pod traffic (Datadog): {total_datadog_tx_gb:.2f} GB TX\n"
            datadog_summary += (
                f"NAT gateway traffic (CloudWatch): {spike_info['bytes_gb']:.2f} GB\n\n"
            )

            if high_traffic_pods:
                datadog_summary += "🔴 High-traffic namespaces detected:\n"
                for pod_data in sorted(high_traffic_pods, key=lambda x: x["tx_gb"], reverse=True):
                    datadog_summary += f"  • {pod_data['namespace']}: {pod_data['tx_gb']:.2f} GB TX ({pod_data['tx_gb']/spike_info['bytes_gb']*100:.1f}% of NAT spike)\n"
            else:
                datadog_summary += "ℹ️  No individual pods with >1GB traffic detected\n"

            datadog_summary += f"\nNamespaces analyzed: {', '.join(datadog_network_data.keys())}\n"

            formatted_output += datadog_summary

        return {
            "correlation_summary": formatted_output,
            "spike_confirmed": spike_confirmed,
            "jobs_found": len(jobs),
            "highest_confidence": correlated_jobs[0]["confidence"] if correlated_jobs else 0,
            "nat_metrics": nat_metrics.to_dict(),
            "correlated_jobs": correlated_jobs,
            "datadog_network_data": datadog_network_data,
            "high_traffic_pods": high_traffic_pods,
            "total_pod_traffic_gb": total_datadog_tx_gb,
        }

    except ValueError as e:
        logger.warning(f"Validation error in correlation: {e}")
        return {"error": str(e), "spike_timestamp": spike_timestamp_str}
    except Exception as e:
        logger.error(f"Error correlating NAT spike: {e}")
        return {"error": f"Failed to correlate spike: {str(e)}"}


# ============================================================
# Datadog Tools (using datadog-api-client)
# ============================================================


async def query_datadog_metrics(params: dict[str, Any]) -> dict[str, Any]:
    """
    Query Datadog metrics for Kubernetes resources.

    Use this when user asks about:
    - Historical performance metrics (CPU, memory over time)
    - Resource usage trends
    - Performance before/after deployments
    - Gradual degradation patterns

    Args:
        params: {
            "metric": str,  # e.g., "kubernetes.cpu.usage", "kubernetes.memory.rss"
            "namespace": str,
            "pod_name": str (optional),
            "time_window_hours": int (default: 1),
            "aggregation": str (default: "avg")  # avg, max, min, sum
        }

    Returns:
        Timeseries data with timestamps and values

    Example usage:
        query_datadog_metrics({
            "metric": "kubernetes.cpu.usage",
            "namespace": "proteus-dev",
            "time_window_hours": 24
        })
    """
    try:
        integrator = DatadogIntegrator()

        metric = params.get("metric")
        namespace = params.get("namespace")
        pod_name = params.get("pod_name")
        hours = params.get("time_window_hours", 1)
        aggregation = params.get("aggregation", "avg")

        if not metric or not namespace:
            return {
                "error": "metric and namespace are required parameters",
                "usage": "query_datadog_metrics(metric='kubernetes.cpu.usage', namespace='proteus-dev')",
                "available_metrics": [
                    "kubernetes.cpu.usage",
                    "kubernetes.memory.rss",
                    "kubernetes.memory.working_set",
                    "kubernetes.network.tx_bytes",
                    "kubernetes.network.rx_bytes",
                ],
            }

        logger.info(
            f"Querying Datadog: {metric} in {namespace}, pod={pod_name or 'all'}, hours={hours}"
        )

        result = await integrator.query_pod_metrics(
            metric=metric,
            namespace=namespace,
            pod_name=pod_name,
            hours_back=hours,
            aggregation=aggregation,
        )

        # Add human-readable summary
        if result.get("series"):
            total_points = sum(len(s.get("pointlist", [])) for s in result["series"])
            summary = {
                "metric": metric,
                "namespace": namespace,
                "pod_name": pod_name or "all pods",
                "time_window": f"Last {hours} hour(s)",
                "aggregation": aggregation,
                "data_points": total_points,
                "series_count": len(result["series"]),
            }
            result["summary"] = summary
            logger.info(
                f"✓ Retrieved {total_points} data points across {len(result['series'])} series"
            )
        elif result.get("error"):
            logger.warning(f"Datadog query failed: {result['error']}")
        else:
            result["summary"] = {
                "metric": metric,
                "namespace": namespace,
                "message": "No data available for this query",
            }

        return result

    except Exception as e:
        logger.error(f"Error querying Datadog metrics: {e}", exc_info=True)
        return {
            "error": str(e),
            "metric": params.get("metric"),
            "namespace": params.get("namespace"),
        }


async def get_resource_usage_trends(params: dict[str, Any]) -> dict[str, Any]:
    """
    Get CPU and memory usage trends for a service over time.

    Useful for identifying:
    - Memory leaks (gradual memory increase)
    - Resource exhaustion patterns
    - Performance degradation over time
    - Pre/post deployment resource changes

    Args:
        params: {
            "namespace": str,
            "pod_name": str (optional),
            "time_window_hours": int (default: 24)
        }

    Returns:
        Combined CPU and memory trends with analysis

    Example usage:
        get_resource_usage_trends({
            "namespace": "artemis-auth-dev",
            "time_window_hours": 168  # 1 week
        })
    """
    try:
        integrator = DatadogIntegrator()

        namespace = params.get("namespace")
        pod_name = params.get("pod_name")
        hours = params.get("time_window_hours", 24)

        if not namespace:
            return {
                "error": "namespace is required",
                "usage": "get_resource_usage_trends(namespace='proteus-dev', time_window_hours=24)",
            }

        logger.info(
            f"Getting resource usage trends for namespace={namespace}, pod={pod_name or 'all'}, hours={hours}"
        )

        # Get both CPU and memory metrics
        result = await integrator.query_container_metrics(
            namespace=namespace, container_name=pod_name, hours_back=hours
        )

        # Add analysis summary
        analysis = {
            "namespace": namespace,
            "pod_name": pod_name or "all pods",
            "time_window": f"Last {hours} hour(s)",
            "metrics_retrieved": list(result.keys()),
            "timestamp": datetime.now().isoformat(),
        }

        # Check if we have data for trend analysis
        has_data = any(
            r.get("series") and len(r.get("series", [])) > 0
            for r in result.values()
            if isinstance(r, dict)
        )

        if has_data:
            analysis["data_availability"] = "Metrics available for trend analysis"
            logger.info(f"✓ Resource trends available for {namespace}")
        else:
            analysis["data_availability"] = (
                "No metrics data available - check if Datadog agent is collecting from this namespace"
            )
            logger.warning(f"No resource trend data for {namespace}")

        result["analysis"] = analysis

        return result

    except Exception as e:
        logger.error(f"Error getting resource trends: {e}", exc_info=True)
        return {"error": str(e), "namespace": params.get("namespace")}


async def check_network_traffic(params: dict[str, Any]) -> dict[str, Any]:
    """
    Check network traffic patterns for pods.

    Useful for:
    - Identifying traffic spikes
    - Correlating with NAT gateway usage
    - Network error investigation
    - Bandwidth analysis

    Args:
        params: {
            "namespace": str,
            "pod_name": str (optional),
            "time_window_hours": int (default: 1)
        }

    Returns:
        Network TX/RX metrics and error rates

    Example usage:
        check_network_traffic({
            "namespace": "zeus-dev",
            "time_window_hours": 2
        })
    """
    try:
        integrator = DatadogIntegrator()

        namespace = params.get("namespace")
        pod_name = params.get("pod_name")
        hours = params.get("time_window_hours", 1)

        if not namespace:
            return {
                "error": "namespace is required",
                "usage": "check_network_traffic(namespace='zeus-dev', time_window_hours=2)",
            }

        logger.info(
            f"Checking network traffic for namespace={namespace}, pod={pod_name or 'all'}, hours={hours}"
        )

        result = await integrator.query_network_metrics(
            namespace=namespace, pod_name=pod_name, hours_back=hours
        )

        # Add summary
        summary = {
            "namespace": namespace,
            "pod_name": pod_name or "all pods",
            "time_window": f"Last {hours} hour(s)",
            "metrics": list(result.keys()),
            "timestamp": datetime.now().isoformat(),
        }

        # Calculate totals if data available
        total_tx_bytes = 0
        total_rx_bytes = 0

        for metric_name, metric_data in result.items():
            if isinstance(metric_data, dict) and metric_data.get("series"):
                for series in metric_data["series"]:
                    pointlist = series.get("pointlist", [])
                    if pointlist and "tx_bytes" in metric_name:
                        # Sum of last values for TX (ensure numeric conversion)
                        for point in pointlist:
                            if point[1]:
                                try:
                                    total_tx_bytes += float(point[1])
                                except (ValueError, TypeError):
                                    continue
                    elif pointlist and "rx_bytes" in metric_name:
                        # Sum of last values for RX (ensure numeric conversion)
                        for point in pointlist:
                            if point[1]:
                                try:
                                    total_rx_bytes += float(point[1])
                                except (ValueError, TypeError):
                                    continue

        if total_tx_bytes > 0 or total_rx_bytes > 0:
            summary["totals"] = {
                "tx_gb": round(total_tx_bytes / (1024**3), 3),
                "rx_gb": round(total_rx_bytes / (1024**3), 3),
                "total_gb": round((total_tx_bytes + total_rx_bytes) / (1024**3), 3),
            }
            logger.info(
                f"✓ Network traffic: TX={summary['totals']['tx_gb']} GB, RX={summary['totals']['rx_gb']} GB"
            )
        else:
            summary["message"] = "No network traffic data available"
            logger.warning(f"No network traffic data for {namespace}")

        result["summary"] = summary

        return result

    except Exception as e:
        logger.error(f"Error checking network traffic: {e}", exc_info=True)
        return {"error": str(e), "namespace": params.get("namespace")}


# ============================================================
# Zeus Refresh Job Analysis Tools (using Zeus Analyzer)
# ============================================================


async def analyze_zeus_refreshes(args: dict[str, Any]) -> dict[str, Any]:
    """
    Comprehensive analysis of Zeus refresh jobs combining Kubernetes + Datadog logs + metrics.

    This tool provides detailed information about Zeus data refresh jobs including:
    - Job status and duration
    - Client names and refresh types (extracted from logs)
    - Databricks job IDs and execution details
    - Resource usage (CPU, memory, network)
    - Error messages and failures

    Args:
        hours_back: Number of hours to look back (default: 1)
        client_name: Optional filter by client name
        status: Optional filter by status (Running, Succeeded, Failed)
        include_logs: Whether to enrich with Datadog logs (default: True)
        include_metrics: Whether to enrich with Datadog metrics (default: True)

    Returns:
        Dictionary with comprehensive Zeus job analysis
    """
    from tools.zeus_analyzer import ZeusAnalyzer

    hours_back = args.get("hours_back", 1)
    client_name = args.get("client_name")
    status = args.get("status")
    include_logs = args.get("include_logs", True)
    include_metrics = args.get("include_metrics", True)

    try:
        analyzer = ZeusAnalyzer()

        result = await analyzer.analyze_zeus_refreshes(
            hours_back=hours_back,
            client_name=client_name,
            status=status,
            include_logs=include_logs,
            include_metrics=include_metrics,
        )

        return result

    except Exception as e:
        logger.error(f"Error analyzing Zeus refreshes: {e}", exc_info=True)
        return {
            "error": str(e),
            "hours_back": hours_back,
            "client_name": client_name,
            "status": status,
        }


async def get_zeus_job_details(args: dict[str, Any]) -> dict[str, Any]:
    """
    Get detailed information about a specific Zeus refresh job.

    Args:
        job_name: Name of the Zeus job (e.g., "zeus-refresh-abc-12345")
        namespace: Namespace where the job runs (e.g., "qa", "devmatt")
        include_logs: Whether to include Datadog logs (default: True)
        include_metrics: Whether to include metrics (default: True)

    Returns:
        Dictionary with detailed job information
    """
    from tools.zeus_analyzer import ZeusAnalyzer

    job_name = args.get("job_name")
    namespace = args.get("namespace")
    include_logs = args.get("include_logs", True)
    include_metrics = args.get("include_metrics", True)

    if not job_name or not namespace:
        return {
            "error": "Both job_name and namespace are required",
            "job_name": job_name,
            "namespace": namespace,
        }

    try:
        analyzer = ZeusAnalyzer()

        # Find the specific job
        from datetime import datetime, timedelta

        start_time = datetime.now(UTC) - timedelta(days=7)  # Look back 7 days

        jobs = analyzer.find_zeus_jobs(start_time=start_time)

        # Filter to the specific job
        target_job = None
        for job in jobs:
            if job.job_name == job_name and job.namespace == namespace:
                target_job = job
                break

        if not target_job:
            return {
                "error": f"Job {job_name} not found in namespace {namespace}",
                "job_name": job_name,
                "namespace": namespace,
            }

        # Enrich with logs and metrics
        if include_logs:
            jobs_with_logs = analyzer.enrich_with_logs([target_job])
            target_job = jobs_with_logs[0] if jobs_with_logs else target_job

        if include_metrics:
            jobs_with_metrics = await analyzer.enrich_with_metrics([target_job])
            target_job = jobs_with_metrics[0] if jobs_with_metrics else target_job

        # Convert to dict
        from dataclasses import asdict

        return {"job": asdict(target_job), "job_name": job_name, "namespace": namespace}

    except Exception as e:
        logger.error(f"Error getting Zeus job details: {e}", exc_info=True)
        return {"error": str(e), "job_name": job_name, "namespace": namespace}


async def find_zeus_jobs_by_client(args: dict[str, Any]) -> dict[str, Any]:
    """
    Find all Zeus refresh jobs for a specific client.

    Args:
        client_name: Client name to search for (e.g., "ABC Corp", "acme")
        hours_back: Number of hours to look back (default: 24)
        status: Optional filter by status (Running, Succeeded, Failed)

    Returns:
        Dictionary with matching Zeus jobs
    """
    from tools.zeus_analyzer import ZeusAnalyzer

    client_name = args.get("client_name")
    hours_back = args.get("hours_back", 24)
    status = args.get("status")

    if not client_name:
        return {"error": "client_name is required", "client_name": client_name}

    try:
        analyzer = ZeusAnalyzer()

        result = await analyzer.analyze_zeus_refreshes(
            hours_back=hours_back,
            client_name=client_name,
            status=status,
            include_logs=True,  # Need logs to extract client names
            include_metrics=True,
        )

        return result

    except Exception as e:
        logger.error(f"Error finding Zeus jobs by client: {e}", exc_info=True)
        return {"error": str(e), "client_name": client_name, "hours_back": hours_back}


# ============================================================
# AWS Cost Explorer Tools
# ============================================================


async def get_cost_anomalies(args: dict[str, Any]) -> dict[str, Any]:
    """
    Detect AWS cost anomalies using AWS Cost Anomaly Detection service.

    Args:
        days_back: Number of days to look back (1-90, default: 7)
        min_impact: Minimum dollar impact threshold (default: 10.0)
        max_results: Maximum anomalies to return (1-100, default: 50)

    Returns:
        Dictionary with detected cost anomalies and analysis
    """
    from tools.aws_cost_explorer import AWSCostExplorer

    days_back = args.get("days_back", 7)
    min_impact = args.get("min_impact", 10.0)
    max_results = args.get("max_results", 50)

    try:
        cost_explorer = AWSCostExplorer()

        anomalies = await cost_explorer.get_cost_anomalies(
            days_back=days_back, min_impact=min_impact, max_results=max_results
        )

        # Calculate total impact
        total_impact = sum(a.get("impact_amount", 0) for a in anomalies)

        return {
            "status": "success",
            "anomalies": anomalies,
            "total_impact": total_impact,
            "anomaly_count": len(anomalies),
            "days_back": days_back,
            "min_impact": min_impact,
        }

    except Exception as e:
        logger.error(f"Error getting cost anomalies: {e}", exc_info=True)
        return {"error": str(e), "days_back": days_back, "min_impact": min_impact}


async def get_daily_costs(args: dict[str, Any]) -> dict[str, Any]:
    """
    Get daily cost breakdown by service or other dimension.

    Args:
        days_back: Number of days to analyze (1-365, default: 30)
        group_by: Dimension to group by (SERVICE, LINKED_ACCOUNT, REGION, USAGE_TYPE)
        granularity: Time granularity (DAILY or MONTHLY, default: DAILY)

    Returns:
        Dictionary with daily cost breakdown and top services
    """
    from tools.aws_cost_explorer import AWSCostExplorer

    days_back = args.get("days_back", 30)
    group_by = args.get("group_by", "SERVICE")
    granularity = args.get("granularity", "DAILY")

    try:
        cost_explorer = AWSCostExplorer()

        result = await cost_explorer.get_daily_costs(
            days_back=days_back, group_by=group_by, granularity=granularity
        )

        return {
            "status": "success",
            **result,
            "days_back": days_back,
            "group_by": group_by,
            "granularity": granularity,
        }

    except Exception as e:
        logger.error(f"Error getting daily costs: {e}", exc_info=True)
        return {"error": str(e), "days_back": days_back, "group_by": group_by}


async def get_ec2_costs_by_tags(args: dict[str, Any]) -> dict[str, Any]:
    """
    Get EC2 costs broken down by specific tags like node groups, Karpenter pools, and Databricks workers.

    Args:
        days_back: Number of days to analyze (1-365, default: 7)
        tag_keys: List of tag keys to group by (default: ['karpenter.sh/nodepool', 'eks:nodegroup-name', 'Refresh-Id'])
        service_filter: AWS service to filter (default: EC2 compute)
        max_tag_values: Maximum tag values to return per tag (default: 10)

    Returns:
        Dictionary with EC2 costs grouped by tags and top cost sources (limited to prevent context overflow)
    """
    from tools.aws_cost_explorer import AWSCostExplorer

    days_back = args.get("days_back", 7)
    tag_keys = args.get("tag_keys", ["karpenter.sh/nodepool", "eks:nodegroup-name", "Refresh-Id"])
    service_filter = args.get("service_filter", "Amazon Elastic Compute Cloud - Compute")
    max_tag_values = args.get("max_tag_values", 10)

    try:
        cost_explorer = AWSCostExplorer()

        result = await cost_explorer.get_ec2_costs_by_tags(
            days_back=days_back,
            tag_keys=tag_keys,
            service_filter=service_filter,
            max_tag_values=max_tag_values,
        )

        # Calculate summary statistics
        total_cost = result.get("total_ec2_cost", 0)
        top_sources = result.get("top_cost_sources", [])
        tag_breakdown = result.get("tag_breakdown", {})

        # Count unique tag values
        total_tag_values = sum(len(values) for values in tag_breakdown.values())

        return {
            "status": "success",
            **result,
            "summary": {
                "total_ec2_cost": total_cost,
                "total_tag_values": total_tag_values,
                "top_3_sources": top_sources[:3] if top_sources else [],
            },
            "days_back": days_back,
            "tag_keys": tag_keys,
        }

    except Exception as e:
        logger.error(f"Error getting EC2 costs by tags: {e}", exc_info=True)
        return {"error": str(e), "days_back": days_back, "tag_keys": tag_keys}
