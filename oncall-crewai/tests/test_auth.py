"""Unit tests for auth module (JWT + API key)."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import jwt as pyjwt
import pytest


@pytest.fixture(autouse=True)
def mock_auth_config(monkeypatch):
    """Set auth config for all tests."""
    monkeypatch.setenv("JWT_SECRET", "test-jwt-secret")
    monkeypatch.setenv("JWT_EXPIRY_HOURS", "24")
    # Reload the config module to pick up env vars
    import shared.config as config_module

    monkeypatch.setattr(config_module, "JWT_SECRET", "test-jwt-secret")
    monkeypatch.setattr(config_module, "JWT_EXPIRY_HOURS", 24)


@pytest.fixture
def auth_module(mock_auth_config, monkeypatch):
    """Import auth module with mocked config."""
    import orchestrator.auth as auth_mod

    monkeypatch.setattr(auth_mod, "JWT_SECRET", "test-jwt-secret")
    monkeypatch.setattr(auth_mod, "JWT_EXPIRY_HOURS", 24)
    return auth_mod


class TestCreateJWT:
    def test_creates_valid_token(self, auth_module):
        token = auth_module.create_jwt("user-123", "alice")
        assert isinstance(token, str)
        assert len(token) > 0

    def test_token_contains_expected_claims(self, auth_module):
        token = auth_module.create_jwt("user-123", "alice")
        payload = pyjwt.decode(token, "test-jwt-secret", algorithms=["HS256"])
        assert payload["sub"] == "user-123"
        assert payload["username"] == "alice"
        assert "exp" in payload
        assert "iat" in payload


class TestVerifyJWT:
    def test_verify_valid_token(self, auth_module):
        token = auth_module.create_jwt("user-123", "alice")
        payload = auth_module.verify_jwt(token)
        assert payload["sub"] == "user-123"
        assert payload["username"] == "alice"

    def test_verify_expired_token_raises(self, auth_module, monkeypatch):
        from fastapi import HTTPException

        # Create token with negative expiry
        payload = {
            "sub": "user-123",
            "username": "alice",
            "iat": datetime.now(timezone.utc) - timedelta(hours=2),
            "exp": datetime.now(timezone.utc) - timedelta(hours=1),
        }
        token = pyjwt.encode(payload, "test-jwt-secret", algorithm="HS256")
        with pytest.raises(HTTPException) as exc_info:
            auth_module.verify_jwt(token)
        assert exc_info.value.status_code == 401
        assert "expired" in exc_info.value.detail.lower()

    def test_verify_invalid_token_raises(self, auth_module):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            auth_module.verify_jwt("not-a-valid-token")
        assert exc_info.value.status_code == 401

    def test_verify_wrong_secret_raises(self, auth_module):
        from fastapi import HTTPException

        payload = {
            "sub": "user-123",
            "username": "alice",
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        }
        token = pyjwt.encode(payload, "wrong-secret", algorithm="HS256")
        with pytest.raises(HTTPException):
            auth_module.verify_jwt(token)


class TestVerifyAuth:
    def _make_request(self, headers: dict) -> MagicMock:
        request = MagicMock()
        request.headers = headers
        return request

    def test_jwt_bearer_auth(self, auth_module, monkeypatch):
        monkeypatch.setattr(auth_module, "API_KEYS", [])
        token = auth_module.create_jwt("user-123", "alice")
        request = self._make_request({"Authorization": f"Bearer {token}", "X-API-Key": ""})
        result = auth_module.verify_auth(request)
        assert result.user_id == "user-123"
        assert result.username == "alice"

    def test_api_key_bearer_auth(self, auth_module, monkeypatch):
        monkeypatch.setattr(auth_module, "API_KEYS", ["test-api-key-1"])
        request = self._make_request(
            {"Authorization": "Bearer test-api-key-1", "X-API-Key": ""}
        )
        result = auth_module.verify_auth(request)
        assert result.user_id is None
        assert result.username is None

    def test_api_key_x_header(self, auth_module, monkeypatch):
        monkeypatch.setattr(auth_module, "API_KEYS", ["test-api-key-1"])
        request = self._make_request(
            {"Authorization": "", "X-API-Key": "test-api-key-1"}
        )
        result = auth_module.verify_auth(request)
        assert result.user_id is None

    def test_invalid_api_key_raises(self, auth_module, monkeypatch):
        from fastapi import HTTPException

        monkeypatch.setattr(auth_module, "API_KEYS", ["test-api-key-1"])
        request = self._make_request(
            {"Authorization": "", "X-API-Key": "wrong-key"}
        )
        with pytest.raises(HTTPException) as exc_info:
            auth_module.verify_auth(request)
        assert exc_info.value.status_code == 401

    def test_no_auth_with_keys_configured_raises(self, auth_module, monkeypatch):
        from fastapi import HTTPException

        monkeypatch.setattr(auth_module, "API_KEYS", ["test-api-key-1"])
        request = self._make_request({"Authorization": "", "X-API-Key": ""})
        with pytest.raises(HTTPException) as exc_info:
            auth_module.verify_auth(request)
        assert exc_info.value.status_code == 401

    def test_no_auth_dev_mode(self, auth_module, monkeypatch):
        monkeypatch.setattr(auth_module, "API_KEYS", [])
        request = self._make_request({"Authorization": "", "X-API-Key": ""})
        result = auth_module.verify_auth(request)
        assert result.user_id is None

    def test_jwt_preferred_over_api_key(self, auth_module, monkeypatch):
        """JWT token should be validated as JWT even when API keys are configured."""
        monkeypatch.setattr(auth_module, "API_KEYS", ["some-api-key"])
        token = auth_module.create_jwt("user-123", "alice")
        request = self._make_request({"Authorization": f"Bearer {token}", "X-API-Key": ""})
        result = auth_module.verify_auth(request)
        assert result.user_id == "user-123"
        assert result.username == "alice"
