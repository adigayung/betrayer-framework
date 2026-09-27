"""Authorizer: may this identity perform this action?

Authorization answers exactly one question — *is this identity allowed to
perform this action on this resource?* — and never *who is this request?*
(that is authentication, Task 16.1).  The framework fixes the contract, not
the policy::

    Authorizer.authorize(identity, action, resource=None, context=None) -> bool

* ``True``  → the request continues,
* ``False`` → the canonical :func:`authorize` check raises
  :class:`~betrayer.web.exceptions.ForbiddenError` (403 ``FORBIDDEN``).

Allow is a plain ``True``; a denial always raises at the call site, so the
result is deterministic and never silently swallowed.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable, Optional

from betrayer.web.exceptions import ForbiddenError

__all__ = [
    "Authorizer",
    "CallbackAuthorizer",
    "AllowAllAuthorizer",
    "authorize",
    "DEFAULT_AUTHORIZER_KEY",
]

#: Canonical container key for the application authorizer::
#:
#:     app.container.instance("authorizer", my_authorizer)
DEFAULT_AUTHORIZER_KEY = "authorizer"


class Authorizer(ABC):
    """Canonical authorization abstraction.

    Every authorizer implements exactly one method::

        authorize(identity, action, resource=None, context=None) -> bool

    * ``identity``  the identity from ``request.user`` (an
      :class:`~betrayer.auth.AnonymousIdentity` when the request is
      anonymous),
    * ``action``    short verb-like string, e.g. ``"view"`` / ``"update"``,
    * ``resource``  optional object the action applies to (an id, a model
      instance, a resource name — the policy decides),
    * ``context``   optional request :class:`~betrayer.web.WebContext`.

    Return ``True`` to allow and ``False`` to deny; the caller turns a
    denial into ``403 FORBIDDEN``, so the policy itself stays a plain
    boolean.
    """

    @abstractmethod
    def authorize(
        self,
        identity: Any,
        action: str,
        resource: Any = None,
        context: Any = None,
    ) -> bool:
        """Decide whether ``identity`` may perform ``action`` on ``resource``."""
        ...

    # -- introspection --------------------------------------------------
    def describe(self) -> dict:
        """Machine readable authorizer description (no secrets)."""
        return {
            "type": type(self).__name__,
            "class": f"{type(self).__module__}.{type(self).__qualname__}",
        }

    to_dict = describe


class CallbackAuthorizer(Authorizer):
    """Authorizer backed by an arbitrary callable.

    Wiring a policy without subclassing::

        from betrayer.auth import CallbackAuthorizer

        def policy(identity, action, resource=None, context=None) -> bool:
            return action == "view" or identity.get("role") == "admin"

        app.container.instance("authorizer", CallbackAuthorizer(policy))
    """

    def __init__(self, callback: Callable[..., bool]) -> None:
        self._callback = callback

    def authorize(
        self,
        identity: Any,
        action: str,
        resource: Any = None,
        context: Any = None,
    ) -> bool:
        return bool(self._callback(identity, action, resource, context))

    def describe(self) -> dict:
        base = super().describe()
        base["callback"] = getattr(self._callback, "__name__", str(self._callback))
        return base


class AllowAllAuthorizer(Authorizer):
    """Allows every *authenticated* identity, denies anonymous ones.

    Minimal starting point for wiring and tests; real policies subclass
    :class:`Authorizer` or use :class:`CallbackAuthorizer`.
    """

    def authorize(
        self,
        identity: Any,
        action: str,
        resource: Any = None,
        context: Any = None,
    ) -> bool:
        return identity is not None and not getattr(identity, "is_anonymous", True)


def _resolve_authorizer(context: Any = None, authorizer: Any = None) -> Optional[Any]:
    """Authorizer resolution order (first match wins):

    1. the explicit ``authorizer`` argument,
    2. the ``context.container`` service ``"authorizer"`` (canonical DI key).
    """
    if authorizer is not None:
        return authorizer
    container = getattr(context, "container", None)
    if container is not None:
        has = getattr(container, "has", None)
        if callable(has) and has(DEFAULT_AUTHORIZER_KEY):
            return container.resolve(DEFAULT_AUTHORIZER_KEY)
    return None


def authorize(
    identity: Any,
    action: str,
    resource: Any = None,
    context: Any = None,
    *,
    authorizer: Any = None,
) -> None:
    """Canonical authorization check — deterministic::

        authorize(identity, action="update", resource=product, context=context)

    Allowed → returns ``None`` and the request continues.  Denied → raises
    :class:`~betrayer.web.exceptions.ForbiddenError` (403 ``FORBIDDEN``,
    canonical code ``FORBIDDEN``) using the existing error envelope.

    The authorizer is resolved in this order:

    1. explicit ``authorizer=`` argument,
    2. ``context.container.resolve("authorizer")`` — the canonical container
       service (:data:`DEFAULT_AUTHORIZER_KEY`).

    With no authorizer available this raises ``RuntimeError`` — a missing DI
    wiring problem, **never** a silent allow.  The denial ``context`` only
    carries the ``action`` name and the resource *type* name, never resource
    values.
    """
    resolved = _resolve_authorizer(context, authorizer)
    if resolved is None:
        raise RuntimeError(
            "No authorizer available for the authorization check. Register "
            "one with app.container.instance('authorizer', ...) or pass "
            "authorizer=... explicitly."
        )
    if resolved.authorize(identity, action, resource=resource, context=context):
        return
    raise ForbiddenError(
        message=f"Not allowed to perform '{action}'",
        context={
            "action": action,
            "resource_type": (
                type(resource).__name__ if resource is not None else None
            ),
        },
    )
