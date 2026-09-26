"""Flask bridge: the only place in Betrayer that touches Flask directly.

Rules encoded here:

* Flask is the HTTP engine, not a second framework.  Every other web module
  works with plain Python data structures and asks this module when it needs
  Flask itself (``import_flask()``, ``import_flask_request()``).
* This module never builds a :class:`betrayer.web.response.Response`; it
  returns plain ``dict`` data (status/code/message/headers) so the response
  format stays owned by :mod:`betrayer.web.errors`.
* Errors are classified in exactly three kinds::

      betrayer  -> raised by Betrayer (WebError / BetrayerError)
      http      -> Flask/Werkzeug HTTPException (404 from routing, abort(403), ...)
      unknown   -> anything else (mapped to a safe 500)

Nothing is ever swallowed here: callers log and translate, and the original
exception stays attached (``error.cause``) or is re-raised.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import Any, Dict, Optional

from betrayer.core.exceptions import BetrayerError
from betrayer.web.exceptions import (
    HTTP_STATUS_CODES,
    FlaskUnavailableError,
    WebError,
)

__all__ = [
    "flask_available",
    "import_flask",
    "import_flask_request",
    "status_code_name",
    "map_http_exception",
    "FlaskErrorBridge",
]

_FLASK_HINT = "install the HTTP engine with: pip install flask"


def flask_available() -> bool:
    """Return ``True`` when Flask can be imported (never raises)."""
    try:  # pragma: no cover - trivial import probe
        import flask  # noqa: F401
    except Exception:  # noqa: BLE001 - any import failure means "not available"
        return False
    return True


def import_flask() -> Any:
    """Return the ``flask`` module or raise :class:`FlaskUnavailableError`."""
    try:
        import flask
    except Exception as exc:  # noqa: BLE001 - converted into a Betrayer error
        raise FlaskUnavailableError(
            message="Flask is not installed; the Betrayer web layer needs it as HTTP engine",
            cause=exc,
            context={"hint": _FLASK_HINT},
        ) from exc
    return flask


def import_flask_request() -> Any:
    """Return the current Flask request proxy (thin wrapper over ``flask.request``)."""
    return import_flask().request


def status_code_name(status: int) -> str:
    """Return the machine readable code for an HTTP status.

    Prefers :data:`betrayer.web.exceptions.HTTP_STATUS_CODES` (the codes
    Betrayer documents) and falls back to the standard ``HTTPStatus`` name.
    """
    if status in HTTP_STATUS_CODES:
        return HTTP_STATUS_CODES[status]
    try:
        return HTTPStatus(int(status)).name
    except ValueError:  # pragma: no cover - defensive, unknown status codes
        return f"HTTP_{status}"


def _http_exception_types() -> tuple:
    """Return ``(HTTPException, RoutingException)`` from werkzeug (Flask's engine).

    ``RoutingException`` was removed in newer Werkzeug releases (3.1+), so the
    import is defensive: the bridge keeps working with the ``HTTPException``
    base class whichever Werkzeug version is installed.
    """
    from werkzeug.exceptions import HTTPException

    routing: Any = None
    try:  # pragma: no cover - depends on the installed werkzeug version
        from werkzeug.exceptions import RoutingException

        routing = RoutingException
    except ImportError:  # pragma: no cover - werkzeug >= 3.1
        routing = HTTPException
    return HTTPException, routing


def map_http_exception(error: BaseException) -> Dict[str, Any]:
    """Translate a Werkzeug ``HTTPException`` into Betrayer friendly data.

    Returns ``{"status", "code", "message", "headers"}``.  The message is the
    exception description when present, otherwise the HTTP reason phrase, so
    the payload never contains framework internals.
    """
    status = int(getattr(error, "code", None) or 500)
    description = getattr(error, "description", None)
    reason = getattr(error, "name", None)
    message = str(description or reason or HTTPStatus(status).phrase if status in {s.value for s in HTTPStatus} else reason or "HTTP error")
    headers = dict(getattr(error, "headers", None) or {})
    return {
        "status": status,
        "code": status_code_name(status),
        "message": message,
        "headers": headers,
    }


class FlaskErrorBridge:
    """Classify exceptions so one policy (``WebErrorHandler``) can map them.

    The bridge is stateless and deterministic: given the same exception it
    always returns the same dictionary, which makes it safe to use in tests,
    introspection output and documentation examples.
    """

    def __init__(self, *, status_codes: Optional[dict] = None) -> None:
        self._status_codes = dict(status_codes or HTTP_STATUS_CODES)

    @property
    def status_codes(self) -> Dict[int, str]:
        """The HTTP status -> error code table this bridge reports."""
        return dict(self._status_codes)

    def code_for_status(self, status: int) -> str:
        """Return the error code for ``status`` (falls back to the HTTP name)."""
        if status in self._status_codes:
            return self._status_codes[status]
        return status_code_name(status)

    def is_http_exception(self, error: BaseException) -> bool:
        """Return ``True`` for Werkzeug ``HTTPException`` instances."""
        if not flask_available():
            return False
        http_exception, _ = _http_exception_types()
        return isinstance(error, http_exception)

    def is_routing_exception(self, error: BaseException) -> bool:
        """Return ``True`` for redirect style routing exceptions."""
        if not flask_available():
            return False
        _, routing_exception = _http_exception_types()
        return isinstance(error, routing_exception)

    def classify(self, error: BaseException) -> Dict[str, Any]:
        """Classify ``error`` into ``betrayer`` / ``http`` / ``unknown``.

        The returned dictionary always has the keys ``kind``, ``status``
        (``None`` when Betrayer code decides), ``code``, ``message`` and
        ``headers``.
        """
        if isinstance(error, WebError):
            return {
                "kind": "betrayer",
                "status": int(error.http_status),
                "code": error.code,
                "message": error.message,
                "headers": dict(error.headers),
            }
        if isinstance(error, BetrayerError):
            return {
                "kind": "betrayer",
                "status": None,
                "code": error.code,
                "message": error.message or type(error).__name__,
                "headers": {},
            }
        if self.is_http_exception(error):
            mapped = map_http_exception(error)
            mapped["kind"] = "http"
            return mapped
        return {
            "kind": "unknown",
            "status": 500,
            "code": self.code_for_status(500),
            "message": "Internal server error",
            "headers": {},
        }
