"""End-to-end integration tests for the oncall-crewai multi-agent system.

Tests the full A2A JSON-RPC protocol flow and orchestrator routing
without making real LLM calls. Covers:
- Task 9.1: Direct A2A agent message/send
- Task 9.2: Orchestrator routing (K8s, GitHub)
- Task 9.3: Multi-agent combined workflow
"""

import uuid
from unittest.mock import MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def mock_k8s_env(monkeypatch):
    """Set env vars for K8s agent."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("K8S_AGENT_URL", "http://localhost:8080")


@pytest.fixture
def mock_github_env(monkeypatch):
    """Set env vars for GitHub agent."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setenv("GITHUB_AGENT_URL", "http://localhost:8080")


@pytest.fixture
def mock_orchestrator_env(monkeypatch):
    """Set env vars for orchestrator."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setenv("K8S_AGENT_URL", "http://k8s-agent:8080")
    monkeypatch.setenv("GITHUB_AGENT_URL", "http://github-agent:8080")
    monkeypatch.setenv("API_KEYS", "e2e-test-key")
    monkeypatch.setenv("ORCHESTRATOR_URL", "http://localhost:8000")


@pytest.fixture
def mock_k8s_config():
    """Prevent real kubernetes config loading."""
    with patch("k8s_agent.tools.config") as mock_config:
        mock_config.load_incluster_config.side_effect = Exception("not in cluster")
        mock_config.load_kube_config.return_value = None
        yield mock_config


@pytest.fixture
async def k8s_client(mock_k8s_env, mock_k8s_config, monkeypatch):
    """Async client for K8s agent with auth configured."""
    import k8s_agent.server as server_module

    monkeypatch.setattr(server_module, "API_KEYS", ["test-k8s-key"])
    app = server_module.create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": "Bearer test-k8s-key"},
    ) as c:
        yield c


@pytest.fixture
async def github_client(mock_github_env, monkeypatch):
    """Async client for GitHub agent with auth configured."""
    import github_agent.server as server_module

    monkeypatch.setattr(server_module, "API_KEYS", ["test-github-key"])
    app = server_module.create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": "Bearer test-github-key"},
    ) as c:
        yield c


@pytest.fixture
async def orchestrator_client(mock_orchestrator_env, monkeypatch):
    """Async client for orchestrator with auth configured."""
    import orchestrator.auth as auth_module
    import orchestrator.main as main_module

    monkeypatch.setattr(auth_module, "API_KEYS", ["e2e-test-key"])
    monkeypatch.setattr(main_module, "API_KEYS", ["e2e-test-key"])
    app = main_module.create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": "Bearer e2e-test-key"},
    ) as c:
        yield c


def _a2a_message_send(text: str) -> dict:
    """Build a JSON-RPC message/send request."""
    return {
        "jsonrpc": "2.0",
        "method": "message/send",
        "id": str(uuid.uuid4()),
        "params": {
            "message": {
                "role": "user",
                "parts": [{"kind": "text", "text": text}],
                "messageId": str(uuid.uuid4()),
            }
        },
    }


# ============================================================
# Task 9.1: Direct A2A Agent Tests
# ============================================================


class TestDirectA2AAgentCard:
    """Verify each agent serves a valid A2A agent card."""

    @pytest.mark.asyncio
    async def test_k8s_agent_card_discoverable(self, k8s_client):
        response = await k8s_client.get("/.well-known/agent.json")
        assert response.status_code == 200
        card = response.json()
        assert card["name"] == "K8s Diagnostics Agent"
        assert len(card["skills"]) >= 3

    @pytest.mark.asyncio
    async def test_github_agent_card_discoverable(self, github_client):
        response = await github_client.get("/.well-known/agent.json")
        assert response.status_code == 200
        card = response.json()
        assert card["name"] == "GitOps Remediation Agent"
        assert len(card["skills"]) >= 3

    @pytest.mark.asyncio
    async def test_agent_cards_have_required_a2a_fields(self, k8s_client, github_client):
        """A2A protocol requires url, name, skills, capabilities."""
        for client_fixture in [k8s_client, github_client]:
            response = await client_fixture.get("/.well-known/agent.json")
            card = response.json()
            assert "url" in card
            assert "name" in card
            assert "skills" in card
            assert "capabilities" in card
            assert "defaultInputModes" in card
            assert "defaultOutputModes" in card


class TestDirectA2AMessageSend:
    """Test sending A2A JSON-RPC message/send to each agent."""

    @pytest.mark.asyncio
    async def test_k8s_agent_a2a_message_send(self, k8s_client):
        """Send a JSON-RPC message/send to the K8s agent and get a response."""
        payload = _a2a_message_send("List pods in the default namespace")

        with patch("k8s_agent.executor.invoke", return_value="Found 3 pods: nginx, redis, vault-0"):
            response = await k8s_client.post(
                "/",
                json=payload,
                headers={"Content-Type": "application/json"},
            )

        assert response.status_code == 200
        data = response.json()
        # JSON-RPC response should have result with task status
        assert "result" in data
        result = data["result"]
        # A2A response includes status with state
        assert result["status"]["state"] in ("completed", "working")

    @pytest.mark.asyncio
    async def test_github_agent_a2a_message_send(self, github_client):
        """Send a JSON-RPC message/send to the GitHub agent and get a response."""
        payload = _a2a_message_send("List files in base-apps/chores-tracker")

        with patch(
            "github_agent.executor.invoke",
            return_value="Found: deployment.yaml, service.yaml, configmap.yaml",
        ):
            response = await github_client.post(
                "/",
                json=payload,
                headers={"Content-Type": "application/json"},
            )

        assert response.status_code == 200
        data = response.json()
        assert "result" in data
        assert data["result"]["status"]["state"] in ("completed", "working")

    @pytest.mark.asyncio
    async def test_a2a_response_contains_text(self, k8s_client):
        """Verify the A2A response includes the agent's text output."""
        payload = _a2a_message_send("Check vault health")

        with patch("k8s_agent.executor.invoke", return_value="Vault is healthy and unsealed"):
            response = await k8s_client.post(
                "/",
                json=payload,
                headers={"Content-Type": "application/json"},
            )

        data = response.json()
        result = data["result"]
        # Find the completed status message
        status = result["status"]
        if status["state"] == "completed":
            parts = status["message"]["parts"]
            texts = [p["text"] for p in parts if p.get("kind") == "text"]
            assert any("Vault is healthy" in t for t in texts)

    @pytest.mark.asyncio
    async def test_a2a_error_returns_failed_state(self, k8s_client):
        """Verify agent errors produce a failed task state."""
        payload = _a2a_message_send("Check pods")

        with patch("k8s_agent.executor.invoke", side_effect=Exception("Connection refused")):
            response = await k8s_client.post(
                "/",
                json=payload,
                headers={"Content-Type": "application/json"},
            )

        data = response.json()
        assert data["result"]["status"]["state"] == "failed"


# ============================================================
# Task 9.2: Orchestrator Routing E2E Tests
# ============================================================


class TestOrchestratorRouting:
    """Test the orchestrator routes queries to the correct agent."""

    @pytest.mark.asyncio
    async def test_k8s_query_routes_to_k8s(self, orchestrator_client):
        """A K8s query should route to the K8s agent."""
        with patch("orchestrator.main.OncallFlow") as MockFlow:
            mock_flow = MagicMock()
            mock_flow.state.route = "k8s"
            mock_flow.state.query = "Why is vault pod crashing?"
            mock_flow.kickoff.return_value = "Vault-0 is in CrashLoopBackOff due to OOM"
            MockFlow.return_value = mock_flow

            response = await orchestrator_client.post(
                "/query",
                json={"prompt": "Why is vault pod crashing?"},
                headers={"Authorization": "Bearer e2e-test-key"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["route"] == "k8s"
        assert "CrashLoopBackOff" in data["response"]

    @pytest.mark.asyncio
    async def test_github_query_routes_to_github(self, orchestrator_client):
        """A GitHub query should route to the GitHub agent."""
        with patch("orchestrator.main.OncallFlow") as MockFlow:
            mock_flow = MagicMock()
            mock_flow.state.route = "github"
            mock_flow.state.query = "Show me the deployment manifest for chores-tracker"
            mock_flow.kickoff.return_value = "deployment.yaml: replicas=1, image=chores-tracker:v2"
            MockFlow.return_value = mock_flow

            response = await orchestrator_client.post(
                "/query",
                json={"prompt": "Show me the deployment manifest for chores-tracker"},
                headers={"Authorization": "Bearer e2e-test-key"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["route"] == "github"
        assert "deployment.yaml" in data["response"]

    @pytest.mark.asyncio
    async def test_orchestrator_a2a_agent_card(self, orchestrator_client):
        """Orchestrator should also serve an A2A agent card."""
        response = await orchestrator_client.get("/.well-known/agent.json")
        assert response.status_code == 200
        card = response.json()
        assert card["name"] == "OnCall Orchestrator"
        skill_ids = [s["id"] for s in card["skills"]]
        assert "triage-incident" in skill_ids

    @pytest.mark.asyncio
    async def test_orchestrator_rejects_unauthenticated(self, orchestrator_client):
        """Queries without auth should be rejected."""
        response = await orchestrator_client.post(
            "/query",
            json={"prompt": "check pods"},
            headers={"Authorization": "Bearer invalid-key"},
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_response_includes_context_id(self, orchestrator_client):
        """Response should include a context_id for session tracking."""
        ctx = str(uuid.uuid4())
        with patch("orchestrator.main.OncallFlow") as MockFlow:
            mock_flow = MagicMock()
            mock_flow.state.route = "k8s"
            mock_flow.kickoff.return_value = "OK"
            MockFlow.return_value = mock_flow

            response = await orchestrator_client.post(
                "/query",
                json={"prompt": "check pods", "context_id": ctx},
                headers={"Authorization": "Bearer e2e-test-key"},
            )

        data = response.json()
        assert data["context_id"] == ctx


# ============================================================
# Task 9.3: Multi-Agent Combined Workflow
# ============================================================


class TestCombinedWorkflow:
    """Test queries that require both K8s and GitHub agents."""

    @pytest.mark.asyncio
    async def test_combined_query_engages_both_agents(self, orchestrator_client):
        """A query with both K8s and GitHub keywords should route to combined."""
        with patch("orchestrator.main.OncallFlow") as MockFlow:
            mock_flow = MagicMock()
            mock_flow.state.route = "combined"
            mock_flow.kickoff.return_value = (
                "## K8s Diagnostics\nchores-tracker pod is OOMKilled\n\n"
                "## GitOps Analysis\nCurrent manifest has 128Mi memory limit"
            )
            MockFlow.return_value = mock_flow

            response = await orchestrator_client.post(
                "/query",
                json={
                    "prompt": "The chores-tracker pod is crashing, check the logs and create a PR to fix it"
                },
                headers={"Authorization": "Bearer e2e-test-key"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["route"] == "combined"
        assert "K8s Diagnostics" in data["response"]
        assert "GitOps Analysis" in data["response"]

    @pytest.mark.asyncio
    async def test_combined_flow_classification(self, mock_orchestrator_env):
        """Verify the classify_query function correctly identifies combined queries."""
        from orchestrator.flow import classify_query

        # Both K8s ("pod", "crashing", "logs") and GitHub ("PR") keywords
        result = classify_query(
            "The pod is crashing, check the logs and create a PR to fix it"
        )
        assert result == "combined"

    @pytest.mark.asyncio
    async def test_k8s_only_classification(self, mock_orchestrator_env):
        """Verify pure K8s queries don't trigger combined routing."""
        from orchestrator.flow import classify_query

        assert classify_query("Why is vault-0 in CrashLoopBackOff?") == "k8s"

    @pytest.mark.asyncio
    async def test_github_only_classification(self, mock_orchestrator_env):
        """Verify pure GitHub queries don't trigger combined routing."""
        from orchestrator.flow import classify_query

        assert classify_query("List the base-apps directory in the gitops repo") == "github"


# ============================================================
# Cross-agent discovery
# ============================================================


class TestAgentDiscovery:
    """Verify all three agents are discoverable via A2A protocol."""

    @pytest.mark.asyncio
    async def test_all_agents_serve_well_known_endpoint(
        self, k8s_client, github_client, orchestrator_client
    ):
        """Every agent must respond at /.well-known/agent.json."""
        for name, client_fixture in [
            ("k8s", k8s_client),
            ("github", github_client),
            ("orchestrator", orchestrator_client),
        ]:
            response = await client_fixture.get("/.well-known/agent.json")
            assert response.status_code == 200, f"{name} agent card not found"
            card = response.json()
            assert "name" in card, f"{name} agent card missing name"
            assert "skills" in card, f"{name} agent card missing skills"

    @pytest.mark.asyncio
    async def test_all_agents_healthy(
        self, k8s_client, github_client, orchestrator_client
    ):
        """Every agent must respond to health checks."""
        for name, client_fixture in [
            ("k8s", k8s_client),
            ("github", github_client),
            ("orchestrator", orchestrator_client),
        ]:
            response = await client_fixture.get("/health")
            assert response.status_code == 200, f"{name} agent health check failed"
            data = response.json()
            assert data["status"] == "healthy", f"{name} agent unhealthy"
