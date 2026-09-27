"""Web layer exceptions.

There is exactly **one** exception hierarchy in Betrayer and the web layer
extends it instead of inventing a second error system:

    BetrayerError (betrayer.core.exceptions)
        └── WebError
              ├── BadRequestError         400  BAD_REQUEST
              ├── UnauthorizedError       401  UNAUTHORIZED
              ├── ForbiddenError          403  FORBIDDEN
              ├── NotFoundError           404  RESOURCE_NOT_FOUND
              ├── MethodNotAllowedError   405  METHOD_NOT_ALLOWED
              ├── ConflictError           409  CONFLICT
              ├── ValidationError         422  VALIDATION_FAILED
              ├── InternalServerError     500  INTERNAL_ERROR
              ├── RouteError              500  ROUTE_ERROR
              ├── WebAdapterError         500  WEB_ADAPTER_ERROR
              └── FlaskUnavailableError   500  FLASK_UNAVAILABLE

Every class declares two machine readable class attributes:

* ``code``        stable error code returned to API clients (``error.code``),
* ``http_status`` HTTP status the web layer maps the exception to.

The runtime mapping table (including plain ``BetrayerError`` subclasses from
core) lives in :mod:`betrayer.web.errors`.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Sequence

from betrayer.core.exceptions import BetrayerError

__all__ = [
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
]

#: HTTP status -> default machine readable error code.
#: Kept here (the lowest layer of the web package) so both the error handler
#: and the Flask bridge read the same table.
HTTP_STATUS_CODES: Dict[int, str] = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "RESOURCE_NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    422: "VALIDATION_FAILED",
    500: "INTERNAL_ERROR",
}


class WebError(BetrayerError):
    """Base class of every web layer error.

    ``http_status`` is the default status for the class and can be overridden
    per instance (``NotFoundError("gone", http_status=410)``).  ``headers``
    carries transport level hints such as ``Allow`` (405) or
    ``WWW-Authenticate`` (401); ``context`` carries machine readable details
    that are safe to expose in development output.
    """

    code = "WEB_ERROR"
    component = "web"
    http_status = 500

    def __init__(
        self,
        message: str = "",
        *,
        code: Optional[str] = None,
        http_status: Optional[int] = None,
        stage: Optional[str] = None,
        cause: Optional[BaseException] = None,
        context: Optional[dict] = None,
        headers: Optional[dict] = None,
    ) -> None:
        super().__init__(
            message=message,
            code=code,
            component="web",
            stage=stage,
            cause=cause,
            context=context,
        )
        self.http_status = int(http_status) if http_status is not None else type(self).http_status
        self.headers = dict(headers or {})


class BadRequestError(WebError):
    """Malformed request (unparsable body, invalid query parameter, ...)."""

    code = "BAD_REQUEST"
    http_status = 400


class UnauthorizedError(WebError):
    """Authentication missing or invalid."""

    code = "UNAUTHORIZED"
    http_status = 401


class ForbiddenError(WebError):
    """Authenticated but not allowed to perform the action."""

    code = "FORBIDDEN"
    http_status = 403


class NotFoundError(WebError):
    """Requested resource (or route) does not exist."""

    code = "RESOURCE_NOT_FOUND"
    http_status = 404


class MethodNotAllowedError(WebError):
    """HTTP method not supported for the matched path.

    ``allowed`` (a sequence of method names) is copied into ``context`` and
    into the ``Allow`` response header.
    """

    code = "METHOD_NOT_ALLOWED"
    http_status = 405

    def __init__(
        self,
        message: str = "Method not allowed for this resource",
        *,
        allowed: Optional[Sequence[str]] = None,
        **kwargs: Any,
    ) -> None:
        context = dict(kwargs.pop("context", None) or {})
        headers = dict(kwargs.pop("headers", None) or {})
        if allowed is not None:
            allowed_methods = [str(method).upper() for method in allowed]
            context["allowed"] = allowed_methods
            headers.setdefault("Allow", ", ".join(allowed_methods))
        super().__init__(message, context=context, headers=headers, **kwargs)


class ConflictError(WebError):
    """Request conflicts with the current state of the resource."""

    code = "CONFLICT"
    http_status = 409


class ValidationError(WebError):
    """Input failed validation; ``errors`` / ``fields`` list the rejected fields.

    Two structured views ride along in ``context`` and reach the wire under
    ``error.details`` (see :mod:`betrayer.web.errors`):

    * ``errors`` -- a list, e.g. ``[{"field": "name", "code": "required",
      "message": "This field is required."}]``;
    * ``fields`` -- a ``{field: [message, ...]}`` mapping, the quick view an
      LLM/client needs to render per-field errors.
    """

    code = "VALIDATION_FAILED"
    http_status = 422

    def __init__(
        self,
        message: str = "Validation failed",
        *,
        errors: Optional[Sequence[Any]] = None,
        fields: Optional[Mapping[str, Sequence[Any]]] = None,
        **kwargs: Any,
    ) -> None:
        context = dict(kwargs.pop("context", None) or {})
        if errors is not None:
            context["errors"] = list(errors)
        if fields is not None:
            context["fields"] = {
                str(name): list(messages) for name, messages in fields.items()
            }
        super().__init__(message, context=context, **kwargs)

    @property
    def errors(self) -> list:
        """The structured field error list (empty when none were attached)."""
        return list(self.context.get("errors", []))

    @property
    def fields(self) -> dict:
        """The ``{field: [message, ...]}`` view (empty when none)."""
        return dict(self.context.get("fields", {}))

    def details(self) -> Optional[dict]:
        """The ``details`` payload for the API error envelope (or ``None``)."""
        payload: dict = {}
        if self.fields:
            payload["fields"] = self.fields
        if self.errors:
            payload["errors"] = self.errors
        return payload or None


class InternalServerError(WebError):
    """Explicit 500 raised by application code (never leaks internals)."""

    code = "INTERNAL_ERROR"
    http_status = 500


class RouteError(WebError):
    """Invalid route declaration (unknown method, bad path, duplicate route).

    Raised while *declaring* routes, not while serving them, so it is a
    development time error with a 500 default status.
    """

    code = "ROUTE_ERROR"
    http_status = 500


class WebAdapterError(WebError):
    """The web adapter was used incorrectly (no Flask app, wrong return type).

    This is a framework/programming error, never a client error.
    """

    code = "WEB_ADAPTER_ERROR"
    http_status = 500


class FlaskUnavailableError(WebAdapterError):
    """Flask is not installed, so the HTTP engine cannot be provided."""

    code = "FLASK_UNAVAILABLE"
