"""A2A protocol surface: health, agent card, executor event flow.
Mirrors oncall-crewai/tests/test_k8s_agent_a2a.py."""

import uuid
from unittest.mock import MagicMock, patch

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
        calls = []

        # execute() now drives astream(), not ainvoke() (Task 4: streaming) —
        # mock astream as an async generator emitting one synthesize delta.
        async def fake_astream(inputs, config=None, stream_mode=None):
            calls.append((inputs, config, stream_mode))
            msg = MagicMock()
            msg.content = "cert-manager issues certs via Argo CD."
            msg.text = "cert-manager issues certs via Argo CD."
            yield ("messages", (msg, {"langgraph_node": "synthesize"}))

        fake_graph = MagicMock()
        fake_graph.astream = fake_astream
        with patch.object(executor, "_graph", fake_graph):
            await executor.execute(context, event_queue)

        # thread_id must be the A2A context_id (one conversation = one thread)
        _, config, _ = calls[0]
        assert config["configurable"]["thread_id"] == context.context_id

        events = []
        while True:
            try:
                events.append(await event_queue.dequeue_event(no_wait=True))
            except Exception:
                break

        # working -> artifact -> completed, in that relative order (extra
        # streamed token-delta "working" events may sit between them now)
        assert events[0].status.state == TaskState.working
        artifact_event = next(e for e in events if getattr(e, "artifact", None) is not None)
        completed_event = next(
            e for e in events if hasattr(e, "status") and e.status.state == TaskState.completed
        )
        assert events.index(artifact_event) < events.index(completed_event)
        assert "cert-manager" in completed_event.status.message.parts[0].root.text

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

        # execute() now drives astream(), not ainvoke() (Task 4: streaming) —
        # mock astream as an async generator that raises before yielding.
        async def boom_astream(inputs, config=None, stream_mode=None):
            raise RuntimeError("LLM timeout")
            yield  # pragma: no cover  (makes this an async generator)

        fake_graph = MagicMock()
        fake_graph.astream = boom_astream
        with patch.object(executor, "_graph", fake_graph):
            await executor.execute(context, event_queue)

        event1 = await event_queue.dequeue_event(no_wait=True)
        assert event1.status.state == TaskState.working
        event2 = await event_queue.dequeue_event(no_wait=True)
        assert event2.status.state == TaskState.failed
        assert "LLM timeout" in event2.status.message.parts[0].root.text


# --- Task 4: streaming ------------------------------------------------------


class TestStreaming:
    async def test_card_advertises_streaming(self, client):
        card = (await client.get("/.well-known/agent.json")).json()
        assert card["capabilities"]["streaming"] is True

    async def test_execute_streams_progress_then_answer(self):
        from a2a.server.events.event_queue import EventQueue
        from a2a.types import TaskState, TextPart

        from homelab_agent.executor import HomelabAgentExecutor

        executor = HomelabAgentExecutor()
        context = MagicMock()
        context.task_id = str(uuid.uuid4())
        context.context_id = str(uuid.uuid4())
        context.message.parts = [TextPart(text="What is cert-manager?")]

        # Fake astream: yield two node-update events, then two synthesize token
        # deltas, matching stream_mode=["updates","messages"] tuple shape.
        async def fake_astream(inputs, config=None, stream_mode=None):
            yield ("updates", {"orient": {"route": "docs"}})
            yield ("updates", {"retrieve": {"doc_findings": "x"}})
            msg1 = MagicMock()
            msg1.content = "cert-"
            msg1.text = "cert-"
            msg2 = MagicMock()
            msg2.content = "manager."
            msg2.text = "manager."
            yield ("messages", (msg1, {"langgraph_node": "synthesize"}))
            yield ("messages", (msg2, {"langgraph_node": "synthesize"}))

        executor._graph = MagicMock()
        executor._graph.astream = fake_astream

        event_queue = EventQueue()
        await executor.execute(context, event_queue)

        events = []
        while True:
            try:
                events.append(await event_queue.dequeue_event(no_wait=True))
            except Exception:
                break

        texts = []
        final_completed = None
        for e in events:
            if hasattr(e, "status") and e.status.message:
                texts.append(e.status.message.parts[0].root.text)
            if hasattr(e, "status") and e.status.state == TaskState.completed:
                final_completed = e
        # progress markers present
        assert any("Retrieving docs" in t for t in texts)
        # streamed synthesize deltas concatenate to the full answer
        assert final_completed is not None
        assert final_completed.status.message.parts[0].root.text == "cert-manager."

    async def test_execute_error_still_fails(self):
        from a2a.server.events.event_queue import EventQueue
        from a2a.types import TaskState, TextPart

        from homelab_agent.executor import HomelabAgentExecutor

        executor = HomelabAgentExecutor()
        context = MagicMock()
        context.task_id = str(uuid.uuid4())
        context.context_id = str(uuid.uuid4())
        context.message.parts = [TextPart(text="boom")]

        async def boom_astream(inputs, config=None, stream_mode=None):
            raise RuntimeError("stream exploded")
            yield  # pragma: no cover  (makes this an async generator)

        executor._graph = MagicMock()
        executor._graph.astream = boom_astream

        event_queue = EventQueue()
        await executor.execute(context, event_queue)

        events = []
        while True:
            try:
                events.append(await event_queue.dequeue_event(no_wait=True))
            except Exception:
                break
        assert any(
            hasattr(e, "status") and e.status.state == TaskState.failed for e in events
        )
        assert any("stream exploded" in e.status.message.parts[0].root.text
                   for e in events if hasattr(e, "status") and e.status.message)

    async def test_execute_uses_authoritative_synthesize_answer_without_token_deltas(self):
        """If synthesize never emits messages-mode deltas (e.g. model doesn't
        stream tokens for some reason), the completed answer must still come
        through — from the authoritative "updates" state, not just
        concatenated tokens (which would be empty here)."""
        from a2a.server.events.event_queue import EventQueue
        from a2a.types import TaskState, TextPart

        from homelab_agent.executor import HomelabAgentExecutor

        executor = HomelabAgentExecutor()
        context = MagicMock()
        context.task_id = str(uuid.uuid4())
        context.context_id = str(uuid.uuid4())
        context.message.parts = [TextPart(text="What is cert-manager?")]

        # No "messages" events at all — only the "updates" delta carrying the
        # synthesize node's authoritative answer.
        async def fake_astream(inputs, config=None, stream_mode=None):
            yield ("updates", {"orient": {"route": "docs"}})
            yield ("updates", {"retrieve": {"doc_findings": "x"}})
            yield (
                "updates",
                {"synthesize": {"answer": "cert-manager issues certs via Argo CD."}},
            )

        executor._graph = MagicMock()
        executor._graph.astream = fake_astream

        event_queue = EventQueue()
        await executor.execute(context, event_queue)

        events = []
        while True:
            try:
                events.append(await event_queue.dequeue_event(no_wait=True))
            except Exception:
                break

        final_completed = next(
            e for e in events if hasattr(e, "status") and e.status.state == TaskState.completed
        )
        assert (
            final_completed.status.message.parts[0].root.text
            == "cert-manager issues certs via Argo CD."
        )
        artifact_event = next(e for e in events if getattr(e, "artifact", None) is not None)
        assert (
            artifact_event.artifact.parts[0].root.text
            == "cert-manager issues certs via Argo CD."
        )
