"""Authentication utilities for JWT and API key auth.

Provides JWT token creation/verification and a unified FastAPI
dependency that accepts either JWT Bearer tokens or API keys.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import HTTPException, Request

from shared.config import API_KEYS, JWT_EXPIRY_HOURS, JWT_SECRET
from shared.logging_config import setup_logging

logger = setup_logging("auth")


@dataclass
class AuthInfo:
    """Result of authentication — identifies the caller."""

    user_id: str | None  # None for API_KEY auth (service-to-service)
    username: str | None  # None for API_KEY auth


def create_jwt(user_id: str, username: str) -> str:
    """Create a signed JWT token for a user."""
    payload = {
        "sub": user_id,
        "username": username,
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRY_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def verify_jwt(token: str) -> dict:
    """Verify and decode a JWT token.

    Returns the payload dict with 'sub' (user_id) and 'username'.
    Raises HTTPException on invalid/expired tokens.
    """
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


def verify_auth(request: Request) -> AuthInfo:
    """Unified auth dependency: accepts JWT Bearer token OR API key.

    - JWT Bearer: returns AuthInfo with user_id and username
    - API_KEY (X-API-Key or Bearer): returns AuthInfo with user_id=None
    - No auth configured (dev mode): returns AuthInfo with user_id=None
    """
    auth_header = request.headers.get("Authorization", "")
    api_key_header = request.headers.get("X-API-Key", "")

    # Check X-API-Key first to establish service-level trust
    api_key_valid = bool(api_key_header and API_KEYS and api_key_header in API_KEYS)

    # Try JWT Bearer token (preferred — gives user scoping)
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        # Check if Bearer value is an API key
        if API_KEYS and token in API_KEYS:
            return AuthInfo(user_id=None, username=None)
        # Try JWT decode
        try:
            payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
            return AuthInfo(
                user_id=payload.get("sub"),
                username=payload.get("username"),
            )
        except jwt.InvalidTokenError:
            # JWT invalid but API_KEY is valid — allow as service call
            if api_key_valid:
                return AuthInfo(user_id=None, username=None)

    # Valid API key without JWT
    if api_key_valid:
        return AuthInfo(user_id=None, username=None)

    # Invalid API key provided
    if api_key_header:
        raise HTTPException(status_code=401, detail="Invalid API key")

    # No auth provided
    if not API_KEYS:
        return AuthInfo(user_id=None, username=None)  # Dev mode

    raise HTTPException(status_code=401, detail="Authentication required")
