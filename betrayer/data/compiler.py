"""SQL compilation: translate a Query Builder state into SQL + parameters.

Task 09.2.  The compiler is the **only** place (besides the dialect) that
turns query intent into SQL text.  It follows strict rules:

* identifiers (table/column names) always pass through
  ``SQLDialect.quote_identifier``;
* **every** user/app value is a bind parameter — never string-interpolated;
* placeholder syntax comes from ``SQLDialect.placeholder``;
* there is **no** ``if database == "sqlite"/"postgres"/...`` branching here;
  database-specific SQL behaviour belongs to the dialect (via
  ``compile_fragment`` / ``features``), never to the Query Builder.

The compiler knows the :class:`~betrayer.data.database.SQLDialect` contract
only — never a concrete driver.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from betrayer.data.database import SQLDialect
from betrayer.data.exceptions import QueryError

__all__ = [
    "CompiledQuery",
    "QueryCompiler",
    "OPERATORS",
]


@dataclass(frozen=True)
class CompiledQuery:
    """A fully compiled statement: SQL text + positional parameters.

    ``sql`` is generated from the dialect contract (quoted identifiers +
    placeholders); ``parameters`` are the values to bind, in order of their
    occurrence in ``sql``.  This is the *contract* Query Builder and ORM
    consume when handing work to :class:`~betrayer.data.database.Connection`.
    """

    sql: str
    parameters: Tuple[Any, ...] = ()
    #: Bound column names, useful for result mapping (``SELECT a, b``).
    columns: Optional[Tuple[str, ...]] = None
    #: The SQL operation this statement performs (select/insert/update/delete).
    operation: Optional[str] = None
    #: Source table for this statement.
    table: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "parameters", tuple(self.parameters))
        if self.columns is not None:
            object.__setattr__(self, "columns", tuple(self.columns))

    def to_dict(self) -> Dict[str, Any]:
        """Serializable, safe representation (values included)."""
        return {
            "sql": self.sql,
            "parameters": list(self.parameters),
            "columns": list(self.columns) if self.columns is not None else None,
            "operation": self.operation,
            "table": self.table,
            "metadata": dict(self.metadata),
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"CompiledQuery(sql={self.sql!r}, parameters={self.parameters!r})"


#: Supported comparison operators for ``where`` / ``where_in`` clauses.
OPERATORS: Dict[str, str] = {
    "=": "=",
    "==": "=",
    "!=": "<>",
    "<>": "<>",
    ">": ">",
    ">=": ">=",
    "<": "<",
    "<=": "<=",
    "like": "LIKE",
    "ilike": "LIKE",
}


class QueryCompiler:
    """Compiles immutable query state (see :class:`~betrayer.data.query.Query`).

    The compiler never mutates the query; it reads its public state
    (``wheres``, ``columns``, ``order_by``, ...) and produces a
    :class:`CompiledQuery`.  It is also usable standalone:

    .. code-block:: python

        compiler = QueryCompiler(dialect)
        compiled = compiler.compile_select(
            table="users",
            columns=["id", "email"],
            wheres=[{"column": "email", "operator": "=", "value": "a@b.c"}],
        )
    """

    def __init__(self, dialect: SQLDialect) -> None:
        if not isinstance(dialect, SQLDialect):
            raise QueryError(
                message="QueryCompiler requires a SQLDialect instance",
                stage="init",
            )
        self._dialect = dialect

    @property
    def dialect(self) -> SQLDialect:
        """The dialect this compiler generates SQL for."""
        return self._dialect

    # ── building blocks ──────────────────────────────────────────────

    def quote(self, identifier: str) -> str:
        """Quote a dynamic identifier through the dialect."""
        if not isinstance(identifier, str) or not identifier.strip():
            raise QueryError(
                message="Identifier must be a non-empty string",
                stage="compile",
                context={"identifier": identifier},
            )
        return self._dialect.quote_identifier(identifier.strip())

    def _placeholder(self, position: int) -> str:
        return self._dialect.placeholder(position)

    # ── where compilation ────────────────────────────────────────────

    def compile_where(self, where: Dict[str, Any], params: List[Any]) -> str:
        """Compile a single where clause and append its values to ``params``.

        ``where`` keys (canonical, produced by the Query Builder):

        * ``column``  — identifier to test
        * ``operator`` — ``=``, ``!=``, ``>``, ``>=``, ``<``, ``<=``, ``like``
        * ``value``  — bind value for binary operators
        * ``kind``   — ``"in"``, ``"null"``, ``"not_null"`` for special forms

        Raises ``QueryError`` for unknown operators / invalid columns.
        """
        column = where.get("column")
        if not isinstance(column, str) or not column.strip():
            raise QueryError(
                message="where clause requires a non-empty column name",
                stage="compile",
                context={"where": dict(where)},
            )
        kind = where.get("kind", "cmp")
        quoted = self.quote(column)

        if kind == "in":
            values = where.get("value")
            if not isinstance(values, (list, tuple, set)) or not values:
                raise QueryError(
                    message="where_in requires a non-empty list/tuple/set of values",
                    stage="compile",
                    context={"column": column},
                )
            placeholders = ", ".join(
                self._placeholder(i) for i in range(len(params) + 1, len(params) + len(values) + 1)
            )
            params.extend(list(values))
            return f"{quoted} IN ({placeholders})"

        if kind == "null":
            return f"{quoted} IS NULL"

        if kind == "not_null":
            return f"{quoted} IS NOT NULL"

        operator = where.get("operator", "=")
        sql_op = OPERATORS.get(operator)
        if sql_op is None:
            raise QueryError(
                message=f"Unsupported where operator {operator!r}",
                stage="compile",
                context={"column": column, "operator": operator},
            )
        params.append(where.get("value"))
        return f"{quoted} {sql_op} {self._placeholder(len(params))}"

    # ── operations ───────────────────────────────────────────────────

    def compile_select(
        self,
        *,
        table: str,
        columns: Optional[Sequence[str]] = None,
        wheres: Optional[Sequence[Dict[str, Any]]] = None,
        order_by: Optional[Sequence[Tuple[str, str]]] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> CompiledQuery:
        """Compile a ``SELECT`` statement."""
        params: List[Any] = []
        if columns:
            quoted_cols = ", ".join(self.quote(c) for c in columns)
        else:
            quoted_cols = "*"
        sql = f"SELECT {quoted_cols} FROM {self.quote(table)}"
        where_sql = self._compile_wheres(wheres, params)
        if where_sql:
            sql += " WHERE " + where_sql
        if order_by:
            parts = []
            for col, direction in order_by:
                direction = (direction or "asc").lower()
                if direction not in ("asc", "desc"):
                    raise QueryError(
                        message=f"Invalid order direction {direction!r}",
                        stage="compile",
                        context={"column": col},
                    )
                parts.append(f"{self.quote(col)} {direction.upper()}")
            sql += " ORDER BY " + ", ".join(parts)
        if limit is not None:
            sql += f" LIMIT {int(limit)}"
        if offset is not None:
            sql += f" OFFSET {int(offset)}"
        return CompiledQuery(
            sql=sql,
            parameters=params,
            columns=tuple(columns) if columns else None,
            operation="select",
            table=table,
            metadata={"limit": limit, "offset": offset},
        )

    def compile_count(
        self,
        *,
        table: str,
        wheres: Optional[Sequence[Dict[str, Any]]] = None,
    ) -> CompiledQuery:
        """Compile ``SELECT COUNT(*)`` preserving where filters."""
        params: List[Any] = []
        sql = f"SELECT COUNT(*) FROM {self.quote(table)}"
        where_sql = self._compile_wheres(wheres, params)
        if where_sql:
            sql += " WHERE " + where_sql
        return CompiledQuery(
            sql=sql,
            parameters=params,
            operation="count",
            table=table,
        )

    def compile_exists(
        self,
        *,
        table: str,
        wheres: Optional[Sequence[Dict[str, Any]]] = None,
    ) -> CompiledQuery:
        """Compile ``SELECT 1 ... LIMIT 1`` used by ``exists()``."""
        params: List[Any] = []
        sql = f"SELECT 1 FROM {self.quote(table)}"
        where_sql = self._compile_wheres(wheres, params)
        if where_sql:
            sql += " WHERE " + where_sql
        sql += " LIMIT 1"
        return CompiledQuery(
            sql=sql,
            parameters=params,
            operation="exists",
            table=table,
        )

    def compile_insert(
        self,
        *,
        table: str,
        values: Dict[str, Any],
    ) -> CompiledQuery:
        """Compile an ``INSERT`` with parameterized values."""
        if not values:
            raise QueryError(
                message="insert requires at least one column/value",
                stage="compile",
            )
        columns = list(values.keys())
        quoted = ", ".join(self.quote(c) for c in columns)
        placeholders = ", ".join(
            self._placeholder(i) for i in range(1, len(columns) + 1)
        )
        sql = f"INSERT INTO {self.quote(table)} ({quoted}) VALUES ({placeholders})"
        return CompiledQuery(
            sql=sql,
            parameters=tuple(values[c] for c in columns),
            columns=tuple(columns),
            operation="insert",
            table=table,
        )

    def compile_update(
        self,
        *,
        table: str,
        values: Dict[str, Any],
        wheres: Optional[Sequence[Dict[str, Any]]] = None,
    ) -> CompiledQuery:
        """Compile an ``UPDATE`` with parameterized SET values.

        An update without a where clause is rejected (safety contract).
        """
        if not values:
            raise QueryError(
                message="update requires at least one column/value",
                stage="compile",
            )
        params: List[Any] = list(values.values())
        set_parts = []
        position = 0
        for col in values:
            position += 1
            set_parts.append(f"{self.quote(col)} = {self._placeholder(position)}")
        sql = f"UPDATE {self.quote(table)} SET " + ", ".join(set_parts)
        where_sql = self._compile_wheres(wheres, params)
        if not where_sql:
            raise QueryError(
                message="update requires a where clause (refusing full-table update)",
                stage="compile",
                context={"table": table},
            )
        sql += " WHERE " + where_sql
        return CompiledQuery(
            sql=sql,
            parameters=params,
            columns=tuple(values.keys()),
            operation="update",
            table=table,
        )

    def compile_delete(
        self,
        *,
        table: str,
        wheres: Optional[Sequence[Dict[str, Any]]] = None,
    ) -> CompiledQuery:
        """Compile a ``DELETE``.  Deleting without a where clause is refused."""
        params: List[Any] = []
        where_sql = self._compile_wheres(wheres, params)
        if not where_sql:
            raise QueryError(
                message="delete requires a where clause (refusing full-table delete)",
                stage="compile",
                context={"table": table},
            )
        sql = f"DELETE FROM {self.quote(table)} WHERE " + where_sql
        return CompiledQuery(
            sql=sql,
            parameters=params,
            operation="delete",
            table=table,
        )

    # ── internals ────────────────────────────────────────────────────

    def _compile_wheres(
        self,
        wheres: Optional[Sequence[Dict[str, Any]]],
        params: List[Any],
    ) -> str:
        if not wheres:
            return ""
        parts = [self.compile_where(w, params) for w in wheres]
        # Sequential AND semantics keep the API predictable (no implicit
        # grouping).  ``or_where`` is intentionally not exposed yet.
        return " AND ".join(parts)

    def _repr(self) -> str:  # pragma: no cover - debug aid
        return f"QueryCompiler(dialect={self._dialect.name})"

    __repr__ = _repr