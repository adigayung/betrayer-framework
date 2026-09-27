"""Flask adapter: the runtime link between Betrayer routes and the HTTP engine.

This module is deliberately the *only* place that mounts Betrayer routes onto a
Flask application.  Everything else in the web layer works with plain data
(:class:`~betrayer.web.routing.Route`, :class:`~betrayer.web.request.Request`,
:class:`~betrayer.web.response.Response`); the adapter is the thin edge that
speaks Flask.

Responsibilities
----------------

* Turn a :class:`~betrayer.web.routing.WebRouter` (or several) into Flask
  ``add_url_rule`` calls.
* Build a :class:`~betrayer.web.request.Request` per incoming request,
  including the matched path parameters.
* Call the route handler with the documented signature
  ``handler(request, context) -> Response`` (sync and async handlers are both
  supported).
* Convert Betrayer normalisation results back into Flask responses: a
  :class:`~betrayer.web.response.Response` is serialised with ``to_flask()``,
  a dict is wrapped as JSON, and :class:`~betrayer.web.exceptions.WebError`
  subclasses become the controlled JSON error responses defined in
  :mod:`betrayer.web.errors`.

Usage::

    from betrayer.application import BetrayerApplication
    from betrayer.web.adapter import FlaskAdapter
    from myapp.routes import router

    app = BetrayerApplication(name="my-app")
    adapter = FlaskAdapter(app, router)
    flask_app = adapter.build()      # a real Flask app, ready to serve

The adapter never creates global mutable state: every instance is bound to the
application and routers given to its constructor.
"""

from __future__ import annotations

import inspect
from typing import Any, Callable, Dict, List, Optional, Sequence

from betrayer.web.context import WebContext
from betrayer.web.errors import register_web_error_handlers
from betrayer.web.flask_bridge import import_flask
from betrayer.web.request import Request
from betrayer.web.response import Response
from betrayer.web.routing import WebRouteRegistry, WebRouter

__all__ = ["FlaskAdapter", "route_is_async"]


def route_is_async(handler: Callable[..., Any]) -> bool:
    """Return ``True`` when ``handler`` is a coroutine function.

    Flask 3.1 calls async views natively, so the adapter only needs to know
    whether the view function must be delegated through Flask's async
    machinery (it handles that itself).  The helper exists so the adapter and
    tests agree on one definition.
    """
    return inspect.iscoroutinefunction(handler)


class FlaskAdapter:
    """Serve one or more :class:`~betrayer.web.routing.WebRouter` on Flask.

    Parameters
    ----------
    application:
        The owning :class:`~betrayer.application.BetrayerApplication`.
    routers:
        One router or an iterable of routers to mount.  Every ``Route`` in
        each router becomes a Flask URL rule.
    app:
        An optional pre-built Flask app; when omitted a fresh one is created.
    url_prefix:
        Optional prefix (e.g. ``"/api"``) prepended to every route path.

    The adapter keeps references to the mounted routers so ``describe()`` /
    ``routes`` stay introspectable through the same API the web layer already
    documents.
    """

    def __init__(
        self,
        application: Any,
        routers: Any = None,
        *,
        app: Any = None,
        url_prefix: str = "",
    ) -> None:
        self.application = application
        if routers is None:
            self.router = WebRouter(name="adapter")
            self._routers: List[WebRouter] = [self.router]
        elif isinstance(routers, WebRouter):
            self._routers = [routers]
            self.router = routers
        elif isinstance(routers, WebRouteRegistry):
            router = WebRouter(routes=routers, name=routers.name)
            self._routers = [router]
            self.router = router
        else:
            collected = [item for item in routers]
            self._routers = collected
            self.router = collected[0] if collected else WebRouter(name="adapter")
        self.url_prefix = (url_prefix or "").rstrip("/")
        self._app = app
        self._mounted = False
        # endpoints already registered on the underlying Flask app (a plain
        # dict, so the same route mounted twice with a different base prefix
        # gets a deterministic unique endpoint like ``product.list_handler.2``)
        self._used_endpoints: Dict[str, int] = {}

    # -- collaborators ------------------------------------------------
    @property
    def flask_app(self) -> Any:
        """The Flask application (builds it lazily when never built)."""
        if self._app is None:
            self._app = self.build()
        return self._app

    # -- route helpers ------------------------------------------------
    @property
    def routes(self) -> List[Any]:
        """Every mounted route across all routers (registration order)."""
        routes: List[Any] = []
        for router in self._routers:
            routes.extend(router.routes.list())
        return routes

    # -- mounting ------------------------------------------------------
    def build(self) -> Any:
        """Create (or reuse) the Flask app and register the Betrayer routes.

        Returns the Flask application.  Safe to call repeatedly; the routes
        are mounted only once so a second ``build()`` never raises duplicate
        rule errors.
        """
        flask = import_flask()
        if self._app is None:
            self._app = flask.Flask(self.application.name or "betrayer")
        if not self._mounted:
            for route in self.routes:
                path = self._flask_path(route.path)
                view = self._make_view(route)
                self._app.add_url_rule(
                    path,
                    endpoint=self._unique_endpoint(route.endpoint),
                    view_func=view,
                    methods=[route.method],
                )
            register_web_error_handlers(self._app)
            self._mounted = True
        return self._app

    # -- mounting extra routers ---------------------------------------
    def add_router(self, router: Any, *, prefix: str = "") -> "FlaskAdapter":
        """Mount an additional ``WebRouter`` on this adapter.

        Routes are registered on the underlying Flask app immediately when
        the app was already built, otherwise they are picked up on the next
        ``build()`` (``build()`` remains idempotent).  Returns ``self``.
        """
        from betrayer.web.routing import WebRouteRegistry

        if isinstance(router, WebRouteRegistry):
            router = WebRouter(routes=router, name=router.name)
        if not isinstance(router, WebRouter):
            raise TypeError(
                "add_router expects a WebRouter or WebRouteRegistry, "
                f"got {type(router).__name__}"
            )
        prefix = (prefix or "").rstrip("/")
        if prefix:
            prefixed = WebRouter(name=f"{prefix}.{router.name}")
            for route in router.routes.list():
                prefixed.add(
                    route.method,
                    f"{prefix}{route.path}",
                    route.handler,
                    name=route.endpoint,
                    module=route.module,
                    middleware=list(route.middleware),
                    metadata=dict(route.metadata),
                )
            router = prefixed
        self._routers.append(router)
        if self._mounted and self._app is not None:
            for route in router.routes.list():
                path = self._flask_path(route.path)
                view = self._make_view(route)
                self._app.add_url_rule(
                    path,
                    endpoint=self._unique_endpoint(route.endpoint),
                    view_func=view,
                    methods=[route.method],
                )
        return self

    # -- adapter helpers to reach the middleware registry ----------------
    @property
    def _middleware_registry(self) -> Any:
        """Resolve the web middleware registry from the application, if any."""
        try:
            return self.application.registry.get("web.middleware")
        except Exception:  # noqa: BLE001 - no registry = no middleware
            return None

    # -- pipeline execution ------------------------------------------------
    def pipeline_for(
        self,
        route: Any,
        request: Any,
        context: Any,
    ) -> "WebPipeline":
        """Build a :class:`WebPipeline` for one request, combining route-level
        and global middleware in the documented order:

        1. middleware declared on the route (in the order listed on the route),
        2. the global middleware registry ordered ascending by
           ``(priority, registration index)``.

        Returns a ``WebPipeline`` that is ready to run ``before_request`` /
        ``after_request`` / ``on_error`` hooks.
        """
        from betrayer.web.middleware import WebPipeline as _WebPipeline

        middleware_objects: List[Any] = []
        seen: set = set()

        mw_registry = self._middleware_registry

        # 1. Route-level middleware (resolved by name from the registry)
        if mw_registry is not None:
            for name in getattr(route, "middleware", ()):
                if name not in seen:
                    try:
                        middleware_objects.append(
                            mw_registry.get(name)
                        )
                        seen.add(name)
                    except Exception:  # noqa: BLE001 - skip unregistered middleware
                        pass

        # 2. Global middleware (enabled ones, ordered)
        if mw_registry is not None:
            for mw in mw_registry.active():
                name = getattr(mw, "middleware_name", lambda: type(mw).__name__)()
                if name not in seen:
                    middleware_objects.append(mw)
                    seen.add(name)

        return _WebPipeline(
            middleware=middleware_objects,
            request=request,
            context=context,
        )

    # -- internals ------------------------------------------------------
    @staticmethod
    def _flask_path(path: str) -> str:
        """Translate ``/users/<id>`` / ``<int:id>`` into Flask syntax.

        Flask uses the exact same ``<converter:name>`` syntax, so the only
        transformation needed is normalising a missing converter
        (``<id>`` -> ``<id>``; Flask treats it as a string converter which is
        exactly what the introspection matcher assumes for plain placeholders).
        """
        if not path or not path.strip():
            return "/"
        return path if path.startswith("/") else "/" + path

    def _unique_endpoint(self, endpoint: str) -> str:
        """Return ``endpoint`` or a deterministic ``endpoint.<n>`` variant.

        Flask forbids two different views sharing one endpoint.  When the same
        handler (e.g. ``product.list_handler``) is mounted at several path
        bases (a registry prefix), the duplicates get ``.2``, ``.3``, ...
        so several resources never conflict.
        """
        if endpoint not in self._used_endpoints:
            self._used_endpoints[endpoint] = 1
            return endpoint
        self._used_endpoints[endpoint] += 1
        return f"{endpoint}.{self._used_endpoints[endpoint]}"

    def _invoke(self, route: Any, request: Request, context: WebContext) -> Any:
        """Call a route handler with signature-appropriate arguments.

        Handlers may declare the documented ``(request, context)`` pair (CRUD
        generator output) or the shorter ``(request)`` form (resource
        generator output).  The adapter inspects the callable and passes only
        what it accepts, so both generated styles keep working.
        """
        try:
            signature = inspect.signature(route.handler)
        except (TypeError, ValueError):  # pragma: no cover - builtins/odd callables
            return route.handler(request, context)
        parameters = list(signature.parameters.values())
        positional = [
            parameter for parameter in parameters
            if parameter.kind
            in (parameter.POSITIONAL_ONLY, parameter.POSITIONAL_OR_KEYWORD)
        ]
        if len(positional) >= 2:
            return route.handler(request, context)
        if len(positional) == 1:
            return route.handler(request)
        return route.handler()

    def _make_view(self, route: Any) -> Callable[..., Any]:
        """Wrap a Betrayer route handler into a Flask view function.

        Async handlers are wrapped in an *async* view so Flask (which detects
        coroutine functions and runs them in its event loop) awaits the result;
        synchronous handlers get a plain synchronous view.  Both paths share
        the same request/context plumbing; only the final conversion to a
        Flask response differs (the async path awaits first).

        Middleware hooks are executed through :meth:`pipeline_for` and
        :class:`~betrayer.web.middleware.WebPipeline.run`.
        """

        def _request_and_context(path_params: dict) -> tuple:
            request = Request.from_flask(path_params=path_params, route=route)
            context = WebContext(
                application=self.application,
                adapter=self,
                request=request,
                route=route,
                module=route.module,
            )
            return request, context

        if route_is_async(route.handler):

            async def async_view(**path_params: Any) -> Any:
                request, context = _request_and_context(path_params)
                try:
                    pipeline = self.pipeline_for(route, request, context)

                    async def call_handler():
                        return await self._invoke(route, request, context)

                    result = await pipeline.run_async(call_handler)
                    return self._to_flask_response(result)
                except BaseException as exc:  # noqa: BLE001 - edge must never leak
                    return self._error_response(exc)

            return async_view

        def view(**path_params: Any) -> Any:
            request, context = _request_and_context(path_params)
            try:
                pipeline = self.pipeline_for(route, request, context)
                result = pipeline.run(
                    handler=lambda: self._invoke(route, request, context)
                )
                return self._to_flask_response(result)
            except BaseException as exc:  # noqa: BLE001 - edge must never leak
                return self._error_response(exc)

        return view

    @staticmethod
    def _to_flask_response(result: Any) -> Any:
        """Normalise a handler result into a Flask response."""
        if isinstance(result, Response):
            return result.to_flask()
        if isinstance(result, dict):
            return Response.json(result).to_flask()
        if isinstance(result, (str, bytes)):
            return Response(result).to_flask()
        if result is None:
            return Response.no_content().to_flask()
        raise TypeError(
            "Route handler returned an unsupported value; return a "
            f"betrayer.web.response.Response, got {type(result).__name__}"
        )

    @staticmethod
    def _error_response(error: BaseException) -> Any:
        """Convert an exception raised by a handler into a controlled response.

        ``WebError`` subclasses keep their status/code/message; anything else
        is classified through the framework bridge so no internals ever leak
        (a raw ``RuntimeError`` becomes a safe 500 with a generic message).

        Validation errors also carry their structured field errors: they are
        forwarded untouched under ``error.details`` (see
        :meth:`betrayer.web.exceptions.ValidationError.details`), so the error
        contract stays the single framework envelope.
        """
        from betrayer.web.flask_bridge import FlaskErrorBridge
        from betrayer.web.response import ApiResponse

        try:
            bridge = FlaskErrorBridge()
            classified = bridge.classify(error)
            status = int(classified.get("status") or 500)
            if status == 500 and classified.get("kind") != "betrayer":
                code = "INTERNAL_SERVER_ERROR"
                message = "Internal server error"
            else:
                code = classified.get("code", "INTERNAL_SERVER_ERROR")
                message = classified.get("message", "Internal server error")
            details = None
            details_fn = getattr(error, "details", None)
            if callable(details_fn):
                try:
                    details = details_fn()
                except Exception:  # noqa: BLE001 - details are best-effort only
                    details = None
            return ApiResponse.error(
                message=message,
                status=status,
                code=code,
                details=details,
            ).to_flask()
        except Exception:  # pragma: no cover - defensive double failure
            return ApiResponse.error(
                message="Internal server error",
                status=500,
                code="INTERNAL_SERVER_ERROR",
            ).to_flask()

    # -- introspection ------------------------------------------------
    def describe(self) -> List[dict]:
        """Route metadata of every mounted router (sorted as the registry does)."""
        from betrayer.web.routing import WebRouteRegistry

        merged = WebRouteRegistry(name="adapter.merged")
        for router in self._routers:
            for route in router.routes.list():
                merged.add(route)
        return merged.describe()

    def to_dict(self) -> dict:
        """JSON friendly snapshot of the adapter surface."""
        return {
            "adapter": "FlaskAdapter",
            "application": self.application.name,
            "mounted": self._mounted,
            "routers": len(self._routers),
            "url_prefix": self.url_prefix,
            "routes": self.describe(),
        }

    describe_all = describe

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<FlaskAdapter application={self.application.name!r} mounted={self._mounted}>"