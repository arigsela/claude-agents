"""
Tests for SessionManager
"""

import pytest
import asyncio
import sys
from pathlib import Path
from datetime import datetime, timedelta

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.api.session_manager import SessionManager, Session


@pytest.fixture
def session_manager():
    """Create a SessionManager instance for testing"""
    return SessionManager(ttl_minutes=1, max_sessions_per_user=3)


def test_create_session(session_manager):
    """Test session creation"""
    session = session_manager.create_session(
        user_id="test-user",
        metadata={"team": "devops"}
    )

    assert session.session_id is not None
    assert session.user_id == "test-user"
    assert session.metadata["team"] == "devops"
    assert len(session.conversation_history) == 0


def test_get_session(session_manager):
    """Test session retrieval"""
    # Create a session
    created = session_manager.create_session("test-user")

    # Retrieve it
    retrieved = session_manager.get_session(created.session_id)

    assert retrieved is not None
    assert retrieved.session_id == created.session_id
    assert retrieved.user_id == "test-user"


def test_get_nonexistent_session(session_manager):
    """Test retrieving non-existent session"""
    session = session_manager.get_session("nonexistent-id")
    assert session is None


def test_update_session_conversation(session_manager):
    """Test updating session with conversation entry"""
    session = session_manager.create_session("test-user")

    # Add conversation entry
    entry = {
        "query": "Test query",
        "response": "Test response"
    }
    updated = session_manager.update_session(
        session.session_id,
        conversation_entry=entry
    )

    assert updated is True

    # Retrieve and verify
    retrieved = session_manager.get_session(session.session_id)
    assert len(retrieved.conversation_history) == 1
    assert retrieved.conversation_history[0] == entry


def test_update_session_metadata(session_manager):
    """Test updating session metadata"""
    session = session_manager.create_session("test-user")

    # Update metadata
    updated = session_manager.update_session(
        session.session_id,
        metadata_update={"new_field": "new_value"}
    )

    assert updated is True

    # Retrieve and verify
    retrieved = session_manager.get_session(session.session_id)
    assert retrieved.metadata["new_field"] == "new_value"


def test_delete_session(session_manager):
    """Test session deletion"""
    session = session_manager.create_session("test-user")

    # Delete it
    deleted = session_manager.delete_session(session.session_id)
    assert deleted is True

    # Verify it's gone
    retrieved = session_manager.get_session(session.session_id)
    assert retrieved is None


def test_delete_nonexistent_session(session_manager):
    """Test deleting non-existent session"""
    deleted = session_manager.delete_session("nonexistent-id")
    assert deleted is False


def test_max_sessions_per_user(session_manager):
    """Test max sessions per user enforcement"""
    user_id = "test-user"

    # Create max sessions (3)
    sessions = []
    for i in range(3):
        session = session_manager.create_session(user_id)
        sessions.append(session)

    # Creating 4th session should remove the oldest
    new_session = session_manager.create_session(user_id)

    # First session should be deleted
    first_session = session_manager.get_session(sessions[0].session_id)
    assert first_session is None

    # New session should exist
    retrieved = session_manager.get_session(new_session.session_id)
    assert retrieved is not None


def test_list_user_sessions(session_manager):
    """Test listing user sessions"""
    user_id = "test-user"

    # Create multiple sessions
    session1 = session_manager.create_session(user_id)
    session2 = session_manager.create_session(user_id)

    # List sessions
    sessions = session_manager.list_user_sessions(user_id)

    assert len(sessions) == 2
    session_ids = [s.session_id for s in sessions]
    assert session1.session_id in session_ids
    assert session2.session_id in session_ids


def test_get_stats(session_manager):
    """Test session statistics"""
    # Create sessions for different users
    session_manager.create_session("user1")
    session_manager.create_session("user2")
    session_manager.create_session("user2")

    stats = session_manager.get_stats()

    assert stats["total_sessions"] == 3
    assert stats["active_sessions"] >= 0
    assert stats["total_users"] == 2
    assert stats["max_sessions_per_user"] == 3


@pytest.mark.asyncio
async def test_session_expiration():
    """Test session expiration"""
    # Create manager with very short TTL
    manager = SessionManager(ttl_minutes=0.01)  # ~0.6 seconds

    # Create session
    session = manager.create_session("test-user")

    # Wait for expiration
    await asyncio.sleep(1)

    # Session should be expired
    retrieved = manager.get_session(session.session_id)
    assert retrieved is None


@pytest.mark.asyncio
async def test_cleanup_task():
    """Test automatic cleanup task"""
    # Create manager with short TTL and cleanup interval
    manager = SessionManager(ttl_minutes=0.01, cleanup_interval_minutes=0.01)

    # Create sessions
    session1 = manager.create_session("user1")
    session2 = manager.create_session("user2")

    # Start cleanup task
    cleanup_task = manager.start_cleanup_task()

    # Wait for sessions to expire and cleanup to run
    await asyncio.sleep(2)

    # Stop cleanup task
    manager.stop_cleanup_task()
    await cleanup_task

    # Sessions should be cleaned up
    stats = manager.get_stats()
    assert stats["active_sessions"] == 0


def test_session_to_dict(session_manager):
    """Test session serialization to dictionary"""
    session = session_manager.create_session(
        "test-user",
        metadata={"test": "data"}
    )

    # Add conversation entry
    session_manager.update_session(
        session.session_id,
        conversation_entry={"query": "test", "response": "test"}
    )

    # Retrieve and convert to dict
    retrieved = session_manager.get_session(session.session_id)
    session_dict = retrieved.to_dict()

    assert "session_id" in session_dict
    assert "user_id" in session_dict
    assert "created_at" in session_dict
    assert "last_accessed" in session_dict
    assert "metadata" in session_dict
    assert "conversation_history" in session_dict
    assert "message_count" in session_dict
    assert session_dict["message_count"] == 1
