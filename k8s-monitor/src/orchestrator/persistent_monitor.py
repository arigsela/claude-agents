"""Persistent monitoring mode using Claude API with long-context conversations."""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from anthropic import Anthropic

from src.config import Settings
from src.orchestrator.monitor import Monitor


class PersistentMonitor:
    """Manages persistent monitoring with long-context conversation history.

    This class wraps the Monitor and maintains a persistent Anthropic API client
    across monitoring cycles, enabling the model to see full conversation history
    and build context over time.
    """

    def __init__(self, settings: Settings, monitor: Monitor):
        """Initialize persistent monitor.

        Args:
            settings: Settings instance with configuration
            monitor: Monitor instance for K8s state gathering
        """
        self.settings = settings
        self.monitor = monitor
        self.logger = logging.getLogger(__name__)

        # API client - initialized in initialize_session
        self.client: Optional[Anthropic] = None

        # Session state
        self.session_id = settings.session_id
        self.session_dir = Path("sessions") / self.session_id
        self.messages: list[dict[str, str]] = []
        self.cycle_count = 0

        # Statistics
        self.stats = {
            "session_id": self.session_id,
            "created_at": datetime.now().isoformat(),
            "cycles_completed": 0,
            "total_tokens_used": 0,
            "last_cycle_timestamp": None,
        }

    async def initialize_session(self) -> None:
        """Initialize or restore persistent session.

        Raises:
            ValueError: If ANTHROPIC_API_KEY is not set
        """
        # Validate API key
        if not self.settings.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY not set in environment")

        # Initialize Anthropic client
        self.client = Anthropic(api_key=self.settings.anthropic_api_key)

        # Create session directory
        self.session_dir.mkdir(parents=True, exist_ok=True)

        # Try to restore existing session
        session_file = self.session_dir / "session.json"
        if session_file.exists():
            self.logger.info(f"📂 Restoring session from {session_file}")
            with open(session_file) as f:
                session_data = json.load(f)
                self.messages = session_data.get("messages", [])
                self.cycle_count = session_data.get("cycle_count", 0)
                self.stats = session_data.get("stats", self.stats)
            self.logger.info(f"✅ Restored session with {len(self.messages)} messages, cycle {self.cycle_count}")
        else:
            # Fresh session
            self.logger.info(f"🆕 Starting new session: {self.session_id}")
            self.cycle_count = 0
            self.messages = []
            self.stats["created_at"] = datetime.now().isoformat()

    async def run_persistent_cycle(self) -> dict[str, Any]:
        """Run a single monitoring cycle with persistent context.

        Returns:
            Dict with cycle results and token usage

        Raises:
            RuntimeError: If session not initialized
        """
        if not self.client:
            raise RuntimeError("Session not initialized. Call initialize_session() first.")

        self.logger.info(f"🔄 Starting persistent cycle #{self.cycle_count + 1}")

        try:
            # Run full monitoring cycle using the Monitor's subagent orchestration
            cycle_results = await self.monitor.run_monitoring_cycle()

            # Format cycle message from results
            cycle_message = self._format_cycle_message(self.cycle_count + 1, cycle_results)

            # Add to message history
            self.messages.append({
                "role": "user",
                "content": cycle_message
            })

            # Call API with full message history
            self.logger.info(f"📨 Calling Claude API with {len(self.messages)} messages in history")

            response = self.client.messages.create(
                model=self.settings.anthropic_model,
                max_tokens=2000,
                system=self._build_system_prompt(),
                messages=self.messages
            )

            # Extract response
            assistant_message = response.content[0].text

            # Add to history
            self.messages.append({
                "role": "assistant",
                "content": assistant_message
            })

            # Track tokens
            tokens_used = response.usage.input_tokens + response.usage.output_tokens
            self.stats["total_tokens_used"] += tokens_used
            self.stats["last_cycle_timestamp"] = datetime.now().isoformat()
            self.stats["cycles_completed"] += 1

            # Check if pruning needed
            if self._should_prune_context():
                self.logger.warning("⚠️  Context window approaching limit, pruning older messages")
                await self._prune_context()

            # Increment cycle count and save
            self.cycle_count += 1
            await self._save_session()

            self.logger.info(f"✅ Cycle {self.cycle_count} complete. Tokens used: {tokens_used}")

            return {
                "cycle": self.cycle_count,
                "status": "success",
                "tokens_used": tokens_used,
                "messages_in_history": len(self.messages),
                "response_preview": assistant_message[:200] + "..." if len(assistant_message) > 200 else assistant_message
            }

        except Exception as e:
            self.logger.error(f"❌ Error in cycle {self.cycle_count + 1}: {e}", exc_info=True)
            return {
                "cycle": self.cycle_count + 1,
                "status": "error",
                "error": str(e)
            }

    async def shutdown(self) -> None:
        """Gracefully shutdown and save final state."""
        self.logger.info("🛑 Shutting down persistent monitor")
        await self._save_session()
        self.logger.info(f"💾 Session saved. Cycles completed: {self.cycle_count}")
        self.logger.info(f"📊 Total tokens used: {self.stats['total_tokens_used']}")

    def _format_cycle_message(self, cycle_num: int, cycle_results: dict[str, Any]) -> str:
        """Format cycle results into clean user message.

        Args:
            cycle_num: Cycle number for context
            cycle_results: Monitoring cycle results from Monitor.run_monitoring_cycle()

        Returns:
            Formatted message for Claude
        """
        timestamp = datetime.now().isoformat()

        message = f"""## Monitoring Cycle #{cycle_num}
**Timestamp:** {timestamp}

### Cycle Results
```json
{json.dumps(cycle_results, indent=2)}
```

Please analyze this cluster state and provide:
1. Health assessment
2. Any critical issues
3. Trends compared to previous cycles (if applicable)
4. Recommended actions
"""
        return message

    def _build_system_prompt(self) -> str:
        """Build system prompt for Claude.

        Returns:
            System prompt string
        """
        return """You are a Kubernetes cluster monitoring agent running continuous cycles of analysis.

Your role is to:
1. Monitor cluster health and identify issues
2. Track trends across multiple monitoring cycles
3. Recognize recurring problems and improvements
4. Provide actionable recommendations
5. Escalate critical issues appropriately

You have access to full conversation history across all previous monitoring cycles.
Use this history to provide intelligent, context-aware analysis that improves over time.

When analyzing cluster state:
- Look for pod crashes, OOMKilled, evictions
- Check node health and resource availability
- Identify services with high error rates
- Track deployment replica counts and readiness
- Summarize findings concisely"""

    def _should_prune_context(self) -> bool:
        """Check if context should be pruned.

        Returns:
            True if message count exceeds threshold
        """
        # Estimate: ~4 tokens per message on average
        estimated_tokens = len(self.messages) * 4 * 500  # avg message ~500 chars
        return estimated_tokens > (self.settings.max_context_tokens * 0.8)

    async def _prune_context(self) -> None:
        """Prune oldest messages to prevent context overflow.

        Keeps at least the last 10 messages (5 cycles worth) to maintain
        recent context while reducing memory footprint.
        """
        min_keep = 10
        if len(self.messages) > min_keep:
            # Keep last N messages
            messages_to_keep = max(min_keep, len(self.messages) // 2)
            removed = len(self.messages) - messages_to_keep
            self.messages = self.messages[-messages_to_keep:]
            self.logger.info(f"🗑️  Pruned {removed} messages, kept {len(self.messages)}")

    async def _save_session(self) -> None:
        """Save session state to disk.

        Raises:
            IOError: If session cannot be saved
        """
        session_file = self.session_dir / "session.json"
        try:
            session_data = {
                "session_id": self.session_id,
                "cycle_count": self.cycle_count,
                "messages": self.messages,
                "stats": self.stats,
                "saved_at": datetime.now().isoformat(),
            }

            with open(session_file, "w") as f:
                json.dump(session_data, f, indent=2)

            self.logger.debug(f"💾 Session saved to {session_file}")
        except IOError as e:
            self.logger.error(f"❌ Failed to save session: {e}")
            raise

    def get_stats(self) -> dict[str, Any]:
        """Get session statistics.

        Returns:
            Dictionary with current session stats
        """
        return {
            **self.stats,
            "messages_in_history": len(self.messages),
            "estimated_context_size": len(self.messages) * 500  # rough estimate
        }
