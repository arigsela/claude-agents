"""Tests for the orchestrator — routing logic, API endpoints, and A2A.

Tests classification, Flow routing, FastAPI endpoints, and auth
without making real LLM or A2A calls.
"""

import json
import uuid
from unittest.mock import MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def mock_env(monkeypatch):
    """Set required env vars."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setenv("K8S_AGENT_URL", "http://k8s-agent:8080")
    monkeypatch.setenv("GITHUB_AGENT_URL", "http://github-agent:8080")
    monkeypatch.setenv("API_KEYS", "valid-key-1,valid-key-2")
    monkeypatch.setenv("ORCHESTRATOR_URL", "http://localhost:8000")


@pytest.fixture
def app(mock_env, monkeypatch):
    """Create the FastAPI app for testing."""
    from orchestrator.main import create_app

    # API_KEYS is evaluated at import time in shared.config, so we must
    # patch the binding in orchestrator.main for tests to see the values.
    monkeypatch.setattr(
        "orchestrator.main.API_KEYS", ["valid-key-1", "valid-key-2"]
    )
    return create_app()


@pytest.fixture
async def client(app):
    """Create an async test client."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ============================================================
# Query classification
# ============================================================


class TestClassifyQuery:
    def test_k8s_query(self, mock_env):
        from orchestrator.flow import classify_query

        assert classify_query("why is the vault pod crashing?") == "k8s"

    def test_k8s_default_for_unknown(self, mock_env):
        from orchestrator.flow import classify_query

        assert classify_query("hello, can you help me?") == "k8s"

    def test_github_query(self, mock_env):
        from orchestrator.flow import classify_query

        assert classify_query("list the base-apps directory") == "github"

    def test_combined_when_both_keywords(self, mock_env):
        from orchestrator.flow import classify_query

        # "deployment" is K8s, "PR" is GitHub -> combined
        assert classify_query("create a PR to fix the deployment") == "combined"

    def test_combined_query(self, mock_env):
        from orchestrator.flow import classify_query

        result = classify_query(
            "the pod is crashing, can you check the logs and create a PR to fix it?"
        )
        assert result == "combined"

    def test_k8s_keywords_detected(self, mock_env):
        from orchestrator.flow import classify_query

        assert classify_query("list all namespaces in the cluster") == "k8s"
        assert classify_query("check deployment status") == "k8s"
        assert classify_query("get pod logs for mysql") == "k8s"
        assert classify_query("is vault sealed?") == "k8s"

    def test_github_keywords_detected(self, mock_env):
        from orchestrator.flow import classify_query

        assert classify_query("list the base-apps directory") == "github"
        assert classify_query("search recent github actions") == "github"
        assert classify_query("show me the gitops manifest") == "github"


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
        assert data["agent"] == "orchestrator"


# ============================================================
# Root endpoint
# ============================================================


class TestRootEndpoint:
    @pytest.mark.asyncio
    async def test_root_returns_info(self, client):
        response = await client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["service"] == "oncall-crewai-orchestrator"
        assert "k8s-diagnostics" in data["agents"]
        assert "github-gitops" in data["agents"]


# ============================================================
# Agent Card
# ============================================================


class TestAgentCard:
    @pytest.mark.asyncio
    async def test_agent_card_returns_valid_json(self, client):
        response = await client.get("/.well-known/agent.json")
        assert response.status_code == 200
        card = response.json()
        assert card["name"] == "OnCall Orchestrator"

    @pytest.mark.asyncio
    async def test_agent_card_has_skills(self, client):
        response = await client.get("/.well-known/agent.json")
        card = response.json()
        skill_ids = [s["id"] for s in card["skills"]]
        assert "triage-incident" in skill_ids
        assert "coordinate-investigation" in skill_ids


# ============================================================
# Authentication
# ============================================================


class TestAuthentication:
    @pytest.mark.asyncio
    async def test_query_with_valid_key(self, client):
        with patch("orchestrator.main.OncallFlow") as MockFlow:
            mock_flow = MagicMock()
            mock_flow.state.route = "k8s"
            mock_flow.kickoff.return_value = "Vault pods are healthy"
            MockFlow.return_value = mock_flow

            response = await client.post(
                "/query",
                json={"prompt": "check vault pods"},
                headers={"Authorization": "Bearer valid-key-1"},
            )

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_query_with_invalid_key(self, client):
        response = await client.post(
            "/query",
            json={"prompt": "check vault pods"},
            headers={"Authorization": "Bearer bad-key"},
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_query_with_x_api_key(self, client):
        with patch("orchestrator.main.OncallFlow") as MockFlow:
            mock_flow = MagicMock()
            mock_flow.state.route = "k8s"
            mock_flow.kickoff.return_value = "OK"
            MockFlow.return_value = mock_flow

            response = await client.post(
                "/query",
                json={"prompt": "check pods"},
                headers={"X-API-Key": "valid-key-2"},
            )

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_no_auth_when_api_keys_empty(self, mock_env):
        """When API_KEYS is empty, auth is disabled (dev mode)."""
        with patch("orchestrator.main.API_KEYS", []):
            from orchestrator.main import create_app

            dev_app = create_app()
            transport = ASGITransport(app=dev_app)
            async with AsyncClient(transport=transport, base_url="http://test") as c:
                with patch("orchestrator.main.OncallFlow") as MockFlow:
                    mock_flow = MagicMock()
                    mock_flow.state.route = "k8s"
                    mock_flow.kickoff.return_value = "OK"
                    MockFlow.return_value = mock_flow

                    response = await c.post(
                        "/query",
                        json={"prompt": "check pods"},
                    )

            assert response.status_code == 200


# ============================================================
# Query endpoint
# ============================================================


class TestQueryEndpoint:
    @pytest.mark.asyncio
    async def test_query_returns_response(self, client):
        with patch("orchestrator.main.OncallFlow") as MockFlow:
            mock_flow = MagicMock()
            mock_flow.state.route = "k8s"
            mock_flow.state.query = "check pods"
            mock_flow.kickoff.return_value = "All pods healthy"
            MockFlow.return_value = mock_flow

            response = await client.post(
                "/query",
                json={"prompt": "check pods"},
                headers={"Authorization": "Bearer valid-key-1"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["response"] == "All pods healthy"
        assert data["route"] == "k8s"

    @pytest.mark.asyncio
    async def test_query_with_context_id(self, client):
        ctx_id = str(uuid.uuid4())

        with patch("orchestrator.main.OncallFlow") as MockFlow:
            mock_flow = MagicMock()
            mock_flow.state.route = "github"
            mock_flow.kickoff.return_value = "PR created"
            MockFlow.return_value = mock_flow

            response = await client.post(
                "/query",
                json={"prompt": "create pr", "context_id": ctx_id},
                headers={"Authorization": "Bearer valid-key-1"},
            )

        data = response.json()
        assert data["context_id"] == ctx_id


# ============================================================
# Orchestrator A2A Executor
# ============================================================


class TestOrchestratorExecutor:
    @pytest.mark.asyncio
    async def test_execute_success(self, mock_env):
        from a2a.server.events.event_queue import EventQueue
        from a2a.types import TaskState, TextPart

        from orchestrator.main import OrchestratorExecutor

        executor = OrchestratorExecutor()
        context = MagicMock()
        context.task_id = str(uuid.uuid4())
        context.context_id = str(uuid.uuid4())
        text_part = TextPart(text="check pods")
        context.message.parts = [text_part]

        event_queue = EventQueue()

        with patch("orchestrator.main.OncallFlow") as MockFlow:
            mock_flow = MagicMock()
            mock_flow.kickoff.return_value = "All healthy"
            MockFlow.return_value = mock_flow

            await executor.execute(context, event_queue)

        event1 = await event_queue.dequeue_event(no_wait=True)
        assert event1.status.state == TaskState.working

        event2 = await event_queue.dequeue_event(no_wait=True)
        assert event2.status.state == TaskState.completed
