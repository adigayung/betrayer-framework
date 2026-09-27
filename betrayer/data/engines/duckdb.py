"""DuckDB adapter: a second concrete :class:`DatabaseEngine` (optional dep).

DuckDB is an in-process analytical database used here to prove that the
Stage 09.1/09.2/09.3 contracts (engine, connection, dialect, Query Builder,
ORM, Repository) are genuinely engine-agnostic: the *same* ORM and Repository
code runs against SQLite and DuckDB without a single ``if database == ...``.

The ``duckdb`` package is an **optional** dependency and is imported lazily
inside :meth:`DuckDBConnection.connect`, so this module (and the framework)
import cleanly when the driver is absent; connecting then raises a structured
``UnsupportedDatabaseError``.  This keeps driver dependencies isolated to the
adapter, exactly like the core contract requires.

DuckDB differences handled by :class:`DuckDBDialect`:

* booleans are native (``TRUE``/``FALSE``), not integers;
* there is **no** inline ``AUTOINCREMENT`` keyword and identity columns are
  not implemented, so auto increment is a sequence-backed ``DEFAULT``
  (``compile_fragment("auto_increment", table=..., column=...)``);
* string/float types are ``VARCHAR``/``DOUBLE`` rather than ``TEXT``/``REAL``.

The ``execute`` result mapping matches
:class:`~betrayer.data.engines.sqlite.SQLiteConnection`: ``{"rows", ...}`` for
``SELECT`` and ``{"affected", ...}`` for writes (DuckDB reports the affected
count through a ``Count`` result column).
"""

from __future__ import annotations

import datetime
import decimal
from typing import Any, Dict, Iterable, Optional

from betrayer.data.database import (
    Connection,
    DatabaseEngine,
    SQLDialect,
    escape_identifier,
)
from betrayer.data.exceptions import (
    ConnectionError,
    DatabaseError,
    TransactionError,
    UnsupportedDatabaseError,
)
from betrayer.data.transaction import Transaction
from betrayer.data.value import canonical_type

__all__ = [
    "DuckDBDialect",
    "DuckDBConnection",
    "DuckDBEngine",
    "DuckDBTransaction",
    "duckdb_available",
]

#: Driver id this adapter implements (``Config["database.<name>.driver"]``).
DRIVER_NAME = "duckdb"

_WRITE_OPERATIONS = {
    "insert",
    "update",
    "delete",
    "replace",
    "create",
    "drop",
    "alter",
    "truncate",
}


def operation_of(sql: str) -> str:
    """Return the leading SQL keyword (``"select"``, ``"insert"``, ...)."""
    text = (sql or "").lstrip()
    if not text:
        return ""
    return text.split(None, 1)[0].lower()


def duckdb_available() -> bool:
    """Whether the optional ``duckdb`` driver can be imported."""
    try:
        import duckdb  # noqa: F401 - availability probe
    except Exception:
        return False
    return True


def _require_duckdb() -> Any:
    """Import and return the ``duckdb`` module, or raise a clear error."""
    try:
        import duckdb  # noqa: WPS433 - intentional lazy optional import
    except Exception as exc:  # pragma: no cover - depends on environment
        raise UnsupportedDatabaseError(
            message="The 'duckdb' driver is not installed (pip install duckdb)",
            stage="connect",
            cause=exc,
            driver=DRIVER_NAME,
        ) from exc
    return duckdb


class DuckDBDialect(SQLDialect):
    """DuckDB-specific SQL behaviour (identifier/placeholder/type/auto-inc)."""

    name = "duckdb"

    _TYPE_NAMES = {
        int: "INTEGER",
        bool: "BOOLEAN",
        float: "DOUBLE",
        str: "VARCHAR",
        bytes: "BLOB",
        bytearray: "BLOB",
    }

    # ── Core SQL behaviour ───────────────────────────────────────────────

    def quote_identifier(self, identifier: str) -> str:
        """Quote an identifier with double quotes (PostgreSQL-compatible)."""
        return escape_identifier(identifier)

    def placeholder(self, position: Optional[int] = None) -> str:
        """DuckDB uses positional ``?`` placeholders."""
        return "?"

    def boolean_value(self, value: bool) -> str:
        """DuckDB has native booleans."""
        return "TRUE" if value else "FALSE"

    def auto_increment(self) -> str:
        """DuckDB auto-increment template (sequence-backed ``DEFAULT``).

        DuckDB has no inline ``AUTOINCREMENT`` keyword and identity columns are
        not implemented, so auto increment is expressed as a sequence-backed
        ``DEFAULT`` following the ``<table>_<column>_seq`` convention.  Use
        :meth:`compile_fragment` for a concrete fragment, or
        :meth:`sequence_name` for the sequence identifier.
        """
        return "INTEGER PRIMARY KEY DEFAULT nextval('<table>_<column>_seq')"

    def type_name(self, python_type: Any) -> str:
        """Map a Python type to a DuckDB column type name."""
        resolved = canonical_type(python_type)
        if resolved is datetime.datetime:
            return "TIMESTAMP"
        if resolved is datetime.date:
            return "DATE"
        if resolved is decimal.Decimal:
            return "DECIMAL"
        return self._TYPE_NAMES.get(resolved, "VARCHAR")

    # ── Extension points ─────────────────────────────────────────────────

    def sequence_name(self, table: str, column: str = "id") -> str:
        """Conventional auto-increment sequence identifier for a table."""
        return f"{table}_{column}_seq"

    def features(self) -> Dict[str, Any]:
        return {
            "supports_auto_increment": True,
            "auto_increment": "sequence",  # via nextval(...) DEFAULT
            "supports_boolean": True,
            "supports_transactions": True,
            "supports_returning": True,
            "driver": DRIVER_NAME,
        }

    def compile_fragment(self, feature: str, **kwargs: Any) -> str:
        if feature == "auto_increment":
            table = kwargs.get("table") or "table"
            column = kwargs.get("column") or "id"
            return (
                "INTEGER PRIMARY KEY DEFAULT "
                f"nextval('{self.sequence_name(table, column)}')"
            )
        if feature == "create_sequence":
            table = kwargs.get("table") or "table"
            column = kwargs.get("column") or "id"
            name = self.sequence_name(table, column)
            return f'CREATE SEQUENCE "{name}"'
        return super().compile_fragment(feature, **kwargs)

    def introspect(self) -> Dict[str, Any]:
        info = super().introspect()
        info["driver"] = DRIVER_NAME
        return info


class DuckDBTransaction(Transaction):
    """A transaction that opens DuckDB's explicit transaction on ``enter``.

    DuckDB does not use implicit transactions like ``sqlite3``: without an
    explicit ``BEGIN`` each statement autocommits and a later ``ROLLBACK`` is a
    no-op.  This subclass drives ``connection.begin()`` on enter; commit and
    rollback (and re-raising the original exception) are inherited unchanged.
    """

    def _begin(self) -> None:
        connection = self._connection
        if connection is not None and hasattr(connection, "begin"):
            connection.begin()
        super()._begin()


class DuckDBConnection(Connection):
    """A :class:`Connection` backed by an in-process ``duckdb`` connection."""

    driver_name = DRIVER_NAME

    def __init__(self, database: str = ":memory:", **options: Any) -> None:
        self._database = database or ":memory:"
        self._options = dict(options)
        self._connection: Any = None
        self._in_transaction = False

    # ── Properties ───────────────────────────────────────────────────────

    @property
    def database(self) -> str:
        """Path/``":memory:"`` of the underlying DuckDB database."""
        return self._database

    @property
    def raw(self) -> Any:
        """The underlying ``duckdb`` connection (or ``None``)."""
        return self._connection

    # ── Connection contract ──────────────────────────────────────────────

    def connect(self) -> None:
        if self._connection is not None:
            return
        duckdb = _require_duckdb()
        try:
            self._connection = duckdb.connect(database=self._database)
        except Exception as exc:  # duckdb raises its own Error hierarchy
            raise ConnectionError(
                message="Failed to open DuckDB database",
                stage="connect",
                cause=exc,
                driver=DRIVER_NAME,
                database=self._database,
            ) from exc

    def close(self) -> None:
        connection = self._connection
        self._connection = None
        self._in_transaction = False
        if connection is None:
            return
        try:
            connection.close()
        except Exception as exc:
            raise ConnectionError(
                message="Failed to close DuckDB database",
                stage="close",
                cause=exc,
                driver=DRIVER_NAME,
                database=self._database,
            ) from exc

    def execute(self, query: str, parameters: Any = None) -> Any:
        raw = self._raw()
        params = self._bind(parameters)
        try:
            if params:
                raw.execute(query, params)
            else:
                raw.execute(query)
        except Exception as exc:
            raise self._error(query, exc) from exc
        return self._shape(query)

    def executemany(self, query: str, parameters: Iterable[Any]) -> Any:
        raw = self._raw()
        batches = [self._bind(p) for p in parameters]
        try:
            raw.executemany(query, batches)
        except Exception as exc:
            raise self._error(query, exc) from exc
        return {"affected": len(batches), "lastrowid": None}

    def commit(self) -> None:
        raw = self._raw()
        try:
            raw.commit()
        except Exception as exc:
            raise TransactionError(
                message="DuckDB commit failed",
                stage="commit",
                cause=exc,
                driver=DRIVER_NAME,
                database=self._database,
            ) from exc
        finally:
            self._in_transaction = False

    def rollback(self) -> None:
        raw = self._raw()
        try:
            raw.rollback()
        except Exception as exc:
            raise TransactionError(
                message="DuckDB rollback failed",
                stage="rollback",
                cause=exc,
                driver=DRIVER_NAME,
                database=self._database,
            ) from exc
        finally:
            self._in_transaction = False

    def begin(self) -> None:
        """Open DuckDB's explicit transaction (idempotent per connection)."""
        raw = self._raw()
        if self._in_transaction:
            return
        try:
            raw.begin()
        except Exception as exc:
            raise TransactionError(
                message="DuckDB begin failed",
                stage="begin",
                cause=exc,
                driver=DRIVER_NAME,
                database=self._database,
            ) from exc
        self._in_transaction = True

    def cursor(self) -> Any:
        return self._raw().cursor()

    # ── Introspection ────────────────────────────────────────────────────

    def introspect(self) -> Dict[str, Any]:
        return {
            "type": "connection",
            "driver": DRIVER_NAME,
            "database": self._database,
            "connected": self._connection is not None,
            "in_transaction": self._in_transaction,
        }

    # ── Internals ────────────────────────────────────────────────────────

    def _raw(self) -> Any:
        if self._connection is None:
            self.connect()
        return self._connection

    @staticmethod
    def _bind(parameters: Any) -> list:
        if parameters is None:
            return []
        if isinstance(parameters, dict):
            return list(parameters.values())
        return list(parameters)

    def _shape(self, query: str) -> Dict[str, Any]:
        """Normalize a DuckDB result into the stable result mapping."""
        raw = self._raw()
        description = getattr(raw, "description", None)
        if not description:
            return {"affected": 0, "lastrowid": None}
        columns = [column[0] for column in description]
        rows = raw.fetchall()
        if operation_of(query) in _WRITE_OPERATIONS:
            affected = int(rows[0][0]) if rows else 0
            return {"affected": affected, "lastrowid": None}
        mapped = [dict(zip(columns, row)) for row in rows]
        return {
            "rows": mapped,
            "columns": columns,
            "affected": len(mapped),
            "lastrowid": None,
        }

    def _error(self, query: str, exc: Exception) -> DatabaseError:
        operation = operation_of(query)
        return DatabaseError(
            message=f"DuckDB query failed during {operation or 'execute'}",
            stage="execute",
            cause=exc,
            driver=DRIVER_NAME,
            database=self._database,
            operation=operation,
            context={"query": query[:120]},
        )


class DuckDBEngine(DatabaseEngine):
    """Concrete engine speaking DuckDB through :class:`DuckDBConnection`."""

    driver_name = DRIVER_NAME

    def __init__(
        self,
        name: str = "default",
        config: Optional[Dict[str, Any]] = None,
        **options: Any,
    ) -> None:
        self._name = name
        self._config = dict(config or {})
        self._options = dict(options)
        self._dialect = DuckDBDialect()
        self._connection: Optional[DuckDBConnection] = None
        self._closed = False

    # ── Properties ───────────────────────────────────────────────────────

    @property
    def name(self) -> str:
        """Connection name this engine was resolved for."""
        return self._name

    @property
    def config(self) -> Dict[str, Any]:
        """Configuration block this engine was built from (no secrets used)."""
        return dict(self._config)

    def database_path(self) -> str:
        """Resolved DuckDB database path (``":memory:"`` by default)."""
        value = self._config.get("database") or self._config.get("path")
        if value in (None, ""):
            value = self._options.get("database") or ":memory:"
        return str(value)

    # ── Engine contract ──────────────────────────────────────────────────

    def connect(self, name: Optional[str] = None, **options: Any) -> Connection:
        if self._closed:
            raise ConnectionError(
                message="DuckDB engine is closed",
                stage="connect",
                driver=DRIVER_NAME,
                database=self._name,
            )
        if self._connection is None:
            self._connection = DuckDBConnection(database=self.database_path())
            # Open eagerly so a missing driver/bad path fails at connect time.
            self._connection.connect()
        return self._connection

    def transaction(self, connection: Optional[Connection] = None, **options: Any):
        if connection is None:
            connection = self.connect()
        return DuckDBTransaction(self, connection=connection)

    def dialect(self) -> SQLDialect:
        return self._dialect

    def close(self) -> None:
        connection = self._connection
        self._connection = None
        self._closed = True
        if connection is not None:
            connection.close()

    def metadata(self) -> Dict[str, Any]:
        return {
            "type": "engine",
            "driver": DRIVER_NAME,
            "database": self._name,
            "database_path": self.database_path(),
            "capabilities": ["connect", "transaction", "dialect"],
        }
