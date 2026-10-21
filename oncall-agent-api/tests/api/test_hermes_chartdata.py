"""
Tests for Hermes ChartData monitoring endpoints

NOTE: These are basic integration tests that verify endpoint registration.
Full functional tests with mocked Kubernetes and Datadog are recommended for production.
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import Mock, patch, AsyncMock
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


@pytest.fixture
def mock_agent():
    """Mock OnCallAgentClient"""
    mock = Mock()
    mock.model = "claude-3-5-sonnet-20241022"
    mock.tools = []
    mock.query = AsyncMock(return_value={"response": "Test response"})
    return mock


@pytest.fixture
def client(mock_agent):
    """Create test client with mocked agent"""
    with patch('src.api.api_server.OnCallAgentClient', return_value=mock_agent):
        from src.api.api_server import app
        from src.api import api_server
        api_server.agent = mock_agent
        return TestClient(app)


def test_endpoint_registration(client):
    """Test that hermes-chartdata endpoints are registered in root"""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()

    assert "endpoints" in data
    assert "hermes_chartdata" in data["endpoints"]

    hermes_endpoints = data["endpoints"]["hermes_chartdata"]
    assert "health" in hermes_endpoints
    assert "metrics" in hermes_endpoints
    assert "slow_queries" in hermes_endpoints
    assert "analyze" in hermes_endpoints


def test_openapi_documentation(client):
    """Test that hermes-chartdata endpoints appear in OpenAPI docs"""
    response = client.get("/openapi.json")
    assert response.status_code == 200

    openapi_spec = response.json()
    paths = openapi_spec.get("paths", {})

    # Check that our endpoints are documented
    assert "/hermes-chartdata/health" in paths
    assert "/hermes-chartdata/metrics" in paths
    assert "/hermes-chartdata/slow-queries" in paths
    assert "/hermes-chartdata/analyze-performance" in paths

    # Check tags
    health_endpoint = paths["/hermes-chartdata/health"]
    assert "get" in health_endpoint
    assert "tags" in health_endpoint["get"]
    assert "hermes-chartdata" in health_endpoint["get"]["tags"]


def test_health_check_requires_params(client):
    """Test health endpoint accepts valid namespace parameter"""
    # Note: Without proper mocking, this will fail with internal errors
    # but we can verify the endpoint is registered and accepts the parameter
    response = client.get("/hermes-chartdata/health?namespace=artemis-preprod")

    # Should not be 404 (endpoint exists)
    assert response.status_code != 404


def test_metrics_endpoint_accepts_params(client):
    """Test metrics endpoint accepts valid parameters"""
    response = client.get(
        "/hermes-chartdata/metrics?namespace=artemis-preprod&time_window_minutes=60"
    )

    # Should not be 404 (endpoint exists)
    assert response.status_code != 404


def test_slow_queries_endpoint_accepts_params(client):
    """Test slow queries endpoint accepts valid parameters"""
    response = client.get(
        "/hermes-chartdata/slow-queries?namespace=artemis-preprod&threshold_seconds=30&time_window_minutes=60"
    )

    # Should not be 404 (endpoint exists)
    assert response.status_code != 404


def test_analyze_performance_endpoint_exists(client):
    """Test analyze performance endpoint is registered"""
    response = client.post(
        "/hermes-chartdata/analyze-performance?namespace=artemis-preprod&time_window_minutes=60"
    )

    # Should not be 404 (endpoint exists)
    assert response.status_code != 404


def test_invalid_namespace_validation(client):
    """Test health check with invalid namespace parameter"""
    response = client.get("/hermes-chartdata/health?namespace=invalid-namespace")

    # Should return 422 for invalid enum value
    assert response.status_code == 422


def test_time_window_too_small(client):
    """Test metrics endpoint rejects time window below minimum"""
    response = client.get(
        "/hermes-chartdata/metrics?namespace=artemis-preprod&time_window_minutes=2"
    )

    # Should return 422 for validation error
    assert response.status_code == 422


def test_time_window_too_large(client):
    """Test metrics endpoint rejects time window above maximum"""
    response = client.get(
        "/hermes-chartdata/metrics?namespace=artemis-preprod&time_window_minutes=2000"
    )

    # Should return 422 for validation error
    assert response.status_code == 422


def test_threshold_below_minimum(client):
    """Test slow queries rejects threshold below 1.0"""
    response = client.get(
        "/hermes-chartdata/slow-queries?namespace=artemis-preprod&threshold_seconds=0.5"
    )

    # Should return 422 for validation error
    assert response.status_code == 422


def test_threshold_above_maximum(client):
    """Test slow queries rejects threshold above 300.0"""
    response = client.get(
        "/hermes-chartdata/slow-queries?namespace=artemis-preprod&threshold_seconds=500"
    )

    # Should return 422 for validation error
    assert response.status_code == 422
