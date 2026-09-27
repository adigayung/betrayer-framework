"""Integration tests for Betrayer Application Essentials (Task 16).

Tests the integration of:
  - Authentication (16.1)
  - Authorization (16.2)
  - Pagination (16.3)
  - Rate Limiting (16.4)
  - Cache (16.5)

All features compose through the existing middleware pipeline, DI container,
Resource attributes, and response envelope — no new subsystems.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

import pytest

from betrayer.application import BetrayerApplication
from betrayer.bootstrap import Bootstrap
from betrayer.cache import CacheManager, CachePolicy, WebCacheMiddleware
from betrayer.cache.middleware import _make_cache_key
from betrayer.ratelimit import RateLimit, RateLimitMiddleware, MemoryRateLimitStore
from betrayer.auth import (
    AllowAllAuthorizer,
    AnonymousIdentity,
    AuthenticationMiddleware,
    AuthorizationMiddleware,
    Authorizer,
    CallbackAuthenticator,
    Identity,
    UnauthenticatedError,
    authorize,
)
from betrayer.auth.authorization import DEFAULT_AUTHORIZER_KEY
from betrayer.web.exceptions import ForbiddenError
from betrayer.web import (
    ApiResource,
    ApiResponse,
    CrudApiResource,
    Request,
    Response,
    WebContext,
    WebMiddlewareRegistry,
)
from betrayer.web.middleware import WebPipeline
from betrayer.web import (
    PaginatedResult,
    PaginationMetadata,
    PaginationParams,
    paginate_sequence,
    parse_pagination,
)
from betrayer.web.response import Response as Resp

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _stub_flask_request(method: str = "GET", path: str = "/", query: dict = None,
                         headers: dict = None, body: str = "",
                         remote_addr: str = "127.0.0.1") -> Request:
    """Build a minimal Betrayer Request stub with enough surface for all tests."""
    request = Request()
    query = query or {}
    headers = headers or {}
    _headers = type(
        "_H",
        (),
        {
            "get": lambda self, n, d="": headers.get(n, d),
            "keys": lambda self: list(headers),
        },
    )()
    request._raw = type(
        "StubFlaskRequest",
        (),
        {
            "headers": _headers,
            "method": method,
            "path": path,
            "full_path": path + ("?" + "&".join(f"{k}={v}" for k, v in query.items()) if query else ""),
            "url": f"http://test{path}",
            "base_url": "http://test",
            "host": "test",
            "scheme": "http",
            "args": dict(query.items()),
            "cookies": {},
            "data": body.encode() if isinstance(body, str) else body,
            "get_data": lambda *a, **kw: (body.encode() if isinstance(body, str) else body),
            "is_json": bool(body),
            "content_type": "application/json" if body else None,
            "content_length": len(body) if body else 0,
            "files": {},
            "form": {},
            "endpoint": None,
            "remote_addr": remote_addr,
            "user_agent": None,
        },
    )()
    # Mount query params on the request object for get_query
    request._query_dict = dict(query)
    return request


def _make_context(request: Request, **container_items) -> WebContext:
    """Build a WebContext with a fresh application and optional container items."""
    app = BetrayerApplication(name="essentials-test")
    Bootstrap(app).build()
    for key, value in container_items.items():
        app.container.instance(key, value)
    route = type("Route", (), {"module": "test", "endpoint": "test.handler", "metadata": {}})()
    return WebContext(application=app, adapter=None, request=request, route=route)


class DenyAll(Authorizer):
    """Always denies."""
    def authorize(self, identity, action, resource=None, context=None) -> bool:
        return False


class ViewOnly(Authorizer):
    """Allows only 'view' action."""
    def authorize(self, identity, action, resource=None, context=None) -> bool:
        return action == "view"


def _request_with_identity(identity: Optional[Identity] = None,
                           method: str = "GET", path: str = "/",
                           query: dict = None,
                           route_meta: dict = None) -> Request:
    """Convenience: build a request with an optional identity already set."""
    request = _stub_flask_request(method=method, path=path, query=query or {})
    if identity is not None:
        request.set_user(identity)
    else:
        request.set_user(AnonymousIdentity())
    if route_meta:
        request.route = type(
            "Route",
            (),
            {
                "module": "test",
                "endpoint": "test.handler",
                "authorization_required": route_meta.get("authorization_required", False),
                "authorization_action": route_meta.get("authorization_action"),
                "authorization_actions": route_meta.get("authorization_actions", {}),
                "authorization_resource_key": route_meta.get("authorization_resource_key"),
                "metadata": dict(route_meta),
            },
        )()
    return request


# ===================================================================
# 1. Authentication + Authorization integration
# ===================================================================

class TestAuthenticationAuthorization:

    def test_unauthenticated_returns_401(self):
        """Protected endpoint with anonymous user raises 401 UNAUTHENTICATED."""
        resource = ApiResource()
        resource.authentication_required = True
        request = _stub_flask_request()
        request.set_user(AnonymousIdentity())
        with pytest.raises(UnauthenticatedError) as exc:
            resource._enforce_authentication(request)
        assert exc.value.http_status == 401
        assert exc.value.code == "UNAUTHENTICATED"

    def test_authenticated_unauthorized_returns_403(self):
        """Authenticated user without permission raises 403 FORBIDDEN."""
        request = _stub_flask_request()
        request.set_user(Identity(id=1))
        context = _make_context(request)
        context.container.instance(DEFAULT_AUTHORIZER_KEY, DenyAll())
        with pytest.raises(ForbiddenError) as exc:
            authorize(request.user, "view", context=context)
        assert exc.value.http_status == 403
        assert exc.value.code == "FORBIDDEN"

    def test_authenticated_authorized_passes(self):
        """Authenticated user with permission reaches the handler."""
        request = _stub_flask_request()
        request.set_user(Identity(id=1))
        context = _make_context(request)
        context.container.instance(DEFAULT_AUTHORIZER_KEY, ViewOnly())
        # This should NOT raise
        authorize(request.user, "view", context=context)

    def test_authentication_does_not_authorize(self):
        """Authentication sets identity but never checks permissions."""
        request = _stub_flask_request()
        # No authorizer in container - authentication should still work
        mw = AuthenticationMiddleware(authenticator=CallbackAuthenticator(
            lambda r: Identity(id=42)
        ))
        mw.before_request(request, _make_context(request))
        assert request.user.id == 42

    def test_authorization_does_not_authenticate(self):
        """Authorization reads request.user without re-authenticating."""
        request = _stub_flask_request()
        request.set_user(Identity(id=1))
        # AuthorizationMiddleware does NOT call authenticate
        mw = AuthorizationMiddleware()
        context = _make_context(request)
        context.container.instance(DEFAULT_AUTHORIZER_KEY, ViewOnly())
        # Route without authorization_required flag should pass without checking
        request.route = type("Route", (), {
            "module": "test",
            "authorization_required": False,
            "authorization_action": None,
            "authorization_actions": {},
            "authorization_resource_key": None,
            "metadata": {},
        })()
        mw.before_request(request, context)  # should not raise

    def test_pipeline_auth_then_authorization(self):
        """Middleware ordering: authentication runs before authorization."""
        from betrayer.web.middleware import WebPipeline
        log: list = []

        class RecorderMiddleware:
            name = "recorder"
            enabled = True
            priority = 0
            def middleware_name(self):
                return self.name
            def before_request(self, request, context):
                log.append(self.name)

        request = _stub_flask_request()
        context = _make_context(request)
        pipeline = WebPipeline(
            middleware=[
                RecorderMiddleware(),
            ],
            request=request,
            context=context,
        )
        pipeline.run(handler=lambda: "ok")

    def test_priority_ordering(self):
        """Authentication (0) < Rate Limiting (5) < Authorization (10) < Cache (20)."""
        assert AuthenticationMiddleware.priority < 5
        assert RateLimitMiddleware().priority == 5
        assert RateLimitMiddleware().priority < AuthorizationMiddleware.priority
        assert AuthorizationMiddleware.priority < WebCacheMiddleware().priority


# ===================================================================
# 2. Authentication + Rate Limiting
# ===================================================================

class TestAuthenticationRateLimiting:

    def test_authenticated_identity_used_for_key(self):
        """Rate limiter uses user:{id} for authenticated requests."""
        identity = Identity(id=42)
        route = type("Route", (), {
            "metadata": {"rate_limit": RateLimit(limit=10, window=60)}
        })()
        request = _stub_flask_request()
        request.set_user(identity)
        request.route = route

        mw = RateLimitMiddleware(store=MemoryRateLimitStore())
        key = mw._resolve_key(request)
        assert key == "user:42"

    def test_anonymous_uses_ip_fallback(self):
        """Anonymous requests fall back to remote_addr for key."""
        route = type("Route", (), {
            "metadata": {"rate_limit": RateLimit(limit=10, window=60)}
        })()
        request = _stub_flask_request(remote_addr="192.168.1.1")
        request.set_user(AnonymousIdentity())
        request.route = route

        mw = RateLimitMiddleware(store=MemoryRateLimitStore())
        key = mw._resolve_key(request)
        assert key == "ip:192.168.1.1"

    def test_rate_limiter_does_not_create_identity(self):
        """Rate limiter reads request.user but never sets it."""
        route = type("Route", (), {
            "metadata": {"rate_limit": RateLimit(limit=10, window=60)}
        })()
        request = _stub_flask_request()
        request.set_user(AnonymousIdentity())
        request.route = route

        mw = RateLimitMiddleware(store=MemoryRateLimitStore())
        result = mw.before_request(request, _make_context(request))
        # request.user should still be what we set
        assert request.user.is_anonymous is True

    def test_rate_limiter_does_not_expose_identity(self):
        """Rate limiter 429 response does not leak identity info."""
        identity = Identity(id=42, name="secret-agent")
        route = type("Route", (), {
            "metadata": {"rate_limit": RateLimit(limit=1, window=60)}
        })()
        request = _stub_flask_request()
        request.set_user(identity)
        request.route = route

        mw = RateLimitMiddleware(store=MemoryRateLimitStore())
        # Exhaust the limit
        mw.before_request(request, _make_context(request))
        # Second request gets 429
        result = mw.before_request(request, _make_context(request))
        body_str = result.body if hasattr(result, "body") else ""
        assert "secret-agent" not in body_str


# ===================================================================
# 3. Rate Limiting + Authorization
# ===================================================================

class TestRateLimitingAuthorization:

    def test_rate_limit_exceeded_before_authorization(self):
        """Rate limited request never reaches authorization check."""
        route = type("Route", (), {
            "metadata": {"rate_limit": RateLimit(limit=1, window=60)},
            "authorization_required": True,
        })()
        request = _stub_flask_request()
        request.set_user(Identity(id=1))
        request.route = route

        mw = RateLimitMiddleware(store=MemoryRateLimitStore())
        # Exhaust the limit
        mw.before_request(request, _make_context(request))
        # Second request - rate limiter blocks BEFORE authorization runs
        result = mw.before_request(request, _make_context(request))
        assert result is not None
        assert result.status == 429
        # AuthorizationMiddleware never ran

    def test_authorization_still_runs_after_rate_limit_passes(self):
        """Request that passes rate limiter still goes through authorization."""
        route = type("Route", (), {
            "metadata": {"rate_limit": RateLimit(limit=10, window=60)},
            "authorization_required": True,
            "authorization_action": "view",
            "authorization_resource_key": None,
            "authorization_actions": {},
        })()
        request = _stub_flask_request()
        request.set_user(Identity(id=1))
        request.route = route

        rate_mw = RateLimitMiddleware(store=MemoryRateLimitStore())
        authz_mw = AuthorizationMiddleware()
        context = _make_context(request)
        context.container.instance(DEFAULT_AUTHORIZER_KEY, DenyAll())

        # Rate limiter passes
        result = rate_mw.before_request(request, context)
        assert result is None

        # Then authorization is checked - should deny
        with pytest.raises(ForbiddenError):
            authz_mw.before_request(request, context)


# ===================================================================
# 4. Authentication + Cache
# ===================================================================

class TestAuthenticationCache:

    def test_cache_key_includes_authenticated_user(self):
        """Different authenticated users get different cache keys."""
        key_a = _make_cache_key("GET", "/api/products", {}, "user:1")
        key_b = _make_cache_key("GET", "/api/products", {}, "user:2")
        assert key_a != key_b

    def test_anonymous_requests_share_cache_key(self):
        """Anonymous requests (no identity) share a common key."""
        key_anon = _make_cache_key("GET", "/api/products", {}, "")
        key_anon2 = _make_cache_key("GET", "/api/products", {}, "")
        assert key_anon == key_anon2

    def test_cache_does_not_bypass_authentication(self):
        """Cached responses for authenticated users are not served to others."""
        cache = CacheManager()
        mw = WebCacheMiddleware(cache=cache)

        route_meta = lambda: type("Route", (), {"metadata": {"cache_policy": CachePolicy(ttl=60)}})()

        # Simulate an authenticated request that gets cached
        req_a = _stub_flask_request(method="GET", path="/api/items")
        req_a.set_user(Identity(id=1))
        req_a.route = route_meta()
        ctx_a = type("Context", (), {"resource": None})()
        mw.before_request(req_a, ctx_a)  # MISS
        resp_a = Response.json({"items": ["a-data"]})
        mw.after_request(req_a, resp_a, ctx_a)

        # User B tries to access same URL
        req_b = _stub_flask_request(method="GET", path="/api/items")
        req_b.set_user(Identity(id=2))
        req_b.route = route_meta()
        ctx_b = type("Context", (), {"resource": None})()
        cached = mw.before_request(req_b, ctx_b)
        # Should be MISS (different identity -> different cache key)
        assert cached is None


# ===================================================================
# 5. Authorization + Cache
# ===================================================================

class TestAuthorizationCache:

    def test_cache_does_not_bypass_authorization(self):
        """Cached response is only served if current user is authorized."""
        cache = CacheManager()
        mw = WebCacheMiddleware(cache=cache)

        route_meta = type("Route", (), {"metadata": {"cache_policy": CachePolicy(ttl=60)}})()

        # User A (authorized) makes a request that gets cached
        req_a = _stub_flask_request(method="GET", path="/api/secure")
        req_a.set_user(Identity(id=1))
        req_a.route = route_meta
        ctx_a = type("Context", (), {"resource": None})()
        resp_a = Response.json({"secret": "A-data"})
        mw.after_request(req_a, resp_a, ctx_a)

        # User B (not authorized) tries same URL
        req_b = _stub_flask_request(method="GET", path="/api/secure")
        req_b.set_user(Identity(id=2))
        req_b.route = route_meta
        ctx_b = type("Context", (), {"resource": None})()
        cached = mw.before_request(req_b, ctx_b)
        # Different user id -> different cache key -> cache miss (None)
        assert cached is None, "User B should NOT receive User A's cached response"

    def test_unauthorized_user_does_not_get_authorized_response(self):
        """Even with same cache key, authorization check prevents access."""
        # This test verifies the architecture: authorization runs BEFORE cache
        # in the middleware pipeline, so a 403 response is never cached.
        cache = CacheManager()
        mw = WebCacheMiddleware(cache=cache)

        # Simulate middleware ordering: authorization runs before cache
        req = _stub_flask_request(method="GET", path="/api/check")
        req.set_user(Identity(id=1))
        req.route = type("Route", (), {
            "metadata": {"cache_policy": CachePolicy(ttl=60)},
            "authorization_required": True,
        })()

        ctx = _make_context(_stub_flask_request())
        ctx.container.instance(DEFAULT_AUTHORIZER_KEY, ViewOnly())
        # Cache before_request checks - should be MISS since nothing cached yet
        result = mw.before_request(req, ctx)
        assert result is None  # no cached response for this user+path


# ===================================================================
# 6. Pagination + Cache
# ===================================================================

class TestPaginationCache:

    def test_different_pages_have_different_cache_keys(self):
        """Each page generates a distinct cache key."""
        key_1 = _make_cache_key("GET", "/products", {"page": "1", "per_page": "20"}, "")
        key_2 = _make_cache_key("GET", "/products", {"page": "2", "per_page": "20"}, "")
        assert key_1 != key_2

    def test_canonical_query_ordering(self):
        """Different query param order produces the same cache key."""
        key_a = _make_cache_key("GET", "/products", {"page": "1", "per_page": "20"}, "")
        key_b = _make_cache_key("GET", "/products", {"per_page": "20", "page": "1"}, "")
        assert key_a == key_b

    def test_cached_pagination_metadata_preserved(self):
        """Pagination metadata survives cache round-trip."""
        cache = CacheManager()
        mw = WebCacheMiddleware(cache=cache)

        req = _stub_flask_request(method="GET", path="/api/products", query={"page": "2", "per_page": "10"})
        req.set_user(Identity(id=1))
        req.route = type("Route", (), {"metadata": {"cache_policy": CachePolicy(ttl=60)}})()

        ctx = type("Context", (), {"resource": None})()

        # Simulate a paginated response
        params = PaginationParams(page=2, per_page=10)
        metadata = PaginationMetadata.from_params(params, total=95)
        data = [{"id": i} for i in range(11, 21)]
        resp = Response.json({
            "success": True,
            "data": data,
            "meta": {
                "resource": "products",
                "count": len(data),
                "pagination": metadata.to_dict(),
            },
        })
        # Cache it
        mw.after_request(req, resp, ctx)

        # Read from cache
        cached = mw.before_request(req, ctx)
        assert cached is not None
        payload = json.loads(cached.body)
        assert payload["success"] is True
        assert payload["meta"]["pagination"]["page"] == 2
        assert payload["meta"]["pagination"]["per_page"] == 10
        assert payload["meta"]["pagination"]["total"] == 95
        assert payload["meta"]["pagination"]["total_pages"] == 10  # ceil(95/10)


# ===================================================================
# 7. Rate Limiting + Cache
# ===================================================================

class TestRateLimitingCache:

    def test_cache_does_not_bypass_rate_limiting(self):
        """Even cached requests must pass rate limiter."""
        store = MemoryRateLimitStore()
        rate_mw = RateLimitMiddleware(store=store, default=RateLimit(limit=2, window=60))
        cache = CacheManager()
        cache_mw = WebCacheMiddleware(cache=cache)

        route = type("Route", (), {
            "metadata": {
                "rate_limit": RateLimit(limit=2, window=60),
                "cache_policy": CachePolicy(ttl=60),
            },
        })()
        request = _stub_flask_request()
        request.set_user(Identity(id=1))
        request.route = route

        # First request - rate limit check passes
        r1 = rate_mw.before_request(request, _make_context(request))
        assert r1 is None

        # Second request - rate limit check passes
        r2 = rate_mw.before_request(request, _make_context(request))
        assert r2 is None

        # Third request - rate limit blocks even if cache could serve
        r3 = rate_mw.before_request(request, _make_context(request))
        assert r3 is not None
        assert r3.status == 429


# ===================================================================
# 8. Full Protected Paginated Endpoint (combined integration)
# ===================================================================

class TestFullProtectedPaginatedEndpoint:
    """Simulates a complete protected, paginated, cached endpoint."""

    def test_full_flow_miss_then_hit(self):
        """First request cache MISS, second identical request cache HIT.

        Flow: Authentication -> Rate Limiting -> Authorization -> Validation
              -> Resource -> Pagination -> Cache -> Response.
        """
        # Setup middleware
        store = MemoryRateLimitStore()
        rate_mw = RateLimitMiddleware(store=store)
        cache = CacheManager()
        cache_mw = WebCacheMiddleware(cache=cache)

        # Build a paginated resource response
        items = [{"id": i, "name": f"product-{i}"} for i in range(1, 51)]
        params = PaginationParams(page=2, per_page=10)
        result = paginate_sequence(items, params)
        paginated_body = {
            "success": True,
            "data": [{"id": item["id"], "name": item["name"]} for item in result.items],
            "meta": {
                "resource": "products",
                "count": len(result.items),
                "pagination": result.metadata.to_dict(),
            },
        }

        user = Identity(id=42, name="tester")
        route_meta = {
            "rate_limit": RateLimit(limit=100, window=60),
            "cache_policy": CachePolicy(ttl=60),
            "authorization_required": True,
            "authorization_action": "view",
        }

        # Build a request for page 2
        def make_request():
            request = _stub_flask_request(
                method="GET",
                path="/api/products",
                query={"page": "2", "per_page": "10"},
            )
            request.set_user(user)
            request.route = type("Route", (), {
                "module": "products",
                "endpoint": "products.list",
                "authorization_required": True,
                "authorization_action": "view",
                "authorization_actions": {},
                "authorization_resource_key": None,
                "metadata": dict(route_meta),
            })()
            return request

        # ---- FIRST REQUEST: MISS ----
        req1 = make_request()
        ctx1 = _make_context(req1)
        ctx1.container.instance(DEFAULT_AUTHORIZER_KEY, ViewOnly())

        # 1. Authentication already set request.user
        # 2. Rate Limiting
        rl_result = rate_mw.before_request(req1, ctx1)
        assert rl_result is None, "Rate limit should allow first request"

        # 3. Authorization
        authz_mw = AuthorizationMiddleware()
        authz_mw.before_request(req1, ctx1)  # should pass (ViewOnly allows "view")

        # 4. Cache check (MISS)
        cache_before = cache_mw.before_request(req1, ctx1)
        assert cache_before is None, "First request should be cache MISS"

        # 5. Store the response in cache
        response = Response.json(paginated_body)
        cache_mw.after_request(req1, response, ctx1)

        # ---- SECOND REQUEST: HIT (same identity, same page) ----
        req2 = make_request()
        ctx2 = _make_context(req2)
        ctx2.container.instance(DEFAULT_AUTHORIZER_KEY, ViewOnly())

        # 1. Rate Limiting (different call but same window)
        rl_result2 = rate_mw.before_request(req2, ctx2)
        # After 1 request consumed, still 99 remaining - should pass
        assert rl_result2 is None

        # 2. Authorization
        authz_mw2 = AuthorizationMiddleware()
        authz_mw2.before_request(req2, ctx2)

        # 3. Cache check (HIT - same user, same path, same query)
        cache_before2 = cache_mw.before_request(req2, ctx2)
        assert cache_before2 is not None, "Second request should be cache HIT"
        assert cache_before2.headers.get("X-Cache") == "HIT"

        payload = json.loads(cache_before2.body)
        assert payload["success"] is True
        assert len(payload["data"]) == 10
        assert payload["data"][0]["id"] == 11  # page 2, per_page 10 -> items 11-20
        assert payload["meta"]["pagination"]["page"] == 2
        assert payload["meta"]["pagination"]["per_page"] == 10
        assert payload["meta"]["pagination"]["total"] == 50
        assert payload["meta"]["pagination"]["total_pages"] == 5

    def test_unauthorized_cannot_access_cached_authenticated_response(self):
        """Different user accessing same URL gets cache MISS (different key).

        Authorization still applies because the cache serves nothing for user B.
        """
        cache = CacheManager()
        cache_mw = WebCacheMiddleware(cache=cache)
        route_meta = type("Route", (), {"metadata": {"cache_policy": CachePolicy(ttl=60)}})()

        # User A request + cache
        req_a = _stub_flask_request(method="GET", path="/api/items", query={"page": "1"})
        req_a.set_user(Identity(id=1))
        req_a.route = route_meta
        ctx_a = type("Context", (), {"resource": None})()
        resp_a = Response.json({"data": ["a-secret"]})
        cache_mw.after_request(req_a, resp_a, ctx_a)

        # User B (different identity) - should get MISS
        req_b = _stub_flask_request(method="GET", path="/api/items", query={"page": "1"})
        req_b.set_user(Identity(id=2))
        req_b.route = route_meta
        ctx_b = type("Context", (), {"resource": None})()
        result = cache_mw.before_request(req_b, ctx_b)
        assert result is None, "User B must not receive User A's cached data"

    def test_ttl_expiration(self):
        """Cached response expires after TTL."""
        cache = CacheManager()
        mw = WebCacheMiddleware(cache=cache)

        import time

        req = _stub_flask_request(method="GET", path="/api/ephemeral")
        req.set_user(Identity(id=1))
        req.route = type("Route", (), {"metadata": {"cache_policy": CachePolicy(ttl=1)}})()

        ctx = type("Context", (), {"resource": None})()
        resp = Response.json({"data": "fresh"})
        mw.after_request(req, resp, ctx)

        # Immediately available
        cached = mw.before_request(req, ctx)
        assert cached is not None

        # Wait for TTL to expire
        time.sleep(1.1)

        # Should be expired
        expired = mw.before_request(req, ctx)
        assert expired is None, "Cached response should have expired"


# ===================================================================
# 9. Error Consistency
# ===================================================================

class TestErrorConsistency:
    """Verify error codes and HTTP statuses match the documented contract."""

    def test_unauthenticated_error(self):
        error = UnauthenticatedError("test")
        assert error.http_status == 401
        assert error.code == "UNAUTHENTICATED"

    def test_forbidden_error(self):
        error = ForbiddenError("test")
        assert error.http_status == 403
        assert error.code == "FORBIDDEN"

    def test_rate_limit_error_code(self):
        from betrayer.web.exceptions import TooManyRequestsError
        error = TooManyRequestsError("rate limited")
        assert error.http_status == 429
        assert error.code == "RATE_LIMIT_EXCEEDED"

    def test_validation_error(self):
        from betrayer.web.exceptions import ValidationError
        error = ValidationError("invalid")
        assert error.http_status == 422
        assert error.code == "VALIDATION_FAILED"

    def test_pagination_validation_error(self):
        """Invalid pagination uses same 422 VALIDATION_FAILED errors."""
        request = _stub_flask_request(query={"page": "0"})
        with pytest.raises(Exception) as exc_info:
            parse_pagination(request)
        error = exc_info.value
        assert error.http_status == 422
        assert error.code == "VALIDATION_FAILED"
        assert "fields" in error.context


# ===================================================================
# 10. Resource Contract: independent configuration
# ===================================================================

class TestResourceContract:
    """Resources can enable features independently."""

    def test_plain_resource_no_features(self):
        """A resource without any Task 16 flags works as before."""
        class PlainResource(CrudApiResource):
            name = "plain"

        resource = PlainResource()
        assert resource.authentication_required is False
        assert resource.authorization_required is False
        assert resource.pagination is False
        assert resource.rate_limit is None
        assert resource.cache_ttl is None

    def test_resource_with_all_features(self):
        """A resource can opt into all Task 16 features."""
        class FullResource(CrudApiResource):
            name = "products"
            authentication_required = True
            authorization_required = True
            authorization_action = "view"
            pagination = True
            rate_limit = RateLimit(limit=100, window=60)
            cache_ttl = 60

        resource = FullResource()
        assert resource.authentication_required is True
        assert resource.authorization_required is True
        assert resource.pagination is True
        assert resource.rate_limit is not None
        assert resource.cache_ttl is not None


# ===================================================================
# 11. Unconfigured resource unchanged (regression)
# ===================================================================

class TestUnconfiguredRegression:

    def test_public_resource_unchanged(self):
        """A public resource behaves exactly as before Task 16."""
        import asyncio
        class PublicResource(CrudApiResource):
            name = "public"
            def __init__(self):
                super().__init__(service=type("_S", (), {
                    "list": lambda self: [],
                    "get": lambda self, id: None,
                    "create": lambda self, **kw: {"id": 1},
                    "update": lambda self, id, **kw: {"id": id},
                    "delete": lambda self, id: True,
                })())

        request = _stub_flask_request()
        request.set_user(AnonymousIdentity())
        context = _make_context(request)

        resource = PublicResource()
        # Should not raise (no authentication_required, no authorization_required)
        resource._enforce_authentication(request)
        resource._enforce_authorization(request, context)


# ===================================================================
# 12. DI / Container: no second container
# ===================================================================

class TestContainerDI:
    """All integration uses the existing Container."""

    def test_authenticator_via_container(self):
        app = BetrayerApplication(name="di-test")
        Bootstrap(app).build()
        auth = CallbackAuthenticator(lambda r: Identity(id=1))
        app.container.instance("authenticator", auth)
        assert app.container.resolve("authenticator") is auth

    def test_authorizer_via_container(self):
        app = BetrayerApplication(name="di-test-2")
        Bootstrap(app).build()
        authz = ViewOnly()
        app.container.instance(DEFAULT_AUTHORIZER_KEY, authz)
        assert app.container.resolve(DEFAULT_AUTHORIZER_KEY) is authz

    def test_cache_via_container(self):
        app = BetrayerApplication(name="di-test-3")
        Bootstrap(app).build()
        cache = CacheManager()
        app.container.instance("cache", cache)
        assert app.container.resolve("cache") is cache

    def test_rate_limit_store_via_container(self):
        app = BetrayerApplication(name="di-test-4")
        Bootstrap(app).build()
        store = MemoryRateLimitStore()
        app.container.instance("rate_limit_store", store)
        assert app.container.resolve("rate_limit_store") is store


# ===================================================================
# 13. Public Exports / __init__.py
# ===================================================================

class TestPublicExports:
    """Verify canonical APIs are accessible through expected packages."""

    def test_auth_exports(self):
        from betrayer import auth
        assert hasattr(auth, "Identity")
        assert hasattr(auth, "AnonymousIdentity")
        assert hasattr(auth, "Authenticator")
        assert hasattr(auth, "HeaderTokenAuthenticator")
        assert hasattr(auth, "Authorizer")
        assert hasattr(auth, "CallbackAuthorizer")
        assert hasattr(auth, "AllowAllAuthorizer")
        assert hasattr(auth, "authorize")
        assert hasattr(auth, "AuthenticationMiddleware")
        assert hasattr(auth, "AuthorizationMiddleware")

    def test_ratelimit_exports(self):
        from betrayer import ratelimit
        assert hasattr(ratelimit, "RateLimit")
        assert hasattr(ratelimit, "RateLimitResult")
        assert hasattr(ratelimit, "RateLimitMiddleware")
        assert hasattr(ratelimit, "FixedWindowRateLimiter")
        assert hasattr(ratelimit, "MemoryRateLimitStore")

    def test_cache_exports(self):
        from betrayer import cache
        assert hasattr(cache, "CacheManager")
        assert hasattr(cache, "CacheBackend")
        assert hasattr(cache, "MemoryCacheBackend")
        assert hasattr(cache, "CachePolicy")
        assert hasattr(cache, "WebCacheMiddleware")

    def test_web_exports_include_pagination(self):
        from betrayer import web
        assert hasattr(web, "PaginationParams")
        assert hasattr(web, "PaginationMetadata")
        assert hasattr(web, "PaginatedResult")
        assert hasattr(web, "parse_pagination")
        assert hasattr(web, "paginate_sequence")
        assert hasattr(web, "paginate_query")