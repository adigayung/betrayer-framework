"""Betrayer Cache — canonical cache API and HTTP integration.

The cache subsystem builds on the core :class:`betrayer.data.cache.CacheManager`
and provides an HTTP response caching middleware plus a declarative resource
configuration mechanism.

Usage::

    from betrayer.cache import (
        CacheManager,          # from betrayer.data
        MemoryCacheBackend,    # from betrayer.data
        CachePolicy,           # declarative cache config
        WebCacheMiddleware,    # HTTP response caching middleware
    )

Application layer::

    cache = CacheManager()  # in-memory by default
    cache.set("key", "value", ttl=60)
    cache.get("key")

Resource with HTTP caching::

    class ProductResource(CrudApiResource):
        name = "product"
        cache_ttl = 60  # opt-in: cache GET responses for 60 seconds
"""

from __future__ import annotations

from betrayer.cache.policy import CachePolicy
from betrayer.cache.middleware import WebCacheMiddleware
from betrayer.data.cache import CacheBackend, CacheManager, MemoryCacheBackend, _MISSING

__all__ = [
    "CacheBackend",
    "CacheManager",
    "MemoryCacheBackend",
    "CachePolicy",
    "WebCacheMiddleware",
    "_MISSING",
]