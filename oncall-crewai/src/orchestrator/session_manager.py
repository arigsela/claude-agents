"""Session Manager for CopilotKit conversation persistence.

Adapted from oncall-agent-api/src/api/session_manager.py.
Provides SQLite-backed session storage with in-memory cache,
TTL expiration, and background cleanup.
"""

import asyncio
import json
import os
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from shared.logging_config import setup_logging

logger = setup_logging("session-manager")

SESSION_DB_PATH = os.getenv("SESSION_DB_PATH", "/data/sessions.db")
SESSION_TTL_HOURS = int(os.getenv("SESSION_TTL_HOURS", "24"))
SESSION_MAX_TOTAL = int(os.getenv("SESSION_MAX_TOTAL", "50"))


@dataclass
class Session:
    """A conversation session with message history."""

    session_id: str
    title: str
    created_at: datetime
    last_accessed: datetime
    messages: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "title": self.title,
            "created_at": self.created_at.isoformat(),
            "last_accessed": self.last_accessed.isoformat(),
            "messages": self.messages,
            "message_count": len(self.messages),
        }

    def to_summary(self) -> dict:
        return {
            "session_id": self.session_id,
            "title": self.title,
            "created_at": self.created_at.isoformat(),
            "last_accessed": self.last_accessed.isoformat(),
            "message_count": len(self.messages),
        }


class SessionManager:
    """Manages conversation sessions with SQLite persistence.

    Features:
    - Auto-create sessions on first message
    - Title from first user message (truncated to 60 chars)
    - TTL-based expiration (default 24 hours)
    - Max total sessions cap (default 50)
    - Background cleanup task
    """

    def __init__(
        self,
        db_path: str = SESSION_DB_PATH,
        ttl_hours: int = SESSION_TTL_HOURS,
        max_sessions: int = SESSION_MAX_TOTAL,
        cleanup_interval_minutes: int = 10,
    ):
        self.db_path = db_path
        self.ttl = timedelta(hours=ttl_hours)
        self.max_sessions = max_sessions
        self.cleanup_interval = timedelta(minutes=cleanup_interval_minutes)
        self.sessions: dict[str, Session] = {}
        self._cleanup_task: asyncio.Task | None = None
        self.conn: sqlite3.Connection | None = None

        self._init_db()
        self._load_sessions_from_db()

        logger.info(
            f"SessionManager initialized: TTL={ttl_hours}h, "
            f"max={max_sessions}, DB={db_path}"
        )

    def _init_db(self) -> None:
        """Initialize SQLite database."""
        db_dir = os.path.dirname(self.db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                title TEXT DEFAULT 'New Chat',
                created_at TEXT NOT NULL,
                last_accessed TEXT NOT NULL,
                messages TEXT DEFAULT '[]'
            );
            CREATE INDEX IF NOT EXISTS idx_sessions_last_accessed
                ON sessions(last_accessed);
        """)
        self.conn.commit()

    def _load_sessions_from_db(self) -> None:
        """Load non-expired sessions from SQLite into memory."""
        if not self.conn:
            return
        rows = self.conn.execute("SELECT * FROM sessions").fetchall()
        loaded = 0
        for row in rows:
            last_accessed = datetime.fromisoformat(row["last_accessed"])
            if datetime.now() - last_accessed > self.ttl:
                self.conn.execute(
                    "DELETE FROM sessions WHERE session_id = ?",
                    (row["session_id"],),
                )
                continue
            session = Session(
                session_id=row["session_id"],
                title=row["title"],
                created_at=datetime.fromisoformat(row["created_at"]),
                last_accessed=last_accessed,
                messages=json.loads(row["messages"]),
            )
            self.sessions[session.session_id] = session
            loaded += 1
        self.conn.commit()
        logger.info(f"Loaded {loaded} sessions from DB")

    def _save_session(self, session: Session) -> None:
        """Write session to SQLite."""
        if not self.conn:
            return
        self.conn.execute(
            """INSERT OR REPLACE INTO sessions
               (session_id, title, created_at, last_accessed, messages)
               VALUES (?, ?, ?, ?, ?)""",
            (
                session.session_id,
                session.title,
                session.created_at.isoformat(),
                session.last_accessed.isoformat(),
                json.dumps(session.messages),
            ),
        )
        self.conn.commit()

    def _enforce_max_sessions(self) -> None:
        """Delete oldest sessions if over the cap."""
        if len(self.sessions) < self.max_sessions:
            return
        sorted_sessions = sorted(
            self.sessions.values(), key=lambda s: s.last_accessed
        )
        to_remove = len(self.sessions) - self.max_sessions + 1
        for session in sorted_sessions[:to_remove]:
            self.delete_session(session.session_id)
            logger.info(f"Evicted oldest session: {session.session_id}")

    def get_or_create_session(self, session_id: str) -> Session:
        """Get existing session or create a new one."""
        session = self.sessions.get(session_id)
        if session and not self._is_expired(session):
            session.last_accessed = datetime.now()
            self._save_session(session)
            return session

        # Try loading from DB
        if not session and self.conn:
            row = self.conn.execute(
                "SELECT * FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if row:
                last_accessed = datetime.fromisoformat(row["last_accessed"])
                if datetime.now() - last_accessed <= self.ttl:
                    session = Session(
                        session_id=row["session_id"],
                        title=row["title"],
                        created_at=datetime.fromisoformat(row["created_at"]),
                        last_accessed=datetime.now(),
                        messages=json.loads(row["messages"]),
                    )
                    self.sessions[session_id] = session
                    self._save_session(session)
                    return session

        # Create new
        self._enforce_max_sessions()
        now = datetime.now()
        session = Session(
            session_id=session_id,
            title="New Chat",
            created_at=now,
            last_accessed=now,
            messages=[],
        )
        self.sessions[session_id] = session
        self._save_session(session)
        logger.info(f"Session created: {session_id}")
        return session

    def append_messages(
        self, session_id: str, user_msg: str, assistant_msg: str
    ) -> None:
        """Add a user/assistant exchange to a session."""
        session = self.get_or_create_session(session_id)
        now = datetime.now().isoformat()

        session.messages.append(
            {"role": "user", "content": user_msg, "timestamp": now}
        )
        session.messages.append(
            {"role": "assistant", "content": assistant_msg, "timestamp": now}
        )

        # Set title from first user message
        if session.title == "New Chat" and user_msg:
            session.title = user_msg[:60].strip()

        session.last_accessed = datetime.now()
        self._save_session(session)

    def list_sessions(self) -> list[dict]:
        """List all sessions sorted by last_accessed desc."""
        active = [
            s for s in self.sessions.values() if not self._is_expired(s)
        ]
        active.sort(key=lambda s: s.last_accessed, reverse=True)
        return [s.to_summary() for s in active]

    def get_session(self, session_id: str) -> Session | None:
        """Get a session by ID, or None if not found/expired."""
        session = self.sessions.get(session_id)
        if session is None and self.conn:
            row = self.conn.execute(
                "SELECT * FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if row:
                session = Session(
                    session_id=row["session_id"],
                    title=row["title"],
                    created_at=datetime.fromisoformat(row["created_at"]),
                    last_accessed=datetime.fromisoformat(row["last_accessed"]),
                    messages=json.loads(row["messages"]),
                )
                self.sessions[session_id] = session

        if session is None:
            return None
        if self._is_expired(session):
            self.delete_session(session_id)
            return None
        return session

    def delete_session(self, session_id: str) -> bool:
        """Delete a session. Returns True if found."""
        session = self.sessions.pop(session_id, None)
        if self.conn:
            self.conn.execute(
                "DELETE FROM sessions WHERE session_id = ?", (session_id,)
            )
            self.conn.commit()
        if session:
            logger.info(f"Session deleted: {session_id}")
            return True
        return False

    def _is_expired(self, session: Session) -> bool:
        return datetime.now() - session.last_accessed > self.ttl

    async def cleanup_expired_sessions(self) -> None:
        """Background task to clean expired sessions."""
        logger.info("Session cleanup task started")
        while True:
            try:
                await asyncio.sleep(self.cleanup_interval.total_seconds())
                expired = [
                    sid
                    for sid, s in list(self.sessions.items())
                    if self._is_expired(s)
                ]
                for sid in expired:
                    self.delete_session(sid)
                if self.conn:
                    cutoff = (datetime.now() - self.ttl).isoformat()
                    self.conn.execute(
                        "DELETE FROM sessions WHERE last_accessed < ?",
                        (cutoff,),
                    )
                    self.conn.commit()
                if expired:
                    logger.info(f"Cleaned up {len(expired)} expired sessions")
            except asyncio.CancelledError:
                logger.info("Session cleanup task cancelled")
                break
            except Exception as e:
                logger.error(f"Cleanup error: {e}", exc_info=True)

    def start_cleanup_task(self) -> asyncio.Task:
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(
                self.cleanup_expired_sessions()
            )
        return self._cleanup_task

    def stop_cleanup_task(self) -> None:
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
