"""Response abstraction and the API response convention.

Handlers never touch Flask: they return a :class:`Response` and the adapter
converts it with :meth:`Response.to_flask` at the very edge.

Design rules (kept deliberately small and explicit):

* Explicit constructors: :meth:`Response.json`, :meth:`Response.text`,
  :meth:`Response.html`, :meth:`Response.redirect`,
  :meth:`Response.no_content`.  A ``dict`` body is **not** serialised
  implicitly - use ``Response.json`` so the wire format stays obvious.
* Chainable modifiers: ``with_status`` / ``with_header`` / ``with_cookie``.
* ``ApiResponse`` provides the framework-wide envelope
  ``{"success", "data", "error"}`` so applications do not invent their own.
"""

from __future__ import annotations

import json as json_module
from typing import Any, Dict, Iterable, List, Optional, Tuple

from betrayer.web.exceptions import WebError
from betrayer.web.flask_bridge import import_flask

__all__ = [
    "CONTENT_TYPE_JSON",
    "CONTENT_TYPE_TEXT",
    "CONTENT_TYPE_HTML",
    "JSON_MIMETYPE",
    "Response",
    "ApiResponse",
]

CONTENT_TYPE_JSON = "application/json"
CONTENT_TYPE_TEXT = "text/plain; charset=utf-8"
CONTENT_TYPE_HTML = "text/html; charset=utf-8"

#: Mimetype used by :meth:`Response.to_flask` for JSON payloads.
JSON_MIMETYPE = "application/json"


class Response:
    """Transport independent HTTP response.

    ``body`` must be ``str`` or ``bytes``; pass a mapping to
    :meth:`Response.json` instead.  Instances are mutable by design so
    middleware can decorate them in place and so chaining stays cheap:

        response = Response.json({"id": 1}).with_status(201).with_header("X-Trace", "1")
    """

    def __init__(
        self,
        body: Any = "",
        *,
        status: int = 200,
        headers: Optional[Dict[str, str]] = None,
        content_type: Optional[str] = None,
        cookies: Optional[Iterable[Tuple[str, str, dict]]] = None,
    ) -> None:
        if not isinstance(body, (str, bytes, bytearray)):
            raise WebError(
                message="Response body must be str or bytes; use Response.json() for mappings",
                code="RESPONSE_INVALID_BODY",
                context={"body_type": type(body).__name__},
            )
        self.body: Any = body
        self.status = self._check_status(status)
        self.headers: Dict[str, str] = {str(k): str(v) for k, v in (headers or {}).items()}
        self.content_type: Optional[str] = content_type
        self.cookies: List[Tuple[str, str, dict]] = [
            (str(name), str(value), dict(options)) for name, value, options in (cookies or [])
        ]

    # -- constructors -------------------------------------------------
    @classmethod
    def json(
        cls,
        data: Any,
        *,
        status: int = 200,
        headers: Optional[Dict[str, str]] = None,
    ) -> "Response":
        """JSON response; keys are sorted so output is deterministic."""
        body = json_module.dumps(data, sort_keys=True, default=str, ensure_ascii=False)
        return cls(body, status=status, headers=headers, content_type=CONTENT_TYPE_JSON)

    @classmethod
    def text(
        cls,
        text: str,
        *,
        status: int = 200,
        headers: Optional[Dict[str, str]] = None,
    ) -> "Response":
        """Plain text response (UTF-8)."""
        return cls(text, status=status, headers=headers, content_type=CONTENT_TYPE_TEXT)

    @classmethod
    def html(
        cls,
        html: str,
        *,
        status: int = 200,
        headers: Optional[Dict[str, str]] = None,
    ) -> "Response":
        """HTML response (UTF-8)."""
        return cls(html, status=status, headers=headers, content_type=CONTENT_TYPE_HTML)

    @classmethod
    def redirect(
        cls,
        location: str,
        *,
        status: int = 302,
        headers: Optional[Dict[str, str]] = None,
    ) -> "Response":
        """Redirect response built from a plain ``Location`` header."""
        merged = {"Location": str(location)}
        merged.update(headers or {})
        return cls("", status=status, headers=merged)

    @classmethod
    def no_content(cls, *, status: int = 204, headers: Optional[Dict[str, str]] = None) -> "Response":
        """Empty response (204 by default)."""
        return cls("", status=status, headers=headers)

    # -- modifiers (chainable, mutate in place and return self) --------
    @staticmethod
    def _check_status(status: Any) -> int:
        try:
            value = int(status)
        except (TypeError, ValueError) as exc:
            raise WebError(
                message=f"Invalid HTTP status: {status!r}",
                code="RESPONSE_INVALID_STATUS",
                cause=exc,
            ) from exc
        if not 100 <= value <= 599:
            raise WebError(
                message=f"HTTP status out of range: {value}",
                code="RESPONSE_INVALID_STATUS",
                context={"status": value},
            )
        return value

    def with_status(self, status: int) -> "Response":
        """Set the status code and return ``self``."""
        self.status = self._check_status(status)
        return self

    def with_header(self, name: str, value: Any) -> "Response":
        """Set (or replace) a single header and return ``self``."""
        self.headers[str(name)] = str(value)
        return self

    def with_headers(self, headers: Dict[str, Any]) -> "Response":
        """Merge a header mapping and return ``self``."""
        for name, value in headers.items():
            self.headers[str(name)] = str(value)
        return self

    def with_cookie(self, name: str, value: str, **options: Any) -> "Response":
        """Attach a cookie (options are handed to Flask's ``set_cookie``)."""
        self.cookies.append((str(name), str(value), dict(options)))
        return self

    # -- inspection ---------------------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        """Machine readable snapshot (never contains the body)."""
        return {
            "status": self.status,
            "content_type": self.content_type,
            "headers": dict(sorted(self.headers.items())),
            "cookies": [name for name, _value, _options in self.cookies],
            "body_length": len(self.body),
            "is_json": self.content_type == CONTENT_TYPE_JSON,
        }

    describe = to_dict

    # -- flask edge ---------------------------------------------------
    def to_flask(self) -> Any:
        """Convert to a Flask/Werkzeug response (the only place Flask appears)."""
        flask = import_flask()
        response = flask.Response(
            self.body,
            status=self.status,
            headers=dict(self.headers) or None,
        )
        if self.content_type:
            response.headers["Content-Type"] = self.content_type
        for name, value, options in self.cookies:
            response.set_cookie(name, value, **options)
        return response

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Response status={self.status} content_type={self.content_type!r}>"


class ApiResponse:
    """The Betrayer API envelope.

    Success::

        {"success": true, "data": {...}, "error": null}

    Error::

        {"success": false, "data": null,
         "error": {"code": "RESOURCE_NOT_FOUND", "message": "..."}}

    Both shapes are produced by :meth:`payload`, so the error handler and
    application code always agree on the wire format.
    """

    @staticmethod
    def payload(
        *,
        success: bool,
        data: Any = None,
        error: Optional[dict] = None,
        meta: Optional[dict] = None,
    ) -> Dict[str, Any]:
        """Build the envelope without wrapping it in a :class:`Response`."""
        body: Dict[str, Any] = {"success": bool(success), "data": data, "error": error}
        if meta is not None:
            body["meta"] = meta
        return body

    @staticmethod
    def success(
        data: Any = None,
        *,
        status: int = 200,
        meta: Optional[dict] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Response:
        """``HTTP < 400`` JSON response holding ``data``."""
        return Response.json(
            ApiResponse.payload(success=True, data=data, meta=meta),
            status=status,
            headers=headers,
        )

    @staticmethod
    def error(
        code: str,
        message: str,
        *,
        status: int = 400,
        details: Optional[Any] = None,
        data: Any = None,
        headers: Optional[Dict[str, str]] = None,
        structured_error: Optional[Dict[str, Any]] = None,
    ) -> Response:
        """JSON error response following the same envelope.

        ``structured_error`` enriches the existing API error shape with the
        canonical LLM contract while retaining backwards compatibility for
        clients that only consume ``code``/``message``/``details``.
        """
        error: Dict[str, Any] = {"code": str(code), "message": str(message)}
        if structured_error:
            for key in ("error_type", "location", "component", "cause", "suggested_context", "traceback", "command"):
                if key in structured_error:
                    error[key] = structured_error[key]
        if details is not None:
            error["details"] = details
        elif structured_error and "details" in structured_error:
            error["details"] = structured_error["details"]
        return Response.json(
            ApiResponse.payload(success=False, data=data, error=error),
            status=status,
            headers=headers,
        )
