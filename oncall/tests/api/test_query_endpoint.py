"""
Tests for /query endpoint
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

    # Mock query to return AssistantMessage-like response
    mock_response = Mock()
    mock_response.content = [Mock(text="This is the agent response")]
    type(mock_response.content[0]).__name__ = "TextBlock"
    type(mock_response).__name__ = "AssistantMessage"

    mock.query = AsyncMock(return_value=[mock_response])
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


def test_query_success(client):
    """Test successful query"""
    response = client.post(
        "/query",
        json={
            "prompt": "What services are you monitoring?",
            "namespace": "default"
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "responses" in data
    assert len(data["responses"]) > 0
    assert data["query"] == "What services are you monitoring?"


def test_query_with_namespace_context(client):
    """Test query with namespace context"""
    response = client.post(
        "/query",
        json={
            "prompt": "Check pod status",
            "namespace": "proteus-dev"
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"


def test_query_with_additional_context(client):
    """Test query with additional context"""
    response = client.post(
        "/query",
        json={
            "prompt": "Analyze errors",
            "namespace": "default",
            "context": {
                "user": "devops-team",
                "source": "n8n"
            }
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"


def test_query_missing_prompt(client):
    """Test query without prompt"""
    response = client.post(
        "/query",
        json={"namespace": "default"}
    )
    assert response.status_code == 422  # Validation error


def test_query_empty_prompt(client):
    """Test query with empty prompt"""
    response = client.post(
        "/query",
        json={"prompt": ""}
    )
    assert response.status_code == 422  # Validation error


def test_query_prompt_too_long(client):
    """Test query with prompt exceeding max length"""
    response = client.post(
        "/query",
        json={"prompt": "x" * 10001}
    )
    assert response.status_code == 422  # Validation error


def test_query_agent_not_initialized():
    """Test query when agent not initialized"""
    with patch('src.api.api_server.OnCallTroubleshootingAgent', side_effect=Exception("Init failed")):
        from src.api.api_server import app
        from src.api import api_server
        api_server.agent = None
        client = TestClient(app)

        response = client.post(
            "/query",
            json={"prompt": "Test"}
        )
        assert response.status_code == 503


def test_query_response_format(client):
    """Test query response has correct format"""
    response = client.post(
        "/query",
        json={"prompt": "Test query"}
    )
    assert response.status_code == 200
    data = response.json()

    # Verify response structure
    assert "status" in data
    assert "responses" in data
    assert "query" in data
    assert "duration_ms" in data
    assert "timestamp" in data

    # Verify responses array structure
    for resp in data["responses"]:
        assert "type" in resp
        assert "content" in resp
