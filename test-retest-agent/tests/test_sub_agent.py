# ==============================================================================
# Sub-Agent Tests
# ==============================================================================
# Tests for the sub-agent's tools, server endpoints, and A2A protocol.
# All LLM calls and external dependencies are mocked.
# ==============================================================================

import pytest
import json
from unittest.mock import patch

from test-sub-agent.tools import search_knowledge, get_system_info, check_health


class TestTools:
    """Tests for the sub-agent's tools."""

    def test_search_knowledge_returns_json(self):
        """search_knowledge should return valid JSON."""
        result = search_knowledge.run("test query")
        data = json.loads(result)
        assert "status" in data
        assert "query" in data

    def test_get_system_info_returns_json(self):
        """get_system_info should return valid JSON."""
        result = get_system_info.run("api")
        data = json.loads(result)
        assert "status" in data

    def test_get_system_info_handles_empty_component(self):
        """get_system_info should work with no component specified."""
        result = get_system_info.run("")
        data = json.loads(result)
        assert data["component"] == "overview"

    def test_check_health_returns_json(self):
        """check_health should return valid JSON."""
        result = check_health.run("")
        data = json.loads(result)
        assert "status" in data


class TestSubAgentServer:
    """Tests for the sub-agent's FastAPI server."""

    def test_health_endpoint(self):
        """The sub-agent should have a working health endpoint."""
        from fastapi.testclient import TestClient
        from test-sub-agent.server import app

        client = TestClient(app)
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"

    def test_auth_middleware_allows_health(self):
        """Health endpoint should be accessible without API key."""
        from fastapi.testclient import TestClient
        from test-sub-agent.server import app

        client = TestClient(app)
        # No API key header — should still work for /health
        response = client.get("/health")
        assert response.status_code == 200


class TestAgentCreation:
    """Tests for agent configuration."""

    def test_agent_has_tools(self):
        """The agent should be created with the expected tools."""
        with patch("test-sub-agent.agent.LLM"):
            from test-sub-agent.agent import create_agent
            agent = create_agent()
            tool_names = [t.name for t in agent.tools]
            assert "search_knowledge" in tool_names
            assert "get_system_info" in tool_names
            assert "check_health" in tool_names

    def test_agent_role_configured(self):
        """The agent should have the configured role."""
        with patch("test-sub-agent.agent.LLM"):
            from test-sub-agent.agent import create_agent
            agent = create_agent()
            assert agent.role is not None
            assert len(agent.role) > 0

