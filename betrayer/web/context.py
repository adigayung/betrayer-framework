"""Per request context handed to handlers and middleware.

``WebContext`` is the web counterpart of
:class:`betrayer.runtime.context.RuntimeContext`: it gives application code the
framework services it may legitimately use while answering a request, without
reaching for global state.

Handlers always have the same, explicit signature::

    def list_users(request: Request, context: WebContext) -> Response:
        service = context.resolve("user_service")   # container from Task 02
        return Response.json({"users": service.list()})

Nothing here duplicates lifecycle, registry or container: every service is a
live delegation to :class:`betrayer.application.BetrayerApplication`.
"""

from __future__ import annotations

from typing import Any, Optional

__all__ = ["WebContext"]

_MISSING = object()


class WebContext:
    """Request scoped access point to framework services.

    Attributes
    ----------
    application:
        The owning :class:`betrayer.application.BetrayerApplication`.
    adapter:
        The :class:`betrayer.web.adapter.FlaskAdapter` serving the request.
    request:
        The :class:`betrayer.web.request.Request` being answered.
    route:
        The matched :class:`betrayer.web.routing.Route` (``None`` for errors
        raised outside routing, e.g. a 404 miss).
    module:
        Owning module name recorded on the route (``None`` when unknown).
    """

    def __init__(
        self,
        *,
        application: Any,
        adapter: Any,
        request: Any,
        route: Any = None,
        module: Optional[str] = None,
    ) -> None:
        self.application = application
        self.adapter = adapter
        self.request = request
        self.route = route
        self.module = module

    # -- framework services ------------------------------------------
    @property
    def container(self) -> Any:
        """Service container from Task 02 (``None`` if the app has none)."""
        return getattr(self.application, "container", None)

    @property
    def registry(self) -> Any:
        """The single application component registry."""
        return getattr(self.application, "registry", None)

    @property
    def config(self) -> Any:
        """Application configuration object."""
        return getattr(self.application, "config", None)

    @property
    def events(self) -> Any:
        """Application event bus (Task 02)."""
        return getattr(self.application, "events", None)

    @property
    def environment(self) -> Any:
        """Detected environment object."""
        return getattr(self.application, "environment", None)

    @property
    def lifecycle(self) -> Any:
        """Application lifecycle (read only for handlers)."""
        return getattr(self.application, "lifecycle", None)

    @property
    def state(self) -> Any:
        """Current lifecycle state of the application."""
        return getattr(self.application, "state", None)

    # -- container helpers (never a second DI container) -------------
    def resolve(self, name: str, default: Any = _MISSING) -> Any:
        """Resolve ``name`` from the Task 02 container.

        ``default`` may be supplied to keep the call non raising; without it a
        missing service raises :class:`betrayer.core.exceptions.DependencyError`.
        """
        container = self.container
        if container is None:
            from .exceptions import WebAdapterError

            raise WebAdapterError(
                message="Application has no service container bound",
                code="WEB_CONTAINER_MISSING",
                context={"service": name},
            )
        if default is _MISSING:
            return container.resolve(name)
        return container.resolve(name, default)

    def has(self, name: str) -> bool:
        """Return ``True`` when ``name`` is registered in the container."""
        container = self.container
        if container is None:
            return False
        return bool(container.has(name))

    # -- events ------------------------------------------------------
    def emit(self, name: str, payload: Any = None) -> Any:
        """Emit an application event through the Task 02 event bus."""
        events = self.events
        if events is None:
            return None
        return events.emit(name, payload)

    # -- introspection ----------------------------------------------
    def to_dict(self) -> dict:
        """Machine readable snapshot (no request bodies, no secrets)."""
        return {
            "module": self.module,
            "route": self.route.to_dict() if hasattr(self.route, "to_dict") else None,
            "state": str(self.state) if self.state is not None else None,
            "application": getattr(self.application, "name", None),
        }

    describe = to_dict

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        method = getattr(self.request, "method", None)
        path = getattr(self.request, "path", None)
        return f"<WebContext {method} {path} module={self.module!r}>"
