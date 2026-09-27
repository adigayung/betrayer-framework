"""Immutable, composable Query Builder over the 09.1 connection contract.

Task 09.2.  ``Query`` is the single canonical way to build and run SQL
statements without writing SQL:

* **immutable** — every modifier (``where``, ``order_by``, ``limit``, ...)
  returns a *new* ``Query`` sharing the same database/dialect;
* **parameterized** — user values are always bound parameters, never string
  interpolated;
* **dialect-delegated** — identifiers and placeholders travel through
  :class:`~betrayer.data.database.SQLDialect`; the Query Builder contains no
  ``if database == "sqlite"/"postgres"/...`` branching;
* **single canonical API** — ``Model.query()`` returns a model-aware
  ``Query`` (``get``/``first`` hydrate model instances), while a standalone
  ``Query(table, database=...)`` returns plain row dicts.

Pipeline::

    Query -> QueryCompiler -> SQLDialect -> compiled (sql, parameters)
        -> DatabaseEngine / Connection -> rows / affected
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple, Union

from betrayer.data.compiler import CompiledQuery, QueryCompiler
from betrayer.data.database import DatabaseEngine, DatabaseManager
from betrayer.data.exceptions import ConnectionError, DatabaseError, QueryError

__all__ = ["Query", "execute_compiled"]

#: Anything the Query accepts as a database source.
DatabaseLike = Union[DatabaseEngine, DatabaseManager, Callable[[], Any]]

_MISSING = object()


def _driver_name(database: Any) -> str:
    if isinstance(database, DatabaseEngine):
        return getattr(database, "driver_name", None) or type(database).__name__
    if isinstance(database, DatabaseManager):
        return type(database.engine).__name__
    return type(database).__name__


def execute_compiled(database: DatabaseLike, compiled: CompiledQuery) -> Any:
    """Execute a :class:`CompiledQuery` through *database*.

    Supported sources:

    * :class:`~betrayer.data.database.DatabaseManager` — uses its active
      connection (manager keeps ownership).
    * :class:`~betrayer.data.database.DatabaseEngine` — acquires a fresh
      connection and closes it afterwards.
    * a zero-argument callable returning a :class:`~betrayer.data.database.Connection`
      (test-friendly provider).

    Driver errors are wrapped into ``DatabaseError`` (stage ``execute``) with
    the driver id and the SQL operation; connection-less managers raise
    ``ConnectionError``.
    """
    if isinstance(database, DatabaseManager):
        if not database.connected or database.connection is None:
            raise ConnectionError(
                message="Database is not connected",
                stage="execute",
                driver=_driver_name(database),
                operation=compiled.operation,
            )
        try:
            return database.execute(compiled.sql, compiled.parameters)
        except (ConnectionError, DatabaseError):
            raise
        except Exception as exc:
            raise DatabaseError(
                message=f"Query execution failed: {compiled.sql[:80]}",
                stage="execute",
                cause=exc,
                driver=_driver_name(database),
                operation=compiled.operation,
                context={"table": compiled.table},
            ) from exc

    connection: Any = None
    try:
        if isinstance(database, DatabaseEngine):
            connection = database.connect()
        elif callable(database):
            connection = database()
        else:
            raise QueryError(
                message=(
                    "Query requires a DatabaseManager, DatabaseEngine, "
                    "or a callable returning a Connection"
                ),
                stage="execute",
            )
        return connection.execute(compiled.sql, compiled.parameters)
    except (ConnectionError, DatabaseError, QueryError):
        raise
    except Exception as exc:
        raise DatabaseError(
            message=f"Query execution failed: {compiled.sql[:80]}",
            stage="execute",
            cause=exc,
            driver=_driver_name(database),
            operation=compiled.operation,
            context={"table": compiled.table},
        ) from exc
    finally:
        if (
            connection is not None
            and not isinstance(database, DatabaseManager)
            and hasattr(connection, "close")
        ):
            try:
                connection.close()
            except Exception:  # pragma: no cover - best effort close
                pass


def _row_to_mapping(row: Any, columns: Optional[Sequence[str]]) -> Any:
    """Normalize a driver row into a mapping when possible."""
    if isinstance(row, dict):
        return dict(row)
    if columns is not None and isinstance(row, (tuple, list)):
        return dict(zip(columns, row))
    return row


class Query:
    """Immutable query builder bound to a database source.

    Usage (standalone, returns row dicts)::

        q = Query("users", database=manager)
        rows = q.where("active", True).order_by("created_at", "desc").limit(10).get()
        count = q.where("active", True).count()
        exists = q.where("email", email).exists()
        first = q.where("id", user_id).first()
        q.where("id", user_id).delete()
        q.where("id", user_id).update({"name": "Jane"})
        Query("users", database=manager).insert({"name": "John"})

    Usage (model-aware, ``Model.query()``) hydrates rows into model instances.
    """

    def __init__(
        self,
        table: str,
        database: Optional[DatabaseLike] = None,
        *,
        dialect: Any = None,
        model: Optional[type] = None,
        columns: Optional[Sequence[str]] = None,
        wheres: Optional[Sequence[Dict[str, Any]]] = None,
        order_by: Optional[Sequence[Tuple[str, str]]] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> None:
        if not isinstance(table, str) or not table.strip():
            raise QueryError(
                message="Query requires a non-empty table name",
                stage="init",
            )
        if database is None:
            raise QueryError(
                message="Query requires a database (DatabaseManager, "
                        "DatabaseEngine, or callable provider)",
                stage="init",
            )
        if dialect is None:
            if isinstance(database, DatabaseManager):
                dialect = database.dialect
            elif isinstance(database, DatabaseEngine):
                dialect = database.dialect()
            else:
                raise QueryError(
                    message="dialect could not be derived; pass dialect=... explicitly",
                    stage="init",
                )
        self._database: DatabaseLike = database
        self._compiler = QueryCompiler(dialect)
        self._table: str = table.strip()
        self._model: Optional[type] = model
        self._columns: Tuple[str, ...] = tuple(columns) if columns else ()
        self._wheres: Tuple[Dict[str, Any], ...] = tuple(wheres or ())
        self._order_by: Tuple[Tuple[str, str], ...] = tuple(order_by or ())
        self._limit: Optional[int] = limit
        self._offset: Optional[int] = offset

    # ── introspection ─────────────────────────────────────────────────

    @property
    def table(self) -> str:
        """The table this query targets."""
        return self._table

    @property
    def model(self) -> Optional[type]:
        """The ORM model class this query hydrates into (or ``None``)."""
        return self._model

    @property
    def database(self) -> DatabaseLike:
        """The database source this query executes against."""
        return self._database

    @property
    def wheres(self) -> Tuple[Dict[str, Any], ...]:
        """Immutable snapshot of the active where clauses."""
        return self._wheres

    def compile(self) -> CompiledQuery:
        """Compile the current state into (*sql*, *parameters*) without executing."""
        return self._compiler.compile_select(
            table=self._table,
            columns=self._columns or None,
            wheres=self._wheres,
            order_by=self._order_by or None,
            limit=self._limit,
            offset=self._offset,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serializable description of the query state (LLM friendly)."""
        return {
            "type": "query",
            "table": self._table,
            "model": self._model.__name__ if self._model else None,
            "columns": list(self._columns) or None,
            "wheres": [dict(w) for w in self._wheres],
            "order_by": [list(o) for o in self._order_by],
            "limit": self._limit,
            "offset": self._offset,
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Query(table={self._table!r}, wheres={len(self._wheres)})"

    # ── composable modifiers (immutable) ─────────────────────────────

    def _replace(self, **changes: Any) -> "Query":
        return type(self)(**{**self._state(), **changes})

    def _state(self) -> Dict[str, Any]:
        return {
            "table": self._table,
            "database": self._database,
            "dialect": self._compiler.dialect,
            "model": self._model,
            "columns": self._columns,
            "wheres": self._wheres,
            "order_by": self._order_by,
            "limit": self._limit,
            "offset": self._offset,
        }

    def select(self, *columns: str) -> "Query":
        """Return a new query selecting only ``columns``."""
        return self._replace(columns=columns)

    def where(self, column: str, value: Any, operator: str = "=") -> "Query":
        """Add a ``column <operator> value`` condition (AND semantics).

        ``where(column, None)`` compiles to ``column IS NULL`` (predictable
        convenience).  Use :meth:`where_in` for ``IN`` lists.
        """
        if value is None and operator in ("=", "==", None):
            return self.where_null(column)
        return self._replace(
            wheres=self._wheres
            + ({"column": column, "operator": operator or "=", "value": value},)
        )

    def where_in(self, column: str, values: Iterable[Any]) -> "Query":
        """Add ``column IN (...values)`` with parameterized placeholders."""
        vals = list(values)
        if not vals:
            raise QueryError(
                message="where_in requires at least one value",
                stage="build",
                context={"column": column},
            )
        return self._replace(
            wheres=self._wheres
            + ({"column": column, "kind": "in", "value": vals},)
        )

    def where_null(self, column: str) -> "Query":
        """Add ``column IS NULL``."""
        return self._replace(
            wheres=self._wheres + ({"column": column, "kind": "null"},)
        )

    def where_not_null(self, column: str) -> "Query":
        """Add ``column IS NOT NULL``."""
        return self._replace(
            wheres=self._wheres + ({"column": column, "kind": "not_null"},)
        )

    def order_by(self, column: str, direction: str = "asc") -> "Query":
        """Return a new query ordered by ``column`` (append semantics)."""
        return self._replace(order_by=self._order_by + ((column, direction),))

    def limit(self, count: int) -> "Query":
        """Return a new query limited to ``count`` rows."""
        return self._replace(limit=int(count))

    def offset(self, count: int) -> "Query":
        """Return a new query skipping ``count`` rows."""
        return self._replace(offset=int(count))

    def paginate(self, page: int = 1, per_page: int = 20) -> Dict[str, Any]:
        """Return one page as ``{"items": [...], "total": int}`` (Task 16.3).

        Minimal page-based pagination on top of the existing ``limit`` /
        ``offset`` / ``count`` / ``get`` surface -- no new abstraction::

            result = Query("users", database=manager).paginate(page=2, per_page=20)
            rows, total = result["items"], result["total"]

        ``page`` must be >= 1 and ``per_page`` >= 1; ``total`` is the
        count of **all** matching rows (ignoring limit/offset) so callers can
        compute ``total_pages``.
        """
        if not isinstance(page, int) or isinstance(page, bool) or page < 1:
            raise QueryError(
                message="paginate() requires page >= 1",
                stage="build",
                context={"page": page},
            )
        if not isinstance(per_page, int) or isinstance(per_page, bool) or per_page < 1:
            raise QueryError(
                message="paginate() requires per_page >= 1",
                stage="build",
                context={"per_page": per_page},
            )
        total = self.count()
        items = self._replace(
            limit=per_page,
            offset=(page - 1) * per_page,
        ).get()
        return {"items": items, "total": total}

    # ── terminal operations (SELECT family) ──────────────────────────

    def get(self, columns: Optional[Sequence[str]] = None) -> List[Any]:
        """Execute the select and return all matching rows.

        Returns hydrated model instances when this query is model-aware
        (``Model.query()``), otherwise a list of row mappings.
        """
        compiled = self._compiler.compile_select(
            table=self._table,
            columns=columns or self._columns or None,
            wheres=self._wheres,
            order_by=self._order_by or None,
            limit=self._limit,
            offset=self._offset,
        )
        rows = self._rows(execute_compiled(self._database, compiled), compiled)
        if self._model is None:
            return [
                _row_to_mapping(r, compiled.columns) if not isinstance(r, dict) else dict(r)
                for r in rows
            ]
        return [self._model._from_row(_row_to_mapping(r, compiled.columns)) for r in rows]

    def all(self, columns: Optional[Sequence[str]] = None) -> List[Any]:
        """Alias of :meth:`get` (``.all()`` and ``.get()`` are synonyms)."""
        return self.get(columns=columns)

    def first(self) -> Any:
        """Execute the select with ``LIMIT 1`` and return the first row/None."""
        compiled = self._compiler.compile_select(
            table=self._table,
            columns=self._columns or None,
            wheres=self._wheres,
            order_by=self._order_by or None,
            limit=1,
            offset=self._offset,
        )
        rows = self._rows(execute_compiled(self._database, compiled), compiled)
        if not rows:
            return None
        row = _row_to_mapping(rows[0], compiled.columns)
        if self._model is None:
            return row
        return self._model._from_row(row)

    def count(self) -> int:
        """Execute ``SELECT COUNT(*)`` and return the integer count."""
        compiled = self._compiler.compile_count(
            table=self._table,
            wheres=self._wheres,
        )
        rows = self._rows(execute_compiled(self._database, compiled), compiled)
        if not rows:
            return 0
        row = rows[0]
        if isinstance(row, dict):
            return int(next(iter(row.values())))
        return int(row[0])

    def exists(self) -> bool:
        """Return ``True`` when at least one matching row exists."""
        compiled = self._compiler.compile_exists(
            table=self._table,
            wheres=self._wheres,
        )
        rows = self._rows(execute_compiled(self._database, compiled), compiled)
        return bool(rows)

    # ── terminal operations (write family) ───────────────────────────

    def insert(self, values: Dict[str, Any]) -> Dict[str, Any]:
        """Insert a row from ``values`` (all values parameterized).

        Returns a stable result dict ``{"affected": int, "lastrowid": any}``.
        ``lastrowid`` depends on driver/result support (``None`` when the
        driver does not expose it).
        """
        compiled = self._compiler.compile_insert(table=self._table, values=dict(values))
        result = execute_compiled(self._database, compiled)
        return self._write_result(result, compiled)

    def update(self, values: Dict[str, Any]) -> Dict[str, Any]:
        """Update matching rows.

        Refuses to run without a where clause (safety contract); returns
        ``{"affected": int}``.
        """
        compiled = self._compiler.compile_update(
            table=self._table,
            values=dict(values),
            wheres=self._wheres,
        )
        result = execute_compiled(self._database, compiled)
        return self._write_result(result, compiled)

    def delete(self) -> Dict[str, Any]:
        """Delete matching rows.  Refuses to run without a where clause."""
        compiled = self._compiler.compile_delete(
            table=self._table,
            wheres=self._wheres,
        )
        result = execute_compiled(self._database, compiled)
        return self._write_result(result, compiled)

    # ── result handling ──────────────────────────────────────────────

    def _rows(self, result: Any, compiled: CompiledQuery) -> List[Any]:
        """Extract a list of rows from a driver result (tolerant contract)."""
        if result is None:
            return []
        if isinstance(result, dict):
            rows = result.get("rows")
            if rows is None:
                rows = result.get("data")
            if rows is None and compiled.operation == "select":
                # A single row mapping?  Only when columns were requested.
                if compiled.columns:
                    return [result]
            return list(rows) if rows is not None else []
        fetchall = getattr(result, "fetchall", None)
        if callable(fetchall):
            return list(fetchall())
        rows = getattr(result, "rows", None)
        if rows is not None:
            return list(rows)
        if isinstance(result, (list, tuple)):
            return list(result)
        return []

    def _write_result(self, result: Any, compiled: CompiledQuery) -> Dict[str, Any]:
        affected: Optional[int] = None
        lastrowid: Any = None
        if isinstance(result, dict):
            affected = result.get("affected")
            for key in ("lastrowid", "inserted_id", "id", "last_insert_id"):
                if key in result and result[key] is not None:
                    lastrowid = result[key]
                    break
            if affected is None and "rowcount" in result:
                affected = result["rowcount"]
        elif isinstance(result, int):
            affected = result
            lastrowid = result
        else:
            rowcount = getattr(result, "rowcount", None)
            if rowcount is not None:
                affected = int(rowcount)
            lastrowid = None
        return {
            "affected": int(affected) if affected is not None else 0,
            "lastrowid": lastrowid,
        }


__all__ = ["Query", "execute_compiled"]