"""SQLite adapter: a concrete :class:`DatabaseEngine` for local dev/testing.

Implements the Stage 09.1 contracts (``DatabaseEngine``, ``Connection``,
``SQLDialect``) on top of the Python standard library ``sqlite3`` module.  It
is deliberately isolated from the core: no ORM, Query Builder or Repository
code knows SQLite exists, and the canonical ``betrayer.data`` API is unchanged.

Registration (extension point)::

    registry.register_engine("sqlite", SQLiteEngine)
    engine = registry.engine("default")       # Config: driver = "sqlite"
    manager = DatabaseManager(engine)
    manager.connect()
    manager.execute('CREATE TABLE "users" ("id" INTEGER PRIMARY KEY)')

Result shape returned by :meth:`SQLiteConnection.execute` is the stable
mapping the Query Builder consumes:

* ``{"rows": [...], "columns": [...]}`` for ``SELECT``;
* ``{"affected": int, "lastrowid": int|None}`` for writes.

Values are **always** bound parameters (``?``); identifiers travel through
:meth:`SQLiteDialect.quote_identifier`.  No value is ever string-interpolated.
"""

from __future__ import annotations

import datetime
import decimal
import sqlite3
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
)
from betrayer.data.transaction import Transaction
from betrayer.data.value import canonical_type

__all__ = ["SQLiteDialect", "SQLiteConnection", "SQLiteEngine"]

#: Driver id this adapter implements (``Config["database.<name>.driver"]``).
DRIVER_NAME = "sqlite"


def operation_of(sql: str) -> str:
    """Return the leading SQL keyword (``"select"``, ``"insert"``, ...)."""
    text = (sql or "").lstrip()
    if not text:
        return ""
    return text.split(None, 1)[0].lower()


def _as_bool(value: Any) -> bool:
    """Coerce a config value (bool or common string) into a boolean."""
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


class SQLiteDialect(SQLDialect):
    """SQLite-specific SQL behaviour (identifier/placeholder/type mapping).

    ``SQLiteDialect`` differs from DuckDB in ``boolean_value`` (SQLite stores
    booleans as integers), ``auto_increment`` (SQLite has an inline
    ``AUTOINCREMENT`` keyword) and ``type_name`` (SQLite uses dynamic typing
    with storage classes).
    """

    name = "sqlite"

    _TYPE_NAMES = {
        int: "INTEGER",
        bool: "INTEGER",
        float: "REAL",
        str: "TEXT",
        bytes: "BLOB",
        bytearray: "BLOB",
    }

    # ── Core SQL behaviour ───────────────────────────────────────────────

    def quote_identifier(self, identifier: str) -> str:
        """Quote an identifier with double quotes (SQL standard)."""
        return escape_identifier(identifier)

    def placeholder(self, position: Optional[int] = None) -> str:
        """SQLite uses positional ``?`` placeholders."""
        return "?"

    def boolean_value(self, value: bool) -> str:
        """SQLite stores booleans as ``0``/``1`` literals."""
        return "1" if value else "0"

    def auto_increment(self) -> str:
        """SQLite's inline auto-increment column declaration."""
        return "INTEGER PRIMARY KEY AUTOINCREMENT"

    def type_name(self, python_type: Any) -> str:
        """Map a Python type to a SQLite storage class name."""
        resolved = canonical_type(python_type)
        if resolved in (datetime.datetime, datetime.date):
            return "TEXT"
        if resolved is decimal.Decimal:
            return "NUMERIC"
        return self._TYPE_NAMES.get(resolved, "TEXT")

    # ── Extension points ─────────────────────────────────────────────────

    def features(self) -> Dict[str, Any]:
        return {
            "supports_auto_increment": True,
            "supports_boolean": True,
            "supports_transactions": True,
            "supports_returning": True,
            "driver": DRIVER_NAME,
        }

    def introspect(self) -> Dict[str, Any]:
        info = super().introspect()
        info["driver"] = DRIVER_NAME
        return info


class SQLiteConnection(Connection):
    """A :class:`Connection` backed by a single ``sqlite3`` connection.

    The connection is opened lazily by :meth:`connect` and reused, so an
    in-memory database (``":memory:"``) keeps its data for the connection's
    lifetime.  ``commit``/``rollback`` follow the ``sqlite3`` module's implicit
    transaction behaviour.
    """

    driver_name = DRIVER_NAME

    def __init__(
        self,
        database: str = ":memory:",
        *,
        timeout: float = 5.0,
        uri: bool = False,
        check_same_thread: bool = False,
        **options: Any,
    ) -> None:
        self._database = database or ":memory:"
        self._timeout = timeout
        self._uri = uri
        # Default False: a single Betrayer connection may be used from more than
        # one thread (e.g. the Flask async-view worker thread), which SQLite's
        # strict per-thread check would otherwise reject.
        self._check_same_thread = bool(check_same_thread)
        self._options = dict(options)
        self._connection: Optional[sqlite3.Connection] = None

    # ── Properties ───────────────────────────────────────────────────────

    @property
    def database(self) -> str:
        """Path/``":memory:"`` of the underlying SQLite database."""
        return self._database

    @property
    def raw(self) -> Optional[sqlite3.Connection]:
        """The underlying ``sqlite3`` connection (or ``None``)."""
        return self._connection

    # ── Connection contract ──────────────────────────────────────────────

    def connect(self) -> None:
        if self._connection is not None:
            return
        try:
            self._connection = sqlite3.connect(
                self._database,
                timeout=self._timeout,
                uri=self._uri,
                check_same_thread=self._check_same_thread,
            )
        except sqlite3.Error as exc:
            raise ConnectionError(
                message="Failed to open SQLite database",
                stage="connect",
                cause=exc,
                driver=DRIVER_NAME,
                database=self._database,
            ) from exc

    def close(self) -> None:
        connection = self._connection
        self._connection = None
        if connection is None:
            return
        try:
            connection.close()
        except sqlite3.Error as exc:
            raise ConnectionError(
                message="Failed to close SQLite database",
                stage="close",
                cause=exc,
                driver=DRIVER_NAME,
                database=self._database,
            ) from exc

    def execute(self, query: str, parameters: Any = None) -> Any:
        cursor = self._raw().cursor()
        try:
            cursor.execute(query, self._bind(parameters))
        except sqlite3.Error as exc:
            raise self._error(query, exc) from exc
        return self._shape(cursor)

    def executemany(self, query: str, parameters: Iterable[Any]) -> Any:
        cursor = self._raw().cursor()
        try:
            cursor.executemany(query, [self._bind(p) for p in parameters])
        except sqlite3.Error as exc:
            raise self._error(query, exc) from exc
        return self._shape(cursor)

    def commit(self) -> None:
        try:
            self._raw().commit()
        except sqlite3.Error as exc:
            raise TransactionError(
                message="SQLite commit failed",
                stage="commit",
                cause=exc,
                driver=DRIVER_NAME,
                database=self._database,
            ) from exc

    def rollback(self) -> None:
        try:
            self._raw().rollback()
        except sqlite3.Error as exc:
            raise TransactionError(
                message="SQLite rollback failed",
                stage="rollback",
                cause=exc,
                driver=DRIVER_NAME,
                database=self._database,
            ) from exc

    def cursor(self) -> Any:
        return self._raw().cursor()

    # ── Introspection ────────────────────────────────────────────────────

    def introspect(self) -> Dict[str, Any]:
        return {
            "type": "connection",
            "driver": DRIVER_NAME,
            "database": self._database,
            "connected": self._connection is not None,
        }

    # ── Internals ────────────────────────────────────────────────────────

    def _raw(self) -> sqlite3.Connection:
        if self._connection is None:
            self.connect()
        assert self._connection is not None  # noqa: S101 - connect guarantees it
        return self._connection

    @staticmethod
    def _bind(parameters: Any) -> Any:
        if parameters is None:
            return ()
        if isinstance(parameters, dict):
            return parameters
        return tuple(parameters)

    def _shape(self, cursor: sqlite3.Cursor) -> Dict[str, Any]:
        """Normalize a ``sqlite3`` cursor into the stable result mapping."""
        affected = cursor.rowcount if cursor.rowcount is not None else 0
        result: Dict[str, Any] = {
            "affected": affected,
            "lastrowid": cursor.lastrowid,
        }
        description = cursor.description
        if description:
            columns = [column[0] for column in description]
            rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
            result["rows"] = rows
            result["columns"] = columns
            result["affected"] = len(rows)
        return result

    def _error(self, query: str, exc: Exception) -> DatabaseError:
        operation = operation_of(query)
        return DatabaseError(
            message=f"SQLite query failed during {operation or 'execute'}",
            stage="execute",
            cause=exc,
            driver=DRIVER_NAME,
            database=self._database,
            operation=operation,
            context={"query": query[:120]},
        )


class SQLiteEngine(DatabaseEngine):
    """Concrete engine speaking SQLite through :class:`SQLiteConnection`."""

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
        self._dialect = SQLiteDialect()
        self._connection: Optional[SQLiteConnection] = None
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
        """Resolved SQLite database path (``":memory:"`` by default)."""
        value = self._config.get("database") or self._config.get("path")
        if value in (None, ""):
            value = self._options.get("database") or ":memory:"
        return str(value)

    # ── Engine contract ──────────────────────────────────────────────────

    def connect(self, name: Optional[str] = None, **options: Any) -> Connection:
        if self._closed:
            raise ConnectionError(
                message="SQLite engine is closed",
                stage="connect",
                driver=DRIVER_NAME,
                database=self._name,
            )
        if self._connection is None:
            self._connection = SQLiteConnection(
                database=self.database_path(),
                timeout=float(self._config.get("timeout", 5.0)),
                check_same_thread=_as_bool(self._config.get("check_same_thread", False)),
            )
            # Open eagerly so a bad path fails at connect time (fail fast),
            # not on the first query.
            self._connection.connect()
        return self._connection

    def transaction(self, connection: Optional[Connection] = None, **options: Any):
        if connection is None:
            connection = self.connect()
        return Transaction(self, connection=connection)

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
