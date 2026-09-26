"""Routing: HTTP routes as data.

One primary API, no second way of doing the same thing::

    router.get("/users", handler)              # registers and returns a Route
    @router.get("/users/<int:user_id>")        # same call, handler omitted
    def get_user(request, context) -> Response: ...

    users = router.module_scoped("users")      # module ownership recorded
    users.post("/users", create_user)

Handlers always have the signature ``handler(request, context) -> Response``
(see :mod:`betrayer.web.request` and :mod:`betrayer.web.context`).

Store
-----

Routes live in :class:`WebRouteRegistry`, a *domain specific* table owned by the
web adapter.  It is **not** a second generic registry: routes are HTTP
resources (method + path), not components, and the table itself is published
through the single application registry under the name ``web.router``::

    context.registry.get("web.router")
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence, Tuple

from .exceptions import NotFoundError, RouteError

__all__ = [
    "HTTP_METHODS",
    "Route",
    "WebRouteRegistry",
    "WebRouter",
    "ModuleRouter",
    "handler_name",
    "normalize_method",
    "normalize_path",
    "module_name",
]

#: HTTP methods the web layer knows about (and can register).
HTTP_METHODS: Tuple[str, ...] = (
    "GET",
    "POST",
    "PUT",
    "PATCH",
    "DELETE",
    "OPTIONS",
    "HEAD",
)

#: URL converters understood by the introspection matcher.  Flask remains the
#: authority for real dispatch; this table keeps ``match()`` predictable.
_CONVERTERS = ("string", "int", "float", "path", "uuid")


def normalize_method(method: Any) -> str:
    """Return the upper case HTTP method or raise :class:`RouteError`."""
    if not isinstance(method, str) or not method.strip():
        raise RouteError(
            message="HTTP method must be a non empty string",
            code="ROUTE_INVALID_METHOD",
            context={"method": repr(method)},
        )
    normalized = method.strip().upper()
    if normalized not in HTTP_METHODS:
        raise RouteError(
            message=f"Unsupported HTTP method: {normalized}",
            code="ROUTE_INVALID_METHOD",
            context={"method": normalized, "supported": list(HTTP_METHODS)},
        )
    return normalized


def normalize_path(path: Any) -> str:
    """Return a normalized route path (leading ``/``, no trailing ``/``)."""
    if not isinstance(path, str) or not path.strip():
        raise RouteError(
            message="Route path must be a non empty string",
            code="ROUTE_INVALID_PATH",
            context={"path": repr(path)},
        )
    normalized = path.strip()
    if not normalized.startswith("/"):
        raise RouteError(
            message="Route path must start with '/'",
            code="ROUTE_INVALID_PATH",
            context={"path": normalized},
        )
    if len(normalized) > 1:
        normalized = normalized.rstrip("/") or "/"
    return normalized


def module_name(module: Any) -> Optional[str]:
    """Return a module name for ``module`` (string, module object or ``None``)."""
    if module is None:
        return None
    if isinstance(module, str):
        return module.strip() or None
    name = getattr(module, "module_name", None)
    if callable(name):
        return name() or None
    name = getattr(module, "name", None)
    if isinstance(name, str) and name.strip():
        return name.strip()
    return type(module).__name__


def middleware_name(middleware: Any) -> str:
    """Return the registered name of a middleware object or name string."""
    if isinstance(middleware, str):
        return middleware
    name = getattr(middleware, "middleware_name", None)
    if callable(name):
        return name()
    name = getattr(middleware, "name", None)
    if isinstance(name, str) and name.strip():
        return name.strip()
    return type(middleware).__name__


def handler_name(handler: Callable[..., Any]) -> str:
    """Qualified, readable handler reference (e.g. ``UserModule.get``)."""
    if handler is None:
        return ""
    owner = getattr(handler, "__self__", None)
    if owner is not None and not isinstance(owner, type):
        return f"{type(owner).__name__}.{getattr(handler, '__name__', 'callable')}"
    name = getattr(handler, "__name__", None)
    if isinstance(name, str) and name:
        return name
    return type(handler).__name__


def _default_endpoint(handler: Callable[..., Any], module: Optional[str]) -> str:
    base = getattr(handler, "__name__", None) or "handler"
    return f"{module}.{base}" if module else str(base)


class Route:
    """A single ``method + path -> handler`` declaration.

    Attributes are plain data so introspection is trivial:

    ============  =======================================================
    ``method``    HTTP method (upper case).
    ``path``      Normalized path, ``<name>`` / ``<int:name>`` placeholders.
    ``endpoint``  Unique name inside the route table (used by Flask too).
    ``handler``   Callable ``handler(request, context) -> Response``.
    ``module``    Owning module name, or ``None`` when not declared.
    ``middleware``Tuple of middleware names applied to this route only.
    ``metadata``  Free form mapping for application/tooling use.
    ============  =======================================================
    """

    __slots__ = ("method", "path", "endpoint", "handler", "module", "middleware", "metadata")

    def __init__(
        self,
        method: str,
        path: str,
        handler: Callable[..., Any],
        *,
        endpoint: Optional[str] = None,
        module: Any = None,
        middleware: Optional[Sequence[Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not callable(handler):
            raise RouteError(
                message="Route handler must be callable",
                code="ROUTE_INVALID_HANDLER",
                context={"path": path, "handler": repr(handler)},
            )
        self.method = normalize_method(method)
        self.path = normalize_path(path)
        self.handler = handler
        self.module = module_name(module)
        self.middleware: Tuple[str, ...] = tuple(
            middleware_name(item) for item in (middleware or ())
        )
        self.metadata: Dict[str, Any] = dict(metadata or {})
        self.endpoint = endpoint or _default_endpoint(handler, self.module)

    # -- introspection ----------------------------------------------
    def to_dict(self) -> dict:
        """JSON friendly metadata (the shape an LLM wants to read)."""
        return {
            "method": self.method,
            "path": self.path,
            "endpoint": self.endpoint,
            "handler": handler_name(self.handler),
            "module": self.module,
            "middleware": list(self.middleware),
            "metadata": dict(self.metadata),
        }

    describe = to_dict

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Route {self.method} {self.path} -> {self.endpoint}>"


def _split_path(path: str) -> List[str]:
    return [segment for segment in path.strip("/").split("/") if segment]


def _is_float(value: str) -> bool:
    try:
        float(value)
    except (TypeError, ValueError):
        return False
    return True


def _match_path(pattern: str, concrete: str) -> Optional[Dict[str, str]]:
    """Match a route pattern against a concrete path; ``None`` when no match."""
    pattern_segments = _split_path(pattern)
    concrete_segments = _split_path(concrete)
    if len(pattern_segments) != len(concrete_segments):
        return None
    params: Dict[str, str] = {}
    for expected, actual in zip(pattern_segments, concrete_segments):
        if expected.startswith("<") and expected.endswith(">"):
            inner = expected[1:-1]
            converter, _, name = inner.partition(":")
            name = name or converter
            if converter == "int" and not actual.lstrip("-").isdigit():
                return None
            if converter == "float" and not _is_float(actual):
                return None
            params[name] = actual
        elif expected != actual:
            return None
    return params


class WebRouteRegistry:
    """Ordered route table of one web adapter (domain specific, not global)."""

    def __init__(self, name: str = "web.router") -> None:
        self.name = name
        self._routes: List[Route] = []

    # -- mutation ----------------------------------------------------
    def add(self, route: Route) -> Route:
        """Append ``route``; duplicate ``method + path`` is rejected.

        Endpoint collisions (same handler name for several methods) are
        resolved deterministically by appending the lower case method, e.g.
        ``users.list_users.post``.
        """
        if not isinstance(route, Route):
            raise RouteError(
                message="WebRouteRegistry.add expects a Route instance",
                code="ROUTE_INVALID",
                context={"value": repr(route)},
            )
        for existing in self._routes:
            if existing.path == route.path and existing.method == route.method:
                raise RouteError(
                    message=f"Route already registered: {route.method} {route.path}",
                    code="ROUTE_DUPLICATE",
                    context={
                        "method": route.method,
                        "path": route.path,
                        "endpoint": existing.endpoint,
                    },
                )
        route.endpoint = self._unique_endpoint(route.endpoint, route.method)
        self._routes.append(route)
        return route

    register = add

    def remove(self, path: str, method: str = "GET") -> Route:
        """Remove and return the route for ``path`` + ``method``."""
        route = self.get(path, method)
        self._routes.remove(route)
        return route

    def clear(self) -> None:
        """Drop every route (used by tests/tooling, not at request time)."""
        self._routes.clear()

    # -- lookup ------------------------------------------------------
    def get(self, path: str, method: str = "GET") -> Route:
        """Return the exact route for ``path`` + ``method`` or raise."""
        wanted_method = normalize_method(method)
        wanted_path = normalize_path(path)
        for route in self._routes:
            if route.path == wanted_path and route.method == wanted_method:
                return route
        raise NotFoundError(
            message=f"Unknown route: {wanted_method} {wanted_path}",
            code="ROUTE_NOT_FOUND",
            context={"method": wanted_method, "path": wanted_path},
        )

    def find(
        self,
        *,
        method: Optional[str] = None,
        path: Optional[str] = None,
        module: Optional[Any] = None,
        endpoint: Optional[str] = None,
        middleware: Optional[str] = None,
        handler: Optional[Callable[..., Any]] = None,
    ) -> List[Route]:
        """Filter routes; unknown filters narrow the result, never raise."""
        wanted_method = normalize_method(method) if method else None
        wanted_path = normalize_path(path) if path else None
        wanted_module = module_name(module) if module is not None else None
        matches: List[Route] = []
        for route in self._routes:
            if wanted_method and route.method != wanted_method:
                continue
            if wanted_path and route.path != wanted_path:
                continue
            if wanted_module is not None and route.module != wanted_module:
                continue
            if endpoint and route.endpoint != endpoint:
                continue
            if middleware and middleware_name(middleware) not in route.middleware:
                continue
            if handler is not None and route.handler is not handler:
                continue
            matches.append(route)
        return matches

    def exists(self, path: str, method: Optional[str] = None) -> bool:
        """``True`` when ``path`` (optionally ``method``) is registered."""
        wanted_path = normalize_path(path)
        if method is None:
            return any(route.path == wanted_path for route in self._routes)
        wanted_method = normalize_method(method)
        return any(
            route.path == wanted_path and route.method == wanted_method
            for route in self._routes
        )

    def methods_for(self, path: str) -> List[str]:
        """HTTP methods registered for ``path`` (deterministic order)."""
        wanted_path = normalize_path(path)
        return sorted(
            route.method for route in self._routes if route.path == wanted_path
        )

    def for_module(self, module: Any) -> List[Route]:
        """Routes owned by ``module``."""
        return self.find(module=module)

    def match(self, method: str, path: str) -> Optional[Tuple[Route, Dict[str, str]]]:
        """Introspection-grade matcher: ``(route, path_params)`` or ``None``.

        Flask stays the authority for real dispatch; this only exists so an
        LLM/tool can answer "which route matches this request?" without
        starting a server.
        """
        wanted_method = normalize_method(method)
        wanted_path = normalize_path(path)
        for route in self._routes:
            if route.method != wanted_method:
                continue
            params = _match_path(route.path, wanted_path)
            if params is not None:
                return route, params
        return None

    # -- introspection ----------------------------------------------
    def list(self) -> List[Route]:
        """Routes in registration order."""
        return list(self._routes)

    def describe(self) -> List[dict]:
        """Routes as JSON friendly dicts, sorted by ``(path, method)``."""
        return [
            route.to_dict()
            for route in sorted(self._routes, key=lambda item: (item.path, item.method))
        ]

    def to_dict(self) -> dict:
        """Full table snapshot."""
        return {
            "name": self.name,
            "count": len(self._routes),
            "routes": self.describe(),
        }

    def _unique_endpoint(self, base: str, method: str) -> str:
        taken = {route.endpoint for route in self._routes}
        if base not in taken:
            return base
        candidate = f"{base}.{method.lower()}"
        if candidate not in taken:
            return candidate
        index = 2
        while f"{candidate}.{index}" in taken:
            index += 1
        return f"{candidate}.{index}"

    def __len__(self) -> int:
        return len(self._routes)

    def __iter__(self) -> Iterator[Route]:
        return iter(list(self._routes))

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<WebRouteRegistry name={self.name!r} routes={len(self._routes)}>"


class WebRouter:
    """Route declaration API of the web adapter (the only registration path).

    Use the verb helpers (``get``, ``post``, ...) or the generic ``route`` /
    ``add`` form; all of them return the created :class:`Route` when a handler
    is given, and a decorator when it is omitted.
    """

    def __init__(
        self,
        routes: Optional[WebRouteRegistry] = None,
        *,
        middleware_registry: Any = None,
        name: str = "web.router",
    ) -> None:
        self.name = name
        self.routes = routes if routes is not None else WebRouteRegistry(name=name)
        self.middleware_registry = middleware_registry

    # -- generic -----------------------------------------------------
    def add(
        self,
        method: str,
        path: str,
        handler: Optional[Callable[..., Any]] = None,
        *,
        name: Optional[str] = None,
        middleware: Optional[Sequence[Any]] = None,
        module: Any = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """Register a route (or return a decorator when ``handler`` is ``None``)."""
        resolved_method = normalize_method(method)
        resolved_path = normalize_path(path)

        def register(target: Callable[..., Any]) -> Route:
            self._check_middleware(middleware)
            route = Route(
                resolved_method,
                resolved_path,
                target,
                endpoint=name,
                module=module,
                middleware=middleware,
                metadata=metadata,
            )
            return self.routes.add(route)

        if handler is None:
            return register
        return register(handler)

    def route(
        self,
        path: str,
        handler: Optional[Callable[..., Any]] = None,
        *,
        methods: Sequence[str] = ("GET",),
        name: Optional[str] = None,
        middleware: Optional[Sequence[Any]] = None,
        module: Any = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """Register ``handler`` for several methods at once.

        Returns the list of created routes (or a decorator when ``handler`` is
        ``None``).
        """
        resolved_methods = [normalize_method(item) for item in methods]

        def register(target: Callable[..., Any]) -> List[Route]:
            return [
                self.add(
                    method,
                    path,
                    target,
                    name=name,
                    middleware=middleware,
                    module=module,
                    metadata=metadata,
                )
                for method in resolved_methods
            ]

        if handler is None:
            return register
        return register(handler)

    # -- verb helpers ------------------------------------------------
    def get(self, path, handler=None, **options) -> Any:
        """Register a ``GET`` route."""
        return self.add("GET", path, handler, **options)

    def post(self, path, handler=None, **options) -> Any:
        """Register a ``POST`` route."""
        return self.add("POST", path, handler, **options)

    def put(self, path, handler=None, **options) -> Any:
        """Register a ``PUT`` route."""
        return self.add("PUT", path, handler, **options)

    def patch(self, path, handler=None, **options) -> Any:
        """Register a ``PATCH`` route."""
        return self.add("PATCH", path, handler, **options)

    def delete(self, path, handler=None, **options) -> Any:
        """Register a ``DELETE`` route."""
        return self.add("DELETE", path, handler, **options)

    def options(self, path, handler=None, **options) -> Any:
        """Register an ``OPTIONS`` route (Flask's automatic OPTIONS is off)."""
        return self.add("OPTIONS", path, handler, **options)

    def head(self, path, handler=None, **options) -> Any:
        """Register a ``HEAD`` route."""
        return self.add("HEAD", path, handler, **options)

    # -- module ownership --------------------------------------------
    def module_scoped(self, module: Any) -> "ModuleRouter":
        """Return a view that stamps ``module`` on every route it registers."""
        return ModuleRouter(self, module)

    # -- introspection ----------------------------------------------
    def describe(self) -> List[dict]:
        """Route metadata, sorted by ``(path, method)``."""
        return self.routes.describe()

    def to_dict(self) -> dict:
        """``WebRouteRegistry`` snapshot."""
        return self.routes.to_dict()

    def _check_middleware(self, middleware: Optional[Sequence[Any]]) -> None:
        if not middleware or self.middleware_registry is None:
            return
        for item in middleware:
            name = middleware_name(item)
            if not self.middleware_registry.exists(name):
                raise RouteError(
                    message=f"Unknown middleware referenced by route: {name}",
                    code="MIDDLEWARE_NOT_FOUND",
                    context={"middleware": name},
                )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<WebRouter routes={len(self.routes)}>"


class ModuleRouter:
    """Module scoped view of :class:`WebRouter` (records module ownership)."""

    def __init__(self, router: WebRouter, module: Any) -> None:
        self.router = router
        self.module = module_name(module)

    def add(self, method: str, path: str, handler=None, **options) -> Any:
        """Register a route owned by this module."""
        options.setdefault("module", self.module)
        return self.router.add(method, path, handler, **options)

    def route(self, path: str, handler=None, **options) -> Any:
        """Register a multi-method route owned by this module."""
        options.setdefault("module", self.module)
        return self.router.route(path, handler, **options)

    def get(self, path, handler=None, **options) -> Any:
        """Register a module owned ``GET`` route."""
        return self.add("GET", path, handler, **options)

    def post(self, path, handler=None, **options) -> Any:
        """Register a module owned ``POST`` route."""
        return self.add("POST", path, handler, **options)

    def put(self, path, handler=None, **options) -> Any:
        """Register a module owned ``PUT`` route."""
        return self.add("PUT", path, handler, **options)

    def patch(self, path, handler=None, **options) -> Any:
        """Register a module owned ``PATCH`` route."""
        return self.add("PATCH", path, handler, **options)

    def delete(self, path, handler=None, **options) -> Any:
        """Register a module owned ``DELETE`` route."""
        return self.add("DELETE", path, handler, **options)

    def options(self, path, handler=None, **options) -> Any:
        """Register a module owned ``OPTIONS`` route."""
        return self.add("OPTIONS", path, handler, **options)

    def head(self, path, handler=None, **options) -> Any:
        """Register a module owned ``HEAD`` route."""
        return self.add("HEAD", path, handler, **options)

    def describe(self) -> List[dict]:
        """Route metadata owned by this module."""
        return [route.to_dict() for route in self.router.routes.for_module(self.module)]

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<ModuleRouter module={self.module!r}>"
