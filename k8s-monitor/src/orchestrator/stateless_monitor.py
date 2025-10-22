"""Stateless monitoring mode without cycle report dependency."""

import json
import logging
from typing import Any, Optional

from src.config import Settings
from src.orchestrator.monitor import Monitor
from src.sessions import ConversationFormatter


class StatelessMonitor:
    """Stateless monitoring wrapper that avoids cycle report dependency.

    This class wraps the Monitor and operates in pure stateless mode,
    forming a clean comparison point against the persistent mode.
    Unlike the standard mode, it:
    - Does NOT save cycle reports to disk
    - Does NOT load previous cycles from history
    - Creates fresh context for each cycle
    - Uses ConversationFormatter for clean output

    This enables direct comparison of performance and quality between
    stateless and persistent modes.
    """

    def __init__(self, settings: Settings, monitor: Monitor):
        """Initialize stateless monitor.

        Args:
            settings: Settings instance with configuration
            monitor: Monitor instance for K8s state gathering
        """
        self.settings = settings
        self.monitor = monitor
        self.logger = logging.getLogger(__name__)
        self.formatter = ConversationFormatter()

        # Statistics tracking
        self.stats = {
            "cycles_completed": 0,
            "total_tokens_used": 0,
            "last_cycle_timestamp": None,
            "mode": "stateless"
        }

    async def run_stateless_cycle(self) -> dict[str, Any]:
        """Run a single stateless monitoring cycle without history.

        Returns:
            Dict with cycle results
        """
        cycle_num = self.stats["cycles_completed"] + 1

        # Update cycle count immediately (even if error occurs)
        self.stats["cycles_completed"] = cycle_num

        try:
            self.logger.info(f"🔄 Starting stateless cycle #{cycle_num}")

            # Gather K8s state
            k8s_state = await self.monitor._gather_cluster_state()

            # Format message WITHOUT previous cycle context
            cycle_message = self.formatter.format_cluster_state_message(
                cycle_num, k8s_state, previous_summary=None
            )

            self.logger.info(f"📊 Cycle {cycle_num} state gathered")
            self.logger.debug(f"K8s state: {k8s_state}")

            # Update timestamp
            self.stats["last_cycle_timestamp"] = self._get_timestamp()

            self.logger.info(f"✅ Stateless cycle {cycle_num} complete")

            return {
                "cycle": cycle_num,
                "status": "success",
                "k8s_state": k8s_state,
                "formatted_message": cycle_message,
                "mode": "stateless",
                "timestamp": self.stats["last_cycle_timestamp"]
            }

        except Exception as e:
            self.logger.error(f"❌ Error in stateless cycle {cycle_num}: {e}", exc_info=True)
            return {
                "cycle": cycle_num,
                "status": "error",
                "error": str(e),
                "mode": "stateless"
            }

    def get_stats(self) -> dict[str, Any]:
        """Get stateless monitor statistics.

        Returns:
            Dictionary with current statistics
        """
        return {
            **self.stats,
            "uptime_cycles": self.stats["cycles_completed"],
            "mode": "stateless"
        }

    def get_comparison_metrics(self) -> dict[str, Any]:
        """Get metrics useful for comparing against persistent mode.

        Returns:
            Dict with comparison metrics
        """
        return {
            "mode": "stateless",
            "cycles_completed": self.stats["cycles_completed"],
            "total_tokens": self.stats["total_tokens_used"],
            "average_tokens_per_cycle": (
                self.stats["total_tokens_used"] / self.stats["cycles_completed"]
                if self.stats["cycles_completed"] > 0 else 0
            ),
            "has_conversation_history": False,
            "can_see_trends": False,
            "depends_on_disk_state": False,
            "context_continuous": False
        }

    def _get_timestamp(self) -> str:
        """Get current timestamp in ISO format.

        Returns:
            ISO format timestamp string
        """
        from datetime import datetime
        return datetime.now().isoformat()

    async def shutdown(self) -> None:
        """Gracefully shutdown stateless monitor.

        In stateless mode, there's minimal state to save.
        """
        self.logger.info("🛑 Shutting down stateless monitor")
        self.logger.info(f"📊 Cycles completed: {self.stats['cycles_completed']}")
        self.logger.info(f"💾 Final stats: {json.dumps(self.stats, indent=2)}")
