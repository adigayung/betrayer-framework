"""Rate limiting middleware — integrates with the existing web pipeline.

The middleware runs ``before_request`` (to check the limit) and
``after_request`` (to attach rate limit headers).  It uses the existing
``Middleware`` contract, adds no second middleware system, and relies on the
framework's error handling for the 429 response.

Pipeline position
-----------------
Register **after** authentication but before resources::

    registry.add(AuthenticationMiddleware(authenticator=...))
    registry.add(RateLimitMiddleware())         # priority=5 or similar
    registry.add(AuthorizationMiddleware())

Key resolution (priority)
-------------------------
1. ``request.user.id`` (authenticated identity) when available,
2. ``request.remote_addr`` (client IP) as fallback.

Opt-in
------
* A **route** may carry ``rate_limit`` metadata (a ``RateLimit``) that
  overrides the default for that specific endpoint.
* A **resource** advertises ``rate_limit`` class attribute pushed into
  route metadata by the resource adapter.
* Routes/resources without rate limit metadata are **not** rate limited
  by this middleware.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional, Tuple

from betrayer.ratelimit.limit import RateLimit, RateLimitResult
from betrayer.ratelimit.limiter import FixedWindowRateLimiter
from betrayer.ratelimit.store import MemoryRateLimitStore, RateLimitStore


#: Metadata key on a Route for rate limit configuration.
RATE_LIMIT_META_KEY = "rate_limit"

#: Default rate limit applied when the route has no explicit configuration.
#: Set to ``None`` to disable default rate limiting.
DEFAULT_RATE_LIMIT: Optional[RateLimit] = None


class RateLimitMiddleware:
    """HTTP middleware that enforces rate limits on opted-in routes.

    The middleware must be registered **after** authentication but **before**
    resource handlers.  Routes without ``rate_limit`` metadata are skipped.

    Usage::

        from betrayer.ratelimit import RateLimitMiddleware

        registry = app.registry.get("web.middleware")
        registry.add(RateLimitMiddleware(default=RateLimit(100, 60)))
    """

    name = "rate_limiting"
    priority: int = 5  # After authentication (0), before authorization (10)

    def __init__(
        self,
        *,
        store: Optional[RateLimitStore] = None,
        default: Optional[RateLimit] = None,
    ) -> None:
        self._store = store or MemoryRateLimitStore()
        self._limiter = FixedWindowRateLimiter(store=self._store)
        self._default_limit = (
            default if default is not None else DEFAULT_RATE_LIMIT
        )

    # -- public API -----------------------------------------------------

    @property
    def limiter(self) -> FixedWindowRateLimiter:
        """The underlying ``FixedWindowRateLimiter`` for explicit checks."""
        return self._limiter

    def check(
        self,
        key: str,
        limit: RateLimit,
        *,
        amount: int = 1,
    ) -> RateLimitResult:
        """Explicit rate limit check (anywhere in application code)."""
        return self._limiter.check(key, limit, amount=amount)

    # -- hooks ---------------------------------------------------------

    def before_request(self, request: Any, context: Any) -> Any:
        """Check rate limit before the request reaches the handler.

        Returns ``None`` (continue) or a ``Response`` (short-circuit with 429).
        """
        route = getattr(request, "route", None)
        if route is None:
            return None

        rate_limit = self._resolve_limit(route)
        if rate_limit is None:
            return None

        key = self._resolve_key(request)
        result = self._limiter.check(key, rate_limit)

        if not result.allowed:
            return self._build_429_response(result, rate_limit)

        # Attach result to request for after_request to read
        request._rate_limit_result = result
        return None

    def after_request(
        self,
        request: Any,
        response: Any,
        context: Any,
    ) -> Any:
        """Attach rate limit headers to the response.

        Only routes that were rate limited (``request._rate_limit_result``
        set) get the headers.  All other responses are untouched.
        """
        result = getattr(request, "_rate_limit_result", None)
        if result is None:
            return None  # unchanged

        # Add headers
        set_header = getattr(response, "with_header", None)
        if callable(set_header):
            response = set_header("X-RateLimit-Limit", str(result.limit))
            response = set_header("X-RateLimit-Remaining", str(result.remaining))
            response = set_header(
                "X-RateLimit-Reset", str(int(result.reset_at))
            )
            # Retry-After if limit exceeded
            if not result.allowed:
                retry_after = max(0, int(result.reset_at - time.time()))
                response = set_header("Retry-After", str(retry_after))
            return response
        return None

    # -- internals -----------------------------------------------------

    def _resolve_limit(self, route: Any) -> Optional[RateLimit]:
        """Resolve rate limit from route metadata or fallback to default.

        Priority:
        1. ``route.metadata.get("rate_limit")`` (a ``RateLimit`` or dict)
        2. Default limit (self._default_limit)
        3. ``None`` (no rate limiting for this route)
        """
        metadata = getattr(route, "metadata", None) or {}
        raw = metadata.get(RATE_LIMIT_META_KEY)
        if raw is not None:
            if isinstance(raw, RateLimit):
                return raw
            if isinstance(raw, dict):
                return RateLimit(**raw)
            return raw
        # Fallback to middleware default
        return self._default_limit

    def _resolve_key(self, request: Any) -> str:
        """Determine the rate limit key for the request.

        Priority:
        1. Authenticated user ID (``request.user.id`` when authenticated)
        2. Remote address (``request.remote_addr``)
        3. ``"anonymous"`` fallback
        """
        user = getattr(request, "user", None)
        if user is not None and not getattr(user, "is_anonymous", True):
            uid = getattr(user, "id", None)
            if uid is not None:
                return f"user:{uid}"
        remote = getattr(request, "remote_addr", None)
        if remote:
            return f"ip:{remote}"
        return "anonymous"

    def _build_429_response(self, result: RateLimitResult, limit: RateLimit) -> Any:
        """Build the HTTP 429 response using the framework error infrastructure.

        Returns a ``Response`` (the middleware short-circuit path).
        """
        from betrayer.web.exceptions import TooManyRequestsError
        from betrayer.web.response import ApiResponse

        retry_after = max(0, int(result.reset_at - time.time()))
        error = TooManyRequestsError(
            message=(
                f"Rate limit exceeded. {result.limit} requests per "
                f"{limit.window}s. Retry after {retry_after}s."
            ),
            headers={
                "X-RateLimit-Limit": str(result.limit),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(int(result.reset_at)),
                "Retry-After": str(retry_after),
            },
        )
        return ApiResponse.error(
            message=str(error.message),
            status=429,
            code="RATE_LIMIT_EXCEEDED",
            headers=error.headers,
        )

    # -- introspection -------------------------------------------------
    def middleware_name(self) -> str:
        return self.name

    def describe(self) -> dict:
        default = None
        if self._default_limit is not None:
            default = self._default_limit.to_dict()
        return {
            "name": self.name,
            "type": type(self).__name__,
            "strategy": "fixed_window",
            "default": default,
            "store": self._store.inspect(),
        }

    to_dict = describe

    def __repr__(self) -> str:
        default = self._default_limit
        return (
            f"<RateLimitMiddleware default={default!r} "
            f"store={type(self._store).__name__}>"
        )