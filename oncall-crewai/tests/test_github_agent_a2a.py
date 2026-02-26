"""Integration tests for the GitHub A2A Agent server.

Tests the A2A endpoints (agent card, health) and executor behavior
without making real LLM or GitHub API calls.
"""

import json
import uuid
from unittest.mock import MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def mock_env(monkeypatch):
    """Set required env vars for agent initialization."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setenv("GITHUB_AGENT_URL", "http://localhost:8080")


@pytest.fixture
def app(mock_env):
    """Create the FastAPI app for testing."""
    from github_agent.server import create_app

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
        assert data["agent"] == "github-gitops"


# ============================================================
# Agent Card
# ============================================================


class TestAgentCard:
    @pytest.mark.asyncio
    async def test_agent_card_returns_valid_json(self, client):
        response = await client.get("/.well-known/agent.json")
        assert response.status_code == 200
        card = response.json()
        assert card["name"] == "GitOps Remediation Agent"
        assert card["version"] == "0.1.0"

    @pytest.mark.asyncio
    async def test_agent_card_has_skills(self, client):
        response = await client.get("/.well-known/agent.json")
        card = response.json()
        skill_ids = [s["id"] for s in card["skills"]]
        assert "inspect-manifests" in skill_ids
        assert "create-remediation-pr" in skill_ids
        assert "check-deployments" in skill_ids

    @pytest.mark.asyncio
    async def test_agent_card_capabilities(self, client):
        response = await client.get("/.well-known/agent.json")
        card = response.json()
        assert card["capabilities"]["streaming"] is False

    @pytest.mark.asyncio
    async def test_agent_card_has_url(self, client):
        response = await client.get("/.well-known/agent.json")
        card = response.json()
        assert card["url"] == "http://localhost:8080"


# ============================================================
# Auth middleware
# ============================================================


class TestAuthMiddleware:
    @pytest.fixture
    def auth_app(self, mock_env, monkeypatch):
        """Create app with API_KEYS enforced."""
        import github_agent.server as server_module

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


class TestGitHubAgentExecutor:
    def test_extract_user_input_text(self, mock_env):
        from a2a.types import TextPart

        from github_agent.executor import GitHubAgentExecutor

        executor = GitHubAgentExecutor()
        context = MagicMock()
        text_part = TextPart(text="Show me the chores-tracker manifests")
        context.message.parts = [text_part]

        result = executor._extract_user_input(context)
        assert result == "Show me the chores-tracker manifests"

    def test_extract_user_input_no_message(self, mock_env):
        from github_agent.executor import GitHubAgentExecutor

        executor = GitHubAgentExecutor()
        context = MagicMock()
        context.message = None

        result = executor._extract_user_input(context)
        assert "base-apps" in result.lower()

    @pytest.mark.asyncio
    async def test_execute_success(self, mock_env):
        from a2a.server.events.event_queue import EventQueue
        from a2a.types import TaskState, TextPart

        from github_agent.executor import GitHubAgentExecutor

        executor = GitHubAgentExecutor()

        context = MagicMock()
        context.task_id = str(uuid.uuid4())
        context.context_id = str(uuid.uuid4())
        text_part = TextPart(text="List base-apps directory")
        context.message.parts = [text_part]

        event_queue = EventQueue()

        with patch(
            "github_agent.executor.invoke",
            return_value="Found 12 services in base-apps/",
        ):
            await executor.execute(context, event_queue)

        event1 = await event_queue.dequeue_event(no_wait=True)
        assert event1.status.state == TaskState.working

        event2 = await event_queue.dequeue_event(no_wait=True)
        # event2 is TaskArtifactUpdateEvent with the result
        assert event2.artifact is not None

        event3 = await event_queue.dequeue_event(no_wait=True)
        assert event3.status.state == TaskState.completed
        response_text = event3.status.message.parts[0].root.text
        assert "12 services" in response_text

    @pytest.mark.asyncio
    async def test_execute_error(self, mock_env):
        from a2a.server.events.event_queue import EventQueue
        from a2a.types import TaskState, TextPart

        from github_agent.executor import GitHubAgentExecutor

        executor = GitHubAgentExecutor()

        context = MagicMock()
        context.task_id = str(uuid.uuid4())
        context.context_id = str(uuid.uuid4())
        text_part = TextPart(text="Create a PR")
        context.message.parts = [text_part]

        event_queue = EventQueue()

        with patch(
            "github_agent.executor.invoke",
            side_effect=Exception("GitHub rate limit"),
        ):
            await executor.execute(context, event_queue)

        event1 = await event_queue.dequeue_event(no_wait=True)
        assert event1.status.state == TaskState.working

        event2 = await event_queue.dequeue_event(no_wait=True)
        assert event2.status.state == TaskState.failed
        response_text = event2.status.message.parts[0].root.text
        assert "GitHub rate limit" in response_text
