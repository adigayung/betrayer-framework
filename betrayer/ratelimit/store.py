"""Rate limit store abstraction and in-memory fixed-window implementation.

``RateLimitStore`` is the abstract interface; ``MemoryRateLimitStore`` is the
default in-process backend adequate for development, testing, and single-process
deployments.

Design
------
* Fixed-window: counters are grouped by ``(key, window_start_timestamp)``.
* The store is agnostic of the rate limit policy (limit/window) — it only
  manages counters.
* Thread-safe: uses ``threading.Lock`` for in-process safety.
* Expired windows are cleaned lazily (on access).

Backends (Redis, etc.) can be added by implementing ``RateLimitStore``.
"""

from __future__ import annotations

import time
import threading
from abc import ABC, abstractmethod
from collections import defaultdict
from typing import Dict, Optional, Tuple


class RateLimitStore(ABC):
    """Abstract rate limit counter store.

    A store manages per-key counters grouped by window.  Each call to
    :meth:`increment` updates the counter for the current window and returns
    metadata the limiter uses to decide whether the request is allowed.
    """

    @abstractmethod
    def increment(
        self,
        key: str,
        window: int,
        *,
        amount: int = 1,
    ) -> Tuple[int, float]:
        """Increment the counter for ``key`` in the current fixed window.

        Parameters
        ----------
        key:
            Rate limit key (e.g. ``"user:42"``, ``"ip:1.2.3.4"``).
        window:
            Window duration in seconds (determines the bucket alignment).
        amount:
            Increment amount (default 1 per request).

        Returns
        -------
        ``(count, window_start)`` where ``count`` is the counter value
        *after* the increment and ``window_start`` is the Unix timestamp
        of the start of the current window for this key.
        """

    @abstractmethod
    def get(self, key: str, window: int) -> Tuple[int, float]:
        """Read the current counter and window start without incrementing.

        Returns ``(count, window_start)``.  When no counter exists for the
        current window, ``(0, window_start)`` where ``window_start`` is the
        start of the current window.
        """

    @abstractmethod
    def reset(self, key: str) -> None:
        """Reset all counters for ``key`` (used by tests/tooling)."""

    @abstractmethod
    def clear_expired(self) -> int:
        """Remove entries whose window has ended.

        Returns the number of removed entries.

        This is called lazily; no background cleanup worker is needed.
        """

    @abstractmethod
    def inspect(self) -> dict:
        """Machine-readable snapshot for LLM introspection."""


class MemoryRateLimitStore(RateLimitStore):
    """Thread-safe in-memory fixed-window rate limit store.

    Counters are stored as ``{key: {window_start: count}}``.
    Expired entries are cleaned lazily on access.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        #: key -> {window_start -> count}
        self._counters: Dict[str, Dict[int, int]] = defaultdict(dict)

    def _window_start(self, window: int) -> int:
        """Return the aligned start of the current fixed window.

        Example for window=60 and time=1234567.0:
          window_start = 1234560  (= int(1234567.0 / 60) * 60)
        """
        now = time.time()
        return int(now / window) * window

    def increment(
        self,
        key: str,
        window: int,
        *,
        amount: int = 1,
    ) -> Tuple[int, float]:
        with self._lock:
            ws = self._window_start(window)
            # Prune expired entries for this key
            self._prune_key(key, ws)
            counters = self._counters[key]
            current = counters.get(ws, 0)
            current += amount
            counters[ws] = current
            return current, float(ws)

    def get(self, key: str, window: int) -> Tuple[int, float]:
        ws = self._window_start(window)
        with self._lock:
            self._prune_key(key, ws)
            count = self._counters[key].get(ws, 0)
            return count, float(ws)

    def reset(self, key: str) -> None:
        with self._lock:
            self._counters.pop(key, None)

    def clear_expired(self) -> int:
        now = time.time()
        removed = 0
        with self._lock:
            for key, windows in list(self._counters.items()):
                expired = [ws for ws in windows if ws + 60 < now]
                for ws in expired:
                    del windows[ws]
                    removed += 1
                if not windows:
                    del self._counters[key]
        return removed

    def _prune_key(self, key: str, current_ws: int) -> None:
        """Remove windows older than ``current_ws`` for one key."""
        windows = self._counters.get(key)
        if windows is None:
            return
        expired = [ws for ws in windows if ws < current_ws]
        for ws in expired:
            del windows[ws]

    def inspect(self) -> dict:
        with self._lock:
            active_keys = len(self._counters)
            now = time.time()
            total_entries = sum(len(w) for w in self._counters.values())
            return {
                "backend": f"{type(self).__module__}.{type(self).__qualname__}",
                "type": "memory",
                "active_keys": active_keys,
                "total_entries": total_entries,
                "lock_type": type(self._lock).__name__,
            }

    def __repr__(self) -> str:
        return f"<MemoryRateLimitStore keys={len(self._counters)}>"