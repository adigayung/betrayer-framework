"""Identity: who is this request?

Authentication answers exactly one question — *who is this request?* — and
never *what is this user allowed to do?* (that is authorization, a separate
capability).  :class:`Identity` is therefore deliberately small: it carries
the resolved user data and nothing else.

There is **no required User model/database**.  An application may back an
``Identity`` with anything (an ORM row, a dict, an external identity
provider); the framework only fixes the accessor contract:

* ``id``          — stable identifier (any JSON-serialisable value),
* ``name``        — optional display name,
* ``email``       — optional email,
* ``attributes``  — optional extra application-defined data (never secrets),
* ``is_authenticated`` / ``is_anonymous`` — the anonymous/authenticated test.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

__all__ = ["Identity", "AnonymousIdentity"]


class Identity:
    """One authenticated identity (the ``who`` of a request).

    Build it from whatever the application resolves a credential into::

        from betrayer.auth import Identity

        Identity(id=42, name="Ada", email="ada@example.com")
        Identity(id="svc-1", attributes={"scopes": ["products.read"]})
    """

    def __init__(
        self,
        id: Any = None,
        *,
        name: Optional[str] = None,
        email: Optional[str] = None,
        attributes: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.id = id
        self.name = name
        self.email = email
        #: Application-defined extra data.  Never store credentials here.
        self.attributes: Dict[str, Any] = dict(attributes or {})

    # -- state ---------------------------------------------------------
    @property
    def is_authenticated(self) -> bool:
        """``True`` for a real (non-anonymous) identity."""
        return True

    @property
    def is_anonymous(self) -> bool:
        """``False`` — this identity resolved from a credential."""
        return False

    # -- attribute access ------------------------------------------------
    def get(self, name: str, default: Any = None) -> Any:
        """One attribute by name (``default`` when absent)."""
        return self.attributes.get(name, default)

    # -- introspection ---------------------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        """Machine readable snapshot (never contains credentials)."""
        return {
            "id": self.id,
            "name": self.name,
            "email": self.email,
            "attributes": dict(self.attributes),
            "anonymous": self.is_anonymous,
        }

    describe = to_dict

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Identity id={self.id!r} name={self.name!r}>"


class AnonymousIdentity(Identity):
    """The identity of an unauthenticated request.

    The authentication middleware attaches exactly one of these to every
    request it runs on, so an anonymous request is always distinguishable
    from an authenticated one (``request.user.is_anonymous``).
    """

    @property
    def is_authenticated(self) -> bool:
        return False

    @property
    def is_anonymous(self) -> bool:
        return True

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "<AnonymousIdentity>"
