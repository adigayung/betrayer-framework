"""Cache abstraction: swappable backend with minimal surface.

Provides a ``CacheBackend`` interface and a ``CacheManager`` that owns the
backend.  The manager can be registered in the Container so that any
subsystem can inject it.

Design decisions:
- ``CacheBackend`` is abstract; concrete implementations (memory, Redis, etc.)
  are provided by the application or future tasks.
- ``CacheManager`` wraps a backend and adds convenience methods.
- TTL is optional; negative TTL is rejected at the manager level.
- A sentinel (``_MISSING``) distinguishes a cache miss from a cached ``None``.
"""

from __future__ import annotations

import abc
import threading
import time
from typing import Any, Callable, Optional, Union


#: Sentinel used to distinguish a cache miss from a cached ``None``.
_MISSING: Any = object()


class CacheBackend(abc.ABC):
    """Abstract cache backend."""

    @abc.abstractmethod
    def get(self, key: str) -> Any:
        """Retrieve a value by key; return ``_MISSING`` if missing/expired."""
        ...

    @abc.abstractmethod
    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Store a value, optionally with a TTL in seconds."""
        ...

    @abc.abstractmethod
    def delete(self, key: str) -> None:
        """Remove a key from the cache."""
        ...

    @abc.abstractmethod
    def has(self, key: str) -> bool:
        """Return True if the key exists and is not expired."""
        ...

    @abc.abstractmethod
    def clear(self) -> None:
        """Remove all entries."""
        ...

    @abc.abstractmethod
    def metadata(self) -> dict:
        """Return backend metadata for introspection."""
        ...


class MemoryCacheBackend(CacheBackend):
    """Simple in-memory cache backend (default).

    Thread-safe via ``threading.Lock``.
    """

    def __init__(self) -> None:
        self._store: dict[str, Any] = {}
        self._expiry: dict[str, float] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Any:
        with self._lock:
            self._evict(key)
            return self._store.get(key, _MISSING)

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        with self._lock:
            self._store[key] = value
            if ttl is not None:
                self._expiry[key] = time.time() + ttl
            elif key in self._expiry:
                del self._expiry[key]

    def delete(self, key: str) -> None:
        with self._lock:
            self._store.pop(key, None)
            self._expiry.pop(key, None)

    def has(self, key: str) -> bool:
        with self._lock:
            self._evict(key)
            return key in self._store

    def clear(self) -> None:
        with self._lock:
            self._store.clear()
            self._expiry.clear()

    def metadata(self) -> dict:
        with self._lock:
            return {
                "backend": "memory",
                "entries": len(self._store),
            }

    def _evict(self, key: str) -> None:
        """Remove key if expired."""
        expires = self._expiry.get(key)
        if expires is not None and time.time() > expires:
            self._store.pop(key, None)
            self._expiry.pop(key, None)


class CacheManager:
    """Owning wrapper around a ``CacheBackend``.

    Can be registered in the Container or Lifecycle for discoverability.

    Canonical API (all methods are thread-safe when backed by a thread-safe
    backend)::

        cache = CacheManager()

        cache.set("user:1", value, ttl=60)
        cache.get("user:1")
        cache.get("user:1", default=None)      # None on miss
        cache.exists("user:1")
        cache.delete("user:1")
        cache.clear()
        cache.get_or_set("key", factory, ttl=300)
    """

    #: Public sentinel for cache-miss detection.
    #: Usage: ``if value is cache.MISSING: ...``
    MISSING: Any = _MISSING

    def __init__(self, backend: Optional[CacheBackend] = None) -> None:
        self._backend: CacheBackend = backend or MemoryCacheBackend()

    @property
    def backend(self) -> CacheBackend:
        return self._backend

    def get(self, key: str, default: Any = _MISSING) -> Any:
        """Retrieve a value.

        Returns ``default`` (or the ``MISSING`` sentinel if omitted) when the
        key is missing or expired, making it possible to distinguish a cache
        miss from a cached ``None``::

            value = cache.get("key")           # MISSING sentinel on miss
            if value is cache.MISSING:
                # cache miss — value not cached (or expired)
                ...
            cached_none = cache.get("key", None)  # None on miss too

        Shortcut::

            cache.get("key", "fallback")       # "fallback" on miss
        """
        result = self._backend.get(key)
        if result is _MISSING:
            return default
        return result

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Store a value, optionally with a TTL in seconds.

        ``ttl`` must be ``None`` (no expiration) or a non-negative integer.
        ``ttl=0`` means the value expires immediately (effectively a no-op).
        ``ttl < 0`` raises ``ValueError``.
        """
        if ttl is not None:
            if not isinstance(ttl, (int, float)):
                raise ValueError(
                    f"TTL must be None or a number, got {type(ttl).__name__}"
                )
            if ttl < 0:
                raise ValueError(
                    f"TTL must be non-negative, got {ttl}"
                )
            if ttl == 0:
                # Value expires immediately — nothing to store.
                return
            ttl = int(ttl)
        self._backend.set(key, value, ttl=ttl)

    def delete(self, key: str) -> None:
        """Remove a key from the cache.  No-op when the key does not exist."""
        self._backend.delete(key)

    def exists(self, key: str) -> bool:
        """Return ``True`` if the key exists and is not expired."""
        return self._backend.has(key)

    def has(self, key: str) -> bool:
        """Alias for :meth:`exists`."""
        return self.exists(key)

    def clear(self) -> None:
        """Remove all entries."""
        self._backend.clear()

    def get_or_set(
        self,
        key: str,
        factory: Union[Callable[[], Any], Any],
        ttl: Optional[int] = None,
    ) -> Any:
        """Return the cached value for ``key``, or compute and cache it.

        When ``key`` is missing or expired ``factory`` is called (no
        arguments) and its return value is stored under ``ttl`` before
        being returned.

        ``factory`` may be a callable or a plain value (in which case it is
        used directly without calling).  This keeps common usage simple::

            user = cache.get_or_set("user:1", fetch_user(1), ttl=300)
            user = cache.get_or_set("config", {"theme": "dark"}, ttl=None)
        """
        result = self._backend.get(key)
        if result is not _MISSING:
            return result
        value = factory() if callable(factory) else factory
        self.set(key, value, ttl=ttl)
        return value

    def metadata(self) -> dict:
        """Return introspection metadata."""
        return {
            "manager": "CacheManager",
            "backend": self._backend.metadata(),
        }


__all__ = [
    "CacheBackend",
    "CacheManager",
    "MemoryCacheBackend",
    "_MISSING",
]