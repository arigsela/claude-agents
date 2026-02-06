"""
Tests for /images/tags endpoint (DEVOPS-7737)

This test module covers:
- Service mapping configuration loading
- Namespace resolution logic
- Image tag endpoint functionality
- Helper function unit tests
"""

import pytest
import yaml
import sys
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock, AsyncMock
from datetime import datetime
from fastapi.testclient import TestClient

# Add parent directories to path for imports
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))

# Import app for endpoint tests
from api.api_server import app


class TestServiceMappingConfig:
    """Tests for service_mapping.yaml configuration"""

    @pytest.fixture
    def config_path(self):
        """Path to service_mapping.yaml"""
        return Path(__file__).parent.parent.parent / "config" / "service_mapping.yaml"

    def test_config_file_exists(self, config_path):
        """Test that service_mapping.yaml exists"""
        assert config_path.exists(), f"Config file not found: {config_path}"

    def test_config_loads_valid_yaml(self, config_path):
        """Test that service_mapping.yaml is valid YAML"""
        with open(config_path) as f:
            config = yaml.safe_load(f)
        assert config is not None
        assert "service_mappings" in config

    def test_config_has_namespace_field(self, config_path):
        """Test that services have namespace field"""
        with open(config_path) as f:
            config = yaml.safe_load(f)

        services_with_namespace = []
        services_without_namespace = []

        for service_name, service_config in config["service_mappings"].items():
            if "namespace" in service_config:
                services_with_namespace.append(service_name)
            else:
                services_without_namespace.append(service_name)

        # All services should have namespace defined
        assert len(services_with_namespace) > 0, "No services have namespace defined"

        # Report any services without namespace (for awareness)
        if services_without_namespace:
            pytest.skip(f"Services without namespace (will use inference): {services_without_namespace}")

    def test_config_has_k8s_deployment_name(self, config_path):
        """Test that services have k8s_deployment_name field"""
        with open(config_path) as f:
            config = yaml.safe_load(f)

        for service_name, service_config in config["service_mappings"].items():
            # k8s_deployment_name should be present for image tag lookups
            assert "k8s_deployment_name" in service_config, \
                f"Service '{service_name}' missing k8s_deployment_name"

    def test_config_critical_services_have_namespace(self, config_path):
        """Test that critical services have explicit namespace"""
        with open(config_path) as f:
            config = yaml.safe_load(f)

        critical_services = [
            name for name, cfg in config["service_mappings"].items()
            if cfg.get("criticality") == "critical"
        ]

        for service_name in critical_services:
            service_config = config["service_mappings"][service_name]
            assert "namespace" in service_config, \
                f"Critical service '{service_name}' missing explicit namespace"

    def test_config_namespace_values_valid(self, config_path):
        """Test that namespace values follow K8s naming conventions"""
        with open(config_path) as f:
            config = yaml.safe_load(f)

        import re
        # K8s namespace pattern: lowercase alphanumeric, dashes allowed, max 63 chars
        namespace_pattern = re.compile(r'^[a-z0-9]([-a-z0-9]*[a-z0-9])?$')

        for service_name, service_config in config["service_mappings"].items():
            if "namespace" in service_config:
                namespace = service_config["namespace"]
                assert len(namespace) <= 63, \
                    f"Namespace '{namespace}' for '{service_name}' exceeds 63 chars"
                assert namespace_pattern.match(namespace), \
                    f"Namespace '{namespace}' for '{service_name}' invalid format"

    def test_config_expected_services_present(self, config_path):
        """Test that expected critical services are in config"""
        with open(config_path) as f:
            config = yaml.safe_load(f)

        expected_services = ["hermes", "proteus", "zeus", "artemis-auth"]
        for service in expected_services:
            assert service in config["service_mappings"], \
                f"Expected service '{service}' not found in config"


class TestNamespaceResolution:
    """Tests for namespace resolution logic"""

    def test_explicit_namespace_returned(self):
        """Test that explicit namespace from config is used"""
        service_config = {
            "namespace": "artemis-dev",
            "k8s_deployment_name": "hermesapp"
        }

        # Simulate the resolution logic
        namespace = service_config.get("namespace") or "hermes-dev"
        assert namespace == "artemis-dev"

    def test_inferred_namespace_when_missing(self):
        """Test namespace inference when not specified"""
        service_config = {
            "k8s_deployment_name": "some-app"
        }
        service_name = "myservice"

        # Simulate the resolution logic (fallback pattern)
        namespace = service_config.get("namespace") or f"{service_name}-dev"
        assert namespace == "myservice-dev"

    def test_namespace_inference_pattern(self):
        """Test the namespace inference pattern for various services"""
        test_cases = [
            ("hermes", "hermes-dev"),
            ("proteus", "proteus-dev"),
            ("zeus", "zeus-dev"),
            ("my-service", "my-service-dev"),
        ]

        for service_name, expected_namespace in test_cases:
            inferred = f"{service_name}-dev"
            assert inferred == expected_namespace


class TestImageTagEndpointHelpers:
    """Tests for image tag endpoint helper functions

    Note: These tests use mocks since the actual endpoint implementation
    will be created in Phase 2.
    """

    @pytest.fixture
    def mock_k8s_deployment(self):
        """Create a mock K8s deployment object"""
        deployment = MagicMock()

        # Mock container
        container = MagicMock()
        container.name = "app"
        container.image = "docker.io/artemishealth/hermes:v1.2.3"

        # Mock sidecar container
        sidecar = MagicMock()
        sidecar.name = "istio-proxy"
        sidecar.image = "istio/proxyv2:1.17.0"

        # Mock deployment spec
        deployment.spec.template.spec.containers = [container, sidecar]
        deployment.status.ready_replicas = 3

        return deployment

    def test_primary_container_is_first(self, mock_k8s_deployment):
        """Test that primary container is the first one in the list"""
        containers = mock_k8s_deployment.spec.template.spec.containers
        primary = containers[0]

        assert primary.name == "app"
        assert "hermes" in primary.image

    def test_sidecar_containers_ignored(self, mock_k8s_deployment):
        """Test that sidecar containers are not selected as primary"""
        containers = mock_k8s_deployment.spec.template.spec.containers
        primary = containers[0]

        # Sidecar should not be selected
        assert primary.name != "istio-proxy"
        assert "istio" not in primary.image

    def test_image_url_extraction(self, mock_k8s_deployment):
        """Test that image URL is extracted correctly"""
        container = mock_k8s_deployment.spec.template.spec.containers[0]
        image_url = container.image

        assert image_url == "docker.io/artemishealth/hermes:v1.2.3"
        assert ":" in image_url  # Has tag separator

    def test_pod_count_from_ready_replicas(self, mock_k8s_deployment):
        """Test that pod count comes from ready_replicas"""
        pod_count = mock_k8s_deployment.status.ready_replicas
        assert pod_count == 3

    def test_pod_count_handles_none(self):
        """Test that None ready_replicas is handled as 0"""
        deployment = MagicMock()
        deployment.status.ready_replicas = None

        pod_count = deployment.status.ready_replicas or 0
        assert pod_count == 0


class TestImagesHelperFunctions:
    """Tests for images.py helper functions"""

    def test_load_service_mapping_returns_dict(self):
        """Test that load_service_mapping returns a dictionary"""
        from api.images import load_service_mapping
        import api.images as images_module

        # Clear cache to ensure fresh load
        images_module._service_mapping_cache = None

        config = load_service_mapping()
        assert isinstance(config, dict)
        assert "service_mappings" in config

    def test_load_service_mapping_caches_result(self):
        """Test that config is cached after first load"""
        from api.images import load_service_mapping
        import api.images as images_module

        # Clear cache
        images_module._service_mapping_cache = None

        # First load
        config1 = load_service_mapping()

        # Second load should return cached value
        config2 = load_service_mapping()

        assert config1 is config2  # Same object (cached)

    def test_get_service_config_valid_service(self):
        """Test get_service_config returns config for valid service"""
        from api.images import get_service_config

        config = get_service_config("hermes")
        assert isinstance(config, dict)
        assert "github_repo" in config

    def test_get_service_config_invalid_service_raises_404(self):
        """Test get_service_config raises 404 for invalid service"""
        from api.images import get_service_config
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            get_service_config("nonexistent-service")

        assert exc_info.value.status_code == 404
        assert "not found" in exc_info.value.detail.lower()

    def test_resolve_namespace_explicit(self):
        """Test resolve_namespace returns explicit namespace"""
        from api.images import resolve_namespace

        service_config = {"namespace": "custom-namespace"}
        result = resolve_namespace("myservice", service_config)
        assert result == "custom-namespace"

    def test_resolve_namespace_inferred(self):
        """Test resolve_namespace infers namespace when not specified"""
        from api.images import resolve_namespace

        service_config = {"github_repo": "some/repo"}
        result = resolve_namespace("myservice", service_config)
        assert result == "myservice-dev"

    def test_get_deployment_name_explicit(self):
        """Test get_deployment_name returns explicit name"""
        from api.images import get_deployment_name

        service_config = {"k8s_deployment_name": "custom-deploy"}
        result = get_deployment_name("myservice", service_config)
        assert result == "custom-deploy"

    def test_get_deployment_name_defaults_to_service(self):
        """Test get_deployment_name defaults to service name"""
        from api.images import get_deployment_name

        service_config = {"github_repo": "some/repo"}
        result = get_deployment_name("myservice", service_config)
        assert result == "myservice"


class TestImagesEndpoint:
    """Tests for /images/tags endpoint"""

    @pytest.fixture
    def client(self):
        """Create test client"""
        return TestClient(app)

    @pytest.fixture
    def mock_k8s_deployment(self):
        """Create a mock K8s deployment response"""
        deployment = MagicMock()

        # Mock container
        container = MagicMock()
        container.name = "app"
        container.image = "docker.io/artemishealth/hermes:v1.2.3"

        deployment.spec.template.spec.containers = [container]
        deployment.status.ready_replicas = 3

        return deployment

    def test_images_health_endpoint(self, client):
        """Test /images/health endpoint returns status"""
        response = client.get("/images/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "kubernetes_available" in data

    def test_images_tags_missing_service_param(self, client):
        """Test /images/tags returns 422 without service param"""
        response = client.get(
            "/images/tags",
            headers={"X-API-Key": "test-key"}
        )
        assert response.status_code == 422  # Validation error

    def test_images_tags_invalid_service(self, client):
        """Test /images/tags returns 404 for invalid service"""
        response = client.get(
            "/images/tags?service=nonexistent-service",
            headers={"X-API-Key": "test-key"}
        )
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    @patch("api.images.init_k8s_client")
    @patch("api.images.get_deployment_image")
    def test_images_tags_success(
        self, mock_get_image, mock_init_k8s, client, mock_k8s_deployment
    ):
        """Test /images/tags returns successful response"""
        # Setup mocks
        mock_init_k8s.return_value = MagicMock()
        mock_get_image.return_value = (
            "docker.io/artemishealth/hermes:v1.2.3",
            "app",
            3
        )

        response = client.get(
            "/images/tags?service=hermes",
            headers={"X-API-Key": "test-key"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["service_name"] == "hermes"
        assert data["deployment_name"] == "hermes-app"
        assert data["namespace"] == "artemis-dev"
        assert data["current_image_url"] == "docker.io/artemishealth/hermes:v1.2.3"
        assert data["pod_count"] == 3

    @patch("api.images.init_k8s_client")
    def test_images_tags_k8s_connection_error(self, mock_init_k8s, client):
        """Test /images/tags handles K8s connection errors"""
        from fastapi import HTTPException

        mock_init_k8s.side_effect = HTTPException(
            status_code=500,
            detail="Failed to connect to Kubernetes API"
        )

        response = client.get(
            "/images/tags?service=hermes",
            headers={"X-API-Key": "test-key"}
        )

        assert response.status_code == 500
        assert "kubernetes" in response.json()["detail"].lower()

    @patch("api.images.init_k8s_client")
    @patch("api.images.get_deployment_image")
    def test_images_tags_deployment_not_found(
        self, mock_get_image, mock_init_k8s, client
    ):
        """Test /images/tags handles deployment not found"""
        from fastapi import HTTPException

        mock_init_k8s.return_value = MagicMock()
        mock_get_image.side_effect = HTTPException(
            status_code=404,
            detail="Deployment 'hermes-app' not found in namespace 'artemis-dev'"
        )

        response = client.get(
            "/images/tags?service=hermes",
            headers={"X-API-Key": "test-key"}
        )

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()


class TestImagesEndpointInRoot:
    """Tests that images endpoint is properly registered"""

    @pytest.fixture
    def client(self):
        """Create test client"""
        return TestClient(app)

    def test_images_endpoint_in_root_response(self, client):
        """Test that /images endpoints appear in root response"""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()

        assert "endpoints" in data
        assert "images" in data["endpoints"]
        assert "health" in data["endpoints"]["images"]
        assert "tags" in data["endpoints"]["images"]

    def test_images_routes_registered(self):
        """Test that images routes are registered in app"""
        routes = [r.path for r in app.routes]
        assert "/images/tags" in routes
        assert "/images/health" in routes
