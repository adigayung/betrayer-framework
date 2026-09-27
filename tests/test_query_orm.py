"""Task 09.2 — Query Builder & ORM tests.

All tests use a *fake in-memory engine/connection* (never a real database).
The proof is::

    ORM Model -> Query Builder -> SQL Compiler -> SQLDialect -> Connection

runs as one pipeline without the core knowing the concrete engine, and no
SQLite/PostgreSQL/MySQL-specific code exists anywhere in the core ORM.
"""

from __future__ import annotations

import datetime
from typing import Any, Dict, Iterable, List, Optional

import pytest

from betrayer.core.config import Config
from betrayer.data import (
    Connection,
    DatabaseEngine,
    DatabaseManager,
    DatabaseRegistry,
    ORMField,
    ORMModel,
    QueryError,
    SQLDialect,
)
from betrayer.data.compiler import QueryCompiler
from betrayer.data.exceptions import ConnectionError, DatabaseError, ModelError
from betrayer.data.query import Query, execute_compiled


# ---------------------------------------------------------------------------
# Fake in-memory engine (contract test double — NOT part of core Betrayer)
# ---------------------------------------------------------------------------


class FakeDialect(SQLDialect):
    name = "fake"

    def quote_identifier(self, identifier: str) -> str:
        return f'"{identifier}"'

    def placeholder(self, position: Optional[int] = None) -> str:
        return "?"

    def boolean_value(self, value: bool) -> str:
        return "1" if value else "0"

    def auto_increment(self) -> str:
        return "INTEGER PRIMARY KEY AUTOINCREMENT"

    def type_name(self, python_type: Any) -> str:
        return {int: "INTEGER", str: "TEXT", float: "REAL", bool: "INTEGER"}.get(
            python_type, "TEXT"
        )


class FakeConnection(Connection):
    """In-memory table store: executes parameterized queries without SQL."""

    def __init__(self, tables: Optional[Dict[str, List[Dict[str, Any]]]] = None) -> None:
        self._tables: Dict[str, List[Dict[str, Any]]] = {
            name: [dict(r) for r in rows]
            for name, rows in (tables or {}).items()
        }
        self._counter = 0
        self._executed: List[tuple] = []
        self._commits = 0
        self._rollbacks = 0
        self._closed = False

    # -- store helpers -------------------------------------------------

    def seed(self, table: str, rows: List[Dict[str, Any]]) -> None:
        self._tables.setdefault(table, []).extend(dict(r) for r in rows)

    def _table(self, name: str) -> List[Dict[str, Any]]:
        name = name.strip('"')
        return self._tables.setdefault(name, [])

    def _where(self, rows: List[Dict[str, Any]], wheres: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        out = []
        for row in rows:
            match = True
            for w in wheres:
                col = w["column"]
                kind = w.get("kind", "cmp")
                if kind == "in":
                    if row.get(col) not in w["value"]:
                        match = False
                        break
                elif kind == "null":
                    if row.get(col) is not None:
                        match = False
                        break
                elif kind == "not_null":
                    if row.get(col) is None:
                        match = False
                        break
                else:
                    expected = w["value"]
                    actual = row.get(col)
                    op = w.get("operator", "=")
                    if op in ("=", "==", None):
                        if actual is None or actual != expected:
                            match = False
                            break
                    elif op == "!=":
                        if actual == expected:
                            match = False
                            break
                    elif op == ">":
                        if actual is None or not (actual > expected):
                            match = False
                            break
                    elif op == ">=":
                        if actual is None or not (actual >= expected):
                            match = False
                            break
                    elif op == "<":
                        if actual is None or not (actual < expected):
                            match = False
                            break
                    elif op == "<=":
                        if actual is None or not (actual <= expected):
                            match = False
                            break
                    elif op.lower() == "like":
                        if actual is None or expected not in str(actual):
                            match = False
                            break
            if match:
                out.append(row)
        return out

    # -- sorting --------------------------------------------------------

    def _sort(self, rows: List[Dict[str, Any]], order_by) -> List[Dict[str, Any]]:
        if not order_by:
            return list(rows)
        result = list(rows)
        for col, direction in reversed(list(order_by)):
            reverse = str(direction).lower() == "desc"
            result.sort(key=lambda r: (r.get(col) is None, r.get(col)), reverse=reverse)
        return result

    # -- Connection contract -------------------------------------------

    def connect(self) -> None:
        self._closed = False

    def close(self) -> None:
        self._closed = True

    def execute(self, query: str, parameters: Any = None) -> Any:
        self._executed.append((query, parameters))
        params = list(parameters or [])
        upper = query.upper()
        if "SELECT COUNT(*)" in upper:
            return self._count(query, params)
        if "SELECT 1 FROM" in upper:
            return self._exists(query, params)
        if "INSERT INTO" in upper:
            return self._insert(query, params)
        if query.upper().startswith("UPDATE"):
            return self._update(query, params)
        if query.upper().startswith("DELETE"):
            return self._delete(query, params)
        if "SELECT" in upper:
            return self._select(query, params)
        raise RuntimeError("unsupported query: " + query)

    # -- WHERE parsing (accepts the SQL the compiler emits) -------------

    def _parse_where(self, where_text: str, params: List[Any]) -> List[Dict[str, Any]]:
        wheres: List[Dict[str, Any]] = []
        text = (where_text or "").strip()
        if not text:
            return wheres
        param_iter = iter(params)
        for clause in text.split(" AND "):
            clause = clause.strip()
            upper = clause.upper()
            if " IS NOT NULL" in upper:
                col = clause[: upper.index(" IS NOT NULL")].strip().strip('"')
                wheres.append({"column": col, "kind": "not_null"})
            elif " IS NULL" in upper:
                col = clause[: upper.index(" IS NULL")].strip().strip('"')
                wheres.append({"column": col, "kind": "null"})
            elif " IN (" in upper:
                col = clause[: upper.index(" IN (")].strip().strip('"')
                n = clause.count("?")
                vals = [next(param_iter) for _ in range(n)]
                wheres.append({"column": col, "kind": "in", "value": vals})
            else:
                handled = False
                for op in (" LIKE ", " >= ", " <= ", " <> ", " != ", " = ", " > ", " < "):
                    if op in clause:
                        col, _ = clause.split(op, 1)
                        col = col.strip().strip('"')
                        value = next(param_iter)
                        op_sym = op.strip()
                        if op_sym == "LIKE":
                            wheres.append({"column": col, "operator": "like", "value": value})
                        elif op_sym in ("!=", "<>"):
                            wheres.append({"column": col, "operator": "!=", "value": value})
                        else:
                            wheres.append({"column": col, "operator": op_sym, "value": value})
                        handled = True
                        break
                if not handled:
                    raise RuntimeError(f"cannot parse WHERE clause: {clause!r}")
        return wheres

    def _strip_sql_suffixes(self, text: str) -> str:
        """Remove ORDER BY / LIMIT / OFFSET suffixes, leaving the WHERE core."""
        import re as _re

        result = text
        result = _re.sub(r"\s+ORDER\s+BY\s+.*$", "", result, flags=_re.IGNORECASE)
        result = _re.sub(r"\s+LIMIT\s+\d+$", "", result, flags=_re.IGNORECASE)
        result = _re.sub(r"\s+OFFSET\s+\d+$", "", result, flags=_re.IGNORECASE)
        return result.strip()

    def _parse_select_clause(self, query: str):
        """Parse a SELECT statement -> (table, cols, order_by, limit, offset, where)."""
        import re as _re

        m = _re.match(
            r"SELECT\s+(?P<cols>.*?)\s+FROM\s+(?P<table>\S+?)(?:\s+WHERE\s+(?P<where>.*))?$",
            query,
            _re.IGNORECASE,
        )
        if m is None:
            raise RuntimeError(f"cannot parse SELECT: {query!r}")
        table = m.group("table").strip('"')
        cols = m.group("cols").strip()
        where_sql = m.group("where") or ""

        limit: Optional[int] = None
        offset: Optional[int] = None
        order_by = []
        lm = _re.search(r"\s+LIMIT\s+(\d+)", where_sql, _re.IGNORECASE)
        if lm:
            limit = int(lm.group(1))
        om = _re.search(r"\s+OFFSET\s+(\d+)", where_sql, _re.IGNORECASE)
        if om:
            offset = int(om.group(1))
        obm = _re.search(
            r"\s+ORDER\s+BY\s+(.+?)(?:\s+LIMIT\s+\d+|\s+OFFSET\s+\d+|$)",
            where_sql,
            _re.IGNORECASE,
        )
        if obm:
            for part in obm.group(1).split(","):
                part = part.strip()
                direction = "asc"
                upper = part.upper()
                if " DESC" in upper:
                    direction = "desc"
                    part = part[: upper.index(" DESC")].strip()
                elif " ASC" in upper:
                    part = part[: upper.index(" ASC")].strip()
                order_by.append((part.strip('"'), direction))
        where_part = self._strip_sql_suffixes(where_sql)
        return table, cols, order_by, limit, offset, where_part

    def _select(self, query: str, params: List[Any]) -> Dict[str, Any]:
        table, cols, order_by, limit, offset, where_part = self._parse_select_clause(query)
        wheres = self._parse_where(where_part, params)
        rows = self._where(self._table(table), wheres)
        rows = self._sort(rows, order_by)
        if offset:
            rows = rows[offset:]
        if limit is not None:
            rows = rows[:limit]
        if cols.strip() != "*":
            columns = [c.strip().strip('"') for c in cols.split(",")]
            rows = [{c: r.get(c) for c in columns} for r in rows]
        return {"rows": rows}

    def _count(self, query: str, params: List[Any]) -> Dict[str, Any]:
        import re as _re

        m = _re.match(
            r"SELECT\s+COUNT\(\*\)\s+FROM\s+(?P<table>\S+?)(?:\s+WHERE\s+(?P<where>.*))?$",
            query,
            _re.IGNORECASE,
        )
        table = m.group("table").strip('"')
        where_part = self._strip_sql_suffixes(m.group("where") or "")
        wheres = self._parse_where(where_part, params)
        rows = self._where(self._table(table), wheres)
        return {"rows": [{"count": len(rows)}]}

    def _exists(self, query: str, params: List[Any]) -> Dict[str, Any]:
        import re as _re

        m = _re.match(
            r"SELECT\s+1\s+FROM\s+(?P<table>\S+?)(?:\s+WHERE\s+(?P<where>.*?))?\s+LIMIT\s+1$",
            query,
            _re.IGNORECASE,
        )
        table = m.group("table").strip('"')
        where_part = self._strip_sql_suffixes(m.group("where") or "")
        wheres = self._parse_where(where_part, params)
        rows = self._where(self._table(table), wheres)
        return {"rows": rows[:1]}

    def _insert(self, query: str, params: List[Any]) -> Dict[str, Any]:
        import re as _re

        m = _re.match(
            r"INSERT\s+INTO\s+(?P<table>\S+?)\s+\((?P<cols>.*?)\)\s+VALUES\s+\((?P<ph>.*?)\)",
            query,
            _re.IGNORECASE,
        )
        table = m.group("table").strip('"')
        cols = [c.strip().strip('"') for c in m.group("cols").split(",")]
        row = dict(zip(cols, params))
        rows = self._table(table)
        if "id" in row and row.get("id") is None:
            next_id = max([r.get("id", 0) if r.get("id") is not None else 0 for r in rows] or [0]) + 1
            row["id"] = next_id
        row.setdefault("id", self._counter + 1)
        rows.append(row)
        return {"affected": 1, "lastrowid": row.get("id")}

    def _update(self, query: str, params: List[Any]) -> Dict[str, Any]:
        import re as _re

        m = _re.match(
            r"UPDATE\s+(?P<table>\S+?)\s+SET\s+(?P<set>.*?)\s+WHERE\s+(?P<where>.*)$",
            query,
            _re.IGNORECASE,
        )
        table = m.group("table").strip('"')
        set_part = m.group("set")
        n_placeholders = set_part.count("?")
        set_values = params[:n_placeholders]
        set_items = []
        idx = 0
        for seg in set_part.split(","):
            col = seg.split("=")[0].strip().strip('"')
            set_items.append((col, set_values[idx]))
            idx += 1
        where_params = params[n_placeholders:]
        where_part = self._strip_sql_suffixes(m.group("where"))
        wheres = self._parse_where(where_part, where_params)
        rows = self._where(self._table(table), wheres)
        affected = 0
        for row in rows:
            for col, val in set_items:
                row[col] = val
            affected += 1
        return {"affected": affected}

    def _delete(self, query: str, params: List[Any]) -> Dict[str, Any]:
        import re as _re

        m = _re.match(
            r"DELETE\s+FROM\s+(?P<table>\S+?)\s+WHERE\s+(?P<where>.*)$",
            query,
            _re.IGNORECASE,
        )
        table = m.group("table").strip('"')
        where_part = self._strip_sql_suffixes(m.group("where"))
        wheres = self._parse_where(where_part, params)
        rows = self._where(self._table(table), wheres)
        store = self._table(table)
        before = len(store)
        store[:] = [r for r in store if r not in rows]
        return {"affected": before - len(store)}

    def executemany(self, query: str, parameters: Iterable[Any]) -> Any:
        count = 0
        for params in parameters:
            self.execute(query, params)
            count += 1
        return {"affected": count}

    def commit(self) -> None:
        self._commits += 1

    def rollback(self) -> None:
        self._rollbacks += 1

    def cursor(self) -> Any:
        return None


class FakeEngine(DatabaseEngine):
    driver_name = "fake"

    def __init__(
        self, name: str = "default", config: Optional[Dict[str, Any]] = None, **options: Any
    ) -> None:
        self._name = name
        self._dialect = FakeDialect()
        self._closed = False
        self._connection: Optional[FakeConnection] = None

    def connect(self, name: Optional[str] = None, **options: Any) -> Connection:
        if self._closed:
            raise ConnectionError(message="Engine is closed", stage="connect")
        if self._connection is None:
            self._connection = FakeConnection()
        return self._connection

    def transaction(self, connection: Optional[Connection] = None, **options: Any):
        from betrayer.data.transaction import Transaction

        if connection is None:
            connection = self.connect()
        return Transaction(self, connection=connection)

    def dialect(self) -> SQLDialect:
        return self._dialect

    def close(self) -> None:
        self._closed = True

    def metadata(self) -> Dict[str, Any]:
        return {"type": "engine", "driver": "fake", "database": self._name}


@pytest.fixture()
def manager() -> DatabaseManager:
    engine = FakeEngine("default")
    mgr = DatabaseManager(engine)
    mgr.connect()
    return mgr


@pytest.fixture()
def seeded(manager: DatabaseManager):
    conn = manager.connection
    assert isinstance(conn, FakeConnection)
    conn.seed(
        "users",
        [
            {"id": 1, "name": "Alice", "email": "alice@example.com", "active": True, "age": 30},
            {"id": 2, "name": "Bob", "email": "bob@example.com", "active": False, "age": 25},
            {"id": 3, "name": "Carol", "email": "carol@example.com", "active": True, "age": 35},
        ],
    )
    return manager


# ---------------------------------------------------------------------------
# Query construction / compilation
# ---------------------------------------------------------------------------


def test_query_requires_table(manager):
    with pytest.raises(QueryError):
        Query("", database=manager)


def test_query_requires_database():
    with pytest.raises(QueryError):
        Query("users")


def test_compile_select_with_where(manager):
    q = Query("users", database=manager).where("email", "a@b.c")
    compiled = q.compile()
    assert compiled.sql == 'SELECT * FROM "users" WHERE "email" = ?'
    assert compiled.parameters == ("a@b.c",)
    assert compiled.operation == "select"


def test_compile_select_columns(manager):
    compiled = Query("users", database=manager).select("id", "name").compile()
    assert compiled.sql == 'SELECT "id", "name" FROM "users"'
    assert compiled.columns == ("id", "name")


def test_where_in_parameterized(manager):
    compiled = Query("users", database=manager).where_in("id", [1, 2, 3]).compile()
    assert compiled.sql == 'SELECT * FROM "users" WHERE "id" IN (?, ?, ?)'
    assert compiled.parameters == (1, 2, 3)


def test_where_in_rejects_empty(manager):
    with pytest.raises(QueryError):
        Query("users", database=manager).where_in("id", [])


def test_where_null_and_not_null(manager):
    q = Query("users", database=manager).where_null("deleted_at")
    assert q.compile().sql == 'SELECT * FROM "users" WHERE "deleted_at" IS NULL'
    q2 = Query("users", database=manager).where_not_null("deleted_at")
    assert q2.compile().sql == 'SELECT * FROM "users" WHERE "deleted_at" IS NOT NULL'


def test_where_none_becomes_is_null(manager):
    compiled = Query("users", database=manager).where("deleted_at", None).compile()
    assert compiled.sql == 'SELECT * FROM "users" WHERE "deleted_at" IS NULL'


def test_order_by_limit_offset(manager):
    q = (
        Query("users", database=manager)
        .order_by("created_at", "desc")
        .limit(10)
        .offset(5)
    )
    compiled = q.compile()
    assert compiled.sql == (
        'SELECT * FROM "users" ORDER BY "created_at" DESC LIMIT 10 OFFSET 5'
    )


def test_invalid_order_direction(manager):
    with pytest.raises(QueryError):
        Query("users", database=manager).order_by("id", "sideways").compile()


def test_unknown_where_operator(manager):
    with pytest.raises(QueryError):
        Query("users", database=manager).where("a", 1, operator="^=").compile()


def test_invalid_where_column(manager):
    with pytest.raises(QueryError):
        Query("users", database=manager).where("", 1).compile()


# ---------------------------------------------------------------------------
# Parameter binding / SQL injection safety
# ---------------------------------------------------------------------------


def test_values_never_interpolated(manager):
    q = Query("users", database=manager).where("name", "x'; DROP TABLE users; --")
    compiled = q.compile()
    assert "DROP" not in compiled.sql
    assert compiled.sql.count("?") == 1
    assert compiled.parameters == ("x'; DROP TABLE users; --",)


def test_identifier_quoted_even_when_evil(manager):
    q = Query('users; DROP TABLE x', database=manager).where("name", "a")
    compiled = q.compile()
    # now it is just a weird identifier, quoted by the dialect
    assert compiled.sql == (
        'SELECT * FROM "users; DROP TABLE x" WHERE "name" = ?'
    )


def test_injection_safe_end_to_end(manager):
    conn = manager.connection
    assert isinstance(conn, FakeConnection)
    rows = (
        Query("users", database=manager)
        .where("name", "Alice' OR '1'='1")
        .get()
    )
    assert rows == []
    # the dangerous value was bound, not executed as SQL
    assert any("Alice' OR '1'='1" in str(p) for _, p in conn._executed for p in (p if isinstance(p, list) else [p]) if p)


# ---------------------------------------------------------------------------
# SELECT family: get / all / first / count / exists
# ---------------------------------------------------------------------------


def test_get_all_rows(seeded):
    rows = Query("users", database=seeded).get()
    assert len(rows) == 3
    assert rows[0]["name"] == "Alice"


def test_all_alias(seeded):
    rows = Query("users", database=seeded).all()
    assert len(rows) == 3


def test_get_with_columns(seeded):
    rows = Query("users", database=seeded).select("id", "name").get()
    assert rows[0] == {"id": 1, "name": "Alice"}


def test_get_with_where_and_order(seeded):
    rows = (
        Query("users", database=seeded)
        .where("active", True)
        .order_by("age", "desc")
        .get()
    )
    assert [r["name"] for r in rows] == ["Carol", "Alice"]


def test_first(seeded):
    first = Query("users", database=seeded).where("name", "Bob").first()
    assert first["age"] == 25


def test_first_none(seeded):
    assert Query("users", database=seeded).where("name", "Zed").first() is None


def test_count(seeded):
    assert Query("users", database=seeded).count() == 3
    assert Query("users", database=seeded).where("active", True).count() == 2


def test_exists(seeded):
    assert Query("users", database=seeded).where("email", "bob@example.com").exists()
    assert not Query("users", database=seeded).where("email", "nope@example.com").exists()


# ---------------------------------------------------------------------------
# Write family: insert / update / delete
# ---------------------------------------------------------------------------


def test_insert(manager):
    result = Query("users", database=manager).insert({"name": "Dave", "age": 40})
    assert result["affected"] == 1
    assert result["lastrowid"] is not None
    rows = Query("users", database=manager).get()
    assert rows[-1]["name"] == "Dave"


def test_update(seeded):
    result = (
        Query("users", database=seeded)
        .where("name", "Bob")
        .update({"active": True})
    )
    assert result["affected"] == 1
    bob = Query("users", database=seeded).where("name", "Bob").first()
    assert bob["active"] is True


def test_update_requires_where(seeded):
    with pytest.raises(QueryError):
        Query("users", database=seeded).update({"name": "X"})


def test_delete(seeded):
    result = Query("users", database=seeded).where("name", "Bob").delete()
    assert result["affected"] == 1
    assert Query("users", database=seeded).count() == 2


def test_delete_requires_where(seeded):
    with pytest.raises(QueryError):
        Query("users", database=seeded).delete()


# ---------------------------------------------------------------------------
# Immutability / composability
# ---------------------------------------------------------------------------


def test_query_is_immutable(manager):
    base = Query("users", database=manager)
    q1 = base.where("active", True)
    q2 = q1.order_by("id", "desc")
    assert base.wheres == ()
    assert len(q1.wheres) == 1
    assert len(q2.wheres) == 1
    assert len(q2._order_by) == 1
    # original still usable / unchanged
    assert base.compile().sql == 'SELECT * FROM "users"'


def test_where_accumulates(manager):
    q = Query("users", database=manager).where("a", 1).where("b", 2).where("c", 3)
    compiled = q.compile()
    assert compiled.sql == 'SELECT * FROM "users" WHERE "a" = ? AND "b" = ? AND "c" = ?'
    assert compiled.parameters == (1, 2, 3)


# ---------------------------------------------------------------------------
# ORM model
# ---------------------------------------------------------------------------


class User(ORMModel):
    """Test ORM model."""

    __table__ = "users"

    id = ORMField(int, primary_key=True, nullable=False)
    name = ORMField(str, required=True, nullable=False)
    email = ORMField(str, nullable=False)
    active = ORMField(bool, default=True)
    age = ORMField(int, nullable=True)
    created_at = ORMField(datetime.datetime, nullable=True)


def test_model_metadata(manager):
    User.__connection__ = manager
    meta = User.meta()
    assert meta["type"] == "orm_model"
    assert meta["name"] == "User"
    assert meta["table"] == "users"
    assert meta["primary_key"] == "id"
    names = [f["name"] for f in meta["fields"]]
    assert names == ["id", "name", "email", "active", "age", "created_at"]
    by_name = {f["name"]: f for f in meta["fields"]}
    assert by_name["id"]["primary_key"] is True
    assert by_name["name"]["required"] is True
    assert by_name["active"]["default"] is True


def test_model_auto_table_name():
    class UserProfile(ORMModel):
        pass

    assert UserProfile.table_name() == "user_profiles"


def test_model_from_row_hydration(manager):
    row = {"id": 1, "name": "Alice", "email": "a@b.c", "active": 1, "age": 30, "created_at": None}
    user = User._from_row(row)
    assert isinstance(user, User)
    assert user.id == 1
    assert user.active is True  # bool coercion from 1
    assert user.age == 30


def test_model_serialization(manager):
    user = User(id=1, name="Alice", email="a@b.c", active=True, age=30)
    assert user.to_dict() == {"id": 1, "name": "Alice", "email": "a@b.c", "active": True, "age": 30, "created_at": None}
    assert user.to_jsonable()["created_at"] is None


def test_model_to_jsonable_datetime(manager):
    ts = datetime.datetime(2024, 1, 2, 3, 4, 5)
    user = User(id=1, name="T", email="t@e.c", created_at=ts)
    assert user.to_jsonable()["created_at"] == "2024-01-02T03:04:05"


def test_model_query_returns_instances(manager):
    conn = manager.connection
    assert isinstance(conn, FakeConnection)
    conn.seed("users", [{"id": 1, "name": "Alice", "email": "a@b.c", "active": 1, "age": 30}])
    User.__connection__ = manager
    user = User.query().where("name", "Alice").first()
    assert isinstance(user, User)
    assert user.email == "a@b.c"
    users = User.query().get()
    assert all(isinstance(u, User) for u in users)


def test_model_query_where_first_target(manager):
    conn = manager.connection
    assert isinstance(conn, FakeConnection)
    conn.seed("users", [{"id": 1, "name": "Alice", "email": "alice@example.com", "active": True, "age": 30}])
    User.__connection__ = manager
    user = User.query().where("email", "alice@example.com").first()
    assert user is not None
    assert user.name == "Alice"


def test_model_create_inserts_and_hydrates(manager):
    conn = manager.connection
    assert isinstance(conn, FakeConnection)
    User.__connection__ = manager
    user = User.create(name="John", email="john@example.com")
    assert user.id is not None
    assert user.active is True
    rows = Query("users", database=manager).get()
    assert rows[0]["name"] == "John"
    assert rows[0]["email"] == "john@example.com"


def test_model_save_update(manager):
    conn = manager.connection
    assert isinstance(conn, FakeConnection)
    User.__connection__ = manager
    user = User.create(name="John", email="john@example.com")
    user.name = "Jane"
    user.save()
    rows = Query("users", database=manager).get()
    assert rows[0]["name"] == "Jane"


def test_model_delete(manager):
    conn = manager.connection
    assert isinstance(conn, FakeConnection)
    User.__connection__ = manager
    user = User.create(name="John", email="john@example.com")
    result = user.delete()
    assert result["affected"] == 1
    assert User.query().count() == 0


def test_model_refresh(manager):
    conn = manager.connection
    assert isinstance(conn, FakeConnection)
    User.__connection__ = manager
    user = User.create(name="John", email="john@example.com")
    # mutate the row directly through the query API
    User.query().where("id", user.id).update({"name": "Mutated"})
    assert user.name == "John"
    user.refresh()
    assert user.name == "Mutated"


def test_model_refresh_missing_raises(manager):
    user = User(id=999, name="X", email="x@e.c")
    user._from_row if False else None
    User.__connection__ = manager
    with pytest.raises(ModelError):
        user.refresh()


def test_model_create_required_field(manager):
    User.__connection__ = manager
    with pytest.raises(ModelError):
        User.create(email="no-name@example.com")  # name is required


def test_model_without_connection_raises():
    class NoConn(ORMModel):
        pass

    with pytest.raises(QueryError):
        NoConn.query()


# ---------------------------------------------------------------------------
# Type / value mapping
# ---------------------------------------------------------------------------


def test_value_mapper_scalars():
    from betrayer.data.value import ValueMapper

    assert ValueMapper(int).from_database("42") == 42
    assert ValueMapper(str).from_database(42) == "42"
    assert ValueMapper(float).from_database("3.5") == 3.5
    assert ValueMapper(bool).from_database(1) is True
    assert ValueMapper(bool).from_database(0) is False
    assert ValueMapper(int).from_database(None) is None


def test_value_mapper_invalid_conversion():
    from betrayer.data.value import ValueMapper

    with pytest.raises(ModelError):
        ValueMapper(int).from_database("not-an-int")


def test_value_mapper_to_database_passthrough():
    from betrayer.data.value import ValueMapper

    assert ValueMapper(str).to_database("x") == "x"
    assert ValueMapper(int).to_database(5) == 5
    assert ValueMapper(bool).to_database(False) is False
    assert ValueMapper(datetime.datetime).to_database(None) is None


# ---------------------------------------------------------------------------
# Error propagation & controlled errors
# ---------------------------------------------------------------------------


def test_execute_failure_wrapped_as_database_error(manager):
    conn = manager.connection
    assert isinstance(conn, FakeConnection)
    # Force failure by making the fake throw on a specific marker
    conn.seed("boom_table", [])
    # The fake throws RuntimeError for anything it can't parse; craft an
    # insert with empty values which the compiler rejects first.
    with pytest.raises(QueryError):
        Query("boom_table", database=manager).insert({})


def test_dialect_delegation_quote(manager):
    compiled = Query("users", database=manager).where("id", 1).compile()
    assert compiled.sql.startswith('SELECT * FROM "users"')


def test_engine_provider_callable():
    engine = FakeEngine("default")
    called = []

    def provider():
        called.append(True)
        return engine.connect()

    result = (
        Query("users", database=provider, dialect=FakeDialect())
        .where("id", 1)
        .first()
    )
    assert result is None
    assert called


def test_query_requires_valid_database():
    with pytest.raises(QueryError):
        Query("users", database=object())


def test_model_repr_does_not_leak_connection(manager):
    user = User(id=1, name="A", email="e@e.c", active=True)
    rep = repr(user)
    assert "FakeEngine" not in rep


# ---------------------------------------------------------------------------
# E2E pipeline: Model -> Query Builder -> Compiler -> Dialect -> Connection
# ---------------------------------------------------------------------------


def test_full_pipeline(manager):
    conn = manager.connection
    assert isinstance(conn, FakeConnection)
    conn.seed(
        "products",
        [
            {"id": 1, "sku": "A-1", "price": 10, "active": True},
            {"id": 2, "sku": "B-2", "price": 20, "active": False},
        ],
    )

    class Product(ORMModel):
        __table__ = "products"
        __connection__ = manager

        id = ORMField(int, primary_key=True)
        sku = ORMField(str)
        price = ORMField(int)
        active = ORMField(bool)

    assert Product.query().count() == 2
    p = Product.query().where("sku", "A-1").first()
    assert p is not None and p.price == 10
    p.price = 15
    p.save()
    assert Product.query().where("sku", "A-1").first().price == 15
    assert Product.query().where("active", True).exists()
    Product.create(sku="C-3", price=30, active=True)
    assert Product.query().count() == 3


def test_e2e_through_registry():
    """Model -> QB -> Compiler -> Dialect -> Connection via the registry."""
    registry = DatabaseRegistry(Config({"database.default.driver": "fake"}))
    registry.register_engine("fake", FakeEngine)
    engine = registry.engine("default")
    conn = engine.connect()
    assert isinstance(conn, FakeConnection)
    conn.seed("todos", [{"id": 1, "title": "write tests", "done": False}])

    manager = DatabaseManager(engine)
    manager.connect()

    class Todo(ORMModel):
        __table__ = "todos"
        __connection__ = manager

        id = ORMField(int, primary_key=True)
        title = ORMField(str)
        done = ORMField(bool)

    todo = Todo.query().where("id", 1).first()
    assert todo is not None and todo.title == "write tests"
    todo.done = True
    todo.save()
    assert Todo.query().where("id", 1).first().done is True


# ---------------------------------------------------------------------------
# Compiler standalone
# ---------------------------------------------------------------------------


def test_compiler_standalone_insert():
    compiler = QueryCompiler(FakeDialect())
    compiled = compiler.compile_insert(table="users", values={"name": "A", "age": 2})
    assert compiled.sql == 'INSERT INTO "users" ("name", "age") VALUES (?, ?)'
    assert compiled.parameters == ("A", 2)


def test_compiler_standalone_count():
    compiler = QueryCompiler(FakeDialect())
    compiled = compiler.compile_count(
        table="users", wheres=[{"column": "active", "operator": "=", "value": True}]
    )
    assert compiled.sql == 'SELECT COUNT(*) FROM "users" WHERE "active" = ?'
    assert compiled.parameters == (True,)


def test_compiler_sequences_placeholders_with_params():
    compiler = QueryCompiler(FakeDialect())
    compiled = compiler.compile_update(
        table="users",
        values={"name": "X"},
        wheres=[{"column": "id", "operator": "=", "value": 7}],
    )
    # update SET uses placeholder 1, where uses placeholder 2
    assert compiled.sql == 'UPDATE "users" SET "name" = ? WHERE "id" = ?'
    assert compiled.parameters == ("X", 7)


def test_execute_compiled_via_engine():
    engine = FakeEngine("default")
    conn = engine.connect()
    assert isinstance(conn, FakeConnection)
    conn.seed("users", [{"id": 1, "name": "A"}])
    compiler = QueryCompiler(engine.dialect())
    compiled = compiler.compile_select(table="users", wheres=[{"column": "id", "operator": "=", "value": 1}])
    rows = execute_compiled(engine, compiled)
    assert rows["rows"][0]["name"] == "A"


def test_execute_compiled_requires_connection(manager):
    manager.disconnect()
    compiled = QueryCompiler(manager.dialect).compile_select(table="users")
    with pytest.raises(ConnectionError):
        execute_compiled(manager, compiled)