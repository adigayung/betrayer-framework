"""WebCacheMiddleware — HTTP response caching for the web pipeline.

This middleware caches HTTP responses in ``after_request`` using a
:class:`betrayer.data.cache.CacheManager`.  Caching is opt-in: only routes
or resources with a ``cache_policy`` are cached, and only ``GET`` / ``HEAD``
requests are candidates.

The cache key is deterministic and based on:

* HTTP method
* request path
* sorted query parameters (normalised to produce the same key regardless
  of parameter ordering)

Response headers ``X-Cache: HIT`` / ``X-Cache: MISS`` are added when a
cached response is served or stored.

Usage (web middleware registry)::

    from betrayer.cache import CacheManager, WebCacheMiddleware

    registry = WebMiddlewareRegistry()
    registry.add(WebCacheMiddleware(cache=CacheManager()))

On routes::

    route.metadata["cache_policy"] = CachePolicy(ttl=60)
"""

from __future__ import annotations

from typing import Any, Optional

from betrayer.cache.policy import CachePolicy
from betrayer.data.cache import CacheManager, MemoryCacheBackend, _MISSING
from betrayer.web.middleware import Middleware
from betrayer.web.response import Response


def _make_cache_key(method: str, path: str, query: dict, identity_key: str = "") -> str:
    """Deterministic cache key from HTTP method, path, sorted query params and optional identity.

    When ``identity_key`` is non-empty (e.g. ``"user:42"``), it is prepended
    to the key so that different authenticated users never see each other's
    cached responses.  Anonymous requests share a common key (no identity).
    """
    items = sorted(query.items())
    qs = "&".join(f"{k}={v}" for k, v in items) if items else ""
    prefix = f"{identity_key}:" if identity_key else ""
    if qs:
        return f"{prefix}{method}:{path}?{qs}"
    return f"{prefix}{method}:{path}"


def _is_cacheable_method(method: str) -> bool:
    """Return True if the HTTP method is safe to cache."""
    return method in ("GET", "HEAD")


def _is_cacheable_response(response: Any) -> bool:
    """Return True if the response is safe to cache (2xx or 3xx)."""
    return 200 <= getattr(response, "status", 500) < 400


class WebCacheMiddleware(Middleware):
    """Cache HTTP responses in the web pipeline.

    Attributes
    ----------
    cache:
        The :class:`~betrayer.data.cache.CacheManager` instance.
    name:
        Middleware name for introspection.
    priority:
        Lower runs earlier.  Default 10 (runs after authentication/rate
        limiting).
    enabled:
        Set to ``False`` to disable caching without unregistering.
    """

    name: str = "WebCacheMiddleware"
    priority: int = 20  # After authorization (priority 10) to prevent security bypass
    enabled: bool = True

    def __init__(
        self,
        cache: Optional[CacheManager] = None,
        *,
        default_policy: Optional[CachePolicy] = None,
    ) -> None:
        super().__init__()
        self._cache: CacheManager = cache or CacheManager(MemoryCacheBackend())
        self._default_policy: Optional[CachePolicy] = default_policy

    @property
    def cache(self) -> CacheManager:
        return self._cache

    def before_request(self, request: Any, context: Any) -> Optional[Response]:
        """Check for a cached response before the handler runs.

        Only applies to ``GET``/``HEAD`` requests on routes that have a
        ``cache_policy`` in their metadata or a resource-level configuration.
        """
        if not self.enabled:
            return None
        if not _is_cacheable_method(getattr(request, "method", "")):
            return None

        policy = self._resolve_policy(request, context)
        if policy is None or policy.ttl == 0:
            return None

        key = self._request_key(request)
        cached = self._cache.get(key)
        if cached is not _MISSING:
            if isinstance(cached, dict):
                body = cached.get("body", "")
                status = cached.get("status", 200)
                content_type = cached.get("content_type")
                headers = cached.get("headers", {})
                resp = Response(
                    body,
                    status=status,
                    headers=headers,
                    content_type=content_type,
                )
                resp.headers["X-Cache"] = "HIT"
                return resp
        return None

    def after_request(
        self, request: Any, response: Response, context: Any
    ) -> Optional[Response]:
        """Store a cacheable response after the handler runs.

        Only caches ``GET``/``HEAD`` responses for routes/resources with a
        ``cache_policy``.
        """
        if not self.enabled:
            return None
        if not _is_cacheable_method(getattr(request, "method", "")):
            return None

        policy = self._resolve_policy(request, context)
        if policy is None or policy.ttl == 0:
            return None

        # Skip error responses unless explicitly allowed
        if not _is_cacheable_response(response) and not policy.cache_error:
            return None

        key = self._request_key(request)
        snapshot = {
            "body": response.body,
            "status": response.status,
            "content_type": response.content_type,
            "headers": dict(response.headers),
        }
        self._cache.set(key, snapshot, ttl=policy.ttl)
        response.with_header("X-Cache", "MISS")
        return None

    # -- internal helpers ------------------------------------------------

    def _resolve_policy(self, request: Any, context: Any) -> Optional[CachePolicy]:
        """Resolve cache policy from route metadata, resource, or default."""
        route = getattr(request, "route", None)
        if route is not None:
            meta = getattr(route, "metadata", None) or {}
            policy = meta.get("cache_policy")
            if policy is not None:
                return policy
        # Check resource object on context for resource-level cache_ttl
        resource = getattr(context, "resource", None) if context is not None else None
        if resource is not None:
            cache_ttl = getattr(resource, "cache_ttl", None)
            if cache_ttl is not None:
                return CachePolicy(ttl=cache_ttl)
        # Fall back to default
        return self._default_policy

    def _request_key(self, request: Any) -> str:
        """Build a deterministic cache key from the request, including user identity.

        Authenticated users get a user-specific key so cached responses are never
        shared across identities.  Anonymous requests use no identity prefix so
        they share a common cache (no sensitive data is at risk).
        """
        method = getattr(request, "method", "GET")
        path = getattr(request, "path", "/")
        query = getattr(request, "query", {})
        identity_key = ""
        user = getattr(request, "user", None)
        if user is not None and not getattr(user, "is_anonymous", True):
            uid = getattr(user, "id", None)
            if uid is not None:
                identity_key = f"user:{uid}"
        return _make_cache_key(method, path, query, identity_key)

    # -- introspection ---------------------------------------------------

    def hooks(self) -> dict:
        return {
            "before_request": True,
            "after_request": True,
            "on_error": False,
        }

    def describe(self) -> dict:
        base = super().describe()
        return {
            **base,
            "cache_backend": type(self._cache.backend).__name__,
            "default_policy": self._default_policy.to_dict() if self._default_policy else None,
        }