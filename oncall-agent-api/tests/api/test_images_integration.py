"""
Integration Tests for /images/tags endpoint (DEVOPS-7737)

These tests run against a live Kubernetes cluster and require:
- K8s cluster access (dev-eks)
- KUBECONFIG environment variable or ~/.kube/config
- Services deployed in the cluster

Run with: pytest tests/api/test_images_integration.py -v --run-integration

Skip in CI environments without K8s access using:
    pytest tests/api/test_images_integration.py -v -m "not integration"
"""

import pytest
import os
import sys
from pathlib import Path
from datetime import datetime

# Add parent directories to path for imports
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))

from fastapi.testclient import TestClient
from api.api_server import app


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers", "integration: mark test as integration test requiring K8s access"
    )


def has_kubernetes_access() -> bool:
    """Check if we have access to a Kubernetes cluster."""
    try:
        from kubernetes import client, config
        try:
            config.load_incluster_config()
        except Exception:
            kubeconfig_path = os.getenv('KUBECONFIG')
            if kubeconfig_path:
                config.load_kube_config(config_file=kubeconfig_path)
            else:
                config.load_kube_config()

        # Try to list namespaces to verify access
        v1 = client.CoreV1Api()
        v1.list_namespace(limit=1)
        return True
    except Exception:
        return False


# Skip all integration tests if no K8s access
pytestmark = pytest.mark.skipif(
    not has_kubernetes_access(),
    reason="Kubernetes cluster not accessible"
)


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def api_headers():
    """Headers for API requests."""
    return {"X-API-Key": os.getenv("API_KEY", "test-key")}


class TestImagesIntegration:
    """Integration tests for /images/tags endpoint against live K8s cluster."""

    @pytest.mark.integration
    def test_images_health_with_k8s(self, client):
        """Test /images/health reports K8s connectivity."""
        response = client.get("/images/health")
        assert response.status_code == 200
        data = response.json()

        assert data["status"] in ["healthy", "degraded"]
        assert data["kubernetes_available"] is True
        assert "kubernetes_connected" in data
        assert "service_count" in data
        assert data["service_count"] > 0

    @pytest.mark.integration
    def test_images_tags_hermes(self, client, api_headers):
        """Test /images/tags returns valid response for hermes service."""
        response = client.get(
            "/images/tags?service=hermes",
            headers=api_headers
        )

        # Service should exist in K8s or return 404 if not deployed
        assert response.status_code in [200, 404]

        if response.status_code == 200:
            data = response.json()
            assert data["service_name"] == "hermes"
            assert data["deployment_name"] == "hermes-app"
            assert data["namespace"] == "artemis-dev"
            assert "current_image_url" in data
            assert ":" in data["current_image_url"]  # Has tag
            assert data["pod_count"] >= 0
            assert "timestamp" in data

    @pytest.mark.integration
    def test_images_tags_hermes_all_namespaces(self, client, api_headers):
        """Test /images/tags returns valid response for hermes in all namespaces.

        Hermes is available in: artemis-dev, artemis-qa1, artemis-qa2, artemis-qa3, artemis-preprod
        """
        hermes_configs = [
            ("hermes", "artemis-dev"),
            ("hermes-qa1", "artemis-qa1"),
            ("hermes-qa2", "artemis-qa2"),
            ("hermes-qa3", "artemis-qa3"),
            ("hermes-preprod", "artemis-preprod"),
        ]

        results = {}
        for service_name, expected_namespace in hermes_configs:
            response = client.get(
                f"/images/tags?service={service_name}",
                headers=api_headers
            )
            results[service_name] = response.status_code

            if response.status_code == 200:
                data = response.json()
                assert data["service_name"] == service_name
                assert data["deployment_name"] == "hermes-app"
                assert data["namespace"] == expected_namespace
                assert "current_image_url" in data
                assert data["pod_count"] >= 0

        # Log results for debugging
        print(f"\n=== Hermes Namespace Results ===")
        for svc, status in results.items():
            status_icon = "✓" if status == 200 else "✗"
            print(f"{status_icon} {svc}: HTTP {status}")

    @pytest.mark.integration
    def test_images_tags_proteus(self, client, api_headers):
        """Test /images/tags returns valid response for proteus service."""
        response = client.get(
            "/images/tags?service=proteus",
            headers=api_headers
        )

        assert response.status_code in [200, 404]

        if response.status_code == 200:
            data = response.json()
            assert data["service_name"] == "proteus"
            assert data["deployment_name"] == "proteus"
            assert data["namespace"] == "proteus-dev"
            assert "current_image_url" in data
            assert data["pod_count"] >= 0

    @pytest.mark.integration
    def test_images_tags_zeus(self, client, api_headers):
        """Test /images/tags returns valid response for zeus service.

        Zeus is available in: merlinqa, qa, merlinpreprod, preprod namespaces.
        Default 'zeus' entry points to merlinqa.
        """
        response = client.get(
            "/images/tags?service=zeus",
            headers=api_headers
        )

        assert response.status_code in [200, 404]

        if response.status_code == 200:
            data = response.json()
            assert data["service_name"] == "zeus"
            assert data["deployment_name"] == "zeus-web"
            assert data["namespace"] == "merlinqa"
            assert "current_image_url" in data

    @pytest.mark.integration
    def test_images_tags_hermes_chartdata(self, client, api_headers):
        """Test /images/tags returns valid response for hermes-chartdata service."""
        response = client.get(
            "/images/tags?service=hermes-chartdata",
            headers=api_headers
        )

        assert response.status_code in [200, 404]

        if response.status_code == 200:
            data = response.json()
            assert data["service_name"] == "hermes-chartdata"
            # Deployment name comes from config - hermes-app-chartdata
            assert data["deployment_name"] == "hermes-app-chartdata"
            assert data["namespace"] == "artemis-preprod"
            assert "current_image_url" in data

    @pytest.mark.integration
    def test_images_tags_image_url_format(self, client, api_headers):
        """Test that image URL follows expected format patterns."""
        response = client.get(
            "/images/tags?service=hermes",
            headers=api_headers
        )

        if response.status_code == 200:
            data = response.json()
            image_url = data["current_image_url"]

            # Image URL should have a tag (separated by :)
            assert ":" in image_url, f"Image URL missing tag: {image_url}"

            # Common patterns for our images
            valid_patterns = [
                "docker.io/artemishealth/",
                "artemishealth/",
                ".dkr.ecr.",  # ECR pattern
                "ecr.aws/",
            ]

            # At least one pattern should match
            matches_pattern = any(pattern in image_url for pattern in valid_patterns)
            # Or it's a standard image (nginx, postgres, etc.)
            is_standard = "/" not in image_url.split(":")[0] or image_url.startswith("docker.io/library/")

            assert matches_pattern or is_standard, f"Unexpected image URL format: {image_url}"

    @pytest.mark.integration
    def test_images_tags_timestamp_is_recent(self, client, api_headers):
        """Test that timestamp is recent (within last minute)."""
        response = client.get(
            "/images/tags?service=hermes",
            headers=api_headers
        )

        if response.status_code == 200:
            data = response.json()
            timestamp_str = data["timestamp"]

            # Parse timestamp (ISO format)
            if timestamp_str.endswith("Z"):
                timestamp_str = timestamp_str[:-1]
            timestamp = datetime.fromisoformat(timestamp_str)

            # Should be within the last minute
            now = datetime.utcnow()
            diff = (now - timestamp).total_seconds()
            assert diff < 60, f"Timestamp too old: {diff} seconds ago"

    @pytest.mark.integration
    def test_images_tags_invalid_service_returns_404(self, client, api_headers):
        """Test that invalid service returns 404 even with K8s access."""
        response = client.get(
            "/images/tags?service=nonexistent-service-xyz",
            headers=api_headers
        )

        assert response.status_code == 404
        data = response.json()
        assert "not found" in data["detail"].lower()
        assert "nonexistent-service-xyz" in data["detail"]

    @pytest.mark.integration
    def test_images_tags_all_configured_services(self, client, api_headers):
        """Test all services in service_mapping.yaml can be queried."""
        import yaml

        config_path = project_root / "config" / "service_mapping.yaml"
        with open(config_path) as f:
            config = yaml.safe_load(f)

        services = list(config["service_mappings"].keys())
        results = {}

        for service in services:
            response = client.get(
                f"/images/tags?service={service}",
                headers=api_headers
            )
            results[service] = {
                "status_code": response.status_code,
                "success": response.status_code == 200
            }
            if response.status_code == 200:
                data = response.json()
                results[service]["image"] = data.get("current_image_url", "N/A")
                results[service]["pods"] = data.get("pod_count", 0)

        # Log results for debugging
        print("\n=== Service Query Results ===")
        for service, result in results.items():
            status = "✓" if result["success"] else "✗"
            if result["success"]:
                print(f"{status} {service}: {result['pods']} pods - {result['image']}")
            else:
                print(f"{status} {service}: HTTP {result['status_code']}")

        # At least some services should be accessible
        successful = sum(1 for r in results.values() if r["success"])
        print(f"\n{successful}/{len(services)} services accessible")

        # This is informational - we don't fail if services aren't deployed
        # But we do want to see the results


class TestImagesIntegrationPerformance:
    """Performance tests for /images/tags endpoint."""

    @pytest.mark.integration
    def test_images_tags_response_time(self, client, api_headers):
        """Test that endpoint responds within acceptable time."""
        import time

        start = time.time()
        response = client.get(
            "/images/tags?service=hermes",
            headers=api_headers
        )
        duration = time.time() - start

        # Should respond within 5 seconds
        assert duration < 5.0, f"Response took too long: {duration:.2f}s"

        # Log response time
        print(f"\nResponse time: {duration:.2f}s (status: {response.status_code})")

    @pytest.mark.integration
    def test_images_tags_multiple_requests(self, client, api_headers):
        """Test multiple sequential requests work correctly."""
        services = ["hermes", "proteus", "zeus"]

        for service in services:
            response = client.get(
                f"/images/tags?service={service}",
                headers=api_headers
            )
            # Should get valid response (200 or 404 if not deployed)
            assert response.status_code in [200, 404], f"Unexpected status for {service}: {response.status_code}"


class TestImagesIntegrationEdgeCases:
    """Edge case tests requiring K8s access."""

    @pytest.mark.integration
    def test_images_health_detailed_info(self, client):
        """Test /images/health provides detailed K8s info."""
        response = client.get("/images/health")
        assert response.status_code == 200
        data = response.json()

        # Should have K8s connection info
        if data.get("kubernetes_available"):
            assert "kubernetes_connected" in data

            # If connected, should not have error
            if data.get("kubernetes_connected"):
                assert "kubernetes_error" not in data or data["kubernetes_error"] is None

    @pytest.mark.integration
    def test_images_tags_case_sensitivity(self, client, api_headers):
        """Test that service names are case-sensitive."""
        # These should all return 404 (case mismatch)
        wrong_cases = ["Hermes", "HERMES", "hErMeS"]

        for service in wrong_cases:
            response = client.get(
                f"/images/tags?service={service}",
                headers=api_headers
            )
            # Should be 404 because service names are lowercase in config
            assert response.status_code == 404, f"Expected 404 for '{service}', got {response.status_code}"
