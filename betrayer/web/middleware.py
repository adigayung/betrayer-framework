"""Middleware: the HTTP request/response pipeline.

Middleware is **not** a second event system.  The split of responsibilities is
intentional and documented:

======================  ===========================================================
Middleware              HTTP request/response pipeline (runs per request)
Event system (Task 02)  application/framework events (bootstrap, ready, stop, ...)
======================  ===========================================================

For application events use ``context.events``; for request/response work use
middleware.

Ordering rule (deterministic, see :class:`WebPipeline`)
-------------------------------------------------------
For every request the pipeline is built in this order:

1. middleware declared on the route (in the order listed on the route), then
2. the global middleware registry ordered ascending by
   ``(priority, registration index)``.

with

* ``before_request``  called in that order (outermost -> innermost),
* ``after_request``   called in exactly the reversed order (innermost -> outermost),
* ``on_error``        called in exactly the reversed order (innermost -> outermost).

Disabled middleware (``enabled = False``) is skipped everywhere but stays
visible in ``web.middleware()`` introspection.

A middleware object is any object exposing some of ``before_request``,
``after_request``, ``on_error`` (all optional).  Subclassing :class:`Middleware`
is only a convenience that documents the hooks and provides defaults.
"""
from __future__ import annotations

from typing import Any, Callable, Iterable, List, Optional, Sequence

from betrayer.web.exceptions import WebError
from betrayer.web.response import Response

__all__ = ["Middleware", "WebMiddlewareRegistry", "WebPipeline"]


class Middleware:
    """Base class for HTTP middleware.

    Attributes
    ----------
    name:
        Registration name; defaults to the class name.
    priority:
        Lower runs earlier (``before_request`` order).  Ties keep the
        registration order, so ordering is always deterministic.
    enabled:
        ``False`` skips the middleware without unregistering it.
    """

    name: str = ""
    priority: int = 0
    enabled: bool = True

    # -- identity -----------------------------------------------------
    def middleware_name(self) -> str:
        """Return the registration/introspection name of this middleware."""
        return self.name or type(self).__name__

    # -- hooks (all optional, all may return a Response) ---------------
    def before_request(self, request: Any, context: Any) -> Optional[Response]:
        """Run before the handler. Return a Response to short-circuit."""
        return None

    def after_request(
        self, request: Any, response: Response, context: Any
    ) -> Optional[Response]:
        """Run after the handler. Return a Response to replace it."""
        return None

    def on_error(self, request: Any, error: BaseException, context: Any) -> Optional[Response]:
        """Run when the request failed. Return a Response to handle it."""
        return None

    # -- introspection -------------------------------------------------
    def hooks(self) -> dict:
        """Map hook name -> bool, so an LLM sees which hooks are implemented."""
        return {
            hook: getattr(type(self), hook, None) is not getattr(Middleware, hook, None)
            for hook in ("before_request", "after_request", "on_error")
        }

    def describe(self) -> dict:
        """Machine readable description (deterministic key order)."""
        return {
            "name": self.middleware_name(),
            "class": f"{type(self).__module__}.{type(self).__qualname__}",
            "priority": int(self.priority),
            "enabled": bool(self.enabled),
            "hooks": self.hooks(),
        }

    to_dict = describe

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"<Middleware {self.middleware_name()} priority={self.priority} "
            f"enabled={self.enabled}>"
        )


def _name_of(middleware: Any) -> str:
    """Duck-typed name of a middleware object."""
    name = getattr(middleware, "middleware_name", None)
    if callable(name):
        return str(name())
    explicit = getattr(middleware, "name", "")
    return str(explicit) or type(middleware).__name__


class WebMiddlewareRegistry:
    """Ordered table of middleware (domain specific view, not a second Registry).

    Deterministic order is ascending ``(priority, registration index)``. The
    registry is stored in the application Registry under ``web.middleware`` by
    the adapter, so it is reachable through the normal framework APIs::

        registry.get("web.middleware")

    API (same verbs as the core registry: register/get/has/unregister/list)::

        add(middleware, position=None)   register(...)   remove(name)
        get(name)   exists(name)   enable(name)   disable(name)
        list()  active()  resolve(names)  clear()  describe()
    """

    def __init__(self, name: str = "web.middleware") -> None:
        self.name = name
        self._entries: List[Any] = []

    # -- registration ---------------------------------------------------
    def add(self, middleware: Any, *, position: Optional[int] = None) -> Any:
        """Register ``middleware``; duplicate names are rejected explicitly."""
        name = _name_of(middleware)
        if self.exists(name):
            raise WebError(
                f"Middleware already registered: {name!r}",
                code="MIDDLEWARE_DUPLICATE",
                stage="web.middleware",
                context={"middleware": name},
            )
        if position is None:
            self._entries.append(middleware)
        else:
            index = max(0, min(int(position), len(self._entries)))
            self._entries.insert(index, middleware)
        return middleware

    register = add

    def remove(self, name: str) -> Any:
        middleware = self.get(name)
        self._entries.remove(middleware)
        return middleware

    unregister = remove

    def get(self, name: str) -> Any:
        for middleware in self._entries:
            if _name_of(middleware) == name:
                return middleware
        raise WebError(
            f"Unknown middleware: {name!r}",
            code="MIDDLEWARE_NOT_FOUND",
            stage="web.middleware",
            context={"middleware": name, "registered": [m for m in self.names()]},
        )

    def exists(self, name: str) -> bool:
        return any(_name_of(middleware) == name for middleware in self._entries)

    has = exists

    # -- enable / disable ------------------------------------------------
    def enable(self, name: str) -> Any:
        middleware = self.get(name)
        middleware.enabled = True
        return middleware

    def disable(self, name: str) -> Any:
        middleware = self.get(name)
        middleware.enabled = False
        return middleware

    # -- ordering / introspection ----------------------------------------
    def _ordered(self) -> List[Any]:
        return sorted(
            enumerate(self._entries),
            key=lambda pair: (
                getattr(pair[1], "priority", 0),
                pair[0],
            ),
        ) and [m for _, m in sorted(
            enumerate(self._entries),
            key=lambda pair: (getattr(pair[1], "priority", 0), pair[0]),
        )]

    def list(self) -> List[Any]:
        """All middleware in execution order (disabled ones included)."""
        return self._ordered()

    def active(self) -> List[Any]:
        """Enabled middleware in execution order (used by the pipeline)."""
        return [m for m in self._ordered() if getattr(m, "enabled", True)]

    def names(self) -> List[str]:
        return [_name_of(m) for m in self._ordered()]

    def resolve(self, names: Iterable[str]) -> List[Any]:
        """Resolve registered names to middleware objects (order preserved)."""
        return [self.get(name) for name in names]

    def clear(self) -> None:
        self._entries.clear()

    def describe(self) -> List[dict]:
        rows: List[dict] = []
        for index, middleware in enumerate(self.active()):
            hooks = sorted(
                hook
                for hook in ("before_request", "after_request", "on_error")
                if callable(getattr(middleware, hook, None))
            )
            rows.append(
                {
                    "index": index,
                    "name": _name_of(middleware),
                    "priority": int(getattr(middleware, "priority", 0)),
                    "enabled": bool(getattr(middleware, "enabled", True)),
                    "hooks": hooks,
                    "class": f"{type(middleware).__module__}.{type(middleware).__name__}",
                }
            )
        return rows

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "order": "route middleware first, then global ascending by "
            "(priority, registration index)",
            "after_order": "reverse of before_request order",
            "middleware": self.describe(),
        }

    def __len__(self) -> int:
        return len(self._entries)

    def __iter__(self):
        return iter(self._ordered())

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<WebMiddlewareRegistry {self.names()}>"


# ---------------------------------------------------------------------------
# Pipeline execution
# ---------------------------------------------------------------------------


class WebPipeline:
    """Per-request middleware execution pipeline.

    Runs ``before_request`` hooks (in order), then ``after_request`` /
    ``on_error`` hooks (reversed order), matching the documented contract in
    this module.

    Usage (from the adapter)::

        pipeline = WebPipeline(middleware=mw_list, request=req, context=ctx)

        # Synchronous handler:
        result = pipeline.run(handler=lambda: route.handler(request, context))

        # Asynchronous handler:
        async def call_handler():
            return await route.handler(request, context)
        result = await pipeline.run_async(call_handler)
    """

    def __init__(
        self,
        *,
        middleware: Sequence[Any],
        request: Any,
        context: Any,
    ) -> None:
        self._middleware = list(middleware)
        self.request = request
        self.context = context

    # -- public API ----------------------------------------------------

    def run(self, handler: Callable[[], Any]) -> Any:
        """Execute the full pipeline::

            before_request (in order) -> handler -> after_request (reversed)

        If any ``before_request`` returns a non-``None`` value the handler is
        skipped and that value is returned as the response.  ``after_request``
        hooks run in the reversed order and may replace the response.

        If an exception is raised the ``on_error`` hooks run (reversed order);
        the first non-``None`` return becomes the response; if no hook handles
        it the exception propagates.
        """
        try:
            response = self._run_before()
            if response is not None:
                return response
            response = handler()
            return self._run_after(response)
        except BaseException as exc:
            handled = self._run_error(exc)
            if handled is not None:
                return handled
            raise

    async def run_async(self, handler: Callable[[], Any]) -> Any:
        """Async variant of :meth:`run` for async route handlers.

        ``handler`` should be an async callable.  The before/after/on_error
        hooks are run synchronously (they are not expected to be async in the
        current design).
        """
        try:
            response = self._run_before()
            if response is not None:
                return response
            response = await handler()
            return self._run_after(response)
        except BaseException as exc:
            handled = self._run_error(exc)
            if handled is not None:
                return handled
            raise

    # -- hook execution -------------------------------------------------

    def _run_before(self) -> Any:
        """Call ``before_request(request, context)`` on each middleware.

        Returns the first non-``None`` response (which short-circuits) or
        ``None`` to continue.
        """
        for mw in self._middleware:
            hook = getattr(mw, "before_request", None)
            if not callable(hook):
                continue
            if not getattr(mw, "enabled", True):
                continue
            result = hook(self.request, self.context)
            if result is not None:
                return result
        return None

    def _run_after(self, response: Any) -> Any:
        """Call ``after_request(request, response, context)`` in reversed order.

        Returns the (possibly replaced) response.
        """
        for mw in reversed(self._middleware):
            hook = getattr(mw, "after_request", None)
            if not callable(hook):
                continue
            if not getattr(mw, "enabled", True):
                continue
            try:
                result = hook(self.request, response, self.context)
                if result is not None:
                    response = result
            except BaseException:  # noqa: BLE001 - middleware error is not fatal
                pass
        return response

    def _run_error(self, error: BaseException) -> Any:
        """Call ``on_error(request, error, context)`` in reversed order.

        Returns the first non-``None`` response (error handled) or ``None``
        to let the exception propagate.
        """
        handled: Any = None
        for mw in reversed(self._middleware):
            hook = getattr(mw, "on_error", None)
            if not callable(hook):
                continue
            if not getattr(mw, "enabled", True):
                continue
            try:
                result = hook(self.request, error, self.context)
                if result is not None:
                    handled = result
                    break
            except BaseException:  # noqa: BLE001 - middleware error is not fatal
                pass
        return handled
