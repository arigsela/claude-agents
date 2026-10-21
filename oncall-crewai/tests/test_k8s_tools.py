"""Tests for K8s agent tools (CrewAI @tool format).

Each tool is tested with:
- A positive case using mocked Kubernetes API responses
- An error case verifying graceful error handling
"""

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, Mock, patch

import pytest


# Patch kubernetes config before importing tools
@pytest.fixture(autouse=True)
def mock_k8s_config():
    """Prevent real kubernetes config loading in all tests."""
    with patch("k8s_agent.tools.config") as mock_config:
        mock_config.load_incluster_config.side_effect = Exception("not in cluster")
        mock_config.load_kube_config.return_value = None
        yield mock_config


@pytest.fixture
def mock_k8s_clients():
    """Create mock CoreV1Api and AppsV1Api clients."""
    mock_v1 = MagicMock()
    mock_apps_v1 = MagicMock()
    with patch("k8s_agent.tools.client") as mock_client:
        mock_client.CoreV1Api.return_value = mock_v1
        mock_client.AppsV1Api.return_value = mock_apps_v1
        yield mock_v1, mock_apps_v1


def _make_namespace(name, status="Active"):
    """Helper: create a mock namespace object."""
    ns = Mock()
    ns.metadata.name = name
    ns.status.phase = status
    ns.metadata.creation_timestamp = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return ns


def _make_pod(name, status="Running", ready=True, restarts=0, containers=1, node="node-1"):
    """Helper: create a mock pod object."""
    pod = Mock()
    pod.metadata.name = name
    pod.status.phase = status
    pod.spec.node_name = node
    pod.metadata.creation_timestamp = datetime(2024, 1, 1, tzinfo=timezone.utc)
    pod.spec.containers = [Mock() for _ in range(containers)]

    container_status = Mock()
    container_status.name = f"{name}-container"
    container_status.ready = ready
    container_status.restart_count = restarts
    container_status.state = Mock()
    container_status.state.running = Mock()
    container_status.state.running.started_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
    container_status.state.waiting = None
    container_status.state.terminated = None

    pod.status.container_statuses = [container_status]
    return pod


def _make_event(obj_name, obj_kind="Pod", event_type="Normal", reason="Pulled", message="OK"):
    """Helper: create a mock event object."""
    event = Mock()
    event.type = event_type
    event.reason = reason
    event.message = message
    event.involved_object.kind = obj_kind
    event.involved_object.name = obj_name
    event.count = 1
    event.first_timestamp = datetime(2024, 1, 1, tzinfo=timezone.utc)
    event.last_timestamp = datetime(2024, 1, 1, 0, 5, tzinfo=timezone.utc)
    return event


def _make_deployment(name, desired=2, ready=2, available=2, unavailable=0):
    """Helper: create a mock deployment object."""
    dep = Mock()
    dep.metadata.name = name
    dep.spec.replicas = desired
    dep.status.ready_replicas = ready
    dep.status.available_replicas = available
    dep.status.unavailable_replicas = unavailable
    condition = Mock()
    condition.type = "Available"
    condition.status = "True"
    condition.reason = "MinimumReplicasAvailable"
    condition.message = "Deployment has minimum availability."
    dep.status.conditions = [condition]
    return dep


def _make_service(name, namespace="default", svc_type="ClusterIP", selector=None):
    """Helper: create a mock service object."""
    svc = Mock()
    svc.metadata.name = name
    svc.metadata.namespace = namespace
    svc.spec.type = svc_type
    svc.spec.cluster_ip = "10.96.0.1"
    svc.spec.selector = selector or {"app": name}
    port = Mock()
    port.name = "http"
    port.protocol = "TCP"
    port.port = 80
    port.target_port = 8080
    svc.spec.ports = [port]
    return svc


# ============================================================
# list_namespaces
# ============================================================


class TestListNamespaces:
    def test_returns_all_namespaces(self, mock_k8s_clients):
        from k8s_agent.tools import list_namespaces

        mock_v1, _ = mock_k8s_clients
        ns_list = Mock()
        ns_list.items = [_make_namespace("default"), _make_namespace("kube-system")]
        mock_v1.list_namespace.return_value = ns_list

        result = json.loads(list_namespaces.run(pattern=""))

        assert result["count"] == 2
        assert result["namespaces"][0]["name"] == "default"
        assert result["namespaces"][1]["name"] == "kube-system"

    def test_filters_by_pattern(self, mock_k8s_clients):
        from k8s_agent.tools import list_namespaces

        mock_v1, _ = mock_k8s_clients
        ns_list = Mock()
        ns_list.items = [_make_namespace("default"), _make_namespace("kube-system")]
        mock_v1.list_namespace.return_value = ns_list

        result = json.loads(list_namespaces.run(pattern="kube"))

        assert result["count"] == 1
        assert result["namespaces"][0]["name"] == "kube-system"

    def test_error_returns_json(self, mock_k8s_clients):
        from k8s_agent.tools import list_namespaces

        mock_v1, _ = mock_k8s_clients
        mock_v1.list_namespace.side_effect = Exception("API unavailable")

        result = json.loads(list_namespaces.run(pattern=""))

        assert "error" in result
        assert "API unavailable" in result["error"]


# ============================================================
# list_pods
# ============================================================


class TestListPods:
    def test_returns_pods_with_status(self, mock_k8s_clients):
        from k8s_agent.tools import list_pods

        mock_v1, _ = mock_k8s_clients
        pod_list = Mock()
        pod_list.items = [_make_pod("web-1"), _make_pod("web-2")]
        mock_v1.list_namespaced_pod.return_value = pod_list

        result = json.loads(list_pods.run(namespace="default"))

        assert result["namespace"] == "default"
        assert result["count"] == 2
        assert result["pods"][0]["name"] == "web-1"
        assert result["pods"][0]["status"] == "Running"
        assert "containers" in result["pods"][0]

    def test_error_returns_json(self, mock_k8s_clients):
        from k8s_agent.tools import list_pods

        mock_v1, _ = mock_k8s_clients
        mock_v1.list_namespaced_pod.side_effect = Exception("Namespace not found")

        result = json.loads(list_pods.run(namespace="nonexistent"))

        assert "error" in result
        assert result["namespace"] == "nonexistent"


# ============================================================
# get_pod_logs
# ============================================================


class TestGetPodLogs:
    def test_returns_logs(self, mock_k8s_clients):
        from k8s_agent.tools import get_pod_logs

        mock_v1, _ = mock_k8s_clients
        mock_v1.read_namespaced_pod_log.return_value = "INFO: Server started\nINFO: Ready"

        result = json.loads(get_pod_logs.run(namespace="default", pod_name="web-1"))

        assert result["pod"] == "web-1"
        assert "Server started" in result["logs"]
        assert result["tail_lines"] == 100

    def test_error_returns_json(self, mock_k8s_clients):
        from k8s_agent.tools import get_pod_logs

        mock_v1, _ = mock_k8s_clients
        mock_v1.read_namespaced_pod_log.side_effect = Exception("Pod not found")

        result = json.loads(get_pod_logs.run(namespace="default", pod_name="gone-pod"))

        assert "error" in result
        assert result["pod"] == "gone-pod"


# ============================================================
# get_pod_events
# ============================================================


class TestGetPodEvents:
    def test_returns_events(self, mock_k8s_clients):
        from k8s_agent.tools import get_pod_events

        mock_v1, _ = mock_k8s_clients
        event_list = Mock()
        event_list.items = [
            _make_event("web-1", reason="Pulled", message="Pulled image"),
            _make_event("web-1", event_type="Warning", reason="BackOff", message="Crash"),
        ]
        mock_v1.list_namespaced_event.return_value = event_list

        result = json.loads(get_pod_events.run(namespace="default", pod_name="web-1"))

        assert len(result["events"]) == 2

    def test_filters_by_pod_name(self, mock_k8s_clients):
        from k8s_agent.tools import get_pod_events

        mock_v1, _ = mock_k8s_clients
        event_list = Mock()
        event_list.items = [
            _make_event("web-1"),
            _make_event("web-2"),
        ]
        mock_v1.list_namespaced_event.return_value = event_list

        result = json.loads(get_pod_events.run(namespace="default", pod_name="web-1"))

        assert len(result["events"]) == 1
        assert result["events"][0]["object"]["name"] == "web-1"

    def test_error_returns_json(self, mock_k8s_clients):
        from k8s_agent.tools import get_pod_events

        mock_v1, _ = mock_k8s_clients
        mock_v1.list_namespaced_event.side_effect = Exception("Forbidden")

        result = json.loads(get_pod_events.run(namespace="default"))

        assert "error" in result


# ============================================================
# get_deployment_status
# ============================================================


class TestGetDeploymentStatus:
    def test_returns_specific_deployment(self, mock_k8s_clients):
        from k8s_agent.tools import get_deployment_status

        _, mock_apps = mock_k8s_clients
        mock_apps.read_namespaced_deployment.return_value = _make_deployment("web")

        result = json.loads(
            get_deployment_status.run(namespace="default", deployment_name="web")
        )

        assert len(result["deployments"]) == 1
        assert result["deployments"][0]["name"] == "web"
        assert result["deployments"][0]["replicas"]["desired"] == 2
        assert result["deployments"][0]["replicas"]["ready"] == 2

    def test_returns_all_deployments(self, mock_k8s_clients):
        from k8s_agent.tools import get_deployment_status

        _, mock_apps = mock_k8s_clients
        dep_list = Mock()
        dep_list.items = [_make_deployment("web"), _make_deployment("api")]
        mock_apps.list_namespaced_deployment.return_value = dep_list

        result = json.loads(get_deployment_status.run(namespace="default"))

        assert len(result["deployments"]) == 2

    def test_error_returns_json(self, mock_k8s_clients):
        from k8s_agent.tools import get_deployment_status

        _, mock_apps = mock_k8s_clients
        mock_apps.read_namespaced_deployment.side_effect = Exception("Not found")

        result = json.loads(
            get_deployment_status.run(namespace="default", deployment_name="missing")
        )

        assert "error" in result


# ============================================================
# list_services
# ============================================================


class TestListServices:
    def test_returns_services_in_namespace(self, mock_k8s_clients):
        from k8s_agent.tools import list_services

        mock_v1, _ = mock_k8s_clients
        svc_list = Mock()
        svc_list.items = [_make_service("web"), _make_service("api")]
        mock_v1.list_namespaced_service.return_value = svc_list

        result = json.loads(list_services.run(namespace="default"))

        assert result["total_count"] == 2
        assert result["filtered_count"] == 2
        assert result["services"][0]["name"] == "web"

    def test_check_label_filters(self, mock_k8s_clients):
        from k8s_agent.tools import list_services

        mock_v1, _ = mock_k8s_clients
        svc_list = Mock()
        svc_list.items = [
            _make_service("web", selector={"app": "web", "app.kubernetes.io/version": "1.0"}),
            _make_service("api", selector={"app": "api"}),
        ]
        mock_v1.list_namespaced_service.return_value = svc_list

        result = json.loads(
            list_services.run(namespace="default", check_label="app.kubernetes.io/version")
        )

        assert result["filtered_count"] == 1
        assert result["services"][0]["name"] == "web"
        assert "label_issue" in result["services"][0]
        assert "analysis" in result

    def test_error_returns_json(self, mock_k8s_clients):
        from k8s_agent.tools import list_services

        mock_v1, _ = mock_k8s_clients
        mock_v1.list_namespaced_service.side_effect = Exception("Forbidden")

        result = json.loads(list_services.run(namespace="default"))

        assert "error" in result


# ============================================================
# analyze_service_health
# ============================================================


class TestAnalyzeServiceHealth:
    def test_healthy_service(self, mock_k8s_clients):
        from k8s_agent.tools import analyze_service_health

        mock_v1, mock_apps = mock_k8s_clients

        # Mock pods
        pod_list = Mock()
        pod_list.items = [_make_pod("web-1"), _make_pod("web-2")]
        mock_v1.list_namespaced_pod.return_value = pod_list

        # Mock deployment
        mock_apps.read_namespaced_deployment.return_value = _make_deployment("web")

        # Mock events
        event_list = Mock()
        event_list.items = [_make_event("web-1", reason="Pulled")]
        mock_v1.list_namespaced_event.return_value = event_list

        result = json.loads(
            analyze_service_health.run(service_name="web", namespace="default")
        )

        assert result["health_score"] == "healthy"
        assert result["issues"] == []

    def test_unhealthy_service(self, mock_k8s_clients):
        from k8s_agent.tools import analyze_service_health

        mock_v1, mock_apps = mock_k8s_clients

        # Mock pods with one unhealthy
        pod_list = Mock()
        pod_list.items = [
            _make_pod("web-1"),
            _make_pod("web-2", status="CrashLoopBackOff", ready=False, restarts=10),
        ]
        mock_v1.list_namespaced_pod.return_value = pod_list

        # Mock deployment
        mock_apps.read_namespaced_deployment.return_value = _make_deployment(
            "web", ready=1, unavailable=1
        )

        # Mock events with warnings
        event_list = Mock()
        event_list.items = [
            _make_event("web-2", event_type="Warning", reason="BackOff", message="Crash"),
        ]
        mock_v1.list_namespaced_event.return_value = event_list

        result = json.loads(
            analyze_service_health.run(service_name="web", namespace="default")
        )

        assert result["health_score"] == "unhealthy"
        assert len(result["issues"]) > 0

    def test_pod_error_reports_in_health_score(self, mock_k8s_clients):
        from k8s_agent.tools import analyze_service_health

        mock_v1, mock_apps = mock_k8s_clients
        mock_v1.list_namespaced_pod.side_effect = Exception("Connection refused")
        mock_apps.read_namespaced_deployment.return_value = _make_deployment("web")
        event_list = Mock()
        event_list.items = []
        mock_v1.list_namespaced_event.return_value = event_list

        result = json.loads(
            analyze_service_health.run(service_name="web", namespace="default")
        )

        assert result["health_score"] == "error"
        assert any("Connection refused" in i for i in result["issues"])
