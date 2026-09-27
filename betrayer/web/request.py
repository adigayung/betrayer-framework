"""Request abstraction over the Flask request.

Handlers receive a :class:`Request` so application code never depends on
Flask's thread local globals directly.  Flask stays the parser: this class is
a thin, predictable, introspectable facade.

Accessors are grouped the way an LLM asks for them:

    method, path, url, query (+ args), headers, cookies, body (+ text, json),
    form, files, remote_addr/remote_user, path parameters (``param``) and the
    matched :class:`betrayer.web.routing.Route`.

Safety: :meth:`Request.to_dict` returns header/cookie/file **names** but not
their values, so it is safe to log or expose through introspection.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from betrayer.web.flask_bridge import import_flask_request

__all__ = ["Request"]

_MISSING = object()


class Request:
    """Betrayer facade for one HTTP request.

    ``raw`` is the underlying Flask request; when it is ``None`` the current
    request proxy is used lazily, which is how the adapter builds requests
    inside a Flask view.
    """

    def __init__(
        self,
        raw: Any = None,
        *,
        path_params: Optional[dict] = None,
        route: Any = None,
    ) -> None:
        self._raw = raw
        self.path_params: Dict[str, Any] = dict(path_params or {})
        self.route = route
        #: Memoised JSON body.  ``get_json`` parses at most once per request,
        #: so the validation pipeline never re-parses the body.
        self._json_cache: Any = _MISSING

    # -- construction -------------------------------------------------
    @classmethod
    def from_flask(
        cls,
        raw: Any = None,
        *,
        path_params: Optional[dict] = None,
        route: Any = None,
    ) -> "Request":
        """Build a Betrayer request from a Flask request (or the current one)."""
        return cls(raw, path_params=path_params, route=route)

    @property
    def raw(self) -> Any:
        """The wrapped Flask request (escape hatch, undocumented internals)."""
        return self._flask_request()

    def bind(self, route: Any, path_params: Optional[dict] = None) -> "Request":
        """Attach the matched route and its path parameters; returns ``self``."""
        self.route = route
        self.path_params = dict(path_params or {})
        return self

    def _flask_request(self) -> Any:
        if self._raw is None:
            self._raw = import_flask_request()
        return self._raw

    # -- path parameters ----------------------------------------------
    def param(self, name: str, default: Any = None) -> Any:
        """Path parameter value (``/users/<user_id>`` -> ``param("user_id")``)."""
        return self.path_params.get(name, default)

    def has_param(self, name: str) -> bool:
        """Return ``True`` when the route declared ``name`` as a path parameter."""
        return name in self.path_params

    # -- request line -------------------------------------------------
    @property
    def method(self) -> str:
        """HTTP method, upper case (``GET``)."""
        return str(self._flask_request().method).upper()

    @property
    def path(self) -> str:
        """URL path without the query string."""
        return self._flask_request().path

    @property
    def full_path(self) -> str:
        """Path including the query string."""
        return self._flask_request().full_path

    @property
    def url(self) -> str:
        """Absolute URL of the request."""
        return self._flask_request().url

    @property
    def base_url(self) -> str:
        """Absolute URL without the query string."""
        return self._flask_request().base_url

    @property
    def host(self) -> str:
        """Host header value (``example.com`` or ``example.com:5000``)."""
        return self._flask_request().host

    @property
    def scheme(self) -> str:
        """``http`` or ``https``."""
        return self._flask_request().scheme

    @property
    def endpoint(self) -> Optional[str]:
        """Flask endpoint name of the matched rule (usually the Betrayer endpoint)."""
        return getattr(self._flask_request(), "endpoint", None)

    # -- query --------------------------------------------------------
    @property
    def query(self) -> Dict[str, Any]:
        """Query string as a plain mapping (first value per key)."""
        return dict(self._flask_request().args)

    @property
    def args(self) -> Dict[str, Any]:
        """Alias of :attr:`query` (Flask naming)."""
        return self.query

    def query_list(self, name: str) -> List[str]:
        """All values of a repeated query parameter (``?tag=a&tag=b``)."""
        return list(self._flask_request().args.getlist(name))

    def get_query(self, name: str, default: Any = _MISSING) -> Any:
        """Single query parameter; raises nothing, returns ``default`` when absent."""
        value = self._flask_request().args.get(name, None)
        if value is None:
            if default is _MISSING:
                return None
            return default
        return value

    # -- headers / cookies --------------------------------------------
    @property
    def headers(self) -> Dict[str, str]:
        """All request headers as a plain mapping."""
        return dict(self._flask_request().headers)

    def header(self, name: str, default: Any = None) -> Any:
        """Single header, case insensitive (``header("Content-Type")``)."""
        return self._flask_request().headers.get(name, default)

    @property
    def content_type(self) -> Optional[str]:
        """``Content-Type`` header value, if any."""
        return self._flask_request().content_type

    @property
    def content_length(self) -> Optional[int]:
        """``Content-Length`` header value, if any."""
        return getattr(self._flask_request(), "content_length", None)

    @property
    def cookies(self) -> Dict[str, str]:
        """All cookies as a plain mapping."""
        return dict(self._flask_request().cookies)

    def cookie(self, name: str, default: Any = None) -> Any:
        """Single cookie value."""
        return self._flask_request().cookies.get(name, default)

    # -- body ---------------------------------------------------------
    @property
    def body(self) -> bytes:
        """Raw request body as bytes."""
        return self._flask_request().get_data()

    @property
    def text(self) -> str:
        """Raw request body decoded as text."""
        return self._flask_request().get_data(as_text=True)

    @property
    def is_json(self) -> bool:
        """Return ``True`` when the request advertises a JSON content type."""
        return bool(self._flask_request().is_json)

    @property
    def json(self) -> Any:
        """Parsed JSON body, or ``None`` when the body is missing/invalid."""
        return self.get_json()

    def get_json(self, default: Any = None) -> Any:
        """Parsed JSON body with an explicit fallback (never raises).

        The body is parsed at most **once** per request: the result is
        memoised on this ``Request`` instance, so callers (the validation
        pipeline, handlers, ...) share one parse and never re-read the stream.
        """
        if self._json_cache is _MISSING:
            raw = self._flask_request()
            try:
                self._json_cache = raw.get_json(silent=True)
            except Exception:  # noqa: BLE001 - defensive: JSON parsing must not 500
                self._json_cache = None
        value = self._json_cache
        return default if value is None else value

    @property
    def form(self) -> Dict[str, Any]:
        """Form fields as a plain mapping (first value per key)."""
        return dict(self._flask_request().form)

    @property
    def files(self) -> Dict[str, Any]:
        """Uploaded files by field name (``FileStorage`` values)."""
        return dict(self._flask_request().files)

    def file(self, name: str, default: Any = None) -> Any:
        """Single uploaded file by field name."""
        return self._flask_request().files.get(name, default)

    # -- remote -------------------------------------------------------
    @property
    def remote_addr(self) -> Optional[str]:
        """Client IP address as reported by the WSGI server/proxy headers."""
        return self._flask_request().remote_addr

    @property
    def remote_user(self) -> Optional[str]:
        """Authenticated user reported by the WSGI server, if any."""
        return getattr(self._flask_request(), "remote_user", None)

    @property
    def user_agent(self) -> Optional[str]:
        """``User-Agent`` header value, if any."""
        return self.header("User-Agent")

    # -- introspection ------------------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        """Machine readable snapshot: metadata only, never header/cookie values."""
        raw = self._flask_request()
        route = self.route
        return {
            "method": self.method,
            "path": self.path,
            "url": self.url,
            "query": self.query,
            "path_params": dict(self.path_params),
            "route": getattr(route, "endpoint", None),
            "endpoint": getattr(raw, "endpoint", None),
            "content_type": self.content_type,
            "content_length": self.content_length,
            "remote_addr": self.remote_addr,
            "is_json": self.is_json,
            "headers": sorted(str(name) for name in raw.headers.keys()),
            "cookies": sorted(str(name) for name in raw.cookies.keys()),
            "files": sorted(str(name) for name in raw.files.keys()),
        }

    describe = to_dict

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Request {self.method} {self.path}>"
