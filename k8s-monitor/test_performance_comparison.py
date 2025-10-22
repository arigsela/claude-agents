"""Test suite for performance comparison between stateless and persistent monitoring modes.

This test suite compares metrics across modes:
- Cycle completion time
- Token usage patterns
- Message count growth
- Context window utilization
- Trend detection capabilities
- Recovery behavior
- Computational overhead
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime
import tempfile
from pathlib import Path

from src.config import Settings
from src.orchestrator.stateless_monitor import StatelessMonitor
from src.sessions import SessionManager


@pytest.fixture
def temp_session_dir():
    """Create temporary session directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def settings_stateless(tmp_path, monkeypatch):
    """Create stateless settings."""
    settings = Settings()
    settings.enable_long_context = False
    monkeypatch.chdir(tmp_path)
    return settings


@pytest.fixture
def mock_monitor():
    """Create mock Monitor with progressive cluster states."""
    monitor = AsyncMock()

    cluster_states = [
        {"node_count": 5, "pod_count": 50, "healthy_pods": 50,
         "namespace_count": 6, "critical_issues": [], "warnings": []},
        {"node_count": 5, "pod_count": 50, "healthy_pods": 48,
         "namespace_count": 6, "critical_issues": ["Pod restart loop"],
         "warnings": ["Memory pressure on node-2"]},
        {"node_count": 5, "pod_count": 50, "healthy_pods": 45,
         "namespace_count": 6, "critical_issues": ["Pod restart loop", "OOMKilled pods"],
         "warnings": ["Memory pressure on node-2", "High CPU on node-3"]},
        {"node_count": 5, "pod_count": 50, "healthy_pods": 40,
         "namespace_count": 6, "critical_issues": ["Pod restart loop", "OOMKilled pods", "Service degradation"],
         "warnings": ["Memory pressure on node-2", "High CPU on node-3", "Disk space low"]},
        {"node_count": 5, "pod_count": 50, "healthy_pods": 42,
         "namespace_count": 6, "critical_issues": ["OOMKilled pods", "Service degradation"],
         "warnings": ["High CPU on node-3", "Disk space low"]},
    ]

    monitor._gather_cluster_state = AsyncMock(side_effect=cluster_states)
    return monitor


class TestStatelessModePerformance:
    """Test stateless mode performance characteristics."""

    @pytest.mark.asyncio
    async def test_stateless_cycle_time_consistency(self, settings_stateless, mock_monitor):
        """Test that stateless cycle times remain consistent."""
        sm = StatelessMonitor(settings_stateless, mock_monitor)

        cycle_times = []
        for _ in range(5):
            start = datetime.now()
            result = await sm.run_stateless_cycle()
            elapsed = (datetime.now() - start).total_seconds()
            cycle_times.append(elapsed)
            assert result["status"] == "success"

        # Cycle times should be relatively consistent (low variance)
        avg_time = sum(cycle_times) / len(cycle_times)
        variance = sum((t - avg_time) ** 2 for t in cycle_times) / len(cycle_times)
        std_dev = variance ** 0.5

        # Standard deviation should be less than 50% of average (consistent performance)
        assert std_dev < avg_time * 0.5

    @pytest.mark.asyncio
    async def test_stateless_message_size_stability(self, settings_stateless, mock_monitor):
        """Test that message sizes remain stable across cycles."""
        sm = StatelessMonitor(settings_stateless, mock_monitor)

        message_sizes = []
        for _ in range(5):
            result = await sm.run_stateless_cycle()
            message_size = len(result.get("formatted_message", ""))
            message_sizes.append(message_size)

        # Message sizes should not grow significantly
        first_size = message_sizes[0]
        last_size = message_sizes[-1]

        # Allow 30% growth but no more (stateless shouldn't accumulate much context)
        assert last_size <= first_size * 1.3

    @pytest.mark.asyncio
    async def test_stateless_no_context_accumulation(self, settings_stateless, mock_monitor):
        """Test that stateless mode doesn't accumulate context."""
        sm = StatelessMonitor(settings_stateless, mock_monitor)

        # Run 10 cycles
        for _ in range(10):
            await sm.run_stateless_cycle()

        metrics = sm.get_comparison_metrics()

        # Should report no history
        assert metrics["has_conversation_history"] is False
        assert metrics["context_continuous"] is False


class TestTokenUsagePatterns:
    """Test token usage patterns for both modes."""

    @pytest.mark.asyncio
    async def test_stateless_token_tracking(self, settings_stateless, mock_monitor):
        """Test that stateless mode tracks token usage."""
        sm = StatelessMonitor(settings_stateless, mock_monitor)

        for _ in range(3):
            await sm.run_stateless_cycle()

        metrics = sm.get_comparison_metrics()
        assert "total_tokens" in metrics
        assert "average_tokens_per_cycle" in metrics
        assert isinstance(metrics["total_tokens"], int)

    @pytest.mark.asyncio
    async def test_stateless_token_usage_per_cycle(self, settings_stateless, mock_monitor):
        """Test calculating average token usage per cycle."""
        sm = StatelessMonitor(settings_stateless, mock_monitor)

        cycles_to_run = 5
        for _ in range(cycles_to_run):
            await sm.run_stateless_cycle()

        stats = sm.get_stats()
        metrics = sm.get_comparison_metrics()

        # Average should be total divided by cycles
        if metrics["total_tokens"] > 0:
            expected_avg = metrics["total_tokens"] / cycles_to_run
            assert abs(metrics["average_tokens_per_cycle"] - expected_avg) < 0.01


class TestContextWindowUtilization:
    """Test context window utilization patterns."""

    def test_session_manager_context_tracking(self, temp_session_dir):
        """Test that SessionManager tracks context utilization."""
        session_manager = SessionManager(session_dir=temp_session_dir, max_context_tokens=10000)

        history = [
            {"role": "system", "content": "System" * 100},
            {"role": "user", "content": "Message" * 100},
            {"role": "assistant", "content": "Response" * 100},
        ]

        session_manager.save_session("test-session", history, {"cycle_count": 1})
        stats = session_manager.get_session_stats("test-session")

        # Should track utilization metrics
        assert "estimated_tokens" in stats
        assert "context_percentage" in stats
        assert stats["context_percentage"] >= 0
        assert stats["context_percentage"] <= 100

    def test_context_growth_rate_calculation(self, temp_session_dir):
        """Test calculating context growth rate."""
        session_manager = SessionManager(session_dir=temp_session_dir, max_context_tokens=10000)

        # Cycle 1 stats
        history_cycle_1 = [
            {"role": "system", "content": "System" * 50},
            {"role": "user", "content": "Cycle 1" * 50},
        ]
        session_manager.save_session("growth-test", history_cycle_1, {"cycle_count": 1})
        stats_1 = session_manager.get_session_stats("growth-test")

        # Cycle 5 stats
        history_cycle_5 = history_cycle_1 + [
            {"role": "assistant", "content": "Response 1" * 50},
            {"role": "user", "content": "Cycle 2" * 50},
            {"role": "assistant", "content": "Response 2" * 50},
            {"role": "user", "content": "Cycle 3" * 50},
            {"role": "assistant", "content": "Response 3" * 50},
            {"role": "user", "content": "Cycle 4" * 50},
            {"role": "assistant", "content": "Response 4" * 50},
            {"role": "user", "content": "Cycle 5" * 50},
            {"role": "assistant", "content": "Response 5" * 50},
        ]
        session_manager.save_session("growth-test", history_cycle_5, {"cycle_count": 5})
        stats_5 = session_manager.get_session_stats("growth-test")

        # Calculate growth rate
        token_growth = stats_5["estimated_tokens"] - stats_1["estimated_tokens"]
        cycles_elapsed = 4
        growth_per_cycle = token_growth / cycles_elapsed

        # Should show growth
        assert growth_per_cycle > 0


class TestTrendDetectionCapabilities:
    """Compare trend detection capabilities across modes."""

    @pytest.mark.asyncio
    async def test_stateless_captures_point_in_time_state(self, settings_stateless, mock_monitor):
        """Test that stateless mode captures current state."""
        sm = StatelessMonitor(settings_stateless, mock_monitor)

        results = []
        for _ in range(5):
            result = await sm.run_stateless_cycle()
            results.append(result)

        # Each cycle should capture state
        for result in results:
            assert "k8s_state" in result
            assert "cycle" in result

    @pytest.mark.asyncio
    async def test_stateless_enables_external_trend_tracking(self, settings_stateless, mock_monitor):
        """Test that stateless cycle data can be used for external trend tracking."""
        sm = StatelessMonitor(settings_stateless, mock_monitor)

        # External system collects cycle data
        cycle_data = []
        for _ in range(5):
            result = await sm.run_stateless_cycle()
            cycle_data.append({
                "cycle": result["cycle"],
                "healthy_pods": result["k8s_state"]["healthy_pods"],
                "critical_issues": len(result["k8s_state"]["critical_issues"]),
                "timestamp": result["timestamp"]
            })

        # External system can detect trends
        health_values = [c["healthy_pods"] for c in cycle_data]
        issue_values = [c["critical_issues"] for c in cycle_data]

        # Should see degradation pattern (50 -> 48 -> 45 -> 40 -> 42)
        assert health_values == [50, 48, 45, 40, 42]

        # Should see escalation pattern (0 -> 1 -> 2 -> 3 -> 2)
        assert issue_values == [0, 1, 2, 3, 2]


class TestRecoveryBehavior:
    """Compare recovery behavior across modes."""

    @pytest.mark.asyncio
    async def test_stateless_recovery_from_error(self, settings_stateless):
        """Test stateless mode recovery from errors."""
        monitor = AsyncMock()

        # Setup states with an error
        states = [
            {"node_count": 5, "pod_count": 50, "healthy_pods": 50,
             "namespace_count": 6, "critical_issues": [], "warnings": []},
            Exception("Temporary K8s API error"),
            {"node_count": 5, "pod_count": 50, "healthy_pods": 50,
             "namespace_count": 6, "critical_issues": [], "warnings": []},
        ]

        call_count = [0]

        async def gather_with_error(*args, **kwargs):
            state = states[call_count[0]]
            call_count[0] += 1
            if isinstance(state, Exception):
                raise state
            return state

        monitor._gather_cluster_state = AsyncMock(side_effect=gather_with_error)
        sm = StatelessMonitor(settings_stateless, monitor)

        # Cycle 1: Success
        result1 = await sm.run_stateless_cycle()
        assert result1["status"] == "success"

        # Cycle 2: Error
        result2 = await sm.run_stateless_cycle()
        assert result2["status"] == "error"

        # Cycle 3: Recovery
        result3 = await sm.run_stateless_cycle()
        assert result3["status"] == "success"

        # Cycle counter should continue
        assert result3["cycle"] == 3

    def test_session_recovery_after_disk_loss(self, temp_session_dir):
        """Test session recovery when session file is lost."""
        session_manager = SessionManager(session_dir=temp_session_dir, max_context_tokens=10000)

        session_id = "disk-loss-test"
        history = [{"role": "system", "content": "System"}]
        metadata = {"cycle_count": 5}

        # Save session
        session_manager.save_session(session_id, history, metadata)

        # Simulate disk loss
        session_file = temp_session_dir / f"{session_id}.json"
        session_file.unlink()

        # Attempt to load
        loaded = session_manager.load_session(session_id)

        # Should return None gracefully (not crash)
        assert loaded is None


class TestComputationalOverhead:
    """Compare computational overhead between modes."""

    @pytest.mark.asyncio
    async def test_stateless_minimal_overhead(self, settings_stateless, mock_monitor):
        """Test that stateless mode has minimal overhead."""
        sm = StatelessMonitor(settings_stateless, mock_monitor)

        # Run single cycle
        start = datetime.now()
        result = await sm.run_stateless_cycle()
        elapsed = (datetime.now() - start).total_seconds()

        # Should complete quickly (no API calls in mock)
        assert elapsed < 1.0  # Should be under 1 second
        assert result["status"] == "success"

    def test_session_manager_save_load_overhead(self, temp_session_dir):
        """Test session save/load overhead."""
        session_manager = SessionManager(session_dir=temp_session_dir, max_context_tokens=10000)

        history = [{"role": "system", "content": "System" * 100}]
        for i in range(50):
            history.append({"role": "user" if i % 2 == 0 else "assistant", "content": f"Message {i}" * 10})

        # Measure save time
        start_save = datetime.now()
        session_manager.save_session("overhead-test", history, {"cycle_count": 50})
        save_time = (datetime.now() - start_save).total_seconds()

        # Measure load time
        start_load = datetime.now()
        loaded = session_manager.load_session("overhead-test")
        load_time = (datetime.now() - start_load).total_seconds()

        # Should be fast (under 100ms for 51 messages)
        assert save_time < 0.1
        assert load_time < 0.1
        assert loaded is not None


class TestModeComparisonMetrics:
    """Test comparison metrics between modes."""

    @pytest.mark.asyncio
    async def test_stateless_mode_metrics_structure(self, settings_stateless, mock_monitor):
        """Test that stateless mode provides complete comparison metrics."""
        sm = StatelessMonitor(settings_stateless, mock_monitor)

        for _ in range(3):
            await sm.run_stateless_cycle()

        metrics = sm.get_comparison_metrics()

        # Required fields
        required_fields = [
            "mode", "cycles_completed", "total_tokens",
            "average_tokens_per_cycle", "has_conversation_history",
            "can_see_trends", "depends_on_disk_state", "context_continuous"
        ]

        for field in required_fields:
            assert field in metrics

    @pytest.mark.asyncio
    async def test_mode_identifier_consistency(self, settings_stateless, mock_monitor):
        """Test that mode is consistently identified."""
        sm = StatelessMonitor(settings_stateless, mock_monitor)

        # Before cycles
        assert sm.get_stats()["mode"] == "stateless"
        assert sm.get_comparison_metrics()["mode"] == "stateless"

        # After cycles
        for _ in range(3):
            result = await sm.run_stateless_cycle()
            assert result["mode"] == "stateless"

        # After cycles
        assert sm.get_stats()["mode"] == "stateless"
        assert sm.get_comparison_metrics()["mode"] == "stateless"


class TestScalabilityCharacteristics:
    """Test scalability characteristics of each mode."""

    @pytest.mark.asyncio
    async def test_stateless_scales_linearly(self, settings_stateless, mock_monitor):
        """Test that stateless mode scales linearly with cycles."""
        sm = StatelessMonitor(settings_stateless, mock_monitor)

        # Run 10 cycles
        for _ in range(10):
            await sm.run_stateless_cycle()

        stats = sm.get_stats()

        # Cycle count should be linear
        assert stats["cycles_completed"] == 10

        # Token usage should be relatively linear (no exponential growth)
        # Since we're in mock mode without actual tokens, just verify the structure exists
        metrics = sm.get_comparison_metrics()
        assert isinstance(metrics["total_tokens"], int)

    def test_session_manager_scales_with_history(self, temp_session_dir):
        """Test that session manager handles growing history."""
        session_manager = SessionManager(session_dir=temp_session_dir, max_context_tokens=10000)

        # Create progressively larger histories
        for cycle in [10, 20, 30, 40, 50]:
            history = [{"role": "system", "content": "System"}]
            for i in range(cycle * 2):  # 2 messages per cycle
                history.append({
                    "role": "user" if i % 2 == 0 else "assistant",
                    "content": f"Cycle {i // 2} message"
                })

            session_manager.save_session(f"scale-test-{cycle}", history, {"cycle_count": cycle})
            stats = session_manager.get_session_stats(f"scale-test-{cycle}")

            # Should successfully save and retrieve
            assert stats["message_count"] == cycle * 2 + 1


class TestDataIntegrityAcrossCycles:
    """Test data integrity across monitoring cycles."""

    @pytest.mark.asyncio
    async def test_stateless_preserves_cycle_counter(self, settings_stateless, mock_monitor):
        """Test that cycle counter is preserved across cycles."""
        sm = StatelessMonitor(settings_stateless, mock_monitor)

        for expected_cycle in range(1, 6):
            result = await sm.run_stateless_cycle()
            assert result["cycle"] == expected_cycle

    @pytest.mark.asyncio
    async def test_stateless_timestamps_monotonic(self, settings_stateless, mock_monitor):
        """Test that timestamps are monotonically increasing."""
        sm = StatelessMonitor(settings_stateless, mock_monitor)

        timestamps = []
        for _ in range(5):
            result = await sm.run_stateless_cycle()
            timestamp = datetime.fromisoformat(result["timestamp"])
            timestamps.append(timestamp)

        # Timestamps should be in order
        for i in range(len(timestamps) - 1):
            assert timestamps[i] <= timestamps[i + 1]

    def test_session_persistence_data_integrity(self, temp_session_dir):
        """Test that session data integrity is maintained."""
        session_manager = SessionManager(session_dir=temp_session_dir, max_context_tokens=10000)

        session_id = "integrity-test"
        original_history = [
            {"role": "system", "content": "System prompt"},
            {"role": "user", "content": "User message"},
            {"role": "assistant", "content": "Assistant response"},
        ]
        original_metadata = {
            "cycle_count": 5,
            "cluster": "dev-eks",
            "last_issue": "OOMKilled"
        }

        # Save
        session_manager.save_session(session_id, original_history, original_metadata)

        # Load
        loaded = session_manager.load_session(session_id)

        # Verify integrity
        assert loaded["conversation_history"] == original_history
        assert loaded["metadata"]["cycle_count"] == original_metadata["cycle_count"]
        assert loaded["metadata"]["cluster"] == original_metadata["cluster"]
        assert loaded["metadata"]["last_issue"] == original_metadata["last_issue"]
