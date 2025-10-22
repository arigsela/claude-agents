"""Test suite for StatelessMonitor functionality."""

import pytest
import json
from unittest.mock import AsyncMock, MagicMock

from src.config import Settings
from src.orchestrator.stateless_monitor import StatelessMonitor


@pytest.fixture
def settings():
    """Create test settings."""
    settings = Settings()
    settings.enable_long_context = False  # Explicitly stateless
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
            "namespace_count": 8,
            "critical_issues": ["Issue 1"],
            "warnings": []
        }
    )
    return monitor


class TestStatelessMonitorBasics:
    """Test basic StatelessMonitor functionality."""

    def test_initialization(self, settings, mock_monitor):
        """Test stateless monitor initialization."""
        sm = StatelessMonitor(settings, mock_monitor)

        assert sm.settings == settings
        assert sm.monitor == mock_monitor
        assert sm.stats["cycles_completed"] == 0
        assert sm.stats["mode"] == "stateless"

    @pytest.mark.asyncio
    async def test_run_single_cycle(self, settings, mock_monitor):
        """Test running a single stateless cycle."""
        sm = StatelessMonitor(settings, mock_monitor)

        result = await sm.run_stateless_cycle()

        assert result["status"] == "success"
        assert result["cycle"] == 1
        assert result["mode"] == "stateless"
        assert "k8s_state" in result
        assert "formatted_message" in result
        assert sm.stats["cycles_completed"] == 1

    @pytest.mark.asyncio
    async def test_run_multiple_cycles(self, settings, mock_monitor):
        """Test running multiple stateless cycles."""
        sm = StatelessMonitor(settings, mock_monitor)

        for i in range(3):
            result = await sm.run_stateless_cycle()
            assert result["status"] == "success"
            assert result["cycle"] == i + 1

        assert sm.stats["cycles_completed"] == 3

    @pytest.mark.asyncio
    async def test_cycle_error_handling(self, settings, mock_monitor):
        """Test error handling in stateless cycles."""
        mock_monitor._gather_cluster_state = AsyncMock(side_effect=Exception("K8s error"))
        sm = StatelessMonitor(settings, mock_monitor)

        result = await sm.run_stateless_cycle()

        assert result["status"] == "error"
        assert "K8s error" in result["error"]


class TestStatelessMonitorStats:
    """Test statistics tracking."""

    def test_get_stats(self, settings, mock_monitor):
        """Test getting stateless monitor stats."""
        sm = StatelessMonitor(settings, mock_monitor)
        sm.stats["cycles_completed"] = 5

        stats = sm.get_stats()

        assert stats["mode"] == "stateless"
        assert stats["cycles_completed"] == 5
        assert "uptime_cycles" in stats

    def test_comparison_metrics(self, settings, mock_monitor):
        """Test comparison metrics."""
        sm = StatelessMonitor(settings, mock_monitor)
        sm.stats["cycles_completed"] = 10
        sm.stats["total_tokens_used"] = 5000

        metrics = sm.get_comparison_metrics()

        assert metrics["mode"] == "stateless"
        assert metrics["cycles_completed"] == 10
        assert metrics["has_conversation_history"] is False
        assert metrics["can_see_trends"] is False
        assert metrics["depends_on_disk_state"] is False
        assert metrics["context_continuous"] is False
        assert metrics["average_tokens_per_cycle"] == 500

    def test_comparison_metrics_empty(self, settings, mock_monitor):
        """Test comparison metrics with no cycles."""
        sm = StatelessMonitor(settings, mock_monitor)

        metrics = sm.get_comparison_metrics()

        assert metrics["average_tokens_per_cycle"] == 0


class TestStatelessMonitorFormatting:
    """Test message formatting in stateless mode."""

    @pytest.mark.asyncio
    async def test_cycle_message_format(self, settings, mock_monitor):
        """Test that cycle messages are properly formatted."""
        sm = StatelessMonitor(settings, mock_monitor)

        result = await sm.run_stateless_cycle()

        message = result["formatted_message"]
        assert "Monitoring Cycle #1" in message
        assert "Current Cluster State" in message
        assert "5" in message  # node count

    @pytest.mark.asyncio
    async def test_no_previous_context(self, settings, mock_monitor):
        """Test that previous cycle context is NOT included."""
        sm = StatelessMonitor(settings, mock_monitor)

        result = await sm.run_stateless_cycle()

        message = result["formatted_message"]
        assert "Previous Cycle Summary" not in message

    @pytest.mark.asyncio
    async def test_k8s_state_included(self, settings, mock_monitor):
        """Test that K8s state is included in result."""
        sm = StatelessMonitor(settings, mock_monitor)

        result = await sm.run_stateless_cycle()

        assert result["k8s_state"]["node_count"] == 5
        assert result["k8s_state"]["pod_count"] == 42


class TestStatelessMonitorShutdown:
    """Test shutdown behavior."""

    @pytest.mark.asyncio
    async def test_shutdown(self, settings, mock_monitor):
        """Test graceful shutdown."""
        sm = StatelessMonitor(settings, mock_monitor)
        sm.stats["cycles_completed"] = 5

        # Should not raise
        await sm.shutdown()

        assert sm.stats["cycles_completed"] == 5


class TestStatelessVsPersistent:
    """Test differences between stateless and persistent modes."""

    def test_mode_identity(self, settings, mock_monitor):
        """Test that mode is clearly marked as stateless."""
        sm = StatelessMonitor(settings, mock_monitor)

        assert sm.stats["mode"] == "stateless"
        assert sm.get_stats()["mode"] == "stateless"
        assert sm.get_comparison_metrics()["mode"] == "stateless"

    @pytest.mark.asyncio
    async def test_no_conversation_history(self, settings, mock_monitor):
        """Test that stateless mode has no conversation history."""
        sm = StatelessMonitor(settings, mock_monitor)

        # Run multiple cycles
        for _ in range(3):
            await sm.run_stateless_cycle()

        # Should not have stored conversation history
        metrics = sm.get_comparison_metrics()
        assert metrics["has_conversation_history"] is False

    @pytest.mark.asyncio
    async def test_no_trend_detection(self, settings, mock_monitor):
        """Test that stateless mode can't detect trends."""
        sm = StatelessMonitor(settings, mock_monitor)

        # Run multiple cycles
        for _ in range(5):
            await sm.run_stateless_cycle()

        metrics = sm.get_comparison_metrics()
        assert metrics["can_see_trends"] is False

    @pytest.mark.asyncio
    async def test_disk_independence(self, settings, mock_monitor):
        """Test that stateless mode doesn't depend on disk state."""
        sm = StatelessMonitor(settings, mock_monitor)

        result = await sm.run_stateless_cycle()

        metrics = sm.get_comparison_metrics()
        assert metrics["depends_on_disk_state"] is False


class TestStatelessMonitorComparison:
    """Tests comparing stateless behavior to what persistent mode would do."""

    @pytest.mark.asyncio
    async def test_fresh_context_each_cycle(self, settings, mock_monitor):
        """Test that each cycle has fresh context."""
        sm = StatelessMonitor(settings, mock_monitor)

        # Run cycles and collect messages
        messages = []
        for _ in range(2):
            result = await sm.run_stateless_cycle()
            messages.append(result["formatted_message"])

        # Each message should be independent
        # (no reference to previous cycles)
        for msg in messages:
            assert "Previous Cycle Summary" not in msg

    @pytest.mark.asyncio
    async def test_no_state_persistence(self, settings, mock_monitor):
        """Test that stateless mode doesn't persist state between cycles."""
        sm = StatelessMonitor(settings, mock_monitor)

        # Create first instance and run cycle
        result1 = await sm.run_stateless_cycle()
        cycle1_data = result1["k8s_state"]

        # Create new instance (simulating restart)
        sm2 = StatelessMonitor(settings, mock_monitor)
        result2 = await sm2.run_stateless_cycle()
        cycle2_data = result2["k8s_state"]

        # Both cycles should get same data (from mock)
        # but have no shared history between instances
        assert sm2.stats["cycles_completed"] == 1
        assert sm2.get_comparison_metrics()["has_conversation_history"] is False


class TestStatelessMonitorEdgeCases:
    """Test edge cases for stateless monitor."""

    @pytest.mark.asyncio
    async def test_empty_cluster_state(self, settings):
        """Test handling of empty cluster state."""
        mock_monitor = AsyncMock()
        mock_monitor._gather_cluster_state = AsyncMock(return_value={})

        sm = StatelessMonitor(settings, mock_monitor)
        result = await sm.run_stateless_cycle()

        assert result["status"] == "success"
        assert result["k8s_state"] == {}

    @pytest.mark.asyncio
    async def test_none_cluster_state(self, settings):
        """Test handling of None cluster state."""
        mock_monitor = AsyncMock()
        mock_monitor._gather_cluster_state = AsyncMock(return_value=None)

        sm = StatelessMonitor(settings, mock_monitor)
        result = await sm.run_stateless_cycle()

        # Should handle gracefully
        assert "status" in result

    def test_timestamp_format(self, settings, mock_monitor):
        """Test that timestamps are in ISO format."""
        sm = StatelessMonitor(settings, mock_monitor)
        timestamp = sm._get_timestamp()

        # Should be ISO format: YYYY-MM-DDTHH:MM:SS.ffffff
        assert "T" in timestamp
        assert "-" in timestamp
        assert ":" in timestamp


class TestStatelessMonitorMetrics:
    """Test metrics and monitoring."""

    def test_average_tokens_calculation(self, settings, mock_monitor):
        """Test average tokens per cycle calculation."""
        sm = StatelessMonitor(settings, mock_monitor)
        sm.stats["cycles_completed"] = 10
        sm.stats["total_tokens_used"] = 15000

        metrics = sm.get_comparison_metrics()

        assert metrics["average_tokens_per_cycle"] == 1500

    def test_zero_division_protection(self, settings, mock_monitor):
        """Test that zero cycles doesn't cause division error."""
        sm = StatelessMonitor(settings, mock_monitor)

        metrics = sm.get_comparison_metrics()

        assert metrics["average_tokens_per_cycle"] == 0

    @pytest.mark.asyncio
    async def test_stats_update_on_error(self, settings, mock_monitor):
        """Test that stats aren't updated on cycle error."""
        mock_monitor._gather_cluster_state = AsyncMock(side_effect=Exception("Error"))
        sm = StatelessMonitor(settings, mock_monitor)

        result = await sm.run_stateless_cycle()

        assert result["status"] == "error"
        # Cycle count should still increment even on error
        assert sm.stats["cycles_completed"] == 1


class TestStatelessMonitorIntegration:
    """Integration tests for stateless monitor."""

    @pytest.mark.asyncio
    async def test_full_cycle_sequence(self, settings, mock_monitor):
        """Test a full sequence of stateless cycles."""
        sm = StatelessMonitor(settings, mock_monitor)

        # Run initial cycles
        for i in range(3):
            result = await sm.run_stateless_cycle()
            assert result["status"] == "success"

        # Get stats
        stats = sm.get_stats()
        assert stats["cycles_completed"] == 3

        # Get comparison metrics
        metrics = sm.get_comparison_metrics()
        assert metrics["cycles_completed"] == 3
        assert metrics["has_conversation_history"] is False

        # Shutdown
        await sm.shutdown()

        # Stats should be preserved
        assert sm.stats["cycles_completed"] == 3
