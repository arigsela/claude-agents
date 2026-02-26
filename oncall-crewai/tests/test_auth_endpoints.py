"""Integration tests for auth endpoints and session scoping.

Tests register, login, /auth/me, and per-user session isolation.
Requires a2a-sdk installed (runs in Docker, may skip locally).
"""

import pytest
from httpx import ASGITransport, AsyncClient

a2a = pytest.importorskip("a2a", reason="a2a-sdk not installed (run in Docker)")


@pytest.fixture
def mock_env(monkeypatch):
    """Set required env vars."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setenv("K8S_AGENT_URL", "http://k8s-agent:8080")
    monkeypatch.setenv("GITHUB_AGENT_URL", "http://github-agent:8080")
    monkeypatch.setenv("ORCHESTRATOR_URL", "http://localhost:8000")
    monkeypatch.setenv("JWT_SECRET", "test-jwt-secret")


@pytest.fixture
def app(mock_env, tmp_path, monkeypatch):
    """Create the FastAPI app with temp DBs."""
    import orchestrator.auth as auth_module

    monkeypatch.setattr(auth_module, "API_KEYS", ["test-api-key"])
    monkeypatch.setattr(auth_module, "JWT_SECRET", "test-jwt-secret")
    monkeypatch.setattr(auth_module, "JWT_EXPIRY_HOURS", 24)

    import shared.config as config_module

    monkeypatch.setattr(config_module, "USERS_DB_PATH", str(tmp_path / "users.db"))
    monkeypatch.setattr(config_module, "SESSION_DB_PATH", str(tmp_path / "sessions.db"))

    # Patch module-level constants too
    import orchestrator.session_manager as sm_module

    monkeypatch.setattr(sm_module, "SESSION_DB_PATH", str(tmp_path / "sessions.db"))

    import orchestrator.user_manager as um_module

    monkeypatch.setattr(um_module, "USERS_DB_PATH", str(tmp_path / "users.db"))

    from orchestrator.main import create_app

    return create_app()


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ============================================================
# Registration
# ============================================================


class TestRegister:
    @pytest.mark.asyncio
    async def test_register_success(self, client):
        response = await client.post(
            "/auth/register",
            json={"username": "alice", "password": "password123"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["username"] == "alice"
        assert "token" in data
        assert "user_id" in data

    @pytest.mark.asyncio
    async def test_register_duplicate_username(self, client):
        await client.post(
            "/auth/register",
            json={"username": "alice", "password": "password123"},
        )
        response = await client.post(
            "/auth/register",
            json={"username": "alice", "password": "other_pass"},
        )
        assert response.status_code == 400
        assert "already taken" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_register_short_password(self, client):
        response = await client.post(
            "/auth/register",
            json={"username": "alice", "password": "short"},
        )
        assert response.status_code == 400


# ============================================================
# Login
# ============================================================


class TestLogin:
    @pytest.mark.asyncio
    async def test_login_success(self, client):
        await client.post(
            "/auth/register",
            json={"username": "alice", "password": "password123"},
        )
        response = await client.post(
            "/auth/login",
            json={"username": "alice", "password": "password123"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["username"] == "alice"
        assert "token" in data

    @pytest.mark.asyncio
    async def test_login_wrong_password(self, client):
        await client.post(
            "/auth/register",
            json={"username": "alice", "password": "password123"},
        )
        response = await client.post(
            "/auth/login",
            json={"username": "alice", "password": "wrong"},
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_login_nonexistent_user(self, client):
        response = await client.post(
            "/auth/login",
            json={"username": "nobody", "password": "password123"},
        )
        assert response.status_code == 401


# ============================================================
# /auth/me
# ============================================================


class TestAuthMe:
    @pytest.mark.asyncio
    async def test_me_with_jwt(self, client):
        reg = await client.post(
            "/auth/register",
            json={"username": "alice", "password": "password123"},
        )
        token = reg.json()["token"]
        response = await client.get(
            "/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["username"] == "alice"

    @pytest.mark.asyncio
    async def test_me_with_api_key_returns_401(self, client):
        """API key auth has no user, so /auth/me should reject it."""
        response = await client.get(
            "/auth/me",
            headers={"X-API-Key": "test-api-key"},
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_me_without_auth_returns_401(self, client):
        response = await client.get("/auth/me")
        assert response.status_code == 401


# ============================================================
# Session scoping
# ============================================================


class TestSessionScoping:
    async def _register_and_get_token(self, client, username, password="password123"):
        reg = await client.post(
            "/auth/register",
            json={"username": username, "password": password},
        )
        return reg.json()["token"]

    @pytest.mark.asyncio
    async def test_sessions_isolated_by_user(self, client):
        """Two users should only see their own sessions."""
        token_alice = await self._register_and_get_token(client, "alice")
        token_bob = await self._register_and_get_token(client, "bob")

        # Create a session for Alice by accessing a session endpoint
        mgr = client._transport.app.state.session_manager
        alice_user_id = (
            await client.get(
                "/auth/me", headers={"Authorization": f"Bearer {token_alice}"}
            )
        ).json()["user_id"]
        bob_user_id = (
            await client.get(
                "/auth/me", headers={"Authorization": f"Bearer {token_bob}"}
            )
        ).json()["user_id"]

        # Directly create sessions for each user
        mgr.get_or_create_session("alice-session-1", user_id=alice_user_id)
        mgr.append_messages("alice-session-1", "hello", "hi there", user_id=alice_user_id)
        mgr.get_or_create_session("bob-session-1", user_id=bob_user_id)
        mgr.append_messages("bob-session-1", "hey", "yo", user_id=bob_user_id)

        # Alice should only see her session
        alice_sessions = await client.get(
            "/sessions", headers={"Authorization": f"Bearer {token_alice}"}
        )
        assert alice_sessions.status_code == 200
        alice_list = alice_sessions.json()
        assert len(alice_list) == 1
        assert alice_list[0]["session_id"] == "alice-session-1"

        # Bob should only see his session
        bob_sessions = await client.get(
            "/sessions", headers={"Authorization": f"Bearer {token_bob}"}
        )
        bob_list = bob_sessions.json()
        assert len(bob_list) == 1
        assert bob_list[0]["session_id"] == "bob-session-1"

    @pytest.mark.asyncio
    async def test_user_cannot_get_other_users_session(self, client):
        token_alice = await self._register_and_get_token(client, "alice")
        token_bob = await self._register_and_get_token(client, "bob")

        alice_user_id = (
            await client.get(
                "/auth/me", headers={"Authorization": f"Bearer {token_alice}"}
            )
        ).json()["user_id"]

        mgr = client._transport.app.state.session_manager
        mgr.get_or_create_session("alice-private", user_id=alice_user_id)
        mgr.append_messages("alice-private", "secret", "reply", user_id=alice_user_id)

        # Bob tries to access Alice's session
        response = await client.get(
            "/sessions/alice-private",
            headers={"Authorization": f"Bearer {token_bob}"},
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_user_cannot_delete_other_users_session(self, client):
        token_alice = await self._register_and_get_token(client, "alice")
        token_bob = await self._register_and_get_token(client, "bob")

        alice_user_id = (
            await client.get(
                "/auth/me", headers={"Authorization": f"Bearer {token_alice}"}
            )
        ).json()["user_id"]

        mgr = client._transport.app.state.session_manager
        mgr.get_or_create_session("alice-session", user_id=alice_user_id)

        # Bob tries to delete Alice's session
        response = await client.delete(
            "/sessions/alice-session",
            headers={"Authorization": f"Bearer {token_bob}"},
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_api_key_sees_all_sessions(self, client):
        """API_KEY auth (no user_id) should see all sessions."""
        token_alice = await self._register_and_get_token(client, "alice")

        alice_user_id = (
            await client.get(
                "/auth/me", headers={"Authorization": f"Bearer {token_alice}"}
            )
        ).json()["user_id"]

        mgr = client._transport.app.state.session_manager
        mgr.get_or_create_session("session-1", user_id=alice_user_id)
        mgr.get_or_create_session("session-2", user_id="other-user")

        response = await client.get(
            "/sessions", headers={"X-API-Key": "test-api-key"}
        )
        assert response.status_code == 200
        sessions = response.json()
        assert len(sessions) == 2
