"""Authentication middleware: runs authentication as part of the HTTP pipeline.

The middleware integrates with the existing ``Middleware`` contract (see
:mod:`betrayer.web.middleware`) so authentication runs in the deterministic
request/response pipeline and is visible through middleware introspection.

Pipeline position
-----------------
Register before your handlers::

    registry.add(AuthenticationMiddleware(authenticator=...))

The middleware sets ``request.user`` on every request it processes (to either
an :class:`~betrayer.auth.Identity` or an
:class:`~betrayer.auth.AnonymousIdentity`), so the canonical API is always
available — ``request.user`` never raises.
"""

from __future__ import annotations

from typing import Any, Optional

from betrayer.auth.authenticator import Authenticator
from betrayer.auth.authorization import (
    DEFAULT_AUTHORIZER_KEY,
    Authorizer,
    authorize,
)
from betrayer.auth.identity import AnonymousIdentity, Identity

__all__ = [
    "AuthenticationMiddleware",
    "auth_middleware",
    "AuthorizationMiddleware",
]


#: Default attribute name for the identity on the request object.
_USER_ATTR = "user"


class AuthenticationMiddleware:
    """HTTP middleware that resolves ``request.user`` on every request.

    The middleware runs ``before_request`` and sets ``request.user`` to either
    an :class:`~betrayer.auth.Identity` (when the authenticator succeeds) or an
    :class:`~betrayer.auth.AnonymousIdentity` (when no credential is present
    or the credential is invalid).

    Protected endpoints (resources with ``authentication_required = True``)
    raise :class:`~betrayer.auth.errors.UnauthenticatedError` when
    ``request.user.is_anonymous`` is ``True`` — this is handled by the
    resource, not by this middleware, so business logic can decide which
    endpoints require authentication.

    Usage::

        from betrayer.auth import AuthenticationMiddleware, HeaderTokenAuthenticator

        authenticator = HeaderTokenAuthenticator(resolver=token_resolver)
        middleware = AuthenticationMiddleware(authenticator=authenticator)
        app.core.registry.get("web.middleware").add(middleware)
    """

    name = "authentication"
    priority: int = 0

    def __init__(
        self,
        authenticator: Optional[Authenticator] = None,
        *,
        user_attr: str = _USER_ATTR,
    ) -> None:
        self.authenticator = authenticator
        self.user_attr = user_attr

    def before_request(self, request: Any, context: Any) -> None:
        """Run authentication and attach the identity to ``request``.

        This never short-circuits — even an anonymous request gets an
        ``AnonymousIdentity`` attached.  Protected endpoints raise the
        401 error themselves, so middleware ordering is simpler.
        """
        identity: Identity
        if self.authenticator is not None:
            try:
                identity = self.authenticator.authenticate(request)
            except Exception:  # noqa: BLE001 - defensive: never crash in auth
                identity = None
        else:
            identity = None

        if identity is None:
            identity = AnonymousIdentity()

        # Use the canonical API: either set_user() or setattr fallback
        set_user = getattr(request, "set_user", None)
        if callable(set_user):
            set_user(identity)
        else:
            setattr(request, self.user_attr, identity)

    # -- introspection ------------------------------------------------
    def middleware_name(self) -> str:
        return self.name

    def describe(self) -> dict:
        return {
            "name": self.name,
            "type": type(self).__name__,
            "has_authenticator": self.authenticator is not None,
            "authenticator": (
                self.authenticator.describe()
                if self.authenticator is not None
                else None
            ),
            "user_attr": self.user_attr,
        }

    to_dict = describe

    def __repr__(self) -> str:  # pragma: no cover — debugging aid
        return f"<AuthenticationMiddleware has_auth={self.authenticator is not None}>"


def auth_middleware(*, authenticator: Optional[Authenticator] = None) -> AuthenticationMiddleware:
    """Convenience factory that calls ``before_request`` automatically on
    the returned middleware — useful for testing.

    Returns an ``AuthenticationMiddleware`` configured with the given
    ``authenticator``.
    """
    return AuthenticationMiddleware(authenticator=authenticator)


class AuthorizationMiddleware:
    """HTTP middleware that runs the authorization check on protected routes.

    Pipeline position — registered **after**
    :class:`~betrayer.auth.AuthenticationMiddleware`, so ``request.user``
    is already resolved when authorization runs (priority ``10`` > ``0``)::

        Authentication -> Authorization -> Validation -> Resource -> Service

    The middleware reads the declarative flags of the matched route::

        authorization_required = True       # check authorization (default False)
        authorization_action = "view"       # default action for every endpoint
        authorization_actions = {"POST": "create", ...}   # optional per method
        authorization_resource_key = "item" # path param passed as `resource`

    Authorization itself is resolved through the existing Container/DI
    (canonical key ``"authorizer"``, see
    :func:`betrayer.auth.authorization.authorize`), so the middleware adds no
    second policy system::

        app.container.instance("authorizer", my_authorizer)

    Usage::

        from betrayer.auth import AuthorizationMiddleware

        app.registry.get("web.middleware").add(AuthorizationMiddleware())
    """

    name = "authorization"
    priority: int = 10

    def __init__(
        self,
        *,
        authorizer: Optional[Authorizer] = None,
        authorizer_key: str = DEFAULT_AUTHORIZER_KEY,
    ) -> None:
        self.authorizer = authorizer
        self.authorizer_key = authorizer_key

    # -- hooks ---------------------------------------------------------
    def before_request(self, request: Any, context: Any) -> None:
        """Run the authorization check when the route requires it.

        Reads ``request.user`` (identity only — never re-authenticates),
        then delegates to :func:`betrayer.auth.authorization.authorize`.
        A denial raises :class:`~betrayer.web.exceptions.ForbiddenError`
        (403 ``FORBIDDEN``) which the existing error layer turns into the
        structured envelope.  Routes without the flags are untouched.
        """
        route = getattr(request, "route", None)
        if route is None or not getattr(route, "authorization_required", False):
            return
        metadata = getattr(route, "metadata", None) or {}
        action = getattr(route, "authorization_action", None) or metadata.get(
            "authorization_action"
        )
        if not action:
            actions = metadata.get("authorization_actions") or {}
            action = actions.get(getattr(request, "method", None))
        resource = None
        resource_key = getattr(
            route, "authorization_resource_key", None
        ) or metadata.get("authorization_resource_key")
        if resource_key:
            resource = request.param(str(resource_key))
        identity = getattr(request, "user", None)
        authorize(
            identity,
            action,
            resource=resource,
            context=context,
            authorizer=self.authorizer,
        )

    # -- introspection ---------------------------------------------------
    def middleware_name(self) -> str:
        return self.name

    def describe(self) -> dict:
        return {
            "name": self.name,
            "type": type(self).__name__,
            "authorizer_key": self.authorizer_key,
            "authorizer": (
                self.authorizer.describe() if self.authorizer is not None else None
            ),
            "runs_after": "authentication",
        }

    to_dict = describe

    def __repr__(self) -> str:  # pragma: no cover — debugging aid
        return f"<AuthorizationMiddleware has_authorizer={self.authorizer is not None}>"