"""Fixed-window rate limiter — the core check logic.

``FixedWindowRateLimiter`` is the canonical fixed-window implementation.
It is storage-agnostic (any ``RateLimitStore``) and stateless beyond the
store reference.

The limiter answers::

    result = limiter.check(key="user:42", limit=RateLimit(100, 60))
    if result.allowed:
        ...
"""

from __future__ import annotations

import time
from typing import Optional

from betrayer.ratelimit.limit import RateLimit, RateLimitResult
from betrayer.ratelimit.store import RateLimitStore


class FixedWindowRateLimiter:
    """Fixed-window rate limiter.

    Usage::

        store = MemoryRateLimitStore()
        limiter = FixedWindowRateLimiter(store=store)

        result = limiter.check(key="user:42", limit=RateLimit(100, 60))
        # result.allowed  -> True/False
        # result.remaining -> remaining count
        # result.reset_at -> unix timestamp when the window resets
    """

    def __init__(self, store: RateLimitStore) -> None:
        self._store = store

    @property
    def store(self) -> RateLimitStore:
        """The underlying store (read-only access)."""
        return self._store

    def check(
        self,
        key: str,
        limit: RateLimit,
        *,
        amount: int = 1,
    ) -> RateLimitResult:
        """Check if ``key`` is allowed under ``limit``.

        Increments the counter and returns the check result.  When
        discouraged by the architecture, use the middleware instead
        of calling ``check()`` directly.

        Parameters
        ----------
        key:
            Rate limit key (e.g. ``"user:42"``, ``"ip:1.2.3.4"``).
        limit:
            The ``RateLimit`` configuration (limit + window).
        amount:
            Increment amount (default 1).

        Returns
        -------
        A ``RateLimitResult`` with ``allowed``, ``remaining``,
        ``reset_at``, etc.
        """
        count, window_start = self._store.increment(key, limit.window, amount=amount)
        remaining = max(0, limit.limit - count)
        allowed = count <= limit.limit
        reset_at = window_start + limit.window
        return RateLimitResult(
            allowed=bool(allowed),
            limit=limit.limit,
            remaining=int(remaining),
            reset_at=float(reset_at),
            key=key,
        )

    def peek(
        self,
        key: str,
        limit: RateLimit,
    ) -> RateLimitResult:
        """Read the current state for ``key`` without incrementing.

        Useful for building status endpoints without consuming a slot.
        """
        count, window_start = self._store.get(key, limit.window)
        remaining = max(0, limit.limit - count)
        allowed = count < limit.limit
        reset_at = window_start + limit.window
        return RateLimitResult(
            allowed=bool(allowed),
            limit=limit.limit,
            remaining=int(remaining),
            reset_at=float(reset_at),
            key=key,
        )

    def reset(self, key: str) -> None:
        """Reset all counters for ``key`` (used by tests/tooling)."""
        self._store.reset(key)

    # -- introspection ------------------------------------------------
    def describe(self) -> dict:
        return {
            "type": "fixed_window",
            "store": self._store.inspect(),
        }

    def to_dict(self) -> dict:
        return self.describe()

    def __repr__(self) -> str:
        return f"<FixedWindowRateLimiter store={type(self._store).__name__}>"