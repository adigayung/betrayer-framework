"""Relationship metadata and predictable relationship queries (Task 09.3).

A :class:`Relationship` is declared on an :class:`~betrayer.data.orm.ORMModel`
exactly like an :class:`~betrayer.data.orm.ORMField`::

    class User(ORMModel):
        id = ORMField(int, primary_key=True)
        posts = HasMany("Post")            # Post.user_id == user.id
        profile = HasOne("Profile")        # Profile.user_id == user.id

    class Post(ORMModel):
        id = ORMField(int, primary_key=True)
        author_id = ORMField(int)
        author = BelongsTo(User)           # Post.author_id == user.id

    class Product(ORMModel):
        id = ORMField(int, primary_key=True)
        categories = ManyToMany("Category")  # via a pivot table

``target`` may be:

* an :class:`~betrayer.data.orm.ORMModel` **class** (resolved immediately);
* a **string** model name, resolved lazily against the declaring model's
  module (this is how the common ``User.posts`` / ``Post.author`` cycle is
  expressed without forward references);
* a **zero-argument callable** returning the model class.

Accessing a relationship on an **instance** returns a small bound accessor
whose call returns a :class:`~betrayer.data.query.Query` scoped to the target
model.  There is **no** lazy loading and **no** magic attribute resolution:
every access is an explicit method call.

.. code-block:: python

    user.posts().get()                     # list[Post]
    user.posts().where("published", True).get()
    post.author().first()                  # User | None
    user.profile().first()                 # Profile | None
    product.categories().get()             # list[Category]

The contract is intentionally minimal and database-agnostic: it produces
ordinary :class:`~betrayer.data.query.Query` objects (or a deterministic
*empty* query) — never SQL, never a concrete driver, never a new query engine.
"""

from __future__ import annotations

import re
import sys
from typing import Any, Dict, Optional, Tuple

from betrayer.data.exceptions import ModelError
from betrayer.data.query import Query

__all__ = [
    "RELATIONSHIP_TYPES",
    "Relationship",
    "BelongsTo",
    "HasOne",
    "HasMany",
    "ManyToMany",
    "BoundRelationship",
]

#: The four canonical relationship types (one canonical name per need).
RELATIONSHIP_TYPES: Tuple[str, ...] = (
    "belongs_to",
    "has_one",
    "has_many",
    "many_to_many",
)

#: Cardinality per relationship type (``"one"`` or ``"many"``).
_CARDINALITY: Dict[str, str] = {
    "belongs_to": "one",
    "has_one": "one",
    "has_many": "many",
    "many_to_many": "many",
}


def _snake(name: str) -> str:
    """``UserProfile`` -> ``user_profile`` (deterministic, no pluralisation)."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def _is_model_like(target: Any) -> bool:
    """A relationship target must be an ORM model class (duck typed)."""
    return (
        isinstance(target, type)
        and callable(getattr(target, "query", None))
        and callable(getattr(target, "primary_key_name", None))
        and callable(getattr(target, "table_name", None))
    )


def _empty_query(target: Any) -> Query:
    """A deterministic query that matches **no** row for *target*.

    Implemented with the existing Query API only (``col IS NULL AND col IS NOT
    NULL`` is always false) — no joins, no raw SQL, no new query engine.
    """
    pk = target.primary_key_name()
    if pk is None:
        raise ModelError(
            message=(
                f"Cannot build relationship query: model {target.__name__} "
                "has no primary key"
            ),
            stage="relationship",
            context={"model": target.__name__},
        )
    return target.query().where_null(pk).where_not_null(pk)


class Relationship:
    """Declarative relationship between two ORM models.

    Prefer the typed helpers :class:`BelongsTo`, :class:`HasOne`,
    :class:`HasMany`, :class:`ManyToMany`.  The base class is exported so it
    can be used for ``isinstance`` checks.

    Parameters
    ----------
    kind:
        One of :data:`RELATIONSHIP_TYPES`.
    target:
        The related model — a class, a model-name string, or a zero-arg
        callable returning the class.
    foreign_key:
        The foreign key column.  Defaults depend on the kind (see each
        helper).  For ``belongs_to`` it lives on the owner; for
        ``has_one``/``has_many`` it lives on the target.
    local_key / target_key:
        Referenced key overrides (default: the relevant primary key).
    pivot / pivot_local_key / pivot_foreign_key:
        Pivot metadata for ``many_to_many``.
    description:
        Human/LLM readable description (metadata only).
    """

    def __init__(
        self,
        kind: str,
        target: Any,
        *,
        foreign_key: Optional[str] = None,
        local_key: Optional[str] = None,
        target_key: Optional[str] = None,
        pivot: Optional[str] = None,
        pivot_local_key: Optional[str] = None,
        pivot_foreign_key: Optional[str] = None,
        description: str = "",
    ) -> None:
        if kind not in RELATIONSHIP_TYPES:
            raise ModelError(
                message=f"Unknown relationship type {kind!r}",
                stage="define",
                context={"type": kind, "supported": list(RELATIONSHIP_TYPES)},
            )
        # A class is validated immediately; a string/callable is validated on
        # first resolution (so forward references work).
        if isinstance(target, type):
            if not _is_model_like(target):
                raise ModelError(
                    message=(
                        "Relationship target must be an ORM model class "
                        "(a subclass of betrayer.data.ORMModel)"
                    ),
                    stage="define",
                    context={"target": getattr(target, "__name__", repr(target))},
                )
        elif isinstance(target, str):
            if not target.strip():
                raise ModelError(
                    message="Relationship target name must be a non-empty string",
                    stage="define",
                )
        elif not callable(target):
            raise ModelError(
                message=(
                    "Relationship target must be an ORM model class, a model "
                    "name string, or a zero-arg callable"
                ),
                stage="define",
                context={"received": type(target).__name__},
            )

        self.kind: str = kind
        self._target_ref: Any = target
        self._resolved_target: Any = target if isinstance(target, type) else None
        self.foreign_key = foreign_key
        self.local_key = local_key
        self.target_key = target_key
        self.pivot = pivot
        self.pivot_local_key = pivot_local_key
        self.pivot_foreign_key = pivot_foreign_key
        self.description = description
        #: Name of the attribute this relationship is bound to (set by ORMeta).
        self.name: str = ""
        #: Owning model class (set by ORMeta for declared relationships).
        self.owner: Optional[type] = None

    # ── target resolution ─────────────────────────────────────────────

    def _resolve_target(self) -> Any:
        ref = self._target_ref
        if isinstance(ref, str):
            if self.owner is None:
                raise ModelError(
                    message=(
                        f"Cannot resolve relationship target {ref!r}: the "
                        "owning model is not known yet"
                    ),
                    stage="relationship",
                )
            module = sys.modules.get(self.owner.__module__)
            candidate = getattr(module, ref, None) if module is not None else None
            if not _is_model_like(candidate):
                raise ModelError(
                    message=(
                        f"Cannot resolve relationship target {ref!r} in module "
                        f"{self.owner.__module__}"
                    ),
                    stage="relationship",
                    context={"relationship": self.name, "target": ref},
                )
            return candidate
        candidate = ref()
        if not _is_model_like(candidate):
            raise ModelError(
                message="Relationship target callable did not return an ORM model",
                stage="relationship",
                context={"relationship": self.name},
            )
        return candidate

    @property
    def target(self) -> Any:
        """The related ORM model class (resolved lazily when needed)."""
        if self._resolved_target is None:
            self._resolved_target = self._resolve_target()
        return self._resolved_target

    # ── metadata ──────────────────────────────────────────────────────

    @property
    def cardinality(self) -> str:
        """``"one"`` for ``belongs_to``/``has_one``, ``"many"`` otherwise."""
        return _CARDINALITY[self.kind]

    def effective_keys(self) -> Dict[str, Any]:
        """Resolved key/pivot metadata (deterministic, no instance needed)."""
        owner = self.owner
        target = self.target
        keys: Dict[str, Any] = {}
        if self.kind == "belongs_to":
            keys["foreign_key"] = self.foreign_key or f"{self.name}_id"
            keys["target_key"] = self.target_key or target.primary_key_name()
            return keys
        if self.kind in ("has_one", "has_many"):
            owner_name = owner.__name__ if owner is not None else None
            keys["foreign_key"] = self.foreign_key or (
                f"{_snake(owner_name)}_id" if owner_name else None
            )
            keys["local_key"] = self.local_key or (
                owner.primary_key_name() if owner is not None else None
            )
            return keys
        # many_to_many
        pivot = self.pivot
        if pivot is None and owner is not None:
            pivot = f"{owner.table_name()}_{target.table_name()}"
        keys["pivot"] = pivot
        keys["pivot_local_key"] = self.pivot_local_key or (
            f"{_snake(owner.__name__)}_id" if owner is not None else None
        )
        keys["pivot_foreign_key"] = self.pivot_foreign_key or (
            f"{_snake(target.__name__)}_id"
        )
        keys["local_key"] = self.local_key or (
            owner.primary_key_name() if owner is not None else None
        )
        keys["target_key"] = self.target_key or target.primary_key_name()
        return keys

    def to_dict(self) -> Dict[str, Any]:
        """Stable, machine readable relationship metadata (LLM friendly)."""
        return {
            "name": self.name,
            "type": self.kind,
            "target": self.target.__name__,
            "cardinality": self.cardinality,
            "keys": self.effective_keys(),
            "description": self.description,
        }

    # ── descriptor protocol: instance access -> bound accessor ─────────

    def __get__(self, instance: Any, owner: Optional[type] = None) -> Any:
        if instance is None:
            return self
        return BoundRelationship(self, instance)

    # ── query building ────────────────────────────────────────────────

    def build_query(self, instance: Any) -> Query:
        """Build the :class:`Query` for this relationship on *instance*."""
        owner = type(instance)
        target = self.target
        if self.kind == "belongs_to":
            fk = self.foreign_key or f"{self.name}_id"
            fk_value = getattr(instance, fk, None)
            target_key = self.target_key or target.primary_key_name()
            if fk_value is None or target_key is None:
                return _empty_query(target)
            return target.query().where(target_key, fk_value)

        if self.kind in ("has_one", "has_many"):
            local_key = self.local_key or owner.primary_key_name()
            fk = self.foreign_key or f"{_snake(owner.__name__)}_id"
            local_value = getattr(instance, local_key, None) if local_key else None
            if local_value is None:
                return _empty_query(target)
            return target.query().where(fk, local_value)

        return self._build_many_to_many(instance, owner, target)

    def _build_many_to_many(self, instance: Any, owner: type, target: Any) -> Query:
        local_key = self.local_key or owner.primary_key_name()
        local_value = getattr(instance, local_key, None) if local_key else None
        target_key = self.target_key or target.primary_key_name()
        if local_value is None or target_key is None:
            return _empty_query(target)

        pivot = self.pivot or f"{owner.table_name()}_{target.table_name()}"
        pivot_local = self.pivot_local_key or f"{_snake(owner.__name__)}_id"
        pivot_foreign = self.pivot_foreign_key or f"{_snake(target.__name__)}_id"

        database = getattr(owner, "__connection__", None)
        if database is None:
            raise ModelError(
                message=(
                    f"many_to_many {self.name!r} requires the owning model "
                    f"{owner.__name__} to declare __connection__"
                ),
                stage="relationship",
                context={"relation": self.name, "pivot": pivot},
            )
        rows = Query(pivot, database=database).where(pivot_local, local_value).get()
        ids = []
        for row in rows:
            value = (
                row.get(pivot_foreign)
                if isinstance(row, dict)
                else getattr(row, pivot_foreign, None)
            )
            if value is not None:
                ids.append(value)
        if not ids:
            return _empty_query(target)
        return target.query().where_in(target_key, ids)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        name = (
            self._target_ref
            if not isinstance(self._target_ref, type)
            else self._target_ref.__name__
        )
        return f"{type(self).__name__}(name={self.name!r}, target={name!r})"


class BelongsTo(Relationship):
    """``owner.foreign_key == target.target_key`` (a single related row).

    ``foreign_key`` defaults to ``"<relationship_name>_id"`` on the owner;
    ``target_key`` defaults to the target's primary key.
    """

    def __init__(
        self,
        target: Any,
        *,
        foreign_key: Optional[str] = None,
        target_key: Optional[str] = None,
        description: str = "",
    ) -> None:
        super().__init__(
            "belongs_to",
            target,
            foreign_key=foreign_key,
            target_key=target_key,
            description=description,
        )


class HasOne(Relationship):
    """One target row whose ``foreign_key`` references the owner's ``local_key``.

    ``foreign_key`` defaults to ``"<owner_snake>_id"`` on the target;
    ``local_key`` defaults to the owner's primary key.
    """

    def __init__(
        self,
        target: Any,
        *,
        foreign_key: Optional[str] = None,
        local_key: Optional[str] = None,
        description: str = "",
    ) -> None:
        super().__init__(
            "has_one",
            target,
            foreign_key=foreign_key,
            local_key=local_key,
            description=description,
        )


class HasMany(Relationship):
    """Many target rows whose ``foreign_key`` references the owner's ``local_key``.

    ``foreign_key`` defaults to ``"<owner_snake>_id"`` on the target;
    ``local_key`` defaults to the owner's primary key.
    """

    def __init__(
        self,
        target: Any,
        *,
        foreign_key: Optional[str] = None,
        local_key: Optional[str] = None,
        description: str = "",
    ) -> None:
        super().__init__(
            "has_many",
            target,
            foreign_key=foreign_key,
            local_key=local_key,
            description=description,
        )


class ManyToMany(Relationship):
    """Many targets linked through a pivot table.

    ``pivot`` defaults to ``"<owner_table>_<target_table>"``;
    ``pivot_local_key`` defaults to ``"<owner_snake>_id"`` and
    ``pivot_foreign_key`` defaults to ``"<target_snake>_id"``.
    """

    def __init__(
        self,
        target: Any,
        *,
        pivot: Optional[str] = None,
        pivot_local_key: Optional[str] = None,
        pivot_foreign_key: Optional[str] = None,
        local_key: Optional[str] = None,
        target_key: Optional[str] = None,
        description: str = "",
    ) -> None:
        super().__init__(
            "many_to_many",
            target,
            pivot=pivot,
            pivot_local_key=pivot_local_key,
            pivot_foreign_key=pivot_foreign_key,
            local_key=local_key,
            target_key=target_key,
            description=description,
        )


class BoundRelationship:
    """Accessor returned when a relationship is read from an instance.

    Calling it (``user.posts()``) or :meth:`query` returns a
    :class:`~betrayer.data.query.Query` scoped to the target model.  Nothing is
    executed until the returned query is consumed (``.get()``/``.first()``/...),
    except for ``many_to_many`` which resolves the pivot ids up front.
    """

    def __init__(self, relationship: Relationship, instance: Any) -> None:
        self._relationship = relationship
        self._instance = instance

    @property
    def name(self) -> str:
        """The attribute name of the relationship."""
        return self._relationship.name

    @property
    def kind(self) -> str:
        """The relationship type (``belongs_to``/``has_one``/...)."""
        return self._relationship.kind

    @property
    def target(self) -> Any:
        """The related model class."""
        return self._relationship.target

    def query(self) -> Query:
        """The :class:`Query` for this relationship."""
        return self._relationship.build_query(self._instance)

    def __call__(self) -> Query:
        """``user.posts()`` -> a :class:`Query` scoped to the target model."""
        return self.query()

    def metadata(self) -> Dict[str, Any]:
        """Relationship metadata (same shape as :meth:`Relationship.to_dict`)."""
        return self._relationship.to_dict()

    def to_dict(self) -> Dict[str, Any]:
        return self.metadata()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"BoundRelationship(name={self.name!r}, kind={self.kind!r}, "
            f"target={self.target.__name__})"
        )
