"""Betrayer web layer: Flask adapter, routing, middleware, request/response.

The web layer depends on ``core`` and ``runtime`` only.  It must never
create a global mutable singleton — every object is bound to an explicit
owner (typically the :class:`~betrayer.web.adapter.FlaskAdapter`).

Public API
----------
.. code-block:: python

    from betrayer.web import (
        WebContext,
        Request,
        Response,
        ApiResponse,
        Route,
        Router,
        WebMiddlewareRegistry,
        WebError,
        BadRequestError,
        NotFoundError,
        ...,
    )
"""

from __future__ import annotations

from betrayer.web.context import WebContext
from betrayer.web.request import Request
from betrayer.web.response import Response, ApiResponse
from betrayer.web.routing import Route, WebRouter as Router
from betrayer.web.adapter import FlaskAdapter, route_is_async
from betrayer.web.resource import (
    ApiResource,
    CrudApiResource,
    ResourceRegistry,
    register_web_router,
)
from betrayer.web.middleware import WebMiddlewareRegistry
from betrayer.web.exceptions import (
    HTTP_STATUS_CODES,
    WebError,
    BadRequestError,
    UnauthorizedError,
    ForbiddenError,
    NotFoundError,
    MethodNotAllowedError,
    ConflictError,
    ValidationError,
    InternalServerError,
    RouteError,
    WebAdapterError,
    FlaskUnavailableError,
)
from betrayer.web.errors import (
    web_error_to_response,
    register_web_error_handlers,
)

__all__ = [
    "WebContext",
    "Request",
    "Response",
    "ApiResponse",
    "Route",
    "Router",
    "FlaskAdapter",
    "route_is_async",
    "ApiResource",
    "CrudApiResource",
    "ResourceRegistry",
    "register_web_router",
    "WebMiddlewareRegistry",
    "HTTP_STATUS_CODES",
    "WebError",
    "BadRequestError",
    "UnauthorizedError",
    "ForbiddenError",
    "NotFoundError",
    "MethodNotAllowedError",
    "ConflictError",
    "ValidationError",
    "InternalServerError",
    "RouteError",
    "WebAdapterError",
    "FlaskUnavailableError",
    "web_error_to_response",
    "register_web_error_handlers",
]