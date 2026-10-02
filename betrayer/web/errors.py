"""Web error handling: Betrayer exception -> HTTP status -> Response.

The mapping is data, not hardcoded Flask behaviour::

    ValidationError       -> 422 VALIDATION_FAILED
    NotFoundError         -> 404 RESOURCE_NOT_FOUND
    UnauthorizedError     -> 401 UNAUTHORIZED
    ForbiddenError        -> 403 FORBIDDEN
    BadRequestError       -> 400 BAD_REQUEST
    MethodNotAllowedError -> 405 METHOD_NOT_ALLOWED
    ConflictError         -> 409 CONFLICT
    InternalServerError   -> 500 INTERNAL_SERVER_ERROR
    WebError (fallback)   -> 500 WEB_ERROR

This module is the **only** place that converts exceptions into responses.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, Optional

from betrayer.core.error_contract import format_error_for_llm
from betrayer.web.exceptions import (
    BadRequestError,
    ConflictError,
    ForbiddenError,
    InternalServerError,
    MethodNotAllowedError,
    NotFoundError,
    TooManyRequestsError,
    UnauthorizedError,
    ValidationError,
    WebError,
)
from betrayer.web.flask_bridge import FlaskErrorBridge
from betrayer.web.response import ApiResponse, Response

if TYPE_CHECKING:
    from flask import Flask


# ---------------------------------------------------------------------------
# Mapping: Betrayer exception class -> (http_status, error_code)
# ---------------------------------------------------------------------------

_ERROR_TO_STATUS: Dict[type, int] = {
    BadRequestError: 400,
    UnauthorizedError: 401,
    ForbiddenError: 403,
    NotFoundError: 404,
    MethodNotAllowedError: 405,
    ConflictError: 409,
    ValidationError: 422,
    TooManyRequestsError: 429,
    InternalServerError: 500,
}

_ERROR_TO_CODE: Dict[type, str] = {
    BadRequestError: "BAD_REQUEST",
    UnauthorizedError: "UNAUTHORIZED",
    ForbiddenError: "FORBIDDEN",
    NotFoundError: "RESOURCE_NOT_FOUND",
    MethodNotAllowedError: "METHOD_NOT_ALLOWED",
    ConflictError: "CONFLICT",
    ValidationError: "VALIDATION_FAILED",
    TooManyRequestsError: "RATE_LIMIT_EXCEEDED",
    InternalServerError: "INTERNAL_SERVER_ERROR",
}


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def _error_details(error: BaseException) -> Any:
    """Best-effort structured ``details`` for an error (validation payload...).

    Only errors that expose a ``details()`` method (such as
    :class:`~betrayer.web.exceptions.ValidationError`) contribute; anything
    else returns ``None`` so the wire payload never grows unexpectedly.
    """
    details_fn = getattr(error, "details", None)
    if not callable(details_fn):
        return None
    try:
        return details_fn()
    except Exception:  # noqa: BLE001 - details are best-effort only
        return None


def web_error_to_response(error: WebError, *, details: Any = None) -> Response:
    """Convert a :class:`WebError` into a :class:`Response`.

    ``details`` is forwarded to :meth:`ApiResponse.error` so that
    validation details (for example) reach the wire.
    """
    status = int(error.http_status) if hasattr(error, "http_status") else 500
    message = getattr(error, "message", None) or str(error)
    code = getattr(error, "code", "WEB_ERROR")
    return ApiResponse.error(
        message=message,
        status=status,
        code=code,
        details=details,
    )


def register_web_error_handlers(app: "Flask") -> None:
    """Register Betrayer exception handlers on a Flask application.

    This function attaches handlers for every ``WebError`` subclass so
    that unhandled Betrayer exceptions produce the correct JSON response
    automatically.

    Handlers return a **Flask** response (the Betrayer
    :class:`~betrayer.web.response.Response` is converted with
    ``to_flask()``), so Flask 3.x accepts them through the standard
    ``register_error_handler`` contract.

    Usage::

        from betrayer.web.errors import register_web_error_handlers

        register_web_error_handlers(flask_app)
    """
    bridge = FlaskErrorBridge()

    # -- Betrayer exception handlers (one per subclass) ---------------
    _handled: set = set()

    for exc_cls in _ERROR_TO_STATUS:
        if exc_cls in _handled:
            continue
        _handled.add(exc_cls)

        def _make_handler(
            _cls: type = exc_cls,
        ) -> Any:
            def handler(error: Exception) -> Any:
                # Classify via bridge for consistent diagnostics
                classified = bridge.classify(error)
                status = classified.get("status", 500)
                code = classified.get("code", "WEB_ERROR")
                message = classified.get("message", str(error))
                return ApiResponse.error(
                    message=message,
                    status=status,
                    code=code,
                    details=_error_details(error),
                ).to_flask()

            handler.__name__ = f"_handle_{_cls.__name__}"  # type: ignore[attr-defined]
            return handler

        app.register_error_handler(exc_cls, _make_handler())

    # -- Fallback: catch-all for any BaseException --------------------
    def _catchall(error: BaseException) -> Any:
        classified = bridge.classify(error)
        status = classified.get("status", 500)
        code = classified.get("code", "INTERNAL_SERVER_ERROR")
        message = classified.get("message", "Internal server error")
        return ApiResponse.error(
            message=message,
            status=status,
            code=code,
        ).to_flask()

    app.register_error_handler(Exception, _catchall)