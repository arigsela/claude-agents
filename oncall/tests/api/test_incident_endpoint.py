"""
Tests for /incident endpoint
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

    # Mock incident response
    mock_response = Mock()
    mock_response.content = [Mock(text="Incident analysis complete")]
    type(mock_response.content[0]).__name__ = "TextBlock"
    type(mock_response).__name__ = "AssistantMessage"

    mock.query = AsyncMock(return_value=[])
    mock.handle_incident = AsyncMock(return_value={
        "agent_response": [mock_response],
        "status": "analyzed"
    })
    return mock


@pytest.fixture
def client(mock_agent):
    """Create test client with mocked agent"""
    with patch('src.api.api_server.OnCallTroubleshootingAgent', return_value=mock_agent):
        from src.api.api_server import app
        from src.api import api_server
        api_server.agent = mock_agent
        return TestClient(app)


def test_incident_success(client):
    """Test successful incident handling"""
    response = client.post(
        "/incident",
        json={
            "service": "proteus",
            "namespace": "proteus-dev",
            "error": "CrashLoopBackOff",
            "pod": "proteus-api-123",
            "restart_count": 5
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "analyzed"
    assert "alert" in data
    assert "analysis" in data
    assert "severity" in data
    assert data["alert"]["service"] == "proteus"


def test_incident_severity_critical(client):
    """Test incident severity classification - critical"""
    response = client.post(
        "/incident",
        json={
            "service": "test",
            "namespace": "default",
            "error": "OOMKilled",
            "restart_count": 10
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert data["severity"] == "critical"


def test_incident_severity_high(client):
    """Test incident severity classification - high"""
    response = client.post(
        "/incident",
        json={
            "service": "test",
            "namespace": "default",
            "error": "CrashLoopBackOff",
            "restart_count": 5
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert data["severity"] == "high"


def test_incident_severity_medium(client):
    """Test incident severity classification - medium"""
    response = client.post(
        "/incident",
        json={
            "service": "test",
            "namespace": "default",
            "error": "Error",
            "restart_count": 2
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert data["severity"] == "medium"


def test_incident_severity_low(client):
    """Test incident severity classification - low"""
    response = client.post(
        "/incident",
        json={
            "service": "test",
            "namespace": "default",
            "error": "Warning",
            "restart_count": 0
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert data["severity"] == "low"


def test_incident_cluster_validation_dev(client):
    """Test cluster validation accepts dev-eks"""
    response = client.post(
        "/incident",
        json={
            "service": "test",
            "namespace": "default",
            "error": "Error",
            "cluster": "dev-eks"
        }
    )
    assert response.status_code == 200


def test_incident_cluster_validation_prod(client):
    """Test cluster validation rejects prod-eks"""
    response = client.post(
        "/incident",
        json={
            "service": "test",
            "namespace": "default",
            "error": "Error",
            "cluster": "prod-eks"
        }
    )
    assert response.status_code == 422  # Validation error


def test_incident_missing_required_fields(client):
    """Test incident without required fields"""
    response = client.post(
        "/incident",
        json={"namespace": "default"}
    )
    assert response.status_code == 422  # Missing service and error


def test_incident_defaults(client):
    """Test incident with default values"""
    response = client.post(
        "/incident",
        json={
            "service": "test",
            "error": "Error"
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert data["alert"]["namespace"] == "default"
    assert data["alert"]["restart_count"] == 0
    assert data["alert"]["cluster"] == "dev-eks"


def test_incident_agent_not_initialized():
    """Test incident when agent not initialized"""
    with patch('src.api.api_server.OnCallTroubleshootingAgent', side_effect=Exception("Init failed")):
        from src.api.api_server import app
        from src.api import api_server
        api_server.agent = None
        client = TestClient(app)

        response = client.post(
            "/incident",
            json={
                "service": "test",
                "error": "Error"
            }
        )
        assert response.status_code == 503


def test_incident_response_format(client):
    """Test incident response has correct format"""
    response = client.post(
        "/incident",
        json={
            "service": "test",
            "namespace": "default",
            "error": "Error"
        }
    )
    assert response.status_code == 200
    data = response.json()

    # Verify response structure
    assert "status" in data
    assert "alert" in data
    assert "analysis" in data
    assert "severity" in data
    assert "duration_ms" in data
    assert "timestamp" in data

    # Verify analysis array structure
    for analysis_item in data["analysis"]:
        assert "type" in analysis_item
        assert "content" in analysis_item
