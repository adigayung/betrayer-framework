"""Canonical Repository layer over the ORM / Query Builder (Task 09.3).

A :class:`BaseRepository` is the single, predictable data-access entry point
between a *Service* and the ORM.  It wraps one explicit
:class:`~betrayer.data.orm.ORMModel` and offers CRUD without the caller ever
writing SQL or touching a dialect::

    class UserRepository(BaseRepository[User]):
        pass

    repo = UserRepository(User)
    user = repo.find(1)                  # User | None
    user = repo.find_or_fail(1)          # User or RepositoryError
    users = repo.all()
    users = repo.where("active", True).order_by("id", "desc").get()
    user = repo.create(name="John", email="john@example.com")
    repo.update(1, {"name": "Jane"})     # -> affected rows
    repo.delete(1)                       # -> affected rows
    repo.count()
    repo.exists(email="a@b.c")

Design rules (LLM-first, database-agnostic):

* it **reuses** :class:`~betrayer.data.query.Query` and
  :class:`~betrayer.data.orm.ORMModel` — no second query engine, no SQL here;
* it contains **no** ``if database == "sqlite"/...`` branching;
* update/delete always carry a primary-key ``where`` — the 09.2 safety
  contract (no accidental full-table write) is preserved;
* its metadata is introspectable via :meth:`BaseRepository.introspect`.

The legacy :class:`betrayer.data.repository.Repository` (a ``Model``-typed,
container-integrated skeleton used by the code generators) is **left
untouched** for backward compatibility.
"""

from __future__ import annotations

from typing import Any, Dict, Generic, List, Mapping, Optional, Type, TypeVar

from betrayer.data.exceptions import RepositoryError

__all__ = ["BaseRepository"]

M = TypeVar("M")


def _is_orm_model(model: Any) -> bool:
    """Duck-typed check: an ORM model exposes ``query``/``table_name``/..."""
    return (
        isinstance(model, type)
        and callable(getattr(model, "query", None))
        and callable(getattr(model, "primary_key_name", None))
        and callable(getattr(model, "table_name", None))
    )


class BaseRepository(Generic[M]):
    """Generic, ORM-backed repository bound to a single model class.

    Parameters
    ----------
    model:
        The :class:`~betrayer.data.orm.ORMModel` subclass this repository
        manages (explicit, never inferred).

    Subclass it to add resource-specific query methods; the CRUD surface and
    metadata contract stay identical::

        class PostRepository(BaseRepository[Post]):
            def published(self):
                return self.where("published", True).get()
    """

    def __init__(self, model: Type[M]) -> None:
        if not _is_orm_model(model):
            raise RepositoryError(
                message=(
                    "BaseRepository requires an ORM model class "
                    "(a subclass of betrayer.data.ORMModel)"
                ),
                stage="init",
                context={
                    "model": getattr(model, "__name__", repr(model)),
                    "received": type(model).__name__,
                },
            )
        self._model: Type[M] = model

    # ── introspection ─────────────────────────────────────────────────

    @property
    def model(self) -> Type[M]:
        """The ORM model class managed by this repository."""
        return self._model

    @property
    def model_class(self) -> Type[M]:
        """Alias of :attr:`model` (framework-wide naming)."""
        return self._model

    def introspect(self) -> Dict[str, Any]:
        """Deterministic, machine readable repository metadata."""
        relationships = []
        if callable(getattr(self._model, "orm_relationships", None)):
            relationships = [
                r.to_dict() for r in self._model.orm_relationships().values()
            ]
        return {
            "type": "repository",
            "name": type(self).__name__,
            "model": self._model.__name__,
            "table": self._model.table_name(),
            "primary_key": self._model.primary_key_name(),
            "relationships": relationships,
        }

    # ── query entry points (reuse the Query Builder) ──────────────────

    def query(self) -> Any:
        """A model-aware :class:`~betrayer.data.query.Query` on the table."""
        return self._model.query()

    def where(self, column: str, value: Any, operator: str = "=") -> Any:
        """A :class:`Query` filtered by ``column <operator> value``."""
        return self._model.query().where(column, value, operator)

    # ── read ──────────────────────────────────────────────────────────

    def find(self, identifier: Any) -> Optional[M]:
        """Return the row with the given primary key (or ``None``)."""
        pk = self._primary_key()
        return self._model.query().where(pk, identifier).first()

    def find_or_fail(self, identifier: Any) -> M:
        """Like :meth:`find`, but raise ``RepositoryError`` when missing."""
        pk = self._primary_key()
        found = self._model.query().where(pk, identifier).first()
        if found is None:
            raise RepositoryError(
                message=f"{self._model.__name__} not found",
                stage="find",
                context={
                    "model": self._model.__name__,
                    "primary_key": pk,
                    "identifier": identifier,
                },
            )
        return found

    def all(self) -> List[M]:
        """Return every row for the managed model."""
        return self._model.query().get()

    def count(self) -> int:
        """Number of rows for the managed model."""
        return self._model.query().count()

    def exists(self, **filters: Any) -> bool:
        """Whether any row matches ``filters`` (column=value); no filters = any."""
        query = self._model.query()
        for column, value in filters.items():
            query = query.where(column, value)
        return query.exists()

    # ── write ─────────────────────────────────────────────────────────

    def create(self, values: Optional[Mapping[str, Any]] = None, **kwargs: Any) -> M:
        """Insert a new row and return the hydrated model instance."""
        data: Dict[str, Any] = dict(values or {})
        data.update(kwargs)
        return self._model.create(**data)

    def update(
        self,
        identifier: Any,
        values: Optional[Mapping[str, Any]] = None,
        **kwargs: Any,
    ) -> int:
        """Update the row ``identifier`` and return the number of affected rows.

        Refuses to run without an identifier — the primary key ``where`` keeps
        the 09.2 safety contract (never a full-table update).
        """
        pk = self._primary_key()
        data: Dict[str, Any] = dict(values or {})
        data.update(kwargs)
        if identifier is None:
            raise RepositoryError(
                message="update requires a primary key identifier",
                stage="update",
                context={"model": self._model.__name__, "primary_key": pk},
            )
        if not data:
            raise RepositoryError(
                message="update requires at least one column/value",
                stage="update",
                context={"model": self._model.__name__},
            )
        result = self._model.query().where(pk, identifier).update(data)
        return int(result.get("affected", 0))

    def delete(self, identifier: Any) -> int:
        """Delete the row ``identifier``; return the number of affected rows.

        Refuses to run without an identifier — never a full-table delete.
        """
        pk = self._primary_key()
        if identifier is None:
            raise RepositoryError(
                message="delete requires a primary key identifier",
                stage="delete",
                context={"model": self._model.__name__, "primary_key": pk},
            )
        result = self._model.query().where(pk, identifier).delete()
        return int(result.get("affected", 0))

    # ── internals ─────────────────────────────────────────────────────

    def _primary_key(self) -> str:
        pk = self._model.primary_key_name()
        if pk is None:
            raise RepositoryError(
                message=f"{self._model.__name__} has no primary key",
                stage="init",
                context={"model": self._model.__name__},
            )
        return pk

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"{type(self).__name__}(model={self._model.__name__})"
