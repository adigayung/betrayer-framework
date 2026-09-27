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
from betrayer.web.validation import (
    Field,
    FieldError,
    Schema,
    ValidationResult,
    validate,
)
from betrayer.web.pagination import (
    PAGE_PARAM,
    PER_PAGE_PARAM,
    DEFAULT_PAGE,
    DEFAULT_PER_PAGE,
    MAX_PER_PAGE,
    PaginationParams,
    PaginationMetadata,
    PaginatedResult,
    parse_pagination,
    paginate_sequence,
    paginate_query,
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
    TooManyRequestsError,
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
from betrayer.web.realtime import (
    Message,
    MessageValidationError,
    RealtimeError,
    Connection,
    CONNECTION_STATE_CONNECTING,
    CONNECTION_STATE_OPEN,
    CONNECTION_STATE_CLOSED,
    Channel,
    CHANNEL_STATE_CONNECT,
    CHANNEL_STATE_READY,
    CHANNEL_STATE_DISCONNECT,
    RealtimeManager,
    FlaskRealtimeAdapter,
    WebSocketConnection,
    SockUnavailableError,
    flask_sock_available,
    ChannelError,
    ChannelNotFoundError,
    ConnectionError,
    ConnectionNotFoundError,
    MessageError,
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
    "Field",
    "FieldError",
    "Schema",
    "ValidationResult",
    "validate",
    "PAGE_PARAM",
    "PER_PAGE_PARAM",
    "DEFAULT_PAGE",
    "DEFAULT_PER_PAGE",
    "MAX_PER_PAGE",
    "PaginationParams",
    "PaginationMetadata",
    "PaginatedResult",
    "parse_pagination",
    "paginate_sequence",
    "paginate_query",
    "WebMiddlewareRegistry",
    "HTTP_STATUS_CODES",
    "WebError",
    "BadRequestError",
    "UnauthorizedError",
    "ForbiddenError",
    "NotFoundError",
    "MethodNotAllowedError",
    "ConflictError",
    "TooManyRequestsError",
    "ValidationError",
    "InternalServerError",
    "RouteError",
    "WebAdapterError",
    "FlaskUnavailableError",
    "web_error_to_response",
    "register_web_error_handlers",
    # realtime (WebSocket)
    "Message",
    "MessageValidationError",
    "RealtimeError",
    "Connection",
    "CONNECTION_STATE_CONNECTING",
    "CONNECTION_STATE_OPEN",
    "CONNECTION_STATE_CLOSED",
    "Channel",
    "CHANNEL_STATE_CONNECT",
    "CHANNEL_STATE_READY",
    "CHANNEL_STATE_DISCONNECT",
    "RealtimeManager",
    "FlaskRealtimeAdapter",
    "WebSocketConnection",
    "SockUnavailableError",
    "flask_sock_available",
    "ChannelError",
    "ChannelNotFoundError",
    "ConnectionError",
    "ConnectionNotFoundError",
    "MessageError",
]