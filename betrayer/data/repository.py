"""Repository abstraction: data access layer integrated with Container/Model/Database.

A Repository encapsulates access to a data source for a specific Model type.
It is **not** an HTTP handler or business workflow layer.

Design rules:
- Repository depends on Model, DatabaseManager (or engine), and optional Container.
- Basic CRUD operations (get, find, list, create, update, delete).
- Does **not** contain HTTP/business logic.
- Works with Model instances (not dicts/raw rows) to enforce type safety.
"""

from __future__ import annotations

import inspect
from typing import (
    Any,
    Dict,
    Generic,
    List,
    Optional,
    Protocol,
    Sequence,
    Tuple,
    Type,
    TypeVar,
)

from betrayer.core.container import Container
from betrayer.data.database import DatabaseManager
from betrayer.data.exceptions import RepositoryError
from betrayer.data.models import Model

M = TypeVar("M", bound=Model)
"""Type variable bound to Model for typed Repository."""


class FindSpec(Protocol):
    """Protocol for finding records by field/value pairs."""

    def __call__(self, **filters: Any) -> Sequence[Model]:
        ...


class Repository(Generic[M]):
    """Generic repository over a Model type.

    Concrete subclasses implement ``_engine_methods``; this class provides
    the public API contract.

    Parameters
    ----------
    model_class : Type[M]
        The Model subclass this Repository manages.
    database : DatabaseManager
        Active database manager for connections/transactions.
    container : Optional[Container]
        Container for dependency injection integration.
    """

    def __init__(
        self,
        model_class: Type[M],
        database: DatabaseManager,
        container: Optional[Container] = None,
    ) -> None:
        if not inspect.isclass(model_class) or not issubclass(model_class, Model):
            raise RepositoryError(
                message=f"{model_class!r} is not a Model subclass",
                stage="init",
            )
        self._model_class: Type[M] = model_class
        self._database: DatabaseManager = database
        self._container: Optional[Container] = container

    # ── Public API ──────────────────────────────────────────────────────

    @property
    def model_class(self) -> Type[M]:
        """The Model type managed by this Repository."""
        return self._model_class

    @property
    def database(self) -> DatabaseManager:
        """Database manager used by this Repository."""
        return self._database

    def get(self, identifier: Any) -> Optional[M]:
        """Retrieve a single record by primary identifier.

        Subclasses override this with the actual query logic.
        """
        raise NotImplementedError  # pragma: no cover

    def find(self, **filters: Any) -> Sequence[M]:
        """Find records matching the given field/value filters.

        Subclasses override this with the actual query logic.
        """
        raise NotImplementedError  # pragma: no cover

    def list(self) -> Sequence[M]:
        """Return all records for the managed model.

        Subclasses override this with the actual query logic.
        """
        raise NotImplementedError  # pragma: no cover

    def create(self, model: M) -> M:
        """Persist a new record.

        Subclasses override this with the actual insert logic.
        """
        raise NotImplementedError  # pragma: no cover

    def update(self, model: M) -> M:
        """Update an existing record.

        Subclasses override this with the actual update logic.
        """
        raise NotImplementedError  # pragma: no cover

    def delete(self, identifier: Any) -> bool:
        """Delete a record by identifier. Returns True if deleted.

        Subclasses override this with the actual delete logic.
        """
        raise NotImplementedError  # pragma: no cover

    # ── Introspection ───────────────────────────────────────────────────

    def introspect(self) -> Dict[str, Any]:
        """Machine readable metadata for LLM inspection."""
        return {
            "type": "repository",
            "model": self._model_class.__name__,
            "model_fields": list(self._model_class._fields),
            "database": str(self._database),
        }


__all__ = [
    "Repository",
    "FindSpec",
]