"""
Rate limiting using SlowAPI.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from fastapi import Request, Response
from typing import Callable

from app.core.settings import settings
from app.core.exceptions import RateLimitExceededError


def get_user_id(request: Request) -> str:
    """
    Get user ID from request for rate limiting.
    Falls back to IP address if user is not authenticated.
    """
    # Try to get user ID from request state (set by auth middleware)
    user_id = getattr(request.state, "user_id", None)
    if user_id:
        return f"user:{user_id}"

    # Fall back to IP address
    return get_remote_address(request)


# Create limiter instance
limiter = Limiter(
    key_func=get_user_id,
    storage_uri=settings.get_redis_url() if settings.rate_limit_enabled else "memory://",
    default_limits=[f"{settings.rate_limit_per_minute}/minute"] if settings.rate_limit_enabled else [],
    enabled=settings.rate_limit_enabled,
)


def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> Response:
    """
    Custom handler for rate limit exceeded errors.
    """
    raise RateLimitExceededError(
        detail=f"Rate limit exceeded: {exc.detail}"
    )


# Decorator for custom rate limits per endpoint
def rate_limit(limit: str):
    """
    Decorator to apply custom rate limit to an endpoint.

    Usage:
        @rate_limit("5/minute")
        async def my_endpoint():
            ...
    """
    def decorator(func: Callable):
        return limiter.limit(limit)(func)
    return decorator
