"""Authenticator: resolves a request to an identity (or nothing).

The framework does **not** dictate *how* authentication happens — it only
fixes the contract::

    Authenticator.authenticate(request) -> Identity | None

Subclasses implement the actual credential extraction and resolution.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, Optional

from betrayer.auth.identity import AnonymousIdentity, Identity

__all__ = [
    "Authenticator",
    "HeaderTokenAuthenticator",
    "TokenResolver",
    "CallbackAuthenticator",
]

TokenResolver = Callable[[str], Optional[Identity]]
"""Given a raw token string, return an ``Identity`` or ``None``."""


class Authenticator(ABC):
    """Canonical authentication abstraction.

    Every authenticator implements exactly one method:

        authenticate(request) -> Identity | None

    The return is ``None`` when the request carries no credential or the
    credential is invalid — the framework never guesses who the request is.

    An authenticator may itself be a callable (if it subclasses this ABC) or
    a plain object with an ``authenticate`` method — the middleware and
    container only require duck-typing on that method name.
    """

    @abstractmethod
    def authenticate(self, request: Any) -> Optional[Identity]:
        """Resolve an authenticated identity from ``request``.

        Returns ``None`` when the request is anonymous (no recognised
        credential or the credential is invalid / unknown).
        """
        ...

    # -- introspection ------------------------------------------------
    def describe(self) -> dict:
        """Machine readable authenticator description."""
        return {
            "type": type(self).__name__,
            "class": f"{type(self).__module__}.{type(self).__qualname__}",
        }

    to_dict = describe


class HeaderTokenAuthenticator(Authenticator):
    """Extracts a Bearer token from ``Authorization: Bearer <token>``.

    Usage in development/testing::

        from betrayer.auth import Identity, HeaderTokenAuthenticator

        def resolve(token: str) -> Identity | None:
            if token == "secret-token":
                return Identity(id="dev-user", name="Dev User")
            return None

        authenticator = HeaderTokenAuthenticator(resolver=resolve)

    ``request`` may be a :class:`~betrayer.web.request.Request` or any object
    with a ``header(name, default)`` method or a ``.headers`` dict.
    """

    def __init__(
        self,
        resolver: TokenResolver,
        *,
        header: str = "Authorization",
        scheme: str = "Bearer",
    ) -> None:
        self._resolver = resolver
        self._header = header
        self._scheme = scheme
        self._prefix = f"{scheme} "

    def authenticate(self, request: Any) -> Optional[Identity]:
        token = self._extract_token(request)
        if token is None:
            return None
        try:
            return self._resolver(token)
        except Exception:  # noqa: BLE001 - resolver failure is not a crash
            return None

    def _extract_token(self, request: Any) -> Optional[str]:
        """Read the credential header from ``request``.

        Supports Betrayer's ``Request.header(name, default)`` method, a plain
        ``.headers`` dict, or a Flask/Werkzeug request object.
        """
        # Betrayer Request API
        header_fn = getattr(request, "header", None)
        if callable(header_fn):
            value = header_fn(self._header)
            if value and value.startswith(self._prefix):
                return value[len(self._prefix):]
            return None

        # Plain headers dict
        headers = getattr(request, "headers", None)
        if isinstance(headers, dict):
            value = headers.get(self._header, "")
            if value and value.startswith(self._prefix):
                return value[len(self._prefix):]
            return None

        # Flask/Werkzeug request
        try:
            value = request.headers.get(self._header, "")
        except (AttributeError, TypeError):
            return None
        if value and value.startswith(self._prefix):
            return value[len(self._prefix):]
        return None

    def describe(self) -> dict:
        base = super().describe()
        base["header"] = self._header
        base["scheme"] = self._scheme
        return base


class CallbackAuthenticator(Authenticator):
    """Authenticator backed by an arbitrary callable.

    Useful for testing or for wiring authentication logic without subclassing::

        from betrayer.auth import Identity, CallbackAuthenticator

        def my_auth(request) -> Identity | None:
            api_key = request.header("X-Api-Key")
            if api_key == "abc":
                return Identity(id=1, name="Service")
            return None

        authenticator = CallbackAuthenticator(callback=my_auth)
    """

    def __init__(self, callback: Callable[[Any], Optional[Identity]]) -> None:
        self._callback = callback

    def authenticate(self, request: Any) -> Optional[Identity]:
        try:
            return self._callback(request)
        except Exception:  # noqa: BLE001 - callback failure is not a crash
            return None

    def describe(self) -> dict:
        base = super().describe()
        base["callback"] = getattr(self._callback, "__name__", str(self._callback))
        return base