# ==============================================================================
# Orchestrator Tests
# ==============================================================================
# Tests for the orchestrator's API endpoints and routing logic.
# These tests mock the CrewAI flow to avoid real LLM calls.
# ==============================================================================

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from orchestrator.main import app


@pytest.fixture
def client():
    """Create a test client for the FastAPI app."""
    return TestClient(app)


class TestHealthEndpoint:
    """Tests for the /health endpoint."""

    def test_health_returns_200(self, client):
        """Health check should always return 200 with status info."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "service" in data

    def test_health_includes_service_name(self, client):
        """Health response should include the project name."""
        response = client.get("/health")
        assert "service" in response.json()


class TestInfoEndpoint:
    """Tests for the /info endpoint."""

    def test_info_returns_200(self, client):
        """Info endpoint should return metadata about the orchestrator."""
        response = client.get("/info")
        assert response.status_code == 200
        data = response.json()
        assert "sub_agents" in data
        assert len(data["sub_agents"]) > 0


class TestInvokeEndpoint:
    """Tests for the /invoke endpoint."""

    @patch("orchestrator.main.OrchestratorFlow")
    def test_invoke_returns_result(self, mock_flow_class, client):
        """Invoke should return the flow's result."""
        # Mock the flow to avoid real LLM calls
        mock_flow = MagicMock()
        mock_flow.kickoff.return_value = "Test response"
        mock_flow.state.route = "sub_agent"
        mock_flow_class.return_value = mock_flow

        response = client.post("/invoke", json={"query": "test query"})
        assert response.status_code == 200
        data = response.json()
        assert "result" in data
        assert "route" in data

    def test_invoke_requires_query(self, client):
        """Invoke should reject requests without a query field."""
        response = client.post("/invoke", json={})
        assert response.status_code == 422  # Validation error


class TestKeywordRouting:
    """Tests for the keyword-based routing logic."""

    def test_routing_keywords_loaded(self):
        """Routing keywords should be loaded from config."""
        from orchestrator.prompts import ROUTING_KEYWORDS
        assert isinstance(ROUTING_KEYWORDS, list)
        # Keywords should be lowercase
        for kw in ROUTING_KEYWORDS:
            assert kw == kw.lower()

