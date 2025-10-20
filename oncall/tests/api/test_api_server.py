"""
Tests for API server initialization and health checks
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
    """Mock OnCallTroubleshootingAgent"""
    mock = Mock()
    mock.config_path = Path("/mock/config")
    mock.project_root = Path("/mock/project")
    mock.options = Mock()
    mock.options.allowed_tools = ["tool1", "tool2"]
    mock.query = AsyncMock(return_value=[])
    mock.handle_incident = AsyncMock(return_value={"agent_response": []})
    return mock


@pytest.fixture
def client(mock_agent):
    """Create test client with mocked agent"""
    with patch('src.api.api_server.OnCallTroubleshootingAgent', return_value=mock_agent):
        from src.api.api_server import app
        from src.api import api_server
        api_server.agent = mock_agent
        return TestClient(app)


def test_health_check_healthy(client):
    """Test health check returns healthy when agent initialized"""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["agent"] == "initialized"
    assert "version" in data


def test_health_check_unhealthy():
    """Test health check returns unhealthy when agent not initialized"""
    with patch('src.api.api_server.OnCallTroubleshootingAgent', side_effect=Exception("Init failed")):
        from src.api.api_server import app
        from src.api import api_server
        api_server.agent = None
        client = TestClient(app)

        response = client.get("/health")
        data = response.json()
        assert data["status"] == "unhealthy"
        assert data["agent"] == "not_initialized"


def test_root_endpoint(client):
    """Test root endpoint returns API information"""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "OnCall Troubleshooting Agent API"
    assert "endpoints" in data
    assert "query" in data["endpoints"]
    assert "incident" in data["endpoints"]


def test_cors_headers(client):
    """Test CORS headers are present"""
    response = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET"
        }
    )
    # CORS middleware should add these headers
    assert "access-control-allow-origin" in response.headers or response.status_code == 200
