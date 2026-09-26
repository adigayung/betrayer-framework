"""Cache abstraction: swappable backend with minimal surface.

Provides a ``CacheBackend`` interface and a ``CacheManager`` that owns the
backend.  The manager can be registered in the Container so that any
subsystem can inject it.

Design decisions:
- ``CacheBackend`` is abstract; concrete implementations (memory, Redis, etc.)
  are provided by the application or future tasks.
- ``CacheManager`` wraps a backend and adds deterministic key handling.
- TTL is optional per-operation when the backend supports it.
"""

from __future__ import annotations

import abc
import threading
import time
from typing import Any, Optional


class CacheBackend(abc.ABC):
    """Abstract cache backend."""

    @abc.abstractmethod
    def get(self, key: str) -> Optional[Any]:
        """Retrieve a value by key; return None if missing/expired."""
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

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            self._evict(key)
            return self._store.get(key)

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
    """

    def __init__(self, backend: Optional[CacheBackend] = None) -> None:
        self._backend: CacheBackend = backend or MemoryCacheBackend()

    @property
    def backend(self) -> CacheBackend:
        return self._backend

    def get(self, key: str) -> Optional[Any]:
        return self._backend.get(key)

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        self._backend.set(key, value, ttl=ttl)

    def delete(self, key: str) -> None:
        self._backend.delete(key)

    def has(self, key: str) -> bool:
        return self._backend.has(key)

    def clear(self) -> None:
        self._backend.clear()

    def metadata(self) -> dict:
        return {
            "manager": "CacheManager",
            "backend": self._backend.metadata(),
        }


__all__ = [
    "CacheBackend",
    "CacheManager",
    "MemoryCacheBackend",
]