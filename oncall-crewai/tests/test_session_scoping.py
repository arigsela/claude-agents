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


class TestTTLZeroNeverExpire:
    """Test that TTL=0 means sessions never expire."""

    @pytest.fixture
    def immortal_mgr(self, tmp_path):
        from orchestrator.session_manager import SessionManager

        return SessionManager(
            db_path=str(tmp_path / "immortal.db"),
            ttl_hours=0,
            max_sessions=500,
        )

    def test_session_never_expires(self, immortal_mgr):
        """Sessions should never be considered expired when TTL=0."""
        from datetime import datetime, timedelta

        session = immortal_mgr.get_or_create_session("s1", user_id="alice")
        # Manually set last_accessed to 30 days ago
        session.last_accessed = datetime.now() - timedelta(days=30)
        assert not immortal_mgr._is_expired(session)

    def test_load_from_db_preserves_old_sessions(self, tmp_path):
        """Sessions from DB should survive reload when TTL=0."""
        from orchestrator.session_manager import SessionManager

        db_path = str(tmp_path / "persist.db")

        # Create a session and add messages
        mgr1 = SessionManager(db_path=db_path, ttl_hours=0, max_sessions=500)
        mgr1.append_messages("s1", "hello", "hi", user_id="alice")
        del mgr1

        # Reload — session should still be there
        mgr2 = SessionManager(db_path=db_path, ttl_hours=0, max_sessions=500)
        session = mgr2.get_session("s1", user_id="alice")
        assert session is not None
        assert len(session.messages) == 2

    def test_cleanup_skips_when_ttl_zero(self, immortal_mgr):
        """_is_expired should return False for all sessions when TTL=0."""
        from datetime import datetime, timedelta

        immortal_mgr.get_or_create_session("s1")
        session = immortal_mgr.sessions["s1"]
        session.last_accessed = datetime.now() - timedelta(days=365)

        expired = [
            sid for sid, s in immortal_mgr.sessions.items()
            if immortal_mgr._is_expired(s)
        ]
        assert len(expired) == 0

    def test_ttl_nonzero_still_expires(self, tmp_path):
        """Verify TTL > 0 still expires normally (regression check)."""
        from datetime import datetime, timedelta

        from orchestrator.session_manager import SessionManager

        mgr = SessionManager(
            db_path=str(tmp_path / "expiring.db"),
            ttl_hours=1,
            max_sessions=50,
        )
        session = mgr.get_or_create_session("s1")
        session.last_accessed = datetime.now() - timedelta(hours=2)
        assert mgr._is_expired(session)


class TestBuildConversationContext:
    """Test SessionManager.build_conversation_context."""

    @pytest.fixture
    def mgr(self, tmp_path):
        from orchestrator.session_manager import SessionManager

        return SessionManager(
            db_path=str(tmp_path / "ctx.db"),
            ttl_hours=0,
            max_sessions=500,
        )

    def test_returns_empty_for_no_session(self, mgr):
        result = mgr.build_conversation_context("nonexistent")
        assert result == ""

    def test_returns_empty_for_no_messages(self, mgr):
        mgr.get_or_create_session("s1")
        result = mgr.build_conversation_context("s1")
        assert result == ""

    def test_builds_context_from_messages(self, mgr):
        mgr.append_messages("s1", "Hello", "Hi there")
        result = mgr.build_conversation_context("s1")
        assert "CONVERSATION HISTORY" in result
        assert "USER: Hello" in result
        assert "ASSISTANT: Hi there" in result

    def test_truncates_long_assistant_messages(self, mgr):
        mgr.append_messages("s1", "short", "A" * 1000)
        result = mgr.build_conversation_context("s1")
        assert "[truncated]" in result

    def test_respects_max_turns(self, mgr):
        for i in range(10):
            mgr.append_messages("s1", f"q{i}", f"a{i}")
        result = mgr.build_conversation_context("s1", max_turns=2)
        # Should only have last 2 exchanges (4 messages)
        assert "q8" in result
        assert "q9" in result
        assert "q0" not in result

    def test_respects_user_ownership(self, mgr):
        mgr.append_messages("s1", "secret", "reply", user_id="alice")
        # Bob should get empty context
        result = mgr.build_conversation_context("s1", user_id="bob")
        assert result == ""
        # Alice should get context
        result = mgr.build_conversation_context("s1", user_id="alice")
        assert "secret" in result

    def test_handles_exception_gracefully(self, mgr):
        # Force an error by closing the DB connection
        mgr.conn.close()
        mgr.conn = None
        mgr.sessions.clear()
        result = mgr.build_conversation_context("s1")
        assert result == ""


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
