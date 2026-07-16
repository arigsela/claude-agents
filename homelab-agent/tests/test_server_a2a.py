"""A2A protocol surface: health, agent card, executor event flow.
Mirrors oncall-crewai/tests/test_k8s_agent_a2a.py."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.delenv("KAGENT_URL", raising=False)
    from homelab_agent.server import create_app

    return create_app()


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestHealth:
    async def test_health_returns_200(self, client):
        response = await client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "healthy", "agent": "homelab-agent"}


class TestAgentCard:
    async def test_card_identity(self, client):
        response = await client.get("/.well-known/agent.json")
        assert response.status_code == 200
        card = response.json()
        assert card["name"] == "homelab-agent"
        assert card["version"] == "0.1.0"

    async def test_card_carries_the_three_skills(self, client):
        card = (await client.get("/.well-known/agent.json")).json()
        ids = [s["id"] for s in card["skills"]]
        assert ids == ["repo-knowledge", "cluster-troubleshooting", "deployment-guidance"]

    async def test_card_skills_have_examples(self, client):
        card = (await client.get("/.well-known/agent.json")).json()
        repo = next(s for s in card["skills"] if s["id"] == "repo-knowledge")
        assert "What is cert-manager and how does it issue certs here?" in repo["examples"]


class TestExecutor:
    async def test_execute_success_emits_working_artifact_completed(self):
        from a2a.server.events.event_queue import EventQueue
        from a2a.types import TaskState, TextPart

        from homelab_agent.executor import HomelabAgentExecutor

        executor = HomelabAgentExecutor()
        context = MagicMock()
        context.task_id = str(uuid.uuid4())
        context.context_id = str(uuid.uuid4())
        context.message.parts = [TextPart(text="What is cert-manager?")]

        event_queue = EventQueue()
        fake_graph = MagicMock()
        fake_graph.ainvoke = AsyncMock(
            return_value={"answer": "cert-manager issues certs via Argo CD."}
        )
        with patch.object(executor, "_graph", fake_graph):
            await executor.execute(context, event_queue)

        # thread_id must be the A2A context_id (one conversation = one thread)
        _, kwargs = fake_graph.ainvoke.call_args
        assert kwargs["config"]["configurable"]["thread_id"] == context.context_id

        event1 = await event_queue.dequeue_event(no_wait=True)
        assert event1.status.state == TaskState.working
        event2 = await event_queue.dequeue_event(no_wait=True)
        assert event2.artifact is not None
        event3 = await event_queue.dequeue_event(no_wait=True)
        assert event3.status.state == TaskState.completed
        assert "cert-manager" in event3.status.message.parts[0].root.text

    async def test_execute_error_emits_failed(self):
        from a2a.server.events.event_queue import EventQueue
        from a2a.types import TaskState, TextPart

        from homelab_agent.executor import HomelabAgentExecutor

        executor = HomelabAgentExecutor()
        context = MagicMock()
        context.task_id = str(uuid.uuid4())
        context.context_id = str(uuid.uuid4())
        context.message.parts = [TextPart(text="boom")]

        event_queue = EventQueue()
        fake_graph = MagicMock()
        fake_graph.ainvoke = AsyncMock(side_effect=RuntimeError("LLM timeout"))
        with patch.object(executor, "_graph", fake_graph):
            await executor.execute(context, event_queue)

        event1 = await event_queue.dequeue_event(no_wait=True)
        assert event1.status.state == TaskState.working
        event2 = await event_queue.dequeue_event(no_wait=True)
        assert event2.status.state == TaskState.failed
        assert "LLM timeout" in event2.status.message.parts[0].root.text
