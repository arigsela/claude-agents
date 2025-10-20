"""
API Middleware for authentication and rate limiting
"""

import os
import logging
from typing import Optional
from fastapi import Request, HTTPException, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

# Initialize rate limiter
limiter = Limiter(key_func=get_remote_address)

# Security scheme for API key
security = HTTPBearer(auto_error=False)


def validate_api_key(api_key: Optional[str]) -> bool:
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

    logger.warning(f"Invalid API key attempted")
    return False


async def verify_api_key(x_api_key: Optional[str] = Header(None)):
    """
    FastAPI dependency for API key verification.

    Args:
        x_api_key: API key from X-API-Key header

    Raises:
        HTTPException: 401 if API key is invalid or missing
    """
    if not validate_api_key(x_api_key):
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key. Include X-API-Key header."
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
            "detail": str(exc)
        },
        headers={
            "Retry-After": "60"  # Suggest retry after 60 seconds
        }
    )


def get_rate_limit() -> str:
    """
    Get rate limit based on authentication status.

    Returns:
        Rate limit string (e.g., "10/minute")
    """
    # Check if request is authenticated
    # This is a simplified version - in production, you'd check actual auth status
    authenticated_limit = os.getenv("RATE_LIMIT_AUTHENTICATED", "60")
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
