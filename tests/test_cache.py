"""Focused tests for the Cache subsystem (Task 16.5).

Covers:

* Core CacheManager operations (get/set/delete/exists/clear)
* TTL behavior (expiration, negative/zero TTL, no expiry)
* Cache miss detection (sentinel vs cached None)
* get_or_set
* MemoryCacheBackend store operations
* Concurrency safety
* WebCacheMiddleware HTTP integration
* Application/service layer usage
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, List

import pytest

from betrayer.cache.middleware import _make_cache_key, _is_cacheable_method
from betrayer.cache.policy import CachePolicy
from betrayer.data.cache import CacheManager, MemoryCacheBackend, _MISSING


# ======================================================================
# Core operations
# ======================================================================


class TestCacheCore:
    """Basic get/set/delete/exists/clear behavior."""

    def test_set_and_get(self):
        cache = CacheManager()
        cache.set("key", "value")
        assert cache.get("key") == "value"

    def test_set_and_get_integer(self):
        cache = CacheManager()
        cache.set("count", 42)
        assert cache.get("count") == 42

    def test_set_and_get_list(self):
        cache = CacheManager()
        cache.set("items", [1, 2, 3])
        assert cache.get("items") == [1, 2, 3]

    def test_get_missing_key_returns_sentinel(self):
        cache = CacheManager()
        result = cache.get("missing")
        assert result is cache.MISSING

    def test_get_missing_key_with_default(self):
        cache = CacheManager()
        assert cache.get("missing", None) is None
        assert cache.get("missing", "fallback") == "fallback"

    def test_cached_none_is_not_a_miss(self):
        cache = CacheManager()
        cache.set("key", None)
        result = cache.get("key")
        assert result is None
        # get with default should still return None (cached value wins)
        assert cache.get("key", "fallback") is None

    def test_exists_returns_true_for_existing_key(self):
        cache = CacheManager()
        cache.set("key", "value")
        assert cache.exists("key") is True

    def test_exists_returns_false_for_missing_key(self):
        cache = CacheManager()
        assert cache.exists("missing") is False

    def test_delete_removes_key(self):
        cache = CacheManager()
        cache.set("key", "value")
        cache.delete("key")
        assert cache.exists("key") is False
        assert cache.get("key") is cache.MISSING

    def test_delete_missing_key_is_noop(self):
        cache = CacheManager()
        cache.delete("does_not_exist")  # should not raise

    def test_clear_removes_all_keys(self):
        cache = CacheManager()
        cache.set("a", 1)
        cache.set("b", 2)
        cache.clear()
        assert cache.exists("a") is False
        assert cache.exists("b") is False
        assert cache.get("a") is cache.MISSING

    def test_overwrite_existing_key(self):
        cache = CacheManager()
        cache.set("key", "first")
        cache.set("key", "second")
        assert cache.get("key") == "second"

    def test_independent_keys(self):
        cache = CacheManager()
        cache.set("a", 1)
        cache.set("b", 2)
        assert cache.get("a") == 1
        assert cache.get("b") == 2
        cache.delete("a")
        assert cache.get("a") is cache.MISSING
        assert cache.get("b") == 2


# ======================================================================
# TTL
# ======================================================================


class TestCacheTTL:
    """TTL expiration and validation."""

    def test_value_before_expiration(self):
        cache = CacheManager()
        cache.set("key", "value", ttl=10)
        assert cache.get("key") == "value"

    def test_value_after_expiration(self):
        """Value expires after TTL seconds."""
        cache = CacheManager()
        cache.set("key", "value", ttl=0.02)
        time.sleep(0.03)
        assert cache.get("key") is cache.MISSING

    def test_ttl_none_means_no_expiration(self):
        cache = CacheManager()
        cache.set("key", "value", ttl=None)
        # Should still be present after a short delay
        time.sleep(0.02)
        assert cache.get("key") == "value"

    def test_ttl_zero_is_noop(self):
        cache = CacheManager()
        cache.set("key", "value", ttl=0)
        assert cache.get("key") is cache.MISSING

    def test_negative_ttl_rejected(self):
        cache = CacheManager()
        with pytest.raises(ValueError, match="non-negative"):
            cache.set("key", "value", ttl=-1)

    def test_expired_value_treated_as_miss(self):
        cache = CacheManager()
        cache.set("key", "value", ttl=0.02)
        time.sleep(0.03)
        assert cache.exists("key") is False
        assert cache.get("key", None) is None

    def test_lazy_expiration_cleanup(self):
        """Expired entries are cleaned up on access."""
        cache = CacheManager()
        cache.set("a", 1, ttl=0.02)
        cache.set("b", 2, ttl=60)  # long-lived
        time.sleep(0.03)
        # Access a to trigger lazy eviction
        _ = cache.get("a")
        # b should still be there
        assert cache.get("b") == 2


# ======================================================================
# get_or_set
# ======================================================================


class TestCacheGetOrSet:
    """get_or_set behavior."""

    def test_get_or_set_returns_cached_value(self):
        cache = CacheManager()
        cache.set("key", "cached")
        result = cache.get_or_set("key", "factory_value")
        assert result == "cached"

    def test_get_or_set_computes_and_stores(self):
        cache = CacheManager()
        result = cache.get_or_set("missing", "computed", ttl=60)
        assert result == "computed"
        assert cache.get("missing") == "computed"

    def test_get_or_set_calls_factory_on_miss(self):
        cache = CacheManager()
        factory_calls: List[int] = []
        result = cache.get_or_set("key", lambda: factory_calls.append(1) or "fresh")
        assert result == "fresh"
        assert len(factory_calls) == 1

    def test_get_or_set_does_not_call_factory_on_hit(self):
        cache = CacheManager()
        cache.set("key", "stale")
        factory_calls: List[int] = []
        result = cache.get_or_set(
            "key", lambda: factory_calls.append(1) or "fresh"
        )
        assert result == "stale"
        assert len(factory_calls) == 0

    def test_get_or_set_with_ttl(self):
        cache = CacheManager()
        result = cache.get_or_set("key", "value", ttl=0.02)
        assert result == "value"
        time.sleep(0.03)
        assert cache.get("key") is cache.MISSING


# ======================================================================
# Key behavior
# ======================================================================


class TestCacheKey:
    """String key handling."""

    def test_string_key(self):
        cache = CacheManager()
        cache.set("user:42", "data")
        assert cache.get("user:42") == "data"

    def test_empty_string_key(self):
        cache = CacheManager()
        cache.set("", "empty")
        assert cache.get("") == "empty"

    def test_key_with_spaces(self):
        cache = CacheManager()
        cache.set("my key", "value")
        assert cache.get("my key") == "value"


# ======================================================================
# Concurrency
# ======================================================================


class TestCacheConcurrency:
    """Thread-safety of MemoryCacheBackend."""

    def test_concurrent_get_set(self):
        cache = CacheManager()
        errors: List[Exception] = []
        lock = threading.Lock()

        def worker(worker_id: int):
            try:
                for i in range(100):
                    key = f"k:{worker_id}:{i}"
                    cache.set(key, worker_id)
                    v = cache.get(key)
                    assert v == worker_id, f"Expected {worker_id}, got {v}"
            except Exception as e:
                with lock:
                    errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(errors) == 0

    def test_concurrent_delete(self):
        cache = CacheManager()
        for i in range(50):
            cache.set(f"k:{i}", i)
        errors: List[Exception] = []

        def deleter(start: int):
            try:
                for i in range(start, start + 25):
                    cache.delete(f"k:{i}")
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=deleter, args=(0,)),
            threading.Thread(target=deleter, args=(25,)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(errors) == 0
        # Verify no corruption
        for i in range(50):
            assert cache.exists(f"k:{i}") is False

    def test_no_state_corruption_under_concurrent_access(self):
        cache = CacheManager()
        N = 500

        def writer():
            for i in range(N):
                cache.set(f"x:{i}", i)
                cache.delete(f"x:{i}")
                cache.set(f"y:{i}", i)

        threads = [threading.Thread(target=writer) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        count = sum(1 for i in range(N) if cache.exists(f"y:{i}"))
        assert count == N


# ======================================================================
# Store isolation and operations
# ======================================================================


class TestStore:
    """MemoryCacheBackend store behavior."""

    def test_store_isolation(self):
        backend1 = MemoryCacheBackend()
        backend2 = MemoryCacheBackend()
        backend1.set("key", "value1")
        backend2.set("key", "value2")
        assert backend1.get("key") == "value1"
        assert backend2.get("key") == "value2"

    def test_store_operations(self):
        backend = MemoryCacheBackend()
        backend.set("a", 1)
        backend.set("b", 2)
        assert backend.has("a") is True
        assert backend.has("b") is True
        backend.delete("a")
        assert backend.has("a") is False
        assert backend.has("b") is True
        backend.clear()
        assert backend.has("b") is False

    def test_expiration_cleanup(self):
        backend = MemoryCacheBackend()
        backend.set("key", "value", ttl=0.02)
        assert backend.has("key") is True
        time.sleep(0.03)
        assert backend.has("key") is False  # lazy eviction on has()

    def test_metadata(self):
        backend = MemoryCacheBackend()
        meta = backend.metadata()
        assert meta["backend"] == "memory"
        assert meta["entries"] == 0
        backend.set("a", 1)
        assert backend.metadata()["entries"] == 1


# ======================================================================
# CachePolicy
# ======================================================================


class TestCachePolicy:
    """CachePolicy value object."""

    def test_default_policy(self):
        policy = CachePolicy(ttl=60)
        assert policy.ttl == 60
        assert policy.cache_error is False
        assert policy.key_prefix is None

    def test_policy_with_all_options(self):
        policy = CachePolicy(ttl=120, cache_error=True, key_prefix="v1")
        assert policy.ttl == 120
        assert policy.cache_error is True
        assert policy.key_prefix == "v1"

    def test_none_ttl(self):
        policy = CachePolicy(ttl=None)
        assert policy.ttl is None

    def test_zero_ttl(self):
        policy = CachePolicy(ttl=0)
        assert policy.ttl == 0

    def test_negative_ttl_rejected(self):
        with pytest.raises(ValueError):
            CachePolicy(ttl=-1)

    def test_to_dict(self):
        policy = CachePolicy(ttl=30, cache_error=True)
        d = policy.to_dict()
        assert d["ttl"] == 30
        assert d["cache_error"] is True


# ======================================================================
# HTTP cache key helpers
# ======================================================================


class TestCacheKeyHelpers:
    """Deterministic HTTP cache key generation."""

    def test_basic_key(self):
        key = _make_cache_key("GET", "/products", {})
        assert key == "GET:/products"

    def test_key_with_query(self):
        key = _make_cache_key("GET", "/products", {"page": "1", "limit": "20"})
        assert key == "GET:/products?limit=20&page=1"

    def test_key_is_deterministic_regardless_of_order(self):
        k1 = _make_cache_key("GET", "/search", {"q": "foo", "sort": "asc"})
        k2 = _make_cache_key("GET", "/search", {"sort": "asc", "q": "foo"})
        assert k1 == k2

    def test_key_with_different_methods(self):
        assert _make_cache_key("GET", "/items", {}) != _make_cache_key("POST", "/items", {})

    def test_is_cacheable_method(self):
        assert _is_cacheable_method("GET") is True
        assert _is_cacheable_method("HEAD") is True
        assert _is_cacheable_method("POST") is False
        assert _is_cacheable_method("PUT") is False
        assert _is_cacheable_method("PATCH") is False
        assert _is_cacheable_method("DELETE") is False


# ======================================================================
# Application / service usage
# ======================================================================


class TestCacheApplicationUsage:
    """Cache usable from service/application layer."""

    def test_cache_usable_directly(self):
        cache = CacheManager()
        data = {"user": "alice", "role": "admin"}
        cache.set("session:abc", data, ttl=300)
        result = cache.get("session:abc")
        assert result == data

    def test_get_or_set_in_service_pattern(self):
        cache = CacheManager()
        # Simulate DB fetch
        db = {1: "Product A", 2: "Product B"}

        def get_product(product_id: int) -> str:
            key = f"product:{product_id}"
            cached = cache.get(key)
            if cached is not cache.MISSING:
                return cached
            value = db[product_id]
            cache.set(key, value, ttl=60)
            return value

        assert get_product(1) == "Product A"
        assert get_product(1) == "Product A"  # from cache
        assert cache.get("product:1") == "Product A"


# ======================================================================
# Web / Resource integration
# ======================================================================


class TestWebCacheMiddleware:
    """HTTP response caching via middleware (Flask optional)."""

    def test_basic_cache_roundtrip(self):
        """Simulate middleware cache flow without Flask."""
        from betrayer.cache import WebCacheMiddleware
        from betrayer.web.response import Response

        cache = CacheManager()
        mw = WebCacheMiddleware(cache=cache)

        # Build a minimal request stub
        class StubRequest:
            method = "GET"
            path = "/api/products"
            query = {"page": "1"}
            route = type("Route", (), {"metadata": {"cache_policy": CachePolicy(ttl=60)}})()
            user = None
            context = None

        req = StubRequest()

        # First request — cache miss
        context = type("Context", (), {"resource": None})()
        before = mw.before_request(req, context)
        assert before is None  # no cached response yet

        response = Response.json({"items": [1, 2]})
        mw.after_request(req, response, context)

        # Second request — cache hit
        before2 = mw.before_request(req, context)
        assert before2 is not None
        assert before2.status == 200
        assert before2.headers.get("X-Cache") == "HIT"

        import json
        payload = json.loads(before2.body)
        assert payload == {"items": [1, 2]}

    def test_post_not_cached(self):
        """POST requests are not cached."""
        from betrayer.cache import WebCacheMiddleware
        from betrayer.web.response import Response

        cache = CacheManager()
        mw = WebCacheMiddleware(cache=cache)

        class StubRequest:
            method = "POST"
            path = "/api/products"
            query = {}
            route = type("Route", (), {"metadata": {"cache_policy": CachePolicy(ttl=60)}})()

        req = StubRequest()
        context = type("Context", (), {"resource": None})()
        before = mw.before_request(req, context)
        assert before is None  # no caching attempted

        response = Response.json({"created": True}, status=201)
        mw.after_request(req, response, context)

        # Should still not be cached
        req2 = StubRequest()
        req2.method = "GET"  # only GET can read cache
        # Verify the cache key for POST was never stored
        assert cache.get("POST:/api/products") is cache.MISSING

    def test_resource_without_cache_unchanged(self):
        """Unconfigured resources are not cached."""
        from betrayer.cache import WebCacheMiddleware
        from betrayer.web.response import Response

        cache = CacheManager()
        mw = WebCacheMiddleware(cache=cache)

        class StubRequest:
            method = "GET"
            path = "/api/uncached"
            query = {}
            route = type("Route", (), {"metadata": {}})()

        req = StubRequest()
        context = type("Context", (), {"resource": None})()
        before = mw.before_request(req, context)
        assert before is None

        response = Response.json({"data": "fresh"})
        mw.after_request(req, response, context)

        req2 = StubRequest()
        before2 = mw.before_request(req2, context)
        assert before2 is None  # not cached

    def test_error_response_not_cached_by_default(self):
        """Error responses are not cached unless cache_error=True."""
        from betrayer.cache import WebCacheMiddleware
        from betrayer.web.response import Response

        cache = CacheManager()
        mw = WebCacheMiddleware(cache=cache)

        class StubRequest:
            method = "GET"
            path = "/api/error"
            query = {}
            route = type("Route", (), {"metadata": {"cache_policy": CachePolicy(ttl=60)}})()

        req = StubRequest()
        context = type("Context", (), {"resource": None})()
        response = Response.json({"error": "not found"}, status=404)
        mw.after_request(req, response, context)

        key = cache.get("GET:/api/error")
        assert key is cache.MISSING

    def test_resource_with_resource_level_cache_ttl(self):
        """Resource-level cache_ttl via context.resource.cache_ttl."""
        from betrayer.cache import WebCacheMiddleware
        from betrayer.web.response import Response

        cache = CacheManager()
        # Use no default policy and no route metadata — will try context.resource
        mw = WebCacheMiddleware(cache=cache)

        class StubResource:
            cache_ttl = 30

        class StubRequest:
            method = "GET"
            path = "/api/test"
            query = {}
            route = type("Route", (), {"metadata": {}})()

        req = StubRequest()
        context = type("Context", (), {"resource": StubResource()})()
        before = mw.before_request(req, context)
        assert before is None  # nothing cached yet

        response = Response.json({"ok": True})
        mw.after_request(req, response, context)

        req2 = StubRequest()
        before2 = mw.before_request(req2, context)
        assert before2 is not None
        assert before2.headers.get("X-Cache") == "HIT"

    def test_middleware_disabled(self):
        """Disabled middleware does not cache."""
        from betrayer.cache import WebCacheMiddleware
        from betrayer.web.response import Response

        cache = CacheManager()
        mw = WebCacheMiddleware(cache=cache)
        mw.enabled = False

        class StubRequest:
            method = "GET"
            path = "/api/test"
            query = {}
            route = type("Route", (), {"metadata": {"cache_policy": CachePolicy(ttl=60)}})()

        req = StubRequest()
        context = type("Context", (), {"resource": None})()
        response = Response.json({"data": "fresh"})
        mw.after_request(req, response, context)

        req2 = StubRequest()
        before2 = mw.before_request(req2, context)
        assert before2 is None  # not cached