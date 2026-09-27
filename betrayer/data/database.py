"""Database abstraction: engine/connection/dialect contracts and lifecycle.

Betrayer is database-agnostic.  This module defines the *contracts* an
implementation must satisfy; it never picks, locks or depends on a concrete
database engine.  Concrete engines (SQLite, PostgreSQL, DuckDB, ...) live
outside this module and are wired in through the database registry and the
engine extension point.

Contract surface (importable from ``betrayer.data``)::

    DatabaseEngine   - capability level contract (connect, transaction, dialect)
    Connection       - per-connection contract (execute, executemany, ...)
    DatabaseManager  - lifecycle-aware wrapper around an engine (backward compat)
    SQLDialect       - database-specific SQL behaviour (identifier/placeholder/...)

Pipeline because of this design:

    Application -> Database Registry -> DatabaseEngine -> Connection -> Implementation
                                             \\-> SQLDialect -> database-specific SQL

Betrayer Core knows only the contracts above.  Concrete implementations are
provided separately (Task 09.4 integration / extension point).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Iterable, Optional, Sequence, Tuple

from betrayer.data.exceptions import (
    ConnectionError,
    DatabaseError,
)

#: Sentinel so ``None`` remains a valid parameter value.
_UNSET = object()

__all__ = [
    # contracts
    "DatabaseEngine",
    "Connection",
    "SQLDialect",
    # manager (backward compatible single-engine wrapper)
    "DatabaseManager",
    # helpers
    "escape_identifier",
    "placeholder",
]


def escape_identifier(identifier: str) -> str:
    """Escape a single SQL identifier with double quotes.

    Used when a query must include a dynamic identifier (table/column name).
    Values must never be interpolated this way - use ``Connection.execute``
    parameters for values.
    """
    if not isinstance(identifier, str) or not identifier:
        raise DatabaseError(
            message="Identifier must be a non-empty string",
            code="DATABASE_IDENTIFIER_INVALID",
            context={"identifier": identifier},
        )
    return '"' + identifier.replace('"', '""') + '"'


def placeholder(position: int) -> str:
    """Return the ``?`` placeholder for a positional parameter."""
    return "?"


class Connection(ABC):
    """Per-connection contract between Betrayer and a concrete driver.

    ``Connection`` is the boundary: Betrayer never talks to a driver/engine
    directly, every data access goes through this contract.  Parameters are
    always passed as a separate sequence/mapping (never interpolated into
    SQL).

    Concrete engines implement this interface (or wrap their driver's
    connection with it).

    Lifecycle::

        connect -> execute/executemany/commit/rollback -> close

    ``commit``/``rollback`` are only meaningful inside an active transaction.
    """

    @abstractmethod
    def connect(self) -> None:
        """Open the underlying driver connection.

        Idempotent: calling on an already-open connection is a no-op.
        Raises ``ConnectionError`` on failure.
        """

    @abstractmethod
    def close(self) -> None:
        """Close the underlying driver connection.

        Safe to call multiple times.  Raises ``ConnectionError`` on failure.
        """

    @abstractmethod
    def execute(self, query: str, parameters: Any = None) -> Any:
        """Execute a single parameterized statement and return its result.

        Parameters may be a sequence (positional ``?``) or a mapping; the
        concrete dialect/spec decides with one are supported.
        """

    @abstractmethod
    def executemany(self, query: str, parameters: Iterable[Any]) -> Any:
        """Execute the same parameterized statement for every parameter set."""

    @abstractmethod
    def commit(self) -> None:
        """Commit the current transaction."""

    @abstractmethod
    def rollback(self) -> None:
        """Roll back the current transaction."""

    @abstractmethod
    def cursor(self) -> Any:
        """Return a driver cursor/result handle for advanced usage."""

    # ── optional introspection (subclasses may override) ────────────────

    def introspect(self) -> Dict[str, Any]:
        """Machine readable metadata: type of this connection."""
        return {"type": "connection", "class": type(self).__name__}

    def __repr__(self) -> str:  # pragma: no cover
        return f"{type(self).__name__}()"


class SQLDialect(ABC):
    """Database-specific SQL behaviour, as an extension point.

    This is a *contract*, not a concrete dialect.  Dialects are resolved by
    engine implementations so that a Query Builder (09.2) can emit SQL
    without ever knowing which database is behind the engine.

    The minimum surface covers the behaviour a Query Builder needs:

    * identifier quoting
    * parameter placeholder
    * boolean representation
    * auto-increment/primary key representation
    * type mapping
    * free-form SQL fragments/features
    """

    # ── Identity ─────────────────────────────────────────────────────────

    @property
    def name(self) -> str:
        """Display name of the dialect (e.g. ``"generic"``)."""
        return type(self).__name__

    # ── Core SQL behaviour ───────────────────────────────────────────────

    @abstractmethod
    def quote_identifier(self, identifier: str) -> str:
        """Quote a single identifier according to this dialect."""

    @abstractmethod
    def placeholder(self, position: Optional[int] = None) -> str:
        """Return the parameter placeholder (``?``, ``%s``, ``:name``, ...)."""

    @abstractmethod
    def boolean_value(self, value: bool) -> str:
        """Return the literal representation of a boolean."""

    @abstractmethod
    def auto_increment(self) -> str:
        """Return the SQL fragment declaring an auto-increment column/type."""

    @abstractmethod
    def type_name(self, python_type: Any) -> str:
        """Map a Python type to the dialect's column type name."""

    # ── Extension points ─────────────────────────────────────────────────

    def features(self) -> Dict[str, Any]:
        """Capability flags of this dialect (overridable)."""
        return {
            "supports_auto_increment": True,
            "supports_boolean": True,
            "supports_transactions": True,
        }

    def compile_fragment(self, feature: str, **kwargs: Any) -> str:
        """Return a database-specific SQL fragment for ``feature``.

        Concrete dialects override this for behaviour that does not fit the
        minimal surface (e.g. ``LIMIT`` syntax, ``RETURNING`` support).
        """
        raise NotImplementedError(
            f"Dialect {self.name!r} does not support fragment {feature!r}"
        )

    def introspect(self) -> Dict[str, Any]:
        """Machine readable metadata for LLM inspection."""
        return {
            "type": "dialect",
            "name": self.name,
            "features": self.features(),
        }


class DatabaseEngine(ABC):
    """Capability-level database engine contract.

    An engine is responsible for database-*level* capabilities:

    * open/acquire a :class:`Connection`
    * transaction scoping
    * the :class:`SQLDialect` it speaks
    * engine metadata and lifecycle

    It is **not** responsible for Model/ORM/Query Builder/Repository/CRUD.

    Concrete engines subclass this contract, so ``db.connect()`` and
    ``with db.transaction():`` behave identically across databases.
    """

    # ── Connections ──────────────────────────────────────────────────────

    @abstractmethod
    def connect(self, name: Optional[str] = None, **options: Any) -> Connection:
        """Open/acquire a connection and return the :class:`Connection`.

        Raises ``ConnectionError`` on failure.  ``options`` may override
        engine defaults for this acquisition.
        """

    # ── Transactions ─────────────────────────────────────────────────────

    @abstractmethod
    def transaction(self, connection: Optional[Connection] = None, **options: Any):
        """Return a transaction context manager for :class:`~.Transaction`.

        Contract: on success the underlying connection is committed; on
        exception it is rolled back and the original exception is re-raised.
        """

    # ── Dialect ──────────────────────────────────────────────────────────

    @abstractmethod
    def dialect(self) -> SQLDialect:
        """Return the :class:`SQLDialect` this engine speaks."""

    # ── Lifecycle ────────────────────────────────────────────────────────

    @abstractmethod
    def close(self) -> None:
        """Close the engine and release any pooled/held resources."""

    # ── Metadata ─────────────────────────────────────────────────────────

    @abstractmethod
    def metadata(self) -> Dict[str, Any]:
        """Engine metadata: driver id, display name, capabilities."""

    def introspect(self) -> Dict[str, Any]:
        """Machine readable metadata for LLM inspection."""
        info = dict(self.metadata())
        info.setdefault("type", "engine")
        info.setdefault("class", type(self).__name__)
        dialect = self.dialect()
        info["dialect"] = dialect.introspect()
        return info


class DatabaseManager:
    """Lifecycle-aware wrapper around a single :class:`DatabaseEngine`.

    ``DatabaseManager`` is the existing single-engine manager kept for
    backward compatibility: repositories, migrations, transactions and the
    Data inspector already consume it.  New code should prefer the registry
    (:class:`~betrayer.data.registry.DatabaseRegistry`) for multi-connection
    setups, but a manager can always target a registered connection by name.

    Usage::

        manager = DatabaseManager(engine)
        manager.connect()                       # wraps engine.connect()
        manager.execute("SELECT ?", [1])        # via the connection
        with manager.transaction():             # via the engine contract
            ...
        manager.disconnect()
    """

    def __init__(self, engine: DatabaseEngine) -> None:
        self._engine = engine
        self._connected = False
        self._connection: Optional[Connection] = None
        self._metadata: Dict[str, Any] = {}

    # ── Properties ───────────────────────────────────────────────────────

    @property
    def engine(self) -> DatabaseEngine:
        """The wrapped engine contract."""
        return self._engine

    @property
    def is_connected(self) -> bool:
        """True when a connection is currently open."""
        return self._connected

    # Backward compatible alias.
    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def connection(self) -> Optional[Connection]:
        """The active :class:`Connection`, or ``None`` when disconnected."""
        return self._connection

    @property
    def dialect(self) -> SQLDialect:
        """The engine's SQL dialect."""
        return self._engine.dialect()

    @property
    def metadata(self) -> Dict[str, Any]:
        return dict(self._metadata)

    # ── Lifecycle ────────────────────────────────────────────────────────

    def connect(self, **options: Any) -> None:
        """Open the engine connection; raises ``ConnectionError`` on failure."""
        if self._connected:
            return
        try:
            self._connection = self._engine.connect(**options)
            self._connected = True
        except ConnectionError:
            raise
        except Exception as exc:
            raise ConnectionError(
                message="Failed to connect to database",
                stage="connect",
                cause=exc,
                driver=getattr(self._engine, "driver_name", None)
                or type(self._engine).__name__,
            ) from exc

    def disconnect(self) -> None:
        """Close the connection; safe to call multiple times."""
        connection = self._connection
        self._connected = False
        self._connection = None
        if connection is None:
            return
        try:
            connection.close()
        except Exception as exc:
            raise ConnectionError(
                message="Error while disconnecting from database",
                stage="disconnect",
                cause=exc,
                driver=getattr(self._engine, "driver_name", None)
                or type(self._engine).__name__,
            ) from exc

    # Backward compatible alias.
    close = disconnect

    # ── Execution ────────────────────────────────────────────────────────

    def execute(self, query: str, parameters: Any = None) -> Any:
        """Execute a parameterized query through the current connection."""
        connection = self._connection
        if connection is None or not self._connected:
            raise ConnectionError(
                message="Database is not connected",
                stage="execute",
                driver=getattr(self._engine, "driver_name", None)
                or type(self._engine).__name__,
            )
        try:
            return connection.execute(query, parameters)
        except DatabaseError:
            # Already a structured Data Layer error (e.g. a concrete adapter
            # wrapped its driver failure): never wrap it a second time.
            raise
        except Exception as exc:
            raise DatabaseError(
                message=f"Query execution failed: {query[:80]}",
                stage="execute",
                cause=exc,
                driver=getattr(self._engine, "driver_name", None)
                or type(self._engine).__name__,
            ) from exc

    def executemany(self, query: str, parameters: Iterable[Any]) -> Any:
        """Execute the same parameterized statement for many parameter sets."""
        connection = self._connection
        if connection is None or not self._connected:
            raise ConnectionError(
                message="Database is not connected",
                stage="executemany",
                driver=getattr(self._engine, "driver_name", None)
                or type(self._engine).__name__,
            )
        try:
            return connection.executemany(query, parameters)
        except DatabaseError:
            # Keep the concrete adapter's structured error (no double wrap).
            raise
        except Exception as exc:
            raise DatabaseError(
                message=f"Bulk query execution failed: {query[:80]}",
                stage="executemany",
                cause=exc,
                driver=getattr(self._engine, "driver_name", None)
                or type(self._engine).__name__,
            ) from exc

    # ── Transactions ─────────────────────────────────────────────────────

    def transaction(self, **options: Any):
        """Return a transaction context manager bound to this manager.

        Backward compatible helper: delegates to the engine's transaction
        contract using the manager's active connection.
        """
        from betrayer.data.transaction import Transaction  # local import

        return Transaction(self, **options)

    # ── Introspection ────────────────────────────────────────────────────

    def introspect(self) -> Dict[str, Any]:
        """Return deterministic metadata for LLM inspection."""
        return {
            "type": "database_manager",
            "engine": type(self._engine).__name__,
            "connected": self._connected,
            "dialect": self.dialect.introspect(),
            "metadata": self._metadata,
        }

    # Backward compatible alias used by the Data inspector.
    def to_dict(self) -> Dict[str, Any]:
        return self.introspect()

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"DatabaseManager(engine={type(self._engine).__name__}, "
            f"connected={self._connected})"
        )