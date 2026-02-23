"""
Session Manager for OnCall Agent API
Manages stateful sessions for multi-turn conversations
"""

import asyncio
import contextlib
import json
import logging
import os
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class Session:
    """Represents a user session with conversation history"""

    session_id: str
    user_id: str
    created_at: datetime
    last_accessed: datetime
    metadata: dict[str, Any] = field(default_factory=dict)
    conversation_history: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert session to dictionary for JSON serialization"""
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "created_at": self.created_at.isoformat(),
            "last_accessed": self.last_accessed.isoformat(),
            "metadata": self.metadata,
            "conversation_history": self.conversation_history,
            "message_count": len(self.conversation_history),
        }


class SessionManager:
    """
    Manages user sessions with TTL and automatic cleanup.

    Features:
    - Session creation with unique IDs
    - TTL-based expiration (default 30 minutes)
    - Max sessions per user limit
    - Automatic cleanup of expired sessions
    - Conversation history tracking
    """

    def __init__(
        self,
        ttl_minutes: int = 30,
        max_sessions_per_user: int = 5,
        cleanup_interval_minutes: int = 5,
        persist_directory: str | None = None,
    ):
        """
        Initialize session manager.

        Args:
            ttl_minutes: Session time-to-live in minutes
            max_sessions_per_user: Maximum concurrent sessions per user
            cleanup_interval_minutes: How often to run cleanup task
            persist_directory: Directory for SQLite persistence. None = in-memory only.
        """
        self.sessions: dict[str, Session] = {}
        self.ttl = timedelta(minutes=ttl_minutes)
        self.max_sessions_per_user = max_sessions_per_user
        self.cleanup_interval = timedelta(minutes=cleanup_interval_minutes)
        self.persist_directory = persist_directory

        # Track sessions by user for limit enforcement
        self.user_sessions: dict[str, list[str]] = {}

        # Cleanup task
        self._cleanup_task: asyncio.Task | None = None

        # SQLite persistence
        self.conn: sqlite3.Connection | None = None
        if persist_directory:
            self._init_db()
            self._load_sessions_from_db()

        logger.info(
            f"SessionManager initialized: TTL={ttl_minutes}min, "
            f"Max per user={max_sessions_per_user}, "
            f"Persist={'SQLite @ ' + persist_directory if persist_directory else 'in-memory'}"
        )

    def _init_db(self) -> None:
        """Initialize SQLite database for session persistence."""
        os.makedirs(self.persist_directory, exist_ok=True)
        db_path = os.path.join(self.persist_directory, "sessions.db")
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                last_accessed TEXT NOT NULL,
                metadata TEXT DEFAULT '{}',
                conversation_history TEXT DEFAULT '[]'
            );
            CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id);
            CREATE INDEX IF NOT EXISTS idx_sessions_last_accessed ON sessions(last_accessed);
        """)
        self.conn.commit()
        logger.info(f"Session DB initialized at {db_path}")

    def _load_sessions_from_db(self) -> None:
        """Load all sessions from SQLite into memory on startup."""
        if not self.conn:
            return
        rows = self.conn.execute("SELECT * FROM sessions").fetchall()
        for row in rows:
            session = Session(
                session_id=row["session_id"],
                user_id=row["user_id"],
                created_at=datetime.fromisoformat(row["created_at"]),
                last_accessed=datetime.fromisoformat(row["last_accessed"]),
                metadata=json.loads(row["metadata"]),
                conversation_history=json.loads(row["conversation_history"]),
            )
            self.sessions[session.session_id] = session
            if session.user_id not in self.user_sessions:
                self.user_sessions[session.user_id] = []
            self.user_sessions[session.user_id].append(session.session_id)
        logger.info(f"Loaded {len(rows)} sessions from DB")

    def _save_session_to_db(self, session: Session) -> None:
        """Write a session to SQLite (insert or replace)."""
        if not self.conn:
            return
        self.conn.execute(
            """INSERT OR REPLACE INTO sessions
               (session_id, user_id, created_at, last_accessed, metadata, conversation_history)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                session.session_id,
                session.user_id,
                session.created_at.isoformat(),
                session.last_accessed.isoformat(),
                json.dumps(session.metadata),
                json.dumps(session.conversation_history),
            ),
        )
        self.conn.commit()

    def _delete_session_from_db(self, session_id: str) -> None:
        """Delete a session from SQLite."""
        if not self.conn:
            return
        self.conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
        self.conn.commit()

    def _load_session_from_db(self, session_id: str) -> Session | None:
        """Try to load a single session from SQLite (fallback on cache miss)."""
        if not self.conn:
            return None
        row = self.conn.execute(
            "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        if not row:
            return None
        return Session(
            session_id=row["session_id"],
            user_id=row["user_id"],
            created_at=datetime.fromisoformat(row["created_at"]),
            last_accessed=datetime.fromisoformat(row["last_accessed"]),
            metadata=json.loads(row["metadata"]),
            conversation_history=json.loads(row["conversation_history"]),
        )

    def create_session(self, user_id: str, metadata: dict[str, Any] | None = None) -> Session:
        """
        Create a new session for a user.

        Args:
            user_id: User identifier
            metadata: Optional metadata to attach to session

        Returns:
            Newly created Session object

        Raises:
            ValueError: If user has reached max session limit
        """
        # Check user's session count
        user_session_ids = self.user_sessions.get(user_id, [])
        active_sessions = [sid for sid in user_session_ids if sid in self.sessions]

        if len(active_sessions) >= self.max_sessions_per_user:
            # Clean up oldest session to make room
            oldest_sid = active_sessions[0]
            logger.info(f"User {user_id} at session limit, removing oldest: {oldest_sid}")
            self.delete_session(oldest_sid)

        # Create new session
        session_id = str(uuid.uuid4())
        now = datetime.now()

        session = Session(
            session_id=session_id,
            user_id=user_id,
            created_at=now,
            last_accessed=now,
            metadata=metadata or {},
            conversation_history=[],
        )

        self.sessions[session_id] = session

        # Track session for user
        if user_id not in self.user_sessions:
            self.user_sessions[user_id] = []
        self.user_sessions[user_id].append(session_id)

        self._save_session_to_db(session)

        logger.info(f"Session created: {session_id} for user {user_id}")
        return session

    def get_session(self, session_id: str) -> Session | None:
        """
        Retrieve a session by ID.

        Args:
            session_id: Session identifier

        Returns:
            Session object if found and not expired, None otherwise
        """
        session = self.sessions.get(session_id)

        # Fallback: try loading from SQLite on cache miss
        if session is None:
            session = self._load_session_from_db(session_id)
            if session:
                # Re-populate memory cache and user tracking
                self.sessions[session.session_id] = session
                if session.user_id not in self.user_sessions:
                    self.user_sessions[session.user_id] = []
                if session.session_id not in self.user_sessions[session.user_id]:
                    self.user_sessions[session.user_id].append(session.session_id)
                logger.info(f"Session loaded from DB fallback: {session_id}")

        if session is None:
            logger.debug(f"Session not found: {session_id}")
            return None

        # Update last accessed time
        session.last_accessed = datetime.now()
        self._save_session_to_db(session)
        return session

    def update_session(
        self,
        session_id: str,
        conversation_entry: dict[str, Any] | None = None,
        metadata_update: dict[str, Any] | None = None,
    ) -> bool:
        """
        Update session with new conversation entry or metadata.

        Args:
            session_id: Session identifier
            conversation_entry: New conversation entry to add
            metadata_update: Metadata updates to apply

        Returns:
            True if updated successfully, False if session not found
        """
        session = self.get_session(session_id)
        if session is None:
            return False

        if conversation_entry:
            session.conversation_history.append(conversation_entry)

        if metadata_update:
            session.metadata.update(metadata_update)

        session.last_accessed = datetime.now()
        self._save_session_to_db(session)
        logger.debug(f"Session updated: {session_id}")
        return True

    def delete_session(self, session_id: str) -> bool:
        """
        Delete a session.

        Args:
            session_id: Session identifier

        Returns:
            True if deleted, False if not found
        """
        session = self.sessions.pop(session_id, None)

        if session:
            # Remove from user's session list
            if session.user_id in self.user_sessions:
                with contextlib.suppress(ValueError):
                    self.user_sessions[session.user_id].remove(session_id)

            self._delete_session_from_db(session_id)
            logger.info(f"Session deleted: {session_id}")
            return True

        return False

    def list_user_sessions(self, user_id: str) -> list[Session]:
        """
        List all active sessions for a user.

        Args:
            user_id: User identifier

        Returns:
            List of active Session objects
        """
        session_ids = self.user_sessions.get(user_id, [])
        sessions = []

        for sid in session_ids:
            session = self.get_session(sid)
            if session:
                sessions.append(session)

        return sessions

    def get_stats(self) -> dict[str, Any]:
        """
        Get session manager statistics.

        Returns:
            Dictionary with session counts and metrics
        """
        total_sessions = len(self.sessions)
        total_users = len(self.user_sessions)

        return {
            "total_sessions": total_sessions,
            "total_users": total_users,
            "max_sessions_per_user": self.max_sessions_per_user,
        }

    async def cleanup_expired_sessions(self):
        """
        Background task placeholder (sessions no longer expire).

        Sessions persist indefinitely. The max_sessions_per_user limit
        handles natural eviction when new sessions are created.
        """
        logger.info("Session cleanup task started (no-op: sessions persist indefinitely)")

        while True:
            try:
                await asyncio.sleep(self.cleanup_interval.total_seconds())
                logger.debug(f"Active sessions: {len(self.sessions)}")
            except asyncio.CancelledError:
                logger.info("Session cleanup task cancelled")
                break
            except Exception as e:
                logger.error(f"Error in cleanup task: {e}", exc_info=True)

    def start_cleanup_task(self) -> asyncio.Task:
        """
        Start the background cleanup task.

        Returns:
            The cleanup task
        """
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self.cleanup_expired_sessions())
            logger.info("Cleanup task started")
        return self._cleanup_task

    def stop_cleanup_task(self):
        """Stop the background cleanup task."""
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            logger.info("Cleanup task stopped")
