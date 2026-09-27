"""Betrayer Rate Limiting — canonical fixed-window rate limiting API.

Rate limiting answers one question: *"may this request proceed, or has it
exceeded the allowed number of requests in the current time window?"*

The API is provider/storage agnostic and integrates into the existing web
middleware pipeline without creating a second middleware or error subsystem.

Usage::

    from betrayer.ratelimit import (
        RateLimit,
        FixedWindowRateLimiter,
        MemoryRateLimitStore,
        RateLimitMiddleware,
    )

    # Middleware (added to the web middleware registry)
    middleware = RateLimitMiddleware(store=MemoryRateLimitStore())

    # Explicit check anywhere
    result = middleware.check(key="user:42", limit=RateLimit(100, 60))
    if result.allowed:
        ...
"""

from __future__ import annotations

from betrayer.ratelimit.limit import RateLimit, RateLimitResult, TooManyRequestsError
from betrayer.ratelimit.limiter import FixedWindowRateLimiter
from betrayer.ratelimit.store import (
    RateLimitStore,
    MemoryRateLimitStore,
)
from betrayer.ratelimit.middleware import RateLimitMiddleware

__all__ = [
    "RateLimit",
    "RateLimitResult",
    "RateLimitStore",
    "MemoryRateLimitStore",
    "FixedWindowRateLimiter",
    "RateLimitMiddleware",
    "TooManyRequestsError",
]