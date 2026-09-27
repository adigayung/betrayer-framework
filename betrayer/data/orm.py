"""ORM model abstraction: declarative table models on top of Query Builder.

Task 09.2.  ``ORMModel`` is the canonical ORM entity.  It is the **only**
model class that talks to the database (via :class:`~betrayer.data.query.Query`
and the 09.1 connection contract).  The existing DTO :class:`~betrayer.data.models.Model`
stays untouched for backward compatibility — it stays a plain data container
and does **not** gain database behaviour.

Declare a model::

    from betrayer.data import ORMModel, ORMField

    class User(ORMModel):
        __table__ = "users"                    # optional (auto: "users")
        __connection__ = manager               # DatabaseManager/Engine/provider

        id = ORMField(int, primary_key=True)
        name = ORMField(str, required=True)
        active = ORMField(bool, default=True)
        email = ORMField(str, nullable=True)

Canonical usage::

    user = User.query().where("email", email).first()
    users = User.query().where("active", True).order_by("created_at", "desc").limit(10).get()
    user = User.create(name="John", email="john@example.com")
    user.name = "Jane"
    user.save()
    user.delete()
    user.refresh()
    user.to_dict()
    User.meta()          # metadata without reading source

The model layer contains **no** concrete database dependency and no
SQLite/PostgreSQL/MySQL-specific code; all SQL behaviour lives in the dialect
and the compiler.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Tuple, Type, Union

from betrayer.data.exceptions import ModelError, QueryError
from betrayer.data.query import Query
from betrayer.data.relationships import Relationship
from betrayer.data.value import ValueMapper, canonical_type, python_type_name

__all__ = [
    "ORMModel",
    "ORMField",
    "ORMeta",
]


def _default_table_name(model_name: str) -> str:
    """``UserProfile`` -> ``user_profiles`` (snake_case + plural)."""
    snake = re.sub(r"(?<!^)(?=[A-Z])", "_", model_name).lower()
    return f"{snake}s"


class ORMField:
    """Declarative column description for an :class:`ORMModel`.

    Parameters
    ----------
    type_ : type
        Python type of the column (``str``, ``int``, ``float``, ``bool``,
        ``datetime``, ``date``, ``Decimal``, ...).
    primary_key : bool
        Mark as the primary key column (one per model).
    required : bool
        Value must be provided on create (unless a default exists).
    default : Any
        Default applied when no value is given.
    nullable : bool
        Column accepts ``None``.
    unique : bool
        Column has a uniqueness constraint (metadata only - DDL lives in the
        migration layer).
    indexed : bool
        Column is indexed (metadata only).
    description : str
        Human/LLM readable description.
    """

    def __init__(
        self,
        type_: type = str,
        *,
        primary_key: bool = False,
        required: bool = False,
        default: Any = None,
        nullable: bool = True,
        unique: bool = False,
        indexed: bool = False,
        description: str = "",
    ) -> None:
        if type_ is None:
            raise ModelError(
                message="ORMField requires a Python type (use type_=...); "
                        "unsupported/ambiguous columns are not allowed",
                stage="init",
            )
        self.type_ = type_
        self.primary_key = primary_key
        self.required = required
        self.default = default
        self.nullable = nullable
        self.unique = unique
        self.indexed = indexed
        self.description = description
        self.name: str = ""
        self._mapper: Optional[ValueMapper] = None

    @property
    def mapper(self) -> ValueMapper:
        """The value mapper for this field (lazily created)."""
        if self._mapper is None:
            self._mapper = ValueMapper(self.type_)
        return self._mapper

    def coerce(self, value: Any) -> Any:
        """Coerce *value* to the declared type (database value conversion)."""
        if value is None:
            return None
        try:
            return self.mapper.from_database(value)
        except ModelError:
            raise
        except Exception as exc:
            raise ModelError(
                message=(
                    f"Cannot convert value {value!r} for field "
                    f"{self.name!r} to {python_type_name(self.type_)}"
                ),
                stage="validate",
                cause=exc,
            ) from exc

    def to_dict(self) -> Dict[str, Any]:
        """Stable, machine readable field metadata."""
        return {
            "name": self.name,
            "type": python_type_name(self.type_),
            "primary_key": self.primary_key,
            "required": self.required,
            "nullable": self.nullable,
            "default": self.default,
            "unique": self.unique,
            "indexed": self.indexed,
            "description": self.description,
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"ORMField({self.name or '?'}: {python_type_name(self.type_)})"


class ORMeta(type):
    """Metaclass that collects :class:`ORMField` and :class:`Relationship`
    declarations into ``_orm_fields`` and ``_orm_relationships``."""

    def __new__(
        mcs, name: str, bases: tuple, namespace: dict
    ) -> "ORMeta":
        cls = super().__new__(mcs, name, bases, namespace)
        fields: Dict[str, ORMField] = {}
        for base in reversed(bases):
            if hasattr(base, "_orm_fields"):
                fields.update(base._orm_fields)
        relationships: Dict[str, Relationship] = {}
        for base in reversed(bases):
            if hasattr(base, "_orm_relationships"):
                relationships.update(base._orm_relationships)
        for attr_name, attr_value in namespace.items():
            if isinstance(attr_value, ORMField):
                attr_value.name = attr_name
                fields[attr_name] = attr_value
            elif isinstance(attr_value, Relationship):
                attr_value.name = attr_name
                attr_value.owner = cls
                relationships[attr_name] = attr_value
        collisions = sorted(set(fields) & set(relationships))
        if collisions:
            raise ModelError(
                message=(
                    f"{name}: name(s) {collisions} declared as both ORMField "
                    "and Relationship"
                ),
                stage="define",
                context={"model": name, "collisions": collisions},
            )
        cls._orm_fields = fields  # type: ignore[attr-defined]
        cls._orm_relationships = relationships  # type: ignore[attr-defined]

        table = namespace.get("__table__") or _default_table_name(name)
        cls._orm_table = table  # type: ignore[attr-defined]

        pk = namespace.get("__primary_key__")
        if pk is None:
            for field in fields.values():
                if field.primary_key:
                    pk = field.name
                    break
            if pk is None:
                pk = "id" if "id" in fields else None
        cls._orm_primary_key = pk  # type: ignore[attr-defined]
        return cls


class ORMModel(metaclass=ORMeta):
    """Base class for ORM entities (database-backed models).

    Class attributes (all optional):

    * ``__table__``       — table name (default: snake_case plural of the class)
    * ``__connection__``  — :class:`~betrayer.data.database.DatabaseManager`,
      :class:`~betrayer.data.database.DatabaseEngine`, or a zero-arg callable
      returning a :class:`~betrayer.data.database.Connection`
    * ``__primary_key__`` — primary key field name (default: the field marked
      ``primary_key=True``, else ``"id"`` when present)
    * ``__repository__``  — optional default repository (a
      :class:`~betrayer.data.base_repository.BaseRepository` subclass or
      instance).  When omitted, ``Model.repository()`` returns a canonical
      ``BaseRepository`` bound to the model.
    """

    __table__: Optional[str] = None
    __connection__: Any = None
    __primary_key__: Optional[str] = None
    __repository__: Any = None

    _orm_fields: Dict[str, ORMField]
    _orm_relationships: Dict[str, Relationship]
    _orm_table: str
    _orm_primary_key: Optional[str]

    def __init__(self, **values: Any) -> None:
        for name, field in self._orm_fields.items():
            if name in values:
                setattr(self, name, field.coerce(values[name]))
            elif field.default is not None:
                setattr(self, name, field.default)
            else:
                setattr(self, name, None)
        for extra, value in values.items():
            if extra not in self._orm_fields:
                setattr(self, extra, value)

    # ── metadata (LLM facing, no source reading required) ─────────────

    @classmethod
    def table_name(cls) -> str:
        """The database table name for this model."""
        return cls._orm_table

    @classmethod
    def primary_key_name(cls) -> Optional[str]:
        """Name of the primary key field (``None`` when not declared)."""
        return cls._orm_primary_key

    @classmethod
    def orm_fields(cls) -> Dict[str, ORMField]:
        """Ordered mapping of field name -> :class:`ORMField`."""
        return dict(cls._orm_fields)

    @classmethod
    def orm_relationships(cls) -> Dict[str, Relationship]:
        """Ordered mapping of relationship name -> :class:`Relationship`."""
        return dict(cls._orm_relationships)

    @classmethod
    def relationship(cls, name: str) -> Relationship:
        """Return a declared :class:`Relationship` by name.

        Raises ``ModelError`` when no such relationship exists.
        """
        rel = cls._orm_relationships.get(name)
        if rel is None:
            raise ModelError(
                message=(
                    f"Model {cls.__name__} has no relationship {name!r}"
                ),
                stage="relationship",
                context={
                    "model": cls.__name__,
                    "relationship": name,
                    "known": sorted(cls._orm_relationships),
                },
            )
        return rel

    @classmethod
    def meta(cls) -> Dict[str, Any]:
        """Deterministic model metadata (no implementation reading needed)."""
        connection = cls.__connection__
        connection_info: Any = None
        if hasattr(connection, "introspect") and callable(connection.introspect):
            try:
                connection_info = connection.introspect()
            except Exception:  # pragma: no cover - best effort
                connection_info = {"type": type(connection).__name__}
        elif connection is not None:
            connection_info = {"type": type(connection).__name__}
        return {
            "type": "orm_model",
            "name": cls.__name__,
            "module": cls.__module__,
            "table": cls.table_name(),
            "primary_key": cls.primary_key_name(),
            "fields": [f.to_dict() for f in cls._orm_fields.values()],
            "relationships": [
                r.to_dict() for r in cls._orm_relationships.values()
            ],
            "connection": connection_info,
        }

    # Alias so ``model.introspect()`` and ``model.meta()`` both work.
    @classmethod
    def introspect(cls) -> Dict[str, Any]:
        return cls.meta()

    # ── class-level row helpers ───────────────────────────────────────

    @classmethod
    def _require_connection(cls) -> Any:
        connection = cls.__connection__
        if connection is None:
            raise QueryError(
                message=(
                    f"Model {cls.__name__} has no __connection__; set "
                    f"__connection__ = DatabaseManager/Engine/provider"
                ),
                stage="init",
                context={"model": cls.__name__},
            )
        return connection

    @classmethod
    def query(cls) -> Query:
        """Start a model-aware query on this model's table."""
        return Query(
            cls.table_name(),
            database=cls._require_connection(),
            model=cls,
        )

    @classmethod
    def repository(cls) -> Any:
        """Return the canonical/default repository for this model.

        Uses ``__repository__`` when declared (a
        :class:`~betrayer.data.base_repository.BaseRepository` subclass or
        instance).  Otherwise returns a plain ``BaseRepository`` bound to this
        model — so every ORM model has a predictable repository without extra
        wiring.
        """
        from betrayer.data.base_repository import BaseRepository

        configured = getattr(cls, "__repository__", None)
        if configured is None:
            return BaseRepository(cls)
        if isinstance(configured, type):
            return configured(cls)
        return configured

    @classmethod
    def _from_row(cls, row: Any) -> "ORMModel":
        if row is None:
            return None  # type: ignore[return-value]
        if not isinstance(row, dict):
            raise ModelError(
                message=(
                    f"Cannot hydrate {cls.__name__}: expected a mapping row, "
                    f"got {type(row).__name__}"
                ),
                stage="hydrate",
                context={"model": cls.__name__},
            )
        values: Dict[str, Any] = {}
        for name, field in cls._orm_fields.items():
            if name in row:
                values[name] = field.coerce(row[name])
        return cls(**values)

    @classmethod
    def create(cls, **values: Any) -> "ORMModel":
        """Insert a new row and return the hydrated instance.

        When the driver exposes the inserted id (``lastrowid``) it is used to
        populate the primary key of the returned instance.
        """
        instance = cls(**values)
        instance._validate_required()
        data = instance._database_values()
        table = cls.table_name()
        result = Query(table, database=cls._require_connection()).insert(data)
        pk = cls.primary_key_name()
        if pk is not None and getattr(instance, pk, None) is None:
            lastrowid = result.get("lastrowid")
            if lastrowid is not None:
                setattr(instance, pk, cls._orm_fields[pk].coerce(lastrowid))
        return instance

    # ── instance behaviour ────────────────────────────────────────────

    def _pk_value(self) -> Any:
        pk = self.primary_key_name()
        if pk is None:
            return None
        return getattr(self, pk, None)

    def _validate_required(self) -> None:
        for name, field in self._orm_fields.items():
            value = getattr(self, name, None)
            if (
                value is None
                and field.required
                and field.default is None
                and not field.nullable
            ):
                raise ModelError(
                    message=f"Field {name!r} is required",
                    stage="validate",
                    context={"model": type(self).__name__, "field": name},
                )

    def _database_values(self) -> Dict[str, Any]:
        """The column -> value mapping for this instance (to bind)."""
        values: Dict[str, Any] = {}
        for name in self._orm_fields:
            values[name] = getattr(self, name, None)
        return values

    def save(self) -> "ORMModel":
        """Persist this instance.

        * primary key ``None``  -> insert (like :meth:`create`);
        * primary key set       -> update the matching row.
        """
        pk = self.primary_key_name()
        if pk is None or self._pk_value() is None:
            return type(self).create(**self.to_dict())
        self._validate_required()
        values = self._database_values()
        values.pop(pk, None)
        table = self.table_name()
        Query(table, database=self._require_connection()).where(pk, self._pk_value()).update(values)
        return self

    def delete(self) -> Dict[str, Any]:
        """Delete the row identified by this instance's primary key."""
        pk = self.primary_key_name()
        if pk is None or self._pk_value() is None:
            raise ModelError(
                message=f"Cannot delete {type(self).__name__}: primary key is not set",
                stage="delete",
                context={"model": type(self).__name__},
            )
        table = self.table_name()
        return (
            Query(table, database=self._require_connection())
            .where(pk, self._pk_value())
            .delete()
        )

    def refresh(self) -> "ORMModel":
        """Reload this instance from the database by primary key.

        Raises ``ModelError`` when the row no longer exists.
        """
        pk = self.primary_key_name()
        if pk is None or self._pk_value() is None:
            raise ModelError(
                message=f"Cannot refresh {type(self).__name__}: primary key is not set",
                stage="refresh",
                context={"model": type(self).__name__},
            )
        table = self.table_name()
        fresh = (
            Query(table, database=self._require_connection(), model=type(self))
            .where(pk, self._pk_value())
            .first()
        )
        if fresh is None:
            raise ModelError(
                message=(
                    f"{type(self).__name__} row with {pk}={self._pk_value()!r} "
                    "no longer exists"
                ),
                stage="refresh",
                context={"model": type(self).__name__, "field": pk},
            )
        for name in self._orm_fields:
            if name != pk and hasattr(fresh, name):
                setattr(self, name, getattr(fresh, name))
        return self

    # ── serialization ─────────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a plain dict (declared fields only)."""
        return {name: getattr(self, name, None) for name in self._orm_fields}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ORMModel":
        """Build an instance from a dict (keys = field names)."""
        return cls(**data)

    def to_jsonable(self) -> Dict[str, Any]:
        """Serialize with datetime/Decimal values made JSON-friendly."""
        result: Dict[str, Any] = {}
        for name, value in self.to_dict().items():
            if hasattr(value, "isoformat"):
                result[name] = value.isoformat()
            else:
                result[name] = value
        return result

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        values = ", ".join(f"{k}={getattr(self, k)!r}" for k in self._orm_fields)
        return f"{type(self).__name__}({values})"