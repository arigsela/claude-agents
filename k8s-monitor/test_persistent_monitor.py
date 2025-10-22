"""Test suite for PersistentMonitor functionality."""

import json
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config import Settings
from src.orchestrator.persistent_monitor import PersistentMonitor


@pytest.fixture
def settings(tmp_path, monkeypatch):
    """Create test settings with unique session ID."""
    settings = Settings()
    settings.enable_long_context = True
    settings.session_id = f"test-persistent-session-{uuid.uuid4().hex[:8]}"
    settings.anthropic_api_key = "test-api-key"
    settings.anthropic_model = "claude-3-5-sonnet-20241022"
    settings.max_context_tokens = 50000
    # Point sessions directory to temp path by changing working directory
    monkeypatch.chdir(tmp_path)
    return settings


@pytest.fixture
def mock_monitor():
    """Create mock Monitor with async _gather_cluster_state."""
    monitor = AsyncMock()
    monitor._gather_cluster_state = AsyncMock(
        return_value={
            "node_count": 5,
            "pod_count": 42,
            "healthy_pods": 40,
            "failed_pods": 2,
            "pending_pods": 0,
            "nodes": [
                {"name": "node-1", "status": "Ready", "cpu_percent": 45.0, "memory_percent": 62.0},
                {"name": "node-2", "status": "Ready", "cpu_percent": 38.0, "memory_percent": 58.0}
            ],
            "services": [
                {"name": "api", "replicas": 3, "ready": 3, "status": "Running"},
                {"name": "worker", "replicas": 5, "ready": 5, "status": "Running"}
            ],
            "timestamp": "2024-10-22T12:00:00Z"
        }
    )
    return monitor


class TestPersistentMonitorInitialization:
    """Tests for session initialization."""

    @pytest.mark.asyncio
    async def test_initialize_session_fresh(self, settings, mock_monitor):
        """Test initializing a fresh session."""
        pm = PersistentMonitor(settings, mock_monitor)

        await pm.initialize_session()

        assert pm.client is not None
        assert pm.cycle_count == 0
        assert len(pm.messages) == 0
        assert pm.stats["session_id"] == settings.session_id
        assert pm.stats["cycles_completed"] == 0

    @pytest.mark.asyncio
    async def test_initialize_session_missing_api_key(self, settings, mock_monitor):
        """Test initialization fails without API key."""
        settings.anthropic_api_key = None
        pm = PersistentMonitor(settings, mock_monitor)

        with pytest.raises(ValueError, match="ANTHROPIC_API_KEY not set"):
            await pm.initialize_session()

    @pytest.mark.asyncio
    async def test_initialize_session_restore_existing(self, settings, mock_monitor, tmp_path):
        """Test restoring an existing session."""
        # Create existing session
        session_dir = tmp_path / "sessions" / settings.session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        session_file = session_dir / "session.json"

        session_data = {
            "session_id": settings.session_id,
            "cycle_count": 3,
            "messages": [
                {"role": "user", "content": "Cycle 1"},
                {"role": "assistant", "content": "Analysis 1"}
            ],
            "stats": {
                "session_id": settings.session_id,
                "cycles_completed": 3,
                "total_tokens_used": 5000
            }
        }

        with open(session_file, "w") as f:
            json.dump(session_data, f)

        pm = PersistentMonitor(settings, mock_monitor)
        await pm.initialize_session()

        assert pm.cycle_count == 3
        assert len(pm.messages) == 2
        assert pm.stats["total_tokens_used"] == 5000

    @pytest.mark.asyncio
    async def test_session_directory_created(self, settings, mock_monitor):
        """Test that session directory is created."""
        pm = PersistentMonitor(settings, mock_monitor)
        await pm.initialize_session()

        assert pm.session_dir.exists()
        assert pm.session_dir.is_dir()


class TestPersistentMonitorCycles:
    """Tests for monitoring cycle execution."""

    @pytest.mark.asyncio
    async def test_run_single_cycle(self, settings, mock_monitor, tmp_path):
        """Test running a single monitoring cycle."""
        pm = PersistentMonitor(settings, mock_monitor)
        await pm.initialize_session()

        # Mock API response
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="Cluster is healthy. 40/42 pods running.")]
        mock_response.usage.input_tokens = 500
        mock_response.usage.output_tokens = 100

        with patch.object(pm.client, "messages") as mock_messages:
            mock_messages.create = MagicMock(return_value=mock_response)

            result = await pm.run_persistent_cycle()

        assert result["status"] == "success"
        assert result["cycle"] == 1
        assert result["tokens_used"] == 600
        assert pm.cycle_count == 1
        assert len(pm.messages) == 2  # user + assistant

    @pytest.mark.asyncio
    async def test_run_multiple_cycles(self, settings, mock_monitor):
        """Test running multiple monitoring cycles."""
        pm = PersistentMonitor(settings, mock_monitor)
        await pm.initialize_session()

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="System healthy")]
        mock_response.usage.input_tokens = 500
        mock_response.usage.output_tokens = 100

        with patch.object(pm.client, "messages") as mock_messages:
            mock_messages.create = MagicMock(return_value=mock_response)

            # Run 3 cycles
            for i in range(3):
                result = await pm.run_persistent_cycle()
                assert result["status"] == "success"
                assert result["cycle"] == i + 1

        assert pm.cycle_count == 3
        assert len(pm.messages) == 6  # 3 user + 3 assistant messages

    @pytest.mark.asyncio
    async def test_cycle_message_format(self, settings, mock_monitor):
        """Test that cycle messages are properly formatted."""
        pm = PersistentMonitor(settings, mock_monitor)

        k8s_state = {
            "pod_count": 42,
            "healthy_pods": 40,
            "timestamp": "2024-10-22T12:00:00Z"
        }

        message = pm._format_cycle_message(1, k8s_state)

        assert "Monitoring Cycle #1" in message
        assert "Cluster State" in message
        assert "pod_count" in message
        assert "42" in message
        assert "Health assessment" in message

    @pytest.mark.asyncio
    async def test_cycle_without_initialization(self, settings, mock_monitor):
        """Test that running cycle without initialization raises error."""
        pm = PersistentMonitor(settings, mock_monitor)

        with pytest.raises(RuntimeError, match="not initialized"):
            await pm.run_persistent_cycle()


class TestPersistentMonitorPersistence:
    """Tests for session persistence and state management."""

    @pytest.mark.asyncio
    async def test_save_session(self, settings, mock_monitor):
        """Test saving session to disk."""
        pm = PersistentMonitor(settings, mock_monitor)
        await pm.initialize_session()

        pm.cycle_count = 2
        pm.messages = [
            {"role": "user", "content": "Cycle 1"},
            {"role": "assistant", "content": "Analysis 1"},
            {"role": "user", "content": "Cycle 2"},
            {"role": "assistant", "content": "Analysis 2"}
        ]
        pm.stats["cycles_completed"] = 2

        await pm._save_session()

        session_file = pm.session_dir / "session.json"
        assert session_file.exists()

        with open(session_file) as f:
            saved_data = json.load(f)

        assert saved_data["cycle_count"] == 2
        assert len(saved_data["messages"]) == 4
        assert saved_data["stats"]["cycles_completed"] == 2

    @pytest.mark.asyncio
    async def test_session_persistence_across_instances(self, settings, mock_monitor):
        """Test that session persists across monitor instances."""
        # Create first instance
        pm1 = PersistentMonitor(settings, mock_monitor)
        await pm1.initialize_session()

        pm1.cycle_count = 1
        pm1.messages = [
            {"role": "user", "content": "Test message"},
            {"role": "assistant", "content": "Test response"}
        ]
        await pm1._save_session()

        # Create second instance with same session ID
        pm2 = PersistentMonitor(settings, mock_monitor)
        await pm2.initialize_session()

        assert pm2.cycle_count == 1
        assert len(pm2.messages) == 2
        assert pm2.messages[0]["content"] == "Test message"

    @pytest.mark.asyncio
    async def test_get_stats(self, settings, mock_monitor):
        """Test getting session statistics."""
        pm = PersistentMonitor(settings, mock_monitor)
        await pm.initialize_session()

        pm.stats["cycles_completed"] = 5
        pm.stats["total_tokens_used"] = 10000
        pm.messages = [{"role": "user", "content": "test"}] * 5

        stats = pm.get_stats()

        assert stats["session_id"] == settings.session_id
        assert stats["cycles_completed"] == 5
        assert stats["total_tokens_used"] == 10000
        assert stats["messages_in_history"] == 5

    @pytest.mark.asyncio
    async def test_reset_session(self, settings, mock_monitor):
        """Test resetting session state."""
        pm = PersistentMonitor(settings, mock_monitor)
        await pm.initialize_session()

        pm.cycle_count = 5
        pm.messages = [{"role": "user", "content": "test"}] * 10
        pm.stats["cycles_completed"] = 5

        # Reset
        pm.cycle_count = 0
        pm.messages = []
        pm.stats["cycles_completed"] = 0

        assert pm.cycle_count == 0
        assert len(pm.messages) == 0
        assert pm.stats["cycles_completed"] == 0


class TestPersistentMonitorShutdown:
    """Tests for graceful shutdown."""

    @pytest.mark.asyncio
    async def test_shutdown_saves_state(self, settings, mock_monitor):
        """Test that shutdown saves session state."""
        pm = PersistentMonitor(settings, mock_monitor)
        await pm.initialize_session()

        pm.cycle_count = 3
        pm.messages = [{"role": "user", "content": f"Cycle {i}"} for i in range(3)]

        await pm.shutdown()

        session_file = pm.session_dir / "session.json"
        assert session_file.exists()

        with open(session_file) as f:
            data = json.load(f)
        assert data["cycle_count"] == 3


class TestContextManagement:
    """Tests for context window management."""

    def test_should_prune_context_false_when_small(self, settings, mock_monitor):
        """Test that small context doesn't trigger pruning."""
        pm = PersistentMonitor(settings, mock_monitor)
        pm.messages = [{"role": "user", "content": "short"}] * 5

        should_prune = pm._should_prune_context()
        assert should_prune is False

    def test_should_prune_context_true_when_large(self, settings, mock_monitor):
        """Test that large context triggers pruning."""
        pm = PersistentMonitor(settings, mock_monitor)
        # Create messages that exceed 80% of max context
        large_message = "x" * 1000
        pm.messages = [{"role": "user", "content": large_message}] * 50

        should_prune = pm._should_prune_context()
        assert should_prune is True

    @pytest.mark.asyncio
    async def test_prune_context_preserves_recent_messages(self, settings, mock_monitor):
        """Test that pruning keeps recent messages."""
        pm = PersistentMonitor(settings, mock_monitor)

        # Create 30 messages
        for i in range(30):
            pm.messages.append({
                "role": "user" if i % 2 == 0 else "assistant",
                "content": f"Message {i}"
            })

        await pm._prune_context()

        # Should keep at least last 15 messages
        assert len(pm.messages) >= 10
        assert pm.messages[-1]["content"] == "Message 29"

    @pytest.mark.asyncio
    async def test_prune_context_min_messages(self, settings, mock_monitor):
        """Test that pruning preserves minimum messages."""
        pm = PersistentMonitor(settings, mock_monitor)

        # Create 5 messages (less than minimum keep of 10)
        for i in range(5):
            pm.messages.append({"role": "user", "content": f"Message {i}"})

        await pm._prune_context()

        # Should keep all 5 since less than minimum
        assert len(pm.messages) == 5


class TestErrorHandling:
    """Tests for error handling in cycles."""

    @pytest.mark.asyncio
    async def test_cycle_error_returns_error_status(self, settings, mock_monitor):
        """Test that API errors are handled gracefully."""
        pm = PersistentMonitor(settings, mock_monitor)
        await pm.initialize_session()

        with patch.object(pm.client, "messages") as mock_messages:
            mock_messages.create = MagicMock(side_effect=Exception("API Error"))

            result = await pm.run_persistent_cycle()

        assert result["status"] == "error"
        assert "API Error" in result["error"]

    @pytest.mark.asyncio
    async def test_gather_cluster_state_delegation(self, settings, mock_monitor):
        """Test that cycles properly delegate to monitor."""
        pm = PersistentMonitor(settings, mock_monitor)
        await pm.initialize_session()

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="Analysis")]
        mock_response.usage.input_tokens = 100
        mock_response.usage.output_tokens = 50

        with patch.object(pm.client, "messages") as mock_messages:
            mock_messages.create = MagicMock(return_value=mock_response)

            await pm.run_persistent_cycle()

        # Verify monitor was called
        mock_monitor._gather_cluster_state.assert_called_once()


class TestSystemPrompt:
    """Tests for system prompt generation."""

    def test_system_prompt_contains_instructions(self, settings, mock_monitor):
        """Test that system prompt has required instructions."""
        pm = PersistentMonitor(settings, mock_monitor)
        prompt = pm._build_system_prompt()

        assert "Kubernetes cluster monitoring agent" in prompt
        assert "cluster health" in prompt
        assert "conversation history" in prompt
        assert "actionable recommendations" in prompt


class TestIntegration:
    """Integration tests combining multiple components."""

    @pytest.mark.asyncio
    async def test_full_cycle_with_save_restore(self, settings, mock_monitor):
        """Test complete cycle with save and restore."""
        # First instance - run cycle and save
        pm1 = PersistentMonitor(settings, mock_monitor)
        await pm1.initialize_session()

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="Cluster healthy")]
        mock_response.usage.input_tokens = 500
        mock_response.usage.output_tokens = 100

        with patch.object(pm1.client, "messages") as mock_messages:
            mock_messages.create = MagicMock(return_value=mock_response)
            result1 = await pm1.run_persistent_cycle()

        assert result1["status"] == "success"
        assert pm1.cycle_count == 1

        # Second instance - restore and verify
        pm2 = PersistentMonitor(settings, mock_monitor)
        await pm2.initialize_session()

        assert pm2.cycle_count == 1
        assert len(pm2.messages) == 2

    @pytest.mark.asyncio
    async def test_token_usage_accumulation(self, settings, mock_monitor):
        """Test that token usage is properly accumulated."""
        pm = PersistentMonitor(settings, mock_monitor)
        await pm.initialize_session()

        tokens_per_cycle = [600, 750, 650]

        for expected_tokens in tokens_per_cycle:
            mock_response = MagicMock()
            mock_response.content = [MagicMock(text="Analysis")]
            mock_response.usage.input_tokens = expected_tokens - 100
            mock_response.usage.output_tokens = 100

            with patch.object(pm.client, "messages") as mock_messages:
                mock_messages.create = MagicMock(return_value=mock_response)
                await pm.run_persistent_cycle()

        expected_total = sum(tokens_per_cycle)
        assert pm.stats["total_tokens_used"] == expected_total
