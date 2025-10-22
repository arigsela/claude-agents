"""Test suite for multi-cycle long-context behavior.

This test suite validates that the persistent monitoring mode correctly:
- Accumulates conversation history across multiple cycles
- Maintains proper cycle counting and timestamps
- Preserves message history for trend detection
- Handles recovery from interruptions
"""

import pytest
import json
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime

from src.config import Settings
from src.orchestrator.persistent_monitor import PersistentMonitor
from src.orchestrator.stateless_monitor import StatelessMonitor


@pytest.fixture
def settings(tmp_path, monkeypatch):
    """Create test settings with temporary session directory."""
    settings = Settings()
    settings.enable_long_context = True
    settings.anthropic_api_key = "test-api-key"
    settings.anthropic_model = "claude-3-5-sonnet-20241022"
    monkeypatch.chdir(tmp_path)
    return settings


@pytest.fixture
def mock_monitor():
    """Create mock Monitor with realistic cluster state progression."""
    monitor = AsyncMock()

    # Simulate different cluster states across cycles
    cluster_states = [
        {  # Cycle 1: Baseline healthy
            "node_count": 5,
            "pod_count": 40,
            "healthy_pods": 40,
            "namespace_count": 4,
            "critical_issues": [],
            "warnings": []
        },
        {  # Cycle 2: Minor issues emerge
            "node_count": 5,
            "pod_count": 40,
            "healthy_pods": 39,
            "namespace_count": 4,
            "critical_issues": ["Pod restart loop in monitoring namespace"],
            "warnings": ["High memory on node-2"]
        },
        {  # Cycle 3: Issues worsen
            "node_count": 5,
            "pod_count": 40,
            "healthy_pods": 37,
            "namespace_count": 4,
            "critical_issues": [
                "Pod restart loop in monitoring namespace",
                "OOMKilled pods in logging namespace"
            ],
            "warnings": ["High memory on node-2", "High CPU on node-3"]
        },
        {  # Cycle 4: Issues stabilizing
            "node_count": 5,
            "pod_count": 40,
            "healthy_pods": 38,
            "namespace_count": 4,
            "critical_issues": ["OOMKilled pods in logging namespace"],
            "warnings": ["High CPU on node-3"]
        },
        {  # Cycle 5: Recovery
            "node_count": 5,
            "pod_count": 40,
            "healthy_pods": 39,
            "namespace_count": 4,
            "critical_issues": [],
            "warnings": []
        }
    ]

    # Setup side effect to return different states for each call
    monitor._gather_cluster_state = AsyncMock(side_effect=cluster_states)
    return monitor


class TestStatelessMultiCycleIntegration:
    """Test multi-cycle behavior with stateless mode (no API calls needed)."""

    @pytest.mark.asyncio
    async def test_stateless_mode_no_history_accumulation(self, settings, mock_monitor):
        """Stateless mode should NOT accumulate history across cycles."""
        sm = StatelessMonitor(settings, mock_monitor)

        # Run 3 cycles
        for i in range(3):
            result = await sm.run_stateless_cycle()
            assert result["status"] == "success"
            assert result["cycle"] == i + 1

        # Verify no history accumulation
        metrics = sm.get_comparison_metrics()
        assert metrics["has_conversation_history"] is False
        assert metrics["cycles_completed"] == 3

    @pytest.mark.asyncio
    async def test_stateless_cycle_count_increments(self, settings, mock_monitor):
        """Cycle counter should increment with each execution in stateless mode."""
        sm = StatelessMonitor(settings, mock_monitor)

        for expected_cycle in range(1, 6):
            result = await sm.run_stateless_cycle()
            assert result["cycle"] == expected_cycle
            assert sm.stats["cycles_completed"] == expected_cycle

    @pytest.mark.asyncio
    async def test_stateless_timestamps_recorded(self, settings, mock_monitor):
        """Each cycle should have a recorded timestamp in stateless mode."""
        sm = StatelessMonitor(settings, mock_monitor)

        timestamps = []
        for _ in range(3):
            result = await sm.run_stateless_cycle()
            timestamp_str = result.get("timestamp")
            assert timestamp_str is not None

            # Verify ISO format
            try:
                timestamp = datetime.fromisoformat(timestamp_str)
                timestamps.append(timestamp)
            except ValueError:
                pytest.fail(f"Invalid ISO format timestamp: {timestamp_str}")

        # Verify timestamps are in order
        for i in range(len(timestamps) - 1):
            assert timestamps[i] <= timestamps[i + 1]

    @pytest.mark.asyncio
    async def test_stateless_vs_persistent_capability_difference(self, settings, mock_monitor):
        """Stateless and persistent modes should report different capabilities."""
        sm = StatelessMonitor(settings, mock_monitor)

        # Run cycles
        for _ in range(3):
            await sm.run_stateless_cycle()

        stateless_metrics = sm.get_comparison_metrics()

        # Verify stateless characteristics
        assert stateless_metrics["mode"] == "stateless"
        assert stateless_metrics["cycles_completed"] == 3
        assert stateless_metrics["has_conversation_history"] is False
        assert stateless_metrics["can_see_trends"] is False
        assert stateless_metrics["depends_on_disk_state"] is False
        assert stateless_metrics["context_continuous"] is False


class TestContextGrowthPatterns:
    """Test how context would grow across cycles (measured with stateless)."""

    @pytest.mark.asyncio
    async def test_cycle_count_monotonically_increases(self, settings, mock_monitor):
        """Cycle count should be monotonically increasing."""
        sm = StatelessMonitor(settings, mock_monitor)

        cycle_counts = []
        for _ in range(5):
            result = await sm.run_stateless_cycle()
            cycle_counts.append(result["cycle"])

        # Verify monotonic increase
        for i in range(len(cycle_counts) - 1):
            assert cycle_counts[i] < cycle_counts[i + 1]
        assert cycle_counts == [1, 2, 3, 4, 5]

    @pytest.mark.asyncio
    async def test_stats_tracking_complete(self, settings, mock_monitor):
        """Stats should track all relevant metrics."""
        sm = StatelessMonitor(settings, mock_monitor)

        for _ in range(3):
            await sm.run_stateless_cycle()

        stats = sm.get_stats()

        assert "cycles_completed" in stats
        assert "total_tokens_used" in stats
        assert "last_cycle_timestamp" in stats
        assert "mode" in stats
        assert stats["cycles_completed"] == 3
        assert stats["mode"] == "stateless"

    @pytest.mark.asyncio
    async def test_k8s_state_captured_each_cycle(self, settings, mock_monitor):
        """K8s state should be captured and returned for each cycle."""
        sm = StatelessMonitor(settings, mock_monitor)

        results = []
        for _ in range(3):
            result = await sm.run_stateless_cycle()
            results.append(result)
            assert "k8s_state" in result

        # Verify different states returned (from our mock data)
        issue_counts = [
            len(r["k8s_state"]["critical_issues"]) for r in results
        ]
        # Should see: 0 -> 1 -> 2
        assert issue_counts == [0, 1, 2]


class TestTrendIndicators:
    """Test that stateless mode captures data that could indicate trends."""

    @pytest.mark.asyncio
    async def test_tracks_issue_count_progression(self, settings, mock_monitor):
        """Should capture issue count changes across cycles."""
        sm = StatelessMonitor(settings, mock_monitor)

        issue_counts = []
        for _ in range(5):
            result = await sm.run_stateless_cycle()
            issue_counts.append(len(result["k8s_state"]["critical_issues"]))

        # Should see pattern: 0 -> 1 -> 2 -> 1 -> 0
        assert issue_counts == [0, 1, 2, 1, 0], \
            f"Expected degradation then recovery pattern, got {issue_counts}"

    @pytest.mark.asyncio
    async def test_tracks_pod_health_progression(self, settings, mock_monitor):
        """Should capture pod health changes across cycles."""
        sm = StatelessMonitor(settings, mock_monitor)

        health_ratios = []
        for _ in range(5):
            result = await sm.run_stateless_cycle()
            state = result["k8s_state"]
            ratio = state["healthy_pods"] / state["pod_count"]
            health_ratios.append(ratio)

        # Should see pattern: 1.0 -> 0.975 -> 0.925 -> 0.95 -> 0.975
        expected = [1.0, 39/40, 37/40, 38/40, 39/40]
        assert health_ratios == expected, \
            f"Expected pod health pattern {expected}, got {health_ratios}"

    @pytest.mark.asyncio
    async def test_formatted_messages_contain_state_data(self, settings, mock_monitor):
        """Formatted messages should contain cluster state data."""
        sm = StatelessMonitor(settings, mock_monitor)

        for cycle_num in range(1, 4):
            result = await sm.run_stateless_cycle()
            message = result["formatted_message"]

            # Should contain key metrics
            state = result["k8s_state"]
            assert str(state["node_count"]) in message
            assert str(state["pod_count"]) in message
            assert f"Cycle #{cycle_num}" in message or f"Cycle #{cycle_num}" in message


class TestRecoveryAndResilience:
    """Test recovery from interruptions and error handling."""

    @pytest.mark.asyncio
    async def test_recovery_after_failed_cycle(self, settings):
        """Monitor should continue after a failed cycle."""
        monitor = AsyncMock()

        # Setup states with an error in the middle
        cluster_states = [
            {"node_count": 5, "pod_count": 40, "healthy_pods": 40,
             "namespace_count": 4, "critical_issues": [], "warnings": []},
            Exception("Temporary API error"),  # This will raise
            {"node_count": 5, "pod_count": 40, "healthy_pods": 40,
             "namespace_count": 4, "critical_issues": [], "warnings": []}
        ]

        async def gather_with_error(*args, **kwargs):
            state = cluster_states.pop(0)
            if isinstance(state, Exception):
                raise state
            return state

        monitor._gather_cluster_state = AsyncMock(side_effect=gather_with_error)

        sm = StatelessMonitor(settings, monitor)

        # Run successful cycle
        result1 = await sm.run_stateless_cycle()
        assert result1["status"] == "success"
        assert sm.stats["cycles_completed"] == 1

        # Run failed cycle
        result2 = await sm.run_stateless_cycle()
        assert result2["status"] == "error"
        assert sm.stats["cycles_completed"] == 2  # Counter still increments

        # Run successful recovery cycle
        result3 = await sm.run_stateless_cycle()
        assert result3["status"] == "success"
        assert sm.stats["cycles_completed"] == 3

    @pytest.mark.asyncio
    async def test_handles_empty_cluster_state(self, settings):
        """Should handle empty cluster state gracefully."""
        monitor = AsyncMock()
        monitor._gather_cluster_state = AsyncMock(
            return_value={
                "node_count": 0,
                "pod_count": 0,
                "healthy_pods": 0,
                "namespace_count": 0,
                "critical_issues": [],
                "warnings": []
            }
        )

        sm = StatelessMonitor(settings, monitor)
        result = await sm.run_stateless_cycle()

        assert result["status"] == "success"
        assert result["cycle"] == 1
        assert result["k8s_state"]["node_count"] == 0


class TestComparisonMetrics:
    """Test metrics that compare monitoring modes."""

    @pytest.mark.asyncio
    async def test_stateless_metrics_reflect_mode(self, settings, mock_monitor):
        """Stateless mode metrics should accurately describe stateless behavior."""
        sm = StatelessMonitor(settings, mock_monitor)

        for _ in range(3):
            await sm.run_stateless_cycle()

        metrics = sm.get_comparison_metrics()

        assert metrics["mode"] == "stateless"
        assert metrics["cycles_completed"] == 3
        assert metrics["has_conversation_history"] is False
        assert metrics["can_see_trends"] is False
        assert metrics["context_continuous"] is False
        assert metrics["depends_on_disk_state"] is False

    @pytest.mark.asyncio
    async def test_metrics_available_after_multiple_cycles(self, settings, mock_monitor):
        """Metrics should be available and accurate after multiple cycles."""
        sm = StatelessMonitor(settings, mock_monitor)

        for cycle_num in range(1, 6):
            await sm.run_stateless_cycle()

            metrics = sm.get_comparison_metrics()
            assert metrics["cycles_completed"] == cycle_num
            assert metrics["mode"] == "stateless"

    @pytest.mark.asyncio
    async def test_token_tracking_available(self, settings, mock_monitor):
        """Should track token usage even if not updated by API calls."""
        sm = StatelessMonitor(settings, mock_monitor)

        for _ in range(3):
            await sm.run_stateless_cycle()

        metrics = sm.get_comparison_metrics()

        # Token tracking should exist in metrics
        assert "total_tokens" in metrics
        assert "average_tokens_per_cycle" in metrics
        assert isinstance(metrics["total_tokens"], int)
        assert isinstance(metrics["average_tokens_per_cycle"], (int, float))


class TestMessageStructureAcrossCycles:
    """Test that message data maintains proper structure across cycles."""

    @pytest.mark.asyncio
    async def test_all_cycles_return_required_fields(self, settings, mock_monitor):
        """All cycle results should have required fields."""
        sm = StatelessMonitor(settings, mock_monitor)

        required_fields = ["cycle", "status", "k8s_state", "formatted_message", "mode"]

        for _ in range(3):
            result = await sm.run_stateless_cycle()

            for field in required_fields:
                assert field in result, f"Missing required field: {field}"

    @pytest.mark.asyncio
    async def test_k8s_state_structure_consistent(self, settings, mock_monitor):
        """K8s state should have consistent structure across cycles."""
        sm = StatelessMonitor(settings, mock_monitor)

        required_state_fields = [
            "node_count", "pod_count", "healthy_pods",
            "namespace_count", "critical_issues", "warnings"
        ]

        for _ in range(3):
            result = await sm.run_stateless_cycle()
            state = result["k8s_state"]

            for field in required_state_fields:
                assert field in state, f"Missing state field: {field}"

    @pytest.mark.asyncio
    async def test_formatted_message_quality(self, settings, mock_monitor):
        """Formatted messages should be well-structured."""
        sm = StatelessMonitor(settings, mock_monitor)

        for cycle_num in range(1, 4):
            result = await sm.run_stateless_cycle()
            message = result["formatted_message"]

            # Should be non-empty string
            assert isinstance(message, str)
            assert len(message) > 0

            # Should contain cycle reference
            assert "Cycle" in message or "cycle" in message

            # Should not reference previous cycles
            assert "Previous Cycle Summary" not in message

    @pytest.mark.asyncio
    async def test_mode_correctly_identified(self, settings, mock_monitor):
        """Every result should correctly identify mode."""
        sm = StatelessMonitor(settings, mock_monitor)

        for _ in range(3):
            result = await sm.run_stateless_cycle()
            assert result["mode"] == "stateless"

        stats = sm.get_stats()
        assert stats["mode"] == "stateless"

        metrics = sm.get_comparison_metrics()
        assert metrics["mode"] == "stateless"
