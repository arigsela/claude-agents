"""Kubernetes diagnostic tools for the K8s A2A agent.

Adapted from oncall-agent-api/src/api/custom_tools.py (K8s section).
All tools are synchronous and return JSON strings per CrewAI @tool requirements.
"""

import json
from datetime import datetime

from crewai.tools import tool
from kubernetes import client, config

from shared.logging_config import setup_logging

logger = setup_logging("k8s-tools")


_k8s_clients: tuple[client.CoreV1Api, client.AppsV1Api] | None = None


def _get_k8s_client() -> tuple[client.CoreV1Api, client.AppsV1Api]:
    """Get initialized Kubernetes client (cached singleton).

    Tries in-cluster config first, falls back to local kubeconfig.
    The client is created once and reused across tool calls.
    """
    global _k8s_clients
    if _k8s_clients is not None:
        return _k8s_clients

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
    _k8s_clients = (client.CoreV1Api(), client.AppsV1Api())
    return _k8s_clients


@tool
def list_namespaces(pattern: str = "") -> str:
    """List all namespaces in the cluster, optionally filtered by pattern.

    Args:
        pattern: Optional substring to filter namespace names (case-insensitive).

    Returns:
        JSON with namespace list including name, status, and creation time.
    """
    try:
        v1, _ = _get_k8s_client()
        all_namespaces = v1.list_namespace()

        namespaces = []
        for ns in all_namespaces.items:
            ns_name = ns.metadata.name
            if pattern and pattern.lower() not in ns_name.lower():
                continue
            namespaces.append({
                "name": ns_name,
                "status": ns.status.phase,
                "created": ns.metadata.creation_timestamp.isoformat(),
            })

        return json.dumps({
            "pattern": pattern,
            "count": len(namespaces),
            "namespaces": namespaces,
        })

    except Exception as e:
        logger.error(f"Error listing namespaces: {e}")
        return json.dumps({"error": str(e), "pattern": pattern})


@tool
def list_pods(namespace: str, label_selector: str = "") -> str:
    """List pods in a Kubernetes namespace with container status details.

    Args:
        namespace: The Kubernetes namespace to list pods from.
        label_selector: Optional label selector to filter pods (e.g. "app=myservice").

    Returns:
        JSON with pod list including status, readiness, restart counts, and container states.
    """
    try:
        v1, _ = _get_k8s_client()
        pods = v1.list_namespaced_pod(namespace=namespace, label_selector=label_selector)

        pod_list = []
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

            if pod.status.container_statuses:
                pod_info["containers"] = []
                for container in pod.status.container_statuses:
                    container_info = {
                        "name": container.name,
                        "ready": container.ready,
                        "restarts": container.restart_count,
                        "state": {},
                    }
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

            pod_list.append(pod_info)

        return json.dumps({
            "namespace": namespace,
            "count": len(pod_list),
            "pods": pod_list,
        })

    except Exception as e:
        logger.error(f"Error listing pods: {e}")
        return json.dumps({"error": str(e), "namespace": namespace})


@tool
def get_pod_logs(
    namespace: str, pod_name: str, container: str = "", tail_lines: int = 100
) -> str:
    """Get logs from a Kubernetes pod.

    Args:
        namespace: The Kubernetes namespace.
        pod_name: Name of the pod to get logs from.
        container: Specific container name (optional, uses default if empty).
        tail_lines: Number of log lines to retrieve from the end (default 100).

    Returns:
        JSON with pod log output.
    """
    try:
        v1, _ = _get_k8s_client()
        logs = v1.read_namespaced_pod_log(
            name=pod_name,
            namespace=namespace,
            container=container if container else None,
            tail_lines=tail_lines,
        )

        return json.dumps({
            "pod": pod_name,
            "namespace": namespace,
            "container": container or "default",
            "tail_lines": tail_lines,
            "logs": logs,
        })

    except Exception as e:
        logger.error(f"Error getting pod logs: {e}")
        return json.dumps({"error": str(e), "pod": pod_name, "namespace": namespace})


@tool
def get_pod_events(namespace: str, pod_name: str = "") -> str:
    """Get Kubernetes events for troubleshooting, optionally filtered by pod.

    Args:
        namespace: The Kubernetes namespace.
        pod_name: Optional pod name to filter events for a specific pod.

    Returns:
        JSON with events sorted by most recent first.
    """
    try:
        v1, _ = _get_k8s_client()
        events = v1.list_namespaced_event(namespace=namespace)

        event_list = []
        for event in events.items:
            if pod_name and event.involved_object.name != pod_name:
                continue

            event_list.append({
                "type": event.type,
                "reason": event.reason,
                "message": event.message,
                "object": {
                    "kind": event.involved_object.kind,
                    "name": event.involved_object.name,
                },
                "count": event.count,
                "first_seen": event.first_timestamp.isoformat() if event.first_timestamp else None,
                "last_seen": event.last_timestamp.isoformat() if event.last_timestamp else None,
            })

        event_list.sort(key=lambda x: x["last_seen"] or "", reverse=True)

        return json.dumps({"namespace": namespace, "events": event_list})

    except Exception as e:
        logger.error(f"Error getting events: {e}")
        return json.dumps({"error": str(e), "namespace": namespace})


@tool
def get_deployment_status(namespace: str, deployment_name: str = "") -> str:
    """Get status of Kubernetes deployments in a namespace.

    Args:
        namespace: The Kubernetes namespace.
        deployment_name: Specific deployment name (optional, lists all if empty).

    Returns:
        JSON with deployment replica counts, conditions, and health status.
    """
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

        dep_list = []
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
                    dep_info["conditions"].append({
                        "type": condition.type,
                        "status": condition.status,
                        "reason": condition.reason or "",
                        "message": condition.message or "",
                    })

            dep_list.append(dep_info)

        return json.dumps({"namespace": namespace, "deployments": dep_list})

    except Exception as e:
        logger.error(f"Error getting deployment status: {e}")
        return json.dumps({
            "error": str(e),
            "namespace": namespace,
            "deployment": deployment_name,
        })


@tool
def list_services(
    namespace: str = "", service_name: str = "", check_label: str = ""
) -> str:
    """List Kubernetes Services with their label selectors and port configuration.

    Useful for identifying services with selector issues (e.g., version labels)
    that may cause routing problems during rolling updates.

    Args:
        namespace: Target namespace (optional, lists across all namespaces if empty).
        service_name: Specific service name to inspect (optional).
        check_label: Specific label key to check in selectors (e.g. "app.kubernetes.io/version").

    Returns:
        JSON with service details including selectors, ports, and label analysis.
    """
    try:
        v1, _ = _get_k8s_client()

        result = {"services": [], "total_count": 0, "filtered_count": 0}

        if namespace:
            result["namespace"] = namespace
        else:
            result["scope"] = "all-namespaces"

        if check_label:
            result["filtered_by_label"] = check_label

        if namespace and service_name:
            service = v1.read_namespaced_service(name=service_name, namespace=namespace)
            services = [service]
        elif namespace:
            service_list = v1.list_namespaced_service(namespace=namespace)
            services = service_list.items
        else:
            service_list = v1.list_service_for_all_namespaces()
            services = service_list.items

        result["total_count"] = len(services)

        for svc in services:
            service_info = {
                "name": svc.metadata.name,
                "namespace": svc.metadata.namespace,
                "type": svc.spec.type,
                "cluster_ip": svc.spec.cluster_ip,
                "selector": svc.spec.selector or {},
                "ports": [],
            }

            if svc.spec.ports:
                for port in svc.spec.ports:
                    service_info["ports"].append({
                        "name": port.name or "",
                        "protocol": port.protocol,
                        "port": port.port,
                        "target_port": str(port.target_port) if port.target_port else "",
                    })

            if check_label:
                if check_label in service_info["selector"]:
                    service_info["label_issue"] = {
                        "problematic_label": check_label,
                        "value": service_info["selector"][check_label],
                        "warning": (
                            f"Service selector uses '{check_label}' which may cause "
                            "routing issues during deployments"
                        ),
                    }
                    result["services"].append(service_info)
                    result["filtered_count"] += 1
            else:
                result["services"].append(service_info)
                result["filtered_count"] += 1

        if check_label and result["filtered_count"] > 0:
            result["analysis"] = {
                "issue": (
                    f"Found {result['filtered_count']} service(s) using "
                    f"'{check_label}' in selector"
                ),
                "impact": (
                    "Services using version labels in selectors won't route traffic "
                    "to new versions during rolling updates"
                ),
                "recommendation": (
                    "Update service selectors to use stable labels like "
                    "'app.kubernetes.io/name' or 'app.kubernetes.io/instance' instead"
                ),
            }
        elif check_label and result["filtered_count"] == 0:
            result["analysis"] = {
                "status": "healthy",
                "message": (
                    f"No services found using '{check_label}' in selector - good practice!"
                ),
            }

        return json.dumps(result)

    except Exception as e:
        logger.error(f"Error listing services: {e}")
        return json.dumps({
            "error": str(e),
            "namespace": namespace or "all",
            "service_name": service_name,
        })


@tool
def analyze_service_health(service_name: str, namespace: str) -> str:
    """Comprehensive health analysis of a Kubernetes service.

    Aggregates pod status, deployment status, and events to produce
    a health score and issue summary.

    Args:
        service_name: Name of the service/deployment to analyze.
        namespace: The Kubernetes namespace.

    Returns:
        JSON with health_score (healthy/unhealthy/error), issues list,
        pod data, deployment data, and recent events.
    """
    try:
        result = {
            "service": service_name,
            "namespace": namespace,
            "timestamp": datetime.now().isoformat(),
            "health_score": "unknown",
            "issues": [],
        }

        # 1. Check pods
        pods_raw = list_pods.run(namespace=namespace, label_selector=f"app={service_name}")
        pods_data = json.loads(pods_raw)
        result["pods"] = pods_data

        # 2. Check deployment
        dep_raw = get_deployment_status.run(
            namespace=namespace, deployment_name=service_name
        )
        deployment_data = json.loads(dep_raw)
        result["deployment"] = deployment_data

        # 3. Check events
        events_raw = get_pod_events.run(namespace=namespace, pod_name="")
        events_data = json.loads(events_raw)

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
            total_pods = pods_data.get("count", 0)
            unhealthy_pods = [
                p
                for p in pods_data.get("pods", [])
                if p["status"] != "Running" or p["ready"] < p["total_containers"]
            ]

            if unhealthy_pods:
                result["health_score"] = "unhealthy"
                result["issues"].append(
                    f"{len(unhealthy_pods)}/{total_pods} pods unhealthy"
                )
            else:
                result["health_score"] = "healthy"

        # Check for high restart counts
        high_restart_pods = [
            p for p in pods_data.get("pods", []) if p.get("restarts", 0) > 3
        ]
        if high_restart_pods:
            result["issues"].append(
                f"{len(high_restart_pods)} pods with high restart counts"
            )

        # Check for warning events
        warning_events = [e for e in service_events if e.get("type") == "Warning"]
        if warning_events:
            result["issues"].append(
                f"{len(warning_events)} warning events detected"
            )

        return json.dumps(result)

    except Exception as e:
        logger.error(f"Error analyzing service health: {e}")
        return json.dumps({
            "error": str(e),
            "service": service_name,
            "namespace": namespace,
        })
