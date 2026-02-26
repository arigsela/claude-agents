"""User Manager for password-based authentication.

SQLite-backed user storage with bcrypt password hashing.
Co-located on the same PVC as sessions DB.
"""

import os
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime

import bcrypt

from shared.config import USERS_DB_PATH
from shared.logging_config import setup_logging

logger = setup_logging("user-manager")


@dataclass
class User:
    user_id: str
    username: str
    created_at: datetime

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "username": self.username,
            "created_at": self.created_at.isoformat(),
        }


class UserManager:
    """Manages user accounts with SQLite persistence and bcrypt hashing."""

    def __init__(self, db_path: str = USERS_DB_PATH):
        self.db_path = db_path
        self.conn: sqlite3.Connection | None = None
        self._init_db()
        logger.info(f"UserManager initialized: DB={db_path}")

    def _init_db(self) -> None:
        db_dir = os.path.dirname(self.db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_users_username
                ON users(username);
        """)
        self.conn.commit()

    def create_user(self, username: str, password: str) -> User:
        """Create a new user. Raises ValueError if username taken."""
        if not username or not password:
            raise ValueError("Username and password are required")
        if len(username) < 3:
            raise ValueError("Username must be at least 3 characters")
        if len(password) < 6:
            raise ValueError("Password must be at least 6 characters")

        user_id = str(uuid.uuid4())
        password_hash = bcrypt.hashpw(
            password.encode("utf-8"), bcrypt.gensalt()
        ).decode("utf-8")
        now = datetime.now()

        try:
            self.conn.execute(
                "INSERT INTO users (user_id, username, password_hash, created_at) VALUES (?, ?, ?, ?)",
                (user_id, username, password_hash, now.isoformat()),
            )
            self.conn.commit()
        except sqlite3.IntegrityError:
            raise ValueError(f"Username '{username}' is already taken")

        logger.info(f"User created: {username} ({user_id})")
        return User(user_id=user_id, username=username, created_at=now)

    def authenticate(self, username: str, password: str) -> User | None:
        """Authenticate a user. Returns User if valid, None otherwise."""
        row = self.conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()
        if not row:
            return None

        if not bcrypt.checkpw(
            password.encode("utf-8"), row["password_hash"].encode("utf-8")
        ):
            return None

        return User(
            user_id=row["user_id"],
            username=row["username"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def get_user(self, user_id: str) -> User | None:
        """Get a user by ID."""
        row = self.conn.execute(
            "SELECT * FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
        if not row:
            return None
        return User(
            user_id=row["user_id"],
            username=row["username"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def list_users(self) -> list[dict]:
        """List all users (without password hashes)."""
        rows = self.conn.execute(
            "SELECT user_id, username, created_at FROM users ORDER BY created_at"
        ).fetchall()
        return [
            {
                "user_id": row["user_id"],
                "username": row["username"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]
