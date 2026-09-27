"""Authentication errors.

Extends the existing Betrayer exception hierarchy with authentication-specific
errors.  Everything stays under ``BetrayerError`` so the existing error
handling (structured envelope, diagnostics, HTTP mapping) works unchanged::

    BetrayerError
        └── AuthenticationError
        └── WebError
              └── UnauthenticatedError  (401 UNAUTHENTICATED)

``UnauthenticatedError`` inherits from
:class:`~betrayer.web.exceptions.WebError` directly (not ``UnauthorizedError``)
so that its ``code`` is ``UNAUTHENTICATED``, not ``UNAUTHORIZED`` — a semantic
distinction the framework and application code both rely on.
"""

from __future__ import annotations

from betrayer.core.exceptions import BetrayerError
from betrayer.web.exceptions import WebError

__all__ = [
    "AuthenticationError",
    "UnauthenticatedError",
]


class AuthenticationError(BetrayerError):
    """Something went wrong during the authentication process.

    An example is a misconfigured authenticator or an unparseable credential
    format.  This is **not** the normal ``401`` case — use
    :class:`UnauthenticatedError` for denied requests.
    """

    code = "AUTHENTICATION_ERROR"
    component = "auth"


class UnauthenticatedError(WebError):
    """Authentication was required but the request has no valid identity.

    ``http_status`` is ``401`` and ``code`` is ``UNAUTHENTICATED`` — the
    exact error the web layer returns when an anonymous request reaches a
    protected endpoint.
    """

    code = "UNAUTHENTICATED"
    http_status = 401