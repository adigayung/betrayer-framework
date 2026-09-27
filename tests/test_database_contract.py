"""Task 09.1 — Database Abstraction & Engine Contract tests.

All tests use a *fake in-memory engine*; no real database server is ever
started.  The proof is::

    Database Contract -> Fake Engine -> Connection -> Transaction -> Registry

runs correctly without the core knowing the engine implementation details.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

import pytest

from betrayer.core.config import Config
from betrayer.data import (
    Connection,
    ConnectionError,
    DatabaseConfigurationError,
    DatabaseEngine,
    DatabaseManager,
    DatabaseRegistry,
    SQLDialect,
    TransactionError,
    UnsupportedDatabaseError,
)
from betrayer.data.exceptions import DatabaseError


# ---------------------------------------------------------------------------
# Fake in-memory engine (contract test double, NOT part of core Betrayer)
# ---------------------------------------------------------------------------


class FakeDialect(SQLDialect):
    """Minimal dialect for the fake engine."""

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
    """In-memory connection backed by a list of rows."""

    def __init__(self, rows: Optional[List[Dict[str, Any]]] = None) -> None:
        self._opened = False
        self._closed = False
        self._commits = 0
        self._rollbacks = 0
        self._rows: List[Dict[str, Any]] = rows if rows is not None else []
        self._executed: List[tuple] = []

    @property
    def rows(self) -> List[Dict[str, Any]]:
        return self._rows

    def connect(self) -> None:
        self._opened = True

    def close(self) -> None:
        self._closed = True
        self._opened = False

    def execute(self, query: str, parameters: Any = None) -> Any:
        self._executed.append((query, parameters))
        if "INSERT" in (query or "").upper():
            self._rows.append({"id": len(self._rows) + 1, "value": parameters[0] if parameters else None})
        if "FAIL" in (query or "").upper():
            raise RuntimeError("boom:" + query)
        return {"affected": 1, "first": (self._rows[0] if self._rows else None)}

    def executemany(self, query: str, parameters: Iterable[Any]) -> Any:
        count = 0
        for params in parameters:
            self._rows.append({"id": len(self._rows) + 1, "value": params[0] if params else None})
            count += 1
        return {"affected": count}

    def commit(self) -> None:
        self._commits += 1

    def rollback(self) -> None:
        self._rollbacks += 1

    def cursor(self) -> Any:
        return list(self._rows)


class FakeEngine(DatabaseEngine):
    """In-memory engine: everyone can use it, always works."""

    driver_name = "fake"

    def __init__(
        self, name: str = "default", config: Optional[Dict[str, Any]] = None, **options: Any
    ) -> None:
        self._name = name
        self._config = config or {}
        self._options = options
        self._dialect = FakeDialect()
        self._closed = False

    @property
    def name(self) -> str:
        return self._name

    def connect(self, name: Optional[str] = None, **options: Any) -> Connection:
        if self._closed:
            raise ConnectionError(
                message="Engine is closed",
                stage="connect",
                driver=self.driver_name,
                database=self._name,
            )
        return FakeConnection()

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
        return {
            "type": "engine",
            "driver": self.driver_name,
            "database": self._name,
            "capabilities": ["connect", "transaction", "dialect"],
        }


# ---------------------------------------------------------------------------
# Engine contract
# ---------------------------------------------------------------------------


def test_engine_lifecycle_connect_and_close():
    engine = FakeEngine("default")
    conn = engine.connect()
    assert isinstance(conn, Connection)
    conn.connect()
    conn.close()
    engine.close()
    assert engine._closed


def test_engine_connect_after_close_raises_connection_error():
    engine = FakeEngine("default")
    engine.close()
    with pytest.raises(ConnectionError):
        engine.connect()


def test_engine_dialect_available():
    engine = FakeEngine("default")
    dialect = engine.dialect()
    assert isinstance(dialect, SQLDialect)
    assert dialect.quote_identifier("users") == '"users"'
    assert dialect.placeholder() == "?"
    assert dialect.boolean_value(True) == "1"
    assert dialect.auto_increment()
    assert dialect.type_name(int) == "INTEGER"


def test_engine_transaction_interface_exists():
    engine = FakeEngine("default")
    cm = engine.transaction()
    with pytest.raises(TypeError):
        # not callable as a function, must be a context manager
        cm()


def test_engine_metadata_structured():
    engine = FakeEngine("default")
    meta = engine.metadata()
    assert meta["driver"] == "fake"
    assert "capabilities" in meta
    info = engine.introspect()
    assert info["dialect"]["name"] == "fake"


# ---------------------------------------------------------------------------
# Connection contract
# ---------------------------------------------------------------------------


def test_connection_execute_and_result():
    conn = FakeConnection()
    result = conn.execute("SELECT 1", [1])
    assert result["affected"] == 1
    assert conn._executed == [("SELECT 1", [1])]


def test_connection_executemany():
    conn = FakeConnection()
    result = conn.executemany("INSERT INTO t VALUES (?)", [[1], [2], [3]])
    assert result["affected"] == 3
    assert len(conn.rows) == 3


def test_connection_cursor():
    conn = FakeConnection([{"v": 1}, {"v": 2}])
    assert conn.cursor() == [{"v": 1}, {"v": 2}]


def test_connection_commit_and_rollback():
    conn = FakeConnection()
    conn.commit()
    conn.rollback()
    conn.close()
    assert conn._commits == 1
    assert conn._rollbacks == 1
    assert conn._closed


# ---------------------------------------------------------------------------
# Transaction contract
# ---------------------------------------------------------------------------


def test_transaction_commit_on_success():
    engine = FakeEngine("default")
    connection = engine.connect()
    with engine.transaction(connection=connection):
        connection.execute("INSERT INTO t VALUES (?)", [1])
    assert connection._commits == 1
    assert connection._rollbacks == 0


def test_transaction_rollback_and_reraise_on_failure():
    engine = FakeEngine("default")
    connection = engine.connect()
    with pytest.raises(RuntimeError, match="boom"):
        with engine.transaction(connection=connection):
            connection.execute("INSERT FAIL", [1])
    assert connection._rollbacks == 1
    assert connection._commits == 0


def test_transaction_states():
    engine = FakeEngine("default")
    connection = engine.connect()
    txn = engine.transaction(connection=connection)
    txn.__enter__()
    assert txn.is_active
    txn.commit()
    assert not txn.is_active


def test_transaction_commit_in_wrong_state_raises():
    engine = FakeEngine("default")
    connection = engine.connect()
    txn = engine.transaction(connection=connection)
    with pytest.raises(TransactionError):
        txn.commit()  # not entered


# ---------------------------------------------------------------------------
# DatabaseManager (backward-compatible wrapper)
# ---------------------------------------------------------------------------


def test_manager_preserves_engine_and_connection():
    engine = FakeEngine("default")
    mgr = DatabaseManager(engine)
    assert mgr.engine is engine
    mgr.connect()
    assert mgr.is_connected
    assert isinstance(mgr.connection, Connection)
    mgr.disconnect()
    assert not mgr.is_connected


def test_manager_execute_uses_connection():
    engine = FakeEngine("default")
    mgr = DatabaseManager(engine)
    mgr.connect()
    result = mgr.execute("SELECT 1", [1])
    assert result["affected"] == 1
    mgr.close()


def test_manager_execute_without_connection_raises():
    mgr = DatabaseManager(FakeEngine("default"))
    with pytest.raises(ConnectionError):
        mgr.execute("SELECT 1")


def test_manager_transaction_uses_manager_connection():
    engine = FakeEngine("default")
    mgr = DatabaseManager(engine)
    mgr.connect()
    with mgr.transaction():
        mgr.execute("INSERT INTO t VALUES (?)", [1])
    assert mgr.connection._commits == 1
    mgr.disconnect()


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def _config(**connections) -> Config:
    flat = {}
    for name, block in connections.items():
        for key, value in block.items():
            flat[f"database.{name}.{key}"] = value
    return Config(flat)


def test_registry_register_and_retrieve():
    registry = DatabaseRegistry(_config(default={"driver": "fake"}))
    registry.register_engine("fake", FakeEngine)
    engine = registry.engine("default")
    assert isinstance(engine, FakeEngine)
    assert engine.name == "default"


def test_registry_multiple_connections():
    registry = DatabaseRegistry(
        _config(
            default={"driver": "fake", "database": "main"},
            analytics={"driver": "fake", "database": "analytics"},
            storage={"driver": "fake", "database": "storage"},
        )
    )
    registry.register_engine("fake", FakeEngine)
    assert isinstance(registry.engine("default"), FakeEngine)
    assert isinstance(registry.engine("analytics"), FakeEngine)
    assert registry.engine("storage").name == "storage"
    assert registry.names() == ["analytics", "default", "storage"]


def test_registry_unknown_connection_raises_configuration_error():
    registry = DatabaseRegistry(_config(default={"driver": "fake"}))
    registry.register_engine("fake", FakeEngine)
    with pytest.raises(DatabaseConfigurationError):
        registry.engine("missing")


def test_registry_registered_driver_lookup():
    registry = DatabaseRegistry(_config(default={"driver": "fake"}))
    registry.register_engine("fake", FakeEngine)
    assert "fake" in registry.registered_drivers()


def test_registry_duplicate_registration_replaces_ok():
    registry = DatabaseRegistry(_config(default={"driver": "fake"}))
    registry.register_engine("fake", FakeEngine)
    registry.register_engine("fake", FakeEngine)  # idempotent replace
    assert "fake" in registry.registered_drivers()


def test_registry_unknown_driver_raises():
    registry = DatabaseRegistry(_config(default={"driver": "missing-driver"}))
    registry.register_engine("fake", FakeEngine)
    with pytest.raises(UnsupportedDatabaseError):
        registry.engine("default")


def test_registry_config_without_driver_raises():
    registry = DatabaseRegistry(_config(default={"database": "x"}))
    registry.register_engine("fake", FakeEngine)
    with pytest.raises(DatabaseConfigurationError):
        registry.engine("default")


# ---------------------------------------------------------------------------
# Configuration integration
# ---------------------------------------------------------------------------


def test_config_loading_and_default_connection():
    registry = DatabaseRegistry(_config(default={"driver": "fake"}))
    registry.register_engine("fake", FakeEngine)
    assert registry.names() == ["default"]
    assert isinstance(registry.engine(), FakeEngine)  # default name


def test_config_invalid_block_raises():
    # "database.default" is a scalar -> not a mapping
    flat = {"database.default": "oops"}
    registry = DatabaseRegistry(Config(flat))
    registry.register_engine("fake", FakeEngine)
    with pytest.raises(DatabaseConfigurationError):
        registry.engine("default")


def test_config_secrets_never_in_introspection():
    flat = {
        "database.default.driver": "fake",
        "database.default.password": "super-secret",
        "database.default.api_key": "sk-123",
    }
    registry = DatabaseRegistry(Config(flat))
    registry.register_engine("fake", FakeEngine)
    info = registry.introspect()
    text = repr(info)
    assert "super-secret" not in text
    assert "sk-123" not in text
    raw = info["connections"]["default"]
    assert raw["driver"] == "fake"
    assert all(k not in raw for k in ("password", "api_key"))


# ---------------------------------------------------------------------------
# Extension point (fake engine through the Database API)
# ---------------------------------------------------------------------------


def test_extension_point_engine_used_without_core_knowledge():
    """Core Betrayer never inspects the concrete implementation."""
    registry = DatabaseRegistry(_config(default={"driver": "custom"}))
    registry.register_engine("custom", FakeEngine)  # the Custom Database Engine
    engine = registry.engine("default")
    assert isinstance(engine, FakeEngine)

    # full canonical flow
    conn = engine.connect()
    conn.execute("INSERT INTO t VALUES (?)", [42])
    assert conn.rows
    with engine.transaction(connection=conn):
        conn.execute("INSERT INTO t VALUES (?)", [43])
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Error contract
# ---------------------------------------------------------------------------


def test_error_preserves_original_cause():
    engine = FakeEngine("default")
    mgr = DatabaseManager(engine)
    mgr.connect()
    try:
        mgr.execute("SELECT FAIL", [1])
    except DatabaseError as exc:
        assert exc.cause is not None
        assert isinstance(exc.cause, RuntimeError)
    else:
        pytest.fail("expected DatabaseError")


def test_error_carries_driver_but_not_secret():
    flat = {
        "database.default.driver": "not-registered",
        "database.default.password": "supersecret",
    }
    registry = DatabaseRegistry(Config(flat))
    registry.register_engine("fake", FakeEngine)  # another driver registered
    try:
        registry.engine("default")
    except DatabaseError as exc:
        assert exc.driver if hasattr(exc, "driver") else True
        assert "supersecret" not in str(exc)
        assert "supersecret" not in repr(exc.to_dict())
        assert "supersecret" not in repr(exc.context)
    else:
        pytest.fail("expected DatabaseError")


def test_database_error_hierarchy():
    assert issubclass(ConnectionError, DatabaseError)
    assert issubclass(TransactionError, DatabaseError)
    assert issubclass(DatabaseConfigurationError, DatabaseError)
    assert issubclass(UnsupportedDatabaseError, DatabaseError)


# ---------------------------------------------------------------------------
# Introspection / LLM discoverability
# ---------------------------------------------------------------------------


def test_registry_introspect_structured():
    registry = DatabaseRegistry(
        _config(default={"driver": "fake"}, analytics={"driver": "fake"})
    )
    registry.register_engine("fake", FakeEngine)
    info = registry.introspect()
    assert info["type"] == "database_registry"
    assert set(info["connections"]) == {"analytics", "default"}
    assert "fake" in info["registered_drivers"]


def test_manager_introspect_structured():
    engine = FakeEngine("default")
    mgr = DatabaseManager(engine)
    info = mgr.introspect()
    assert info["type"] == "database_manager"
    assert info["connected"] is False
    assert info["dialect"]["name"] == "fake"


def test_dialect_introspect_structured():
    dialect = FakeDialect().introspect()
    assert dialect["type"] == "dialect"
    assert dialect["name"] == "fake"
    assert dialect["features"]["supports_transactions"] is True