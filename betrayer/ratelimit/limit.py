"""RateLimit configuration and result data classes.

RateLimit defines **how many** requests are allowed in **what period**
(e.g. ``100 requests / 60 seconds``).

RateLimitResult carries the outcome of a check with enough detail to build
response headers (``X-RateLimit-Limit``, ``X-RateLimit-Remaining``,
``X-RateLimit-Reset``).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class RateLimit:
    """Canonical rate limit configuration.

    ``limit`` is the maximum number of requests allowed within ``window``
    seconds.  Both must be >= 1; validation is explicit at construction time
    (raises ``ValueError`` with a clear message).

    Usage::

        RateLimit(limit=100, window=60)   # 100 requests / 60 seconds
        RateLimit(limit=10, window=1)     # 10 requests / second
    """

    limit: int
    window: int  # seconds

    def __post_init__(self) -> None:
        if not isinstance(self.limit, int) or self.limit < 1:
            raise ValueError(
                f"RateLimit.limit must be >= 1, got {self.limit!r}"
            )
        if not isinstance(self.window, int) or self.window < 1:
            raise ValueError(
                f"RateLimit.window must be >= 1, got {self.window!r}"
            )

    # -- introspection ------------------------------------------------
    def to_dict(self) -> dict:
        return {"limit": self.limit, "window": self.window}

    def __repr__(self) -> str:
        return f"RateLimit(limit={self.limit}, window={self.window})"


@dataclass(frozen=True)
class RateLimitResult:
    """Result of a rate limit check.

    Attributes
    ----------
    allowed:
        ``True`` when the request may proceed.
    limit:
        The configured limit (copied from ``RateLimit.limit``).
    remaining:
        How many requests are still allowed in the current window.
    reset_at:
        Unix timestamp (seconds since epoch) when the window resets.
        Callers may compute ``Retry-After`` as ``reset_at - time.time()``.
    key:
        The resolved key that was checked (for diagnostics).
    """

    allowed: bool
    limit: int
    remaining: int
    reset_at: float
    key: str

    # -- introspection ------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "allowed": self.allowed,
            "limit": self.limit,
            "remaining": self.remaining,
            "reset_at": self.reset_at,
            "key": self.key,
        }

    def __repr__(self) -> str:
        return (
            f"<RateLimitResult allowed={self.allowed} "
            f"{self.remaining}/{self.limit} reset_at={self.reset_at:.2f}>"
        )


class TooManyRequestsError(Exception):
    """Raised by explicit checks (not middleware) when the limit is exceeded.

    The middleware raises :class:`betrayer.web.exceptions.TooManyRequestsError`
    which produces the canonical HTTP 429 ``RATE_LIMIT_EXCEEDED`` response.
    This error is for non-middleware contexts where the caller wants to catch
    and handle the rejection themselves.
    """

    def __init__(
        self,
        key: str,
        limit: int,
        window: int,
        remaining: int,
        reset_at: float,
    ) -> None:
        self.key = key
        self.limit = limit
        self.window = window
        self.remaining = remaining
        self.reset_at = reset_at
        retry_after = max(0.0, reset_at - time.time())
        super().__init__(
            f"Rate limit exceeded for {key!r}: {limit} requests per "
            f"{window}s. Retry after {retry_after:.0f}s."
        )