"""Persistent session management for long-context monitoring."""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Any


class SessionManager:
    """Manages persistent session state for Claude SDK client."""

    def __init__(
        self,
        session_dir: Path = Path("sessions"),
        max_context_tokens: int = 120000
    ):
        """
        Initialize session manager.

        Args:
            session_dir: Directory to store session files
            max_context_tokens: Maximum context window (for pruning decisions)
        """
        self.session_dir = Path(session_dir)
        self.session_dir.mkdir(exist_ok=True)
        self.max_context_tokens = max_context_tokens
        self.logger = logging.getLogger(__name__)

    def save_session(
        self,
        session_id: str,
        conversation_history: list,
        metadata: dict
    ) -> None:
        """
        Save session state to disk.

        Args:
            session_id: Unique session identifier
            conversation_history: List of messages from SDK client
            metadata: Session metadata (created_at, cycle_count, etc.)
        """
        session_file = self.session_dir / f"{session_id}.json"
        session_data = {
            "session_id": session_id,
            "conversation_history": conversation_history,
            "metadata": metadata,
            "saved_at": datetime.now(timezone.utc).isoformat()
        }

        try:
            with open(session_file, 'w') as f:
                json.dump(session_data, f, indent=2)
            self.logger.info(f"Session {session_id} saved ({len(conversation_history)} messages)")
        except Exception as e:
            self.logger.error(f"Failed to save session {session_id}: {e}")
            raise

    def load_session(self, session_id: str) -> Optional[dict]:
        """
        Load session state from disk.

        Args:
            session_id: Session identifier

        Returns:
            session_data dict or None if not found
        """
        session_file = self.session_dir / f"{session_id}.json"
        if not session_file.exists():
            self.logger.debug(f"Session file not found: {session_file}")
            return None

        try:
            with open(session_file, 'r') as f:
                session_data = json.load(f)
            self.logger.info(f"Session {session_id} loaded ({len(session_data.get('conversation_history', []))} messages)")
            return session_data
        except Exception as e:
            self.logger.error(f"Failed to load session {session_id}: {e}")
            return None

    def prune_old_messages(
        self,
        conversation_history: list,
        max_tokens: int = None
    ) -> list:
        """
        Prune old messages if context is getting large.

        Strategy: Keep system messages and latest N messages to stay under token limit.
        Rough token estimation: ~4 characters per token

        Args:
            conversation_history: Full conversation history
            max_tokens: Token limit (uses self.max_context_tokens if None)

        Returns:
            Pruned conversation history
        """
        if max_tokens is None:
            max_tokens = self.max_context_tokens

        # Estimate tokens (rough: ~4 chars per token)
        total_chars = sum(len(msg.get("content", "")) for msg in conversation_history)
        estimated_tokens = total_chars // 4

        # Check if pruning is needed (at 80% of limit)
        if estimated_tokens < max_tokens * 0.8:
            return conversation_history

        # Keep system message + latest 50 messages
        system_msgs = [m for m in conversation_history if m.get("role") == "system"]
        other_msgs = [m for m in conversation_history if m.get("role") != "system"]

        # Keep latest 50 messages (should be ~12-13 cycles at 4 messages/cycle)
        pruned = system_msgs + other_msgs[-50:]

        self.logger.warning(
            f"Pruned conversation: {len(conversation_history)} → {len(pruned)} messages "
            f"(estimated tokens: {estimated_tokens} → {estimated_tokens * len(pruned) // len(conversation_history)})"
        )
        return pruned

    def smart_prune(self, conversation_history: list) -> list:
        """
        Smart pruning that preserves semantic importance.

        Strategy:
        1. Always keep system message
        2. Keep recent 30 messages (latest cycles)
        3. Keep any messages with critical/escalation keywords
        4. Remove old routine health check messages

        Args:
            conversation_history: Full conversation history

        Returns:
            Intelligently pruned history preserving critical context
        """
        if not conversation_history:
            return []

        system_msgs = [m for m in conversation_history if m.get("role") == "system"]
        other_msgs = [m for m in conversation_history if m.get("role") != "system"]

        # Keywords indicating important messages to preserve
        critical_keywords = [
            "critical", "escalation", "failed", "error", "down", "outage",
            "severe", "major", "p0", "p1", "crash", "oom", "crashed"
        ]

        # Identify critical messages
        critical_msgs = [
            m for m in other_msgs
            if any(
                keyword in m.get("content", "").lower()
                for keyword in critical_keywords
            )
        ]

        # Keep latest 30 messages
        recent_msgs = other_msgs[-30:]

        # Combine and deduplicate (prefer to keep more messages)
        important_msgs = list(set(id(m) for m in (critical_msgs + recent_msgs)))
        preserved_msgs = [m for m in (critical_msgs + recent_msgs) if id(m) in important_msgs]

        # Final composition
        pruned = system_msgs + preserved_msgs[-30:]

        if len(pruned) < len(conversation_history):
            self.logger.warning(
                f"Smart pruned conversation: {len(conversation_history)} → {len(pruned)} messages"
            )

        return pruned

    def delete_session(self, session_id: str) -> None:
        """
        Delete session file.

        Args:
            session_id: Session identifier
        """
        session_file = self.session_dir / f"{session_id}.json"
        if session_file.exists():
            try:
                session_file.unlink()
                self.logger.info(f"Session {session_id} deleted")
            except Exception as e:
                self.logger.error(f"Failed to delete session {session_id}: {e}")

    def list_sessions(self) -> list[str]:
        """
        List all available sessions.

        Returns:
            List of session IDs
        """
        sessions = [f.stem for f in self.session_dir.glob("*.json")]
        return sorted(sessions)

    def get_session_stats(self, session_id: str) -> dict:
        """
        Get statistics about a session.

        Args:
            session_id: Session identifier

        Returns:
            Dict with message_count, estimated_tokens, cycle_count, context_percentage
        """
        session_data = self.load_session(session_id)
        if not session_data:
            return {}

        history = session_data.get("conversation_history", [])
        total_chars = sum(len(m.get("content", "")) for m in history)
        estimated_tokens = total_chars // 4

        return {
            "session_id": session_id,
            "message_count": len(history),
            "estimated_tokens": estimated_tokens,
            "cycle_count": session_data.get("metadata", {}).get("cycle_count", 0),
            "context_percentage": round((estimated_tokens / self.max_context_tokens) * 100, 2),
            "saved_at": session_data.get("saved_at", "unknown")
        }

    def should_prune(self, conversation_history: list) -> bool:
        """
        Check if pruning is needed.

        Args:
            conversation_history: Full conversation history

        Returns:
            True if at 80% of max context
        """
        total_chars = sum(len(m.get("content", "")) for m in conversation_history)
        estimated_tokens = total_chars // 4
        threshold_tokens = self.max_context_tokens * 0.8
        return estimated_tokens > threshold_tokens
