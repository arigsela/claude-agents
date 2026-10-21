"""
API Middleware for authentication and rate limiting
"""

import base64
import hashlib
import hmac
import logging
import os
import time

from fastapi import Header, HTTPException, Request
from fastapi.security import HTTPBearer
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

# Initialize rate limiter
limiter = Limiter(key_func=get_remote_address)

# Security scheme for API key
security = HTTPBearer(auto_error=False)


def validate_api_key(api_key: str | None) -> bool:
    """
    Validate API key against configured keys.

    Args:
        api_key: API key from request header

    Returns:
        True if valid, False otherwise
    """
    # Get configured API keys (comma-separated)
    valid_keys = os.getenv("API_KEYS", "").split(",")
    valid_keys = [k.strip() for k in valid_keys if k.strip()]

    # If no keys configured, accept all requests (dev mode)
    if not valid_keys:
        logger.warning("No API_KEYS configured - authentication disabled (development mode)")
        return True

    # Check if provided key is valid
    if api_key and api_key in valid_keys:
        return True

    logger.warning("Invalid API key attempted")
    return False


async def verify_api_key(x_api_key: str | None = Header(None)):
    """
    FastAPI dependency for API key verification.

    Args:
        x_api_key: API key from X-API-Key header

    Raises:
        HTTPException: 401 if API key is invalid or missing
    """
    if not validate_api_key(x_api_key):
        raise HTTPException(
            status_code=401, detail="Invalid or missing API key. Include X-API-Key header."
        )
    return x_api_key


def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """
    Custom handler for rate limit exceeded errors.

    Args:
        request: The request that exceeded rate limit
        exc: The RateLimitExceeded exception

    Returns:
        JSONResponse with rate limit error details
    """
    logger.warning(f"Rate limit exceeded for {request.client.host}")

    return JSONResponse(
        status_code=429,
        content={
            "status": "error",
            "error": "RateLimitExceeded",
            "message": "Too many requests. Please slow down.",
            "detail": str(exc),
        },
        headers={"Retry-After": "60"},  # Suggest retry after 60 seconds
    )


def get_rate_limit() -> str:
    """
    Get rate limit based on authentication status.

    Returns:
        Rate limit string (e.g., "10/minute")
    """
    # Check if request is authenticated
    # This is a simplified version - in production, you'd check actual auth status
    os.getenv("RATE_LIMIT_AUTHENTICATED", "60")
    unauthenticated_limit = os.getenv("RATE_LIMIT_UNAUTHENTICATED", "10")

    # For now, return unauthenticated limit
    # In a real implementation, this would check the request context
    return f"{unauthenticated_limit}/minute"


# Custom key function that considers API key for rate limiting
def get_rate_limit_key(request: Request) -> str:
    """
    Generate rate limit key based on API key or IP address.

    Authenticated users get their own rate limit bucket based on API key.
    Unauthenticated users share a bucket based on IP address.

    Args:
        request: FastAPI request object

    Returns:
        Rate limit key string
    """
    api_key = request.headers.get("x-api-key")

    if api_key and validate_api_key(api_key):
        # Use API key for authenticated requests
        return f"apikey:{api_key[:8]}"  # Use first 8 chars for privacy
    else:
        # Use IP address for unauthenticated requests
        return f"ip:{get_remote_address(request)}"


# Rate limiter with custom key function
limiter_with_key = Limiter(key_func=get_rate_limit_key)


def validate_teams_hmac(body: bytes, auth_header: str, secret: str) -> bool:
    """
    Validate HMAC-SHA256 signature from Microsoft Teams Outgoing Webhook.

    Teams sends:
    - Authorization header: "HMAC {base64_signature}"
    - Secret from Teams is base64-encoded

    Args:
        body: Raw request body bytes
        auth_header: Authorization header value (e.g., "HMAC abc123...")
        secret: Base64-encoded HMAC secret from Teams webhook configuration

    Returns:
        True if signature is valid, False otherwise
    """
    if not secret:
        logger.error("TEAMS_WEBHOOK_SECRET not configured")
        return False

    if not auth_header or not auth_header.startswith("HMAC "):
        logger.warning("Missing or invalid Authorization header for Teams webhook")
        return False

    # Extract signature from header (remove "HMAC " prefix)
    provided_signature = auth_header[5:]

    # Decode the secret (Teams provides it base64-encoded)
    try:
        secret_bytes = base64.b64decode(secret)
    except Exception as e:
        logger.error(f"Failed to decode TEAMS_WEBHOOK_SECRET: {e}")
        return False

    # Compute HMAC-SHA256
    computed_hmac = hmac.new(secret_bytes, body, hashlib.sha256)
    computed_signature = base64.b64encode(computed_hmac.digest()).decode()

    # Use constant-time comparison to prevent timing attacks
    is_valid = hmac.compare_digest(computed_signature, provided_signature)

    if not is_valid:
        logger.warning("Invalid HMAC signature for Teams webhook")

    return is_valid


def validate_slack_signature(
    body: bytes, timestamp: str, signature: str, signing_secret: str
) -> bool:
    """
    Validate Slack request signature using HMAC-SHA256.

    Slack sends:
    - X-Slack-Request-Timestamp header
    - X-Slack-Signature header: "v0={hex_digest}"
    - Signing secret from app's "Basic Information" page

    The signature base string is: "v0:{timestamp}:{body}"

    Args:
        body: Raw request body bytes
        timestamp: X-Slack-Request-Timestamp header value
        signature: X-Slack-Signature header value (e.g., "v0=abc123...")
        signing_secret: Slack app signing secret

    Returns:
        True if signature is valid, False otherwise
    """
    if not signing_secret:
        logger.error("SLACK_SIGNING_SECRET not configured")
        return False

    if not signature or not signature.startswith("v0="):
        logger.warning("Missing or invalid X-Slack-Signature header")
        return False

    if not timestamp:
        logger.warning("Missing X-Slack-Request-Timestamp header")
        return False

    # Reject requests older than 5 minutes to prevent replay attacks
    try:
        request_timestamp = int(timestamp)
    except ValueError:
        logger.warning("Invalid timestamp format in Slack request")
        return False

    if abs(time.time() - request_timestamp) > 300:
        logger.warning("Slack request timestamp too old (possible replay attack)")
        return False

    # Compute expected signature: v0:timestamp:body
    sig_basestring = f"v0:{timestamp}:{body.decode('utf-8')}"
    computed_hash = hmac.new(
        signing_secret.encode("utf-8"),
        sig_basestring.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    computed_signature = f"v0={computed_hash}"

    # Use constant-time comparison to prevent timing attacks
    is_valid = hmac.compare_digest(computed_signature, signature)

    if not is_valid:
        logger.warning("Invalid Slack request signature")

    return is_valid
