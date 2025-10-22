"""Test suite for context accumulation and growth across monitoring cycles.

This test suite validates behavior patterns that demonstrate context accumulation,
focusing on measurable and testable aspects:
- Cycle counter progression
- Timestamp tracking across cycles
- Stateless vs persistent mode differences
- Message history simulation
- Context growth metrics
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta
import json

from src.config import Settings
from src.orchestrator.stateless_monitor import StatelessMonitor


@pytest.fixture
def settings_stateless(tmp_path, monkeypatch):
    """Create stateless settings for testing."""
    settings = Settings()
    settings.enable_long_context = False
    monkeypatch.chdir(tmp_path)
    return settings


@pytest.fixture
def mock_monitor():
    """Create mock Monitor with progressive cluster states."""
    monitor = AsyncMock()

    # Simulate cluster states that get progressively worse then stabilize
    cluster_states = [
        {  # Cycle 1: Baseline healthy
            "node_count": 5, "pod_count": 50, "healthy_pods": 50,
            "namespace_count": 6, "critical_issues": [], "warnings": []
        },
        {  # Cycle 2: Minor issues emerge
            "node_count": 5, "pod_count": 50, "healthy_pods": 48,
            "namespace_count": 6, "critical_issues": ["Pod restart loop"],
            "warnings": ["Memory pressure on node-2"]
        },
        {  # Cycle 3: Issues worsen
            "node_count": 5, "pod_count": 50, "healthy_pods": 45,
            "namespace_count": 6, "critical_issues": ["Pod restart loop", "OOMKilled pods"],
            "warnings": ["Memory pressure on node-2", "High CPU on node-3"]
        },
        {  # Cycle 4: More cascading
            "node_count": 5, "pod_count": 50, "healthy_pods": 40,
            "namespace_count": 6, "critical_issues": ["Pod restart loop", "OOMKilled pods", "Service degradation"],
            "warnings": ["Memory pressure on node-2", "High CPU on node-3", "Disk space low"]
        },
        {  # Cycle 5: Stabilizing
            "node_count": 5, "pod_count": 50, "healthy_pods": 42,
            "namespace_count": 6, "critical_issues": ["OOMKilled pods", "Service degradation"],
            "warnings": ["High CPU on node-3", "Disk space low"]
        },
    ]

    monitor._gather_cluster_state = AsyncMock(side_effect=cluster_states)
    return monitor


class TestStatelessCycleAccumulation:
    """Test cycle tracking in stateless mode."""

    @pytest.mark.asyncio
    async def test_cycle_counter_increments(self, settings_stateless, mock_monitor):
        """Test that cycle counter increments properly."""
        sm = StatelessMonitor(settings_stateless, mock_monitor)

        for expected_cycle in range(1, 6):
            result = await sm.run_stateless_cycle()
            assert result["status"] == "success"
            assert result["cycle"] == expected_cycle
            assert sm.stats["cycles_completed"] == expected_cycle

    @pytest.mark.asyncio
    async def test_cycle_counter_monotonic_increase(self, settings_stateless, mock_monitor):
        """Test that cycle counter is monotonically increasing."""
        sm = StatelessMonitor(settings_stateless, mock_monitor)

        cycle_numbers = []
        for _ in range(5):
            result = await sm.run_stateless_cycle()
            assert result["status"] == "success"
            cycle_numbers.append(result["cycle"])

        # Verify strict monotonic increase
        for i in range(len(cycle_numbers) - 1):
            assert cycle_numbers[i] < cycle_numbers[i + 1]
        assert cycle_numbers == [1, 2, 3, 4, 5]

    @pytest.mark.asyncio
    async def test_timestamp_progression(self, settings_stateless, mock_monitor):
        """Test that timestamps progress correctly across cycles."""
        sm = StatelessMonitor(settings_stateless, mock_monitor)

        timestamps = []
        for _ in range(3):
            result = await sm.run_stateless_cycle()
            assert result["status"] == "success"

            timestamp_str = result.get("timestamp")
            assert timestamp_str is not None

            try:
                timestamp = datetime.fromisoformat(timestamp_str)
                timestamps.append(timestamp)
            except ValueError:
                pytest.fail(f"Invalid ISO format timestamp: {timestamp_str}")

        # Timestamps should be in order (non-decreasing)
        for i in range(len(timestamps) - 1):
            assert timestamps[i] <= timestamps[i + 1]


class TestStatelessModeCharacteristics:
    """Test defining characteristics of stateless mode."""

    @pytest.mark.asyncio
    async def test_no_conversation_history(self, settings_stateless, mock_monitor):
        """Test that stateless mode explicitly reports no history."""
        sm = StatelessMonitor(settings_stateless, mock_monitor)

        # Run multiple cycles
        for _ in range(3):
            result = await sm.run_stateless_cycle()
            assert result["status"] == "success"

        # Verify no conversation history claimed
        metrics = sm.get_comparison_metrics()
        assert metrics["has_conversation_history"] is False
        assert metrics["context_continuous"] is False
        assert metrics["can_see_trends"] is False
        assert metrics["depends_on_disk_state"] is False

    @pytest.mark.asyncio
    async def test_fresh_context_each_cycle(self, settings_stateless, mock_monitor):
        """Test that each cycle has independent context."""
        sm = StatelessMonitor(settings_stateless, mock_monitor)

        messages = []
        for i in range(3):
            result = await sm.run_stateless_cycle()
            assert result["status"] == "success"

            message = result.get("formatted_message", "")
            messages.append(message)

            # Each message should not reference previous cycles
            assert "Previous Cycle Summary" not in message
            assert "Last cycle" not in message
            assert "from the previous" not in message


class TestStatelessContextGrowthPatterns:
    """Test how context grows (or doesn't) in stateless mode."""

    @pytest.mark.asyncio
    async def test_message_independence(self, settings_stateless, mock_monitor):
        """Test that cycle messages are independent."""
        sm = StatelessMonitor(settings_stateless, mock_monitor)

        messages = []
        for _ in range(3):
            result = await sm.run_stateless_cycle()
            assert result["status"] == "success"
            if "formatted_message" in result:
                messages.append(result["formatted_message"])

        # All messages should be similar length (no accumulation)
        if len(messages) > 1:
            for i in range(1, len(messages)):
                # Message length should be similar (within 50%)
                # Not accumulating means roughly same length
                assert abs(len(messages[i]) - len(messages[0])) < len(messages[0]) * 0.5

    @pytest.mark.asyncio
    async def test_token_tracking_capability(self, settings_stateless, mock_monitor):
        """Test that token tracking is available even in stateless mode."""
        sm = StatelessMonitor(settings_stateless, mock_monitor)

        for _ in range(3):
            result = await sm.run_stateless_cycle()
            assert result["status"] == "success"

        metrics = sm.get_comparison_metrics()
        assert "total_tokens" in metrics
        assert "average_tokens_per_cycle" in metrics
        assert isinstance(metrics["total_tokens"], int)
        assert isinstance(metrics["average_tokens_per_cycle"], (int, float))

    @pytest.mark.asyncio
    async def test_stats_available_after_cycles(self, settings_stateless, mock_monitor):
        """Test that stats are available after running cycles."""
        sm = StatelessMonitor(settings_stateless, mock_monitor)

        for _ in range(3):
            result = await sm.run_stateless_cycle()
            assert result["status"] == "success"

        stats = sm.get_stats()
        assert stats["cycles_completed"] == 3
        assert stats["mode"] == "stateless"
        assert "uptime_cycles" in stats
        assert stats["uptime_cycles"] == 3


class TestClusterStateCapture:
    """Test capturing and comparing cluster state across cycles."""

    @pytest.mark.asyncio
    async def test_cluster_state_captured_each_cycle(self, settings_stateless, mock_monitor):
        """Test that cluster state is captured for each cycle."""
        sm = StatelessMonitor(settings_stateless, mock_monitor)

        states = []
        for _ in range(3):
            result = await sm.run_stateless_cycle()
            assert result["status"] == "success"
            assert "k8s_state" in result

            states.append(result["k8s_state"])

        # Should have captured 3 different states
        assert len(states) == 3

        # Verify state structure
        for state in states:
            assert "node_count" in state
            assert "pod_count" in state
            assert "healthy_pods" in state
            assert "namespace_count" in state
            assert "critical_issues" in state
            assert "warnings" in state

    @pytest.mark.asyncio
    async def test_cluster_degradation_pattern(self, settings_stateless, mock_monitor):
        """Test detecting cluster degradation pattern across cycles."""
        sm = StatelessMonitor(settings_stateless, mock_monitor)

        healthy_progression = []
        critical_progression = []

        for _ in range(5):
            result = await sm.run_stateless_cycle()
            assert result["status"] == "success"

            state = result["k8s_state"]
            healthy_progression.append(state["healthy_pods"])
            critical_progression.append(len(state.get("critical_issues", [])))

        # Verify degradation pattern: 50 -> 48 -> 45 -> 40 -> 42
        assert healthy_progression == [50, 48, 45, 40, 42]

        # Verify critical issues escalation
        assert critical_progression[0] == 0  # Healthy start
        assert critical_progression[1] == 1  # Issues start
        assert critical_progression[2] == 2  # Issues escalate
        assert critical_progression[3] == 3  # Peak
        assert critical_progression[4] == 2  # Stabilizing

    @pytest.mark.asyncio
    async def test_manual_trend_detection_stateless(self, settings_stateless, mock_monitor):
        """Test that stateless mode CAN detect trends if user captures data."""
        sm = StatelessMonitor(settings_stateless, mock_monitor)

        # Even though stateless mode doesn't maintain history,
        # external code CAN track cycles and compute trends
        cycle_snapshots = []

        for _ in range(5):
            result = await sm.run_stateless_cycle()
            cycle_snapshots.append({
                "cycle": result["cycle"],
                "healthy_pods": result["k8s_state"]["healthy_pods"],
                "critical_issues": len(result["k8s_state"].get("critical_issues", []))
            })

        # External code can now analyze the trend
        assert len(cycle_snapshots) == 5

        # Trend: degradation from cycle 1-4, then stabilizing
        for i in range(3):
            assert cycle_snapshots[i]["healthy_pods"] >= cycle_snapshots[i + 1]["healthy_pods"]


class TestModeComparison:
    """Compare stateless mode characteristics to persistent mode expectations."""

    @pytest.mark.asyncio
    async def test_stateless_mode_identity_consistency(self, settings_stateless, mock_monitor):
        """Test that mode is consistently identified as stateless."""
        sm = StatelessMonitor(settings_stateless, mock_monitor)

        # Check before any cycles
        assert sm.stats["mode"] == "stateless"
        assert sm.get_stats()["mode"] == "stateless"
        assert sm.get_comparison_metrics()["mode"] == "stateless"

        # Run cycles
        for _ in range(3):
            result = await sm.run_stateless_cycle()
            assert result["mode"] == "stateless"

        # Check after cycles
        assert sm.stats["mode"] == "stateless"
        assert sm.get_stats()["mode"] == "stateless"
        assert sm.get_comparison_metrics()["mode"] == "stateless"

    @pytest.mark.asyncio
    async def test_comparison_metrics_definition(self, settings_stateless, mock_monitor):
        """Test that comparison metrics clearly define stateless limitations."""
        sm = StatelessMonitor(settings_stateless, mock_monitor)

        for _ in range(3):
            result = await sm.run_stateless_cycle()
            assert result["status"] == "success"

        metrics = sm.get_comparison_metrics()

        # These are the key differentiators from persistent mode
        assert metrics["mode"] == "stateless"
        assert metrics["has_conversation_history"] is False
        assert metrics["can_see_trends"] is False
        assert metrics["context_continuous"] is False
        assert metrics["depends_on_disk_state"] is False

        # But we do track basic metrics
        assert metrics["cycles_completed"] == 3
        assert "total_tokens" in metrics
        assert "average_tokens_per_cycle" in metrics


class TestContextAccumulationConceptual:
    """Test understanding of context accumulation concepts."""

    @pytest.mark.asyncio
    async def test_persistent_mode_would_accumulate(self, settings_stateless, mock_monitor):
        """Document what persistent mode WOULD do vs stateless mode."""
        # This test documents the conceptual difference

        # Stateless: Each cycle is independent
        sm = StatelessMonitor(settings_stateless, mock_monitor)

        results = []
        for i in range(3):
            result = await sm.run_stateless_cycle()
            results.append(result)

        # In stateless mode:
        # - Message 1: "Initial cluster state: 50 healthy pods"
        # - Message 2: "Initial cluster state: 48 healthy pods" (NO previous context)
        # - Message 3: "Initial cluster state: 45 healthy pods" (NO trend info)

        for result in results:
            msg = result.get("formatted_message", "")
            # Should NOT contain reference to previous cycles
            assert "Previously reported" not in msg
            assert "Trend from last cycle" not in msg
            assert "Last 5 cycles" not in msg

    @pytest.mark.asyncio
    async def test_accumulation_would_increase_context_window(self, settings_stateless, mock_monitor):
        """Document how persistent mode would accumulate context."""
        # This test explains the concept through stateless behavior

        sm = StatelessMonitor(settings_stateless, mock_monitor)

        message_lengths = []
        for _ in range(5):
            result = await sm.run_stateless_cycle()
            msg = result.get("formatted_message", "")
            message_lengths.append(len(msg))

        # In stateless mode: message lengths stay similar (no accumulation)
        # If all messages are 200-300 chars, there's NO accumulation
        avg_length = sum(message_lengths) / len(message_lengths)
        variance = sum((x - avg_length) ** 2 for x in message_lengths) / len(message_lengths)
        std_dev = variance ** 0.5

        # Standard deviation should be small (messages are similar length)
        assert std_dev < avg_length * 0.3  # < 30% variation

        # In persistent mode, messages would GROW because of context history
        # That would NOT be true here (stateless doesn't accumulate)

