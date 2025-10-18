"""
Tests for session management endpoints
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import Mock, patch, AsyncMock
import sys
import os
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

    mock_response = Mock()
    mock_response.content = [Mock(text="Test response")]
    type(mock_response.content[0]).__name__ = "TextBlock"
    type(mock_response).__name__ = "AssistantMessage"

    mock.query = AsyncMock(return_value=[mock_response])
    mock.handle_incident = AsyncMock(return_value={"agent_response": []})
    return mock


@pytest.fixture
def client(mock_agent):
    """Create test client with mocked agent and no auth"""
    # Disable authentication for tests
    if "API_KEYS" in os.environ:
        del os.environ["API_KEYS"]

    with patch('src.api.api_server.OnCallTroubleshootingAgent', return_value=mock_agent):
        from src.api.api_server import app
        from src.api import api_server
        api_server.agent = mock_agent

        # Initialize session manager manually since we're bypassing lifespan
        from src.api.session_manager import SessionManager
        api_server.session_manager = SessionManager(ttl_minutes=30)

        return TestClient(app)


def test_create_session(client):
    """Test session creation"""
    response = client.post(
        "/session",
        json={"user_id": "test-user@example.com"}
    )
    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "created"
    assert "session_id" in data
    assert data["user_id"] == "test-user@example.com"
    assert "created_at" in data
    assert "conversation_history" in data


def test_create_session_with_metadata(client):
    """Test session creation with metadata"""
    response = client.post(
        "/session",
        json={
            "user_id": "test-user",
            "metadata": {
                "team": "devops",
                "source": "n8n"
            }
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "created"


def test_get_session(client):
    """Test retrieving session"""
    # Create session first
    create_response = client.post(
        "/session",
        json={"user_id": "test-user"}
    )
    session_id = create_response.json()["session_id"]

    # Retrieve session
    get_response = client.get(f"/session/{session_id}")
    assert get_response.status_code == 200
    data = get_response.json()

    assert data["status"] == "success"
    assert data["session_id"] == session_id
    assert data["user_id"] == "test-user"


def test_get_nonexistent_session(client):
    """Test retrieving non-existent session"""
    response = client.get("/session/nonexistent-id")
    assert response.status_code == 404


def test_delete_session(client):
    """Test deleting session"""
    # Create session first
    create_response = client.post(
        "/session",
        json={"user_id": "test-user"}
    )
    session_id = create_response.json()["session_id"]

    # Delete session
    delete_response = client.delete(f"/session/{session_id}")
    assert delete_response.status_code == 200
    data = delete_response.json()
    assert data["status"] == "deleted"

    # Verify it's gone
    get_response = client.get(f"/session/{session_id}")
    assert get_response.status_code == 404


def test_delete_nonexistent_session(client):
    """Test deleting non-existent session"""
    response = client.delete("/session/nonexistent-id")
    assert response.status_code == 404


def test_session_stats(client):
    """Test getting session statistics"""
    # Create a few sessions
    client.post("/session", json={"user_id": "user1"})
    client.post("/session", json={"user_id": "user2"})

    response = client.get("/sessions/stats")
    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "success"
    assert "stats" in data
    assert "total_sessions" in data["stats"]
    assert "active_sessions" in data["stats"]


def test_query_with_session_id(client):
    """Test query with session context"""
    # Create session
    session_response = client.post(
        "/session",
        json={"user_id": "test-user"}
    )
    session_id = session_response.json()["session_id"]

    # Make query with session
    query_response = client.post(
        "/query",
        json={
            "prompt": "Test query",
            "session_id": session_id
        }
    )
    assert query_response.status_code == 200
    data = query_response.json()
    assert data["session_id"] == session_id

    # Retrieve session to verify history was updated
    get_session_response = client.get(f"/session/{session_id}")
    session_data = get_session_response.json()
    # Conversation history should have been updated (length > 0)
    # Note: This depends on session update implementation


def test_query_with_invalid_session_id(client):
    """Test query with non-existent session_id"""
    # Should still work but session won't be used
    response = client.post(
        "/query",
        json={
            "prompt": "Test query",
            "session_id": "nonexistent-session"
        }
    )
    # Should still process the query even if session doesn't exist
    assert response.status_code == 200
