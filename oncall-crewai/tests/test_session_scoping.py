"""Unit tests for SessionManager user scoping.

Tests user_id column migration, per-user session isolation,
and ownership verification without needing a2a-sdk.
"""

import pytest


@pytest.fixture
def session_mgr(tmp_path):
    """Create a SessionManager with a temporary database."""
    from orchestrator.session_manager import SessionManager

    return SessionManager(
        db_path=str(tmp_path / "test_sessions.db"),
        ttl_hours=24,
        max_sessions=50,
    )


class TestUserIdMigration:
    def test_user_id_column_exists(self, session_mgr):
        """user_id column should exist after initialization."""
        cols = [
            row[1]
            for row in session_mgr.conn.execute(
                "PRAGMA table_info(sessions)"
            ).fetchall()
        ]
        assert "user_id" in cols

    def test_new_session_has_user_id(self, session_mgr):
        session = session_mgr.get_or_create_session("s1", user_id="user-123")
        assert session.user_id == "user-123"

    def test_new_session_default_empty_user_id(self, session_mgr):
        session = session_mgr.get_or_create_session("s1")
        assert session.user_id == ""


class TestListSessionsByUser:
    def test_list_filters_by_user(self, session_mgr):
        session_mgr.get_or_create_session("s1", user_id="alice")
        session_mgr.append_messages("s1", "hi", "hello", user_id="alice")
        session_mgr.get_or_create_session("s2", user_id="bob")
        session_mgr.append_messages("s2", "hey", "yo", user_id="bob")

        alice_sessions = session_mgr.list_sessions(user_id="alice")
        assert len(alice_sessions) == 1
        assert alice_sessions[0]["session_id"] == "s1"

        bob_sessions = session_mgr.list_sessions(user_id="bob")
        assert len(bob_sessions) == 1
        assert bob_sessions[0]["session_id"] == "s2"

    def test_list_no_user_returns_all(self, session_mgr):
        """user_id=None (API_KEY auth) sees all sessions."""
        session_mgr.get_or_create_session("s1", user_id="alice")
        session_mgr.get_or_create_session("s2", user_id="bob")

        all_sessions = session_mgr.list_sessions(user_id=None)
        assert len(all_sessions) == 2


class TestGetSessionOwnership:
    def test_get_own_session(self, session_mgr):
        session_mgr.get_or_create_session("s1", user_id="alice")
        session = session_mgr.get_session("s1", user_id="alice")
        assert session is not None
        assert session.session_id == "s1"

    def test_get_other_users_session_returns_none(self, session_mgr):
        session_mgr.get_or_create_session("s1", user_id="alice")
        session = session_mgr.get_session("s1", user_id="bob")
        assert session is None

    def test_get_session_no_user_returns_any(self, session_mgr):
        """user_id=None sees any session (admin/API_KEY mode)."""
        session_mgr.get_or_create_session("s1", user_id="alice")
        session = session_mgr.get_session("s1", user_id=None)
        assert session is not None


class TestDeleteSessionOwnership:
    def test_delete_own_session(self, session_mgr):
        session_mgr.get_or_create_session("s1", user_id="alice")
        assert session_mgr.delete_session("s1", user_id="alice") is True
        assert session_mgr.get_session("s1") is None

    def test_delete_other_users_session_fails(self, session_mgr):
        session_mgr.get_or_create_session("s1", user_id="alice")
        assert session_mgr.delete_session("s1", user_id="bob") is False
        # Session should still exist
        assert session_mgr.get_session("s1", user_id="alice") is not None

    def test_delete_no_user_deletes_any(self, session_mgr):
        """user_id=None (admin) can delete any session."""
        session_mgr.get_or_create_session("s1", user_id="alice")
        assert session_mgr.delete_session("s1", user_id=None) is True


class TestAppendMessagesWithUser:
    def test_append_creates_session_with_user(self, session_mgr):
        session_mgr.append_messages("s1", "hello", "hi", user_id="alice")
        session = session_mgr.get_session("s1", user_id="alice")
        assert session is not None
        assert session.user_id == "alice"
        assert len(session.messages) == 2

    def test_append_existing_session_preserves_user(self, session_mgr):
        session_mgr.get_or_create_session("s1", user_id="alice")
        session_mgr.append_messages("s1", "hello", "hi", user_id="alice")
        session = session_mgr.get_session("s1", user_id="alice")
        assert session.user_id == "alice"


class TestBackwardsCompatibility:
    def test_legacy_sessions_have_empty_user_id(self, session_mgr):
        """Sessions created without user_id should default to empty string."""
        session_mgr.get_or_create_session("legacy-1")
        session = session_mgr.get_session("legacy-1")
        assert session.user_id == ""

    def test_legacy_sessions_visible_to_empty_user_id(self, session_mgr):
        """Empty user_id sessions are visible to user_id='' queries."""
        session_mgr.get_or_create_session("legacy-1")
        sessions = session_mgr.list_sessions(user_id="")
        assert len(sessions) == 1

    def test_legacy_sessions_visible_to_admin(self, session_mgr):
        """Admin (user_id=None) sees legacy sessions."""
        session_mgr.get_or_create_session("legacy-1")
        sessions = session_mgr.list_sessions(user_id=None)
        assert len(sessions) == 1
