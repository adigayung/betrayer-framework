"""Betrayer Authentication & Authorization capability.

Authentication determines **who** the request is (identity), not **what** the
request may do (authorization).  This package provides:

* :class:`Identity` / :class:`AnonymousIdentity` — who the request is
* :class:`Authenticator` — resolves ``request -> Identity | None``
* :class:`HeaderTokenAuthenticator` — ``Bearer <token>`` authenticator
* :class:`CallbackAuthenticator` — authenticator backed by any callable
* :class:`AuthenticationMiddleware` — sets ``request.user`` on every request
* :class:`AuthenticationError` / :class:`UnauthenticatedError` — auth errors

Authorization (Task 16.2) decides **what the identity may do**; it never
re-resolves identity:

* :class:`Authorizer` — ``authorize(identity, action, resource, context) -> bool``
* :class:`CallbackAuthorizer` / :class:`AllowAllAuthorizer` — ready-made policies
* :func:`authorize` — the explicit check; denial raises 403 ``FORBIDDEN``
* :class:`AuthorizationMiddleware` — pipeline middleware (after authentication)
* :class:`ForbiddenError` — 403 (re-exported from the existing web errors)
"""

from __future__ import annotations

from betrayer.auth.identity import AnonymousIdentity, Identity
from betrayer.auth.authenticator import (
    Authenticator,
    CallbackAuthenticator,
    HeaderTokenAuthenticator,
    TokenResolver,
)
from betrayer.auth.errors import AuthenticationError, UnauthenticatedError
from betrayer.auth.middleware import (
    AuthenticationMiddleware,
    AuthorizationMiddleware,
    auth_middleware,
)
from betrayer.auth.authorization import (
    AllowAllAuthorizer,
    Authorizer,
    CallbackAuthorizer,
    DEFAULT_AUTHORIZER_KEY,
    authorize,
)
from betrayer.web.exceptions import ForbiddenError

__all__ = [
    "Identity",
    "AnonymousIdentity",
    "Authenticator",
    "HeaderTokenAuthenticator",
    "CallbackAuthenticator",
    "TokenResolver",
    "AuthenticationMiddleware",
    "auth_middleware",
    "AuthenticationError",
    "UnauthenticatedError",
    # authorization (Task 16.2)
    "Authorizer",
    "CallbackAuthorizer",
    "AllowAllAuthorizer",
    "authorize",
    "AuthorizationMiddleware",
    "DEFAULT_AUTHORIZER_KEY",
    "ForbiddenError",
]