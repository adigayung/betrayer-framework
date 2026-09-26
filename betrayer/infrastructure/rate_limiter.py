"""Rate limiter abstraction with explicit configuration.

Design decisions:
- ``RateLimiter`` is the abstract interface; concrete backends implement it.
- ``InMemoryRateLimiter`` is the default backend — adequate for dev/testing/single-process.
- Backend can be replaced via Container registration (Redis, etc.).
- Supports window-based and token-bucket style limiting.
- No overlap with middleware/authentication rate limiting — this is a general mechanism.

Usage::

    from betrayer.infrastructure import InMemoryRateLimiter

    limiter = InMemoryRateLimiter(max_requests=10, window_seconds=60)
    if limiter.allowed("user:42"):
        # process request
        pass
    else:
        # rate limited
        pass
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, Optional


class RateLimitExceeded(Exception):
    """Raised when a rate limit is exceeded."""

    def __init__(self, key: str, max_requests: int, window_seconds: float, retry_after: float) -> None:
        self.key = key
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.retry_after = retry_after
        super().__init__(
            f"Rate limit exceeded for {key!r}: {max_requests} requests per {window_seconds}s. "
            f"Retry after {retry_after:.2f}s"
        )


class RateLimiter(ABC):
    """Abstract interface for rate limiting."""

    @abstractmethod
    def allowed(self, key: str, *, increment: int = 1) -> bool:
        """Check if *key* is allowed within the rate limit.
        
        Returns True if allowed, False if rate limited.
        Optionally increments the counter.
        """

    @abstractmethod
    def remaining(self, key: str) -> int:
        """Return remaining allowed requests for *key*."""

    @abstractmethod
    def reset(self, key: str) -> None:
        """Reset the rate limit counter for *key*."""

    @abstractmethod
    def retry_after(self, key: str) -> float:
        """Return seconds until *key* can retry."""

    @abstractmethod
    def inspect(self) -> dict:
        """Return machine-readable metadata for LLM introspection."""


@dataclass
class _WindowEntry:
    timestamps: list = field(default_factory=list)


class InMemoryRateLimiter(RateLimiter):
    """In-memory sliding window rate limiter.

    Suitable for development and single-process deployments.
    """

    def __init__(self, max_requests: int = 100, window_seconds: float = 60.0, name: str = "memory") -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.name = name
        self._windows: Dict[str, _WindowEntry] = defaultdict(_WindowEntry)

    def allowed(self, key: str, *, increment: int = 1) -> bool:
        now = time.time()
        entry = self._windows[key]
        cutoff = now - self.window_seconds
        # Prune expired timestamps
        entry.timestamps = [t for t in entry.timestamps if t > cutoff]
        if len(entry.timestamps) >= self.max_requests:
            return False
        for _ in range(increment):
            entry.timestamps.append(now)
        return True

    def remaining(self, key: str) -> int:
        now = time.time()
        entry = self._windows[key]
        cutoff = now - self.window_seconds
        active = sum(1 for t in entry.timestamps if t > cutoff)
        return max(0, self.max_requests - active)

    def reset(self, key: str) -> None:
        self._windows.pop(key, None)

    def retry_after(self, key: str) -> float:
        now = time.time()
        entry = self._windows[key]
        if not entry.timestamps:
            return 0.0
        cutoff = now - self.window_seconds
        # Find the oldest timestamp still in the window
        active = [t for t in entry.timestamps if t > cutoff]
        if len(active) < self.max_requests:
            return 0.0
        oldest = min(active)
        return max(0.0, oldest + self.window_seconds - now)

    def inspect(self) -> dict:
        now = time.time()
        active_keys = sum(
            1 for entry in self._windows.values()
            if any(t > now - self.window_seconds for t in entry.timestamps)
        )
        return {
            "backend": f"{type(self).__module__}.{type(self).__qualname__}",
            "max_requests": self.max_requests,
            "window_seconds": self.window_seconds,
            "active_keys": active_keys,
            "total_keys": len(self._windows),
        }


__all__ = [
    "RateLimitExceeded",
    "RateLimiter",
    "InMemoryRateLimiter",
]