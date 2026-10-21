"""Unit tests for UserManager."""

import os
import tempfile

import pytest


@pytest.fixture
def user_manager(tmp_path):
    """Create a UserManager with a temporary database."""
    db_path = str(tmp_path / "test_users.db")
    from orchestrator.user_manager import UserManager

    return UserManager(db_path=db_path)


class TestUserManager:
    def test_create_user(self, user_manager):
        user = user_manager.create_user("testuser", "password123")
        assert user.username == "testuser"
        assert user.user_id is not None

    def test_create_duplicate_username_raises(self, user_manager):
        user_manager.create_user("testuser", "password123")
        with pytest.raises(ValueError, match="already taken"):
            user_manager.create_user("testuser", "different_pass")

    def test_create_user_short_username_raises(self, user_manager):
        with pytest.raises(ValueError, match="at least 3"):
            user_manager.create_user("ab", "password123")

    def test_create_user_short_password_raises(self, user_manager):
        with pytest.raises(ValueError, match="at least 6"):
            user_manager.create_user("testuser", "short")

    def test_create_user_empty_fields_raises(self, user_manager):
        with pytest.raises(ValueError, match="required"):
            user_manager.create_user("", "password123")
        with pytest.raises(ValueError, match="required"):
            user_manager.create_user("testuser", "")

    def test_authenticate_correct_password(self, user_manager):
        user_manager.create_user("testuser", "password123")
        user = user_manager.authenticate("testuser", "password123")
        assert user is not None
        assert user.username == "testuser"

    def test_authenticate_wrong_password(self, user_manager):
        user_manager.create_user("testuser", "password123")
        user = user_manager.authenticate("testuser", "wrongpassword")
        assert user is None

    def test_authenticate_nonexistent_user(self, user_manager):
        user = user_manager.authenticate("nobody", "password123")
        assert user is None

    def test_get_user(self, user_manager):
        created = user_manager.create_user("testuser", "password123")
        fetched = user_manager.get_user(created.user_id)
        assert fetched is not None
        assert fetched.username == "testuser"
        assert fetched.user_id == created.user_id

    def test_get_user_not_found(self, user_manager):
        user = user_manager.get_user("nonexistent-id")
        assert user is None

    def test_list_users(self, user_manager):
        user_manager.create_user("alice", "password123")
        user_manager.create_user("bob", "password456")
        users = user_manager.list_users()
        assert len(users) == 2
        usernames = [u["username"] for u in users]
        assert "alice" in usernames
        assert "bob" in usernames

    def test_password_not_in_list_users(self, user_manager):
        user_manager.create_user("alice", "password123")
        users = user_manager.list_users()
        assert "password_hash" not in users[0]

    def test_user_to_dict(self, user_manager):
        user = user_manager.create_user("testuser", "password123")
        d = user.to_dict()
        assert d["username"] == "testuser"
        assert "user_id" in d
        assert "created_at" in d
