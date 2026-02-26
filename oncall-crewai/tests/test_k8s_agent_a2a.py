"""Integration tests for the K8s A2A Agent server.

Tests the A2A endpoints (agent card, health) and executor behavior
without making real LLM or K8s API calls.
"""

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def mock_env(monkeypatch):
    """Set required env vars for agent initialization."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("K8S_AGENT_URL", "http://localhost:8080")


@pytest.fixture
def mock_k8s_config():
    """Prevent real kubernetes config loading."""
    with patch("k8s_agent.tools.config") as mock_config:
        mock_config.load_incluster_config.side_effect = Exception("not in cluster")
        mock_config.load_kube_config.return_value = None
        yield mock_config


@pytest.fixture
def app(mock_env, mock_k8s_config):
    """Create the FastAPI app for testing."""
    # Import here so env vars are set first
    from k8s_agent.server import create_app

    return create_app()


@pytest.fixture
async def client(app):
    """Create an async test client."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ============================================================
# Health endpoint
# ============================================================


class TestHealthEndpoint:
    @pytest.mark.asyncio
    async def test_health_returns_200(self, client):
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["agent"] == "k8s-diagnostics"


# ============================================================
# Agent Card (/.well-known/agent.json)
# ============================================================


class TestAgentCard:
    @pytest.mark.asyncio
    async def test_agent_card_returns_valid_json(self, client):
        response = await client.get("/.well-known/agent.json")
        assert response.status_code == 200
        card = response.json()
        assert card["name"] == "K8s Diagnostics Agent"
        assert card["version"] == "0.1.0"

    @pytest.mark.asyncio
    async def test_agent_card_has_skills(self, client):
        response = await client.get("/.well-known/agent.json")
        card = response.json()
        skills = card["skills"]
        skill_ids = [s["id"] for s in skills]
        assert "diagnose-pods" in skill_ids
        assert "check-deployments" in skill_ids
        assert "analyze-service-health" in skill_ids

    @pytest.mark.asyncio
    async def test_agent_card_capabilities(self, client):
        response = await client.get("/.well-known/agent.json")
        card = response.json()
        assert card["capabilities"]["streaming"] is False

    @pytest.mark.asyncio
    async def test_agent_card_has_url(self, client):
        response = await client.get("/.well-known/agent.json")
        card = response.json()
        assert "url" in card
        assert card["url"] == "http://localhost:8080"


# ============================================================
# Auth middleware
# ============================================================


class TestAuthMiddleware:
    @pytest.fixture
    def auth_app(self, mock_env, mock_k8s_config, monkeypatch):
        """Create app with API_KEYS enforced."""
        import k8s_agent.server as server_module

        monkeypatch.setattr(
            server_module, "API_KEYS", ["test-api-key-1", "test-api-key-2"]
        )
        return server_module.create_app()

    @pytest.fixture
    async def auth_client(self, auth_app):
        transport = ASGITransport(app=auth_app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c

    @pytest.mark.asyncio
    async def test_health_no_auth_required(self, auth_client):
        response = await auth_client.get("/health")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_agent_card_no_auth_required(self, auth_client):
        response = await auth_client.get("/.well-known/agent.json")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_post_without_key_returns_401(self, auth_client):
        response = await auth_client.post(
            "/",
            json={"jsonrpc": "2.0", "method": "message/send", "id": "1"},
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_post_with_valid_x_api_key(self, auth_client):
        response = await auth_client.post(
            "/",
            json={"jsonrpc": "2.0", "method": "message/send", "id": "1"},
            headers={"X-API-Key": "test-api-key-1"},
        )
        # Should not be 401 — may be 400/422 due to incomplete payload, but auth passed
        assert response.status_code != 401

    @pytest.mark.asyncio
    async def test_post_with_valid_bearer_token(self, auth_client):
        response = await auth_client.post(
            "/",
            json={"jsonrpc": "2.0", "method": "message/send", "id": "1"},
            headers={"Authorization": "Bearer test-api-key-2"},
        )
        assert response.status_code != 401

    @pytest.mark.asyncio
    async def test_post_with_invalid_key_returns_401(self, auth_client):
        response = await auth_client.post(
            "/",
            json={"jsonrpc": "2.0", "method": "message/send", "id": "1"},
            headers={"X-API-Key": "wrong-key"},
        )
        assert response.status_code == 401


# ============================================================
# Executor unit tests
# ============================================================


class TestK8sAgentExecutor:
    def test_extract_user_input_text(self, mock_env, mock_k8s_config):
        from a2a.types import TextPart

        from k8s_agent.executor import K8sAgentExecutor

        executor = K8sAgentExecutor()
        context = MagicMock()
        text_part = TextPart(text="Why is vault-0 crashing?")
        context.message.parts = [text_part]

        result = executor._extract_user_input(context)
        assert result == "Why is vault-0 crashing?"

    def test_extract_user_input_no_message(self, mock_env, mock_k8s_config):
        from k8s_agent.executor import K8sAgentExecutor

        executor = K8sAgentExecutor()
        context = MagicMock()
        context.message = None

        result = executor._extract_user_input(context)
        assert "general cluster health check" in result.lower()

    @pytest.mark.asyncio
    async def test_execute_success(self, mock_env, mock_k8s_config):
        from a2a.server.events.event_queue import EventQueue
        from a2a.types import TaskState, TextPart

        from k8s_agent.executor import K8sAgentExecutor

        executor = K8sAgentExecutor()

        context = MagicMock()
        context.task_id = str(uuid.uuid4())
        context.context_id = str(uuid.uuid4())
        text_part = TextPart(text="Check vault pods")
        context.message.parts = [text_part]

        event_queue = EventQueue()

        with patch("k8s_agent.executor.invoke", return_value="Vault pods are healthy"):
            await executor.execute(context, event_queue)

        # Should have 3 events: working + artifact + completed
        event1 = await event_queue.dequeue_event(no_wait=True)
        assert event1.status.state == TaskState.working

        event2 = await event_queue.dequeue_event(no_wait=True)
        # event2 is TaskArtifactUpdateEvent with the result
        assert event2.artifact is not None

        event3 = await event_queue.dequeue_event(no_wait=True)
        assert event3.status.state == TaskState.completed
        # Check the response text
        response_text = event3.status.message.parts[0].root.text
        assert "Vault pods are healthy" in response_text

    @pytest.mark.asyncio
    async def test_execute_error(self, mock_env, mock_k8s_config):
        from a2a.server.events.event_queue import EventQueue
        from a2a.types import TaskState, TextPart

        from k8s_agent.executor import K8sAgentExecutor

        executor = K8sAgentExecutor()

        context = MagicMock()
        context.task_id = str(uuid.uuid4())
        context.context_id = str(uuid.uuid4())
        text_part = TextPart(text="Check pods")
        context.message.parts = [text_part]

        event_queue = EventQueue()

        with patch("k8s_agent.executor.invoke", side_effect=Exception("LLM timeout")):
            await executor.execute(context, event_queue)

        # Should have 2 events: working + failed
        event1 = await event_queue.dequeue_event(no_wait=True)
        assert event1.status.state == TaskState.working

        event2 = await event_queue.dequeue_event(no_wait=True)
        assert event2.status.state == TaskState.failed
        response_text = event2.status.message.parts[0].root.text
        assert "LLM timeout" in response_text
