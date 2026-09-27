"""Concrete database engine adapters (Stage 09.4).

The core (``betrayer.data.database``) defines *contracts* and never picks a
database.  Concrete engines live here, outside the core, and are wired in
through the existing extension point
(``DatabaseRegistry.register_engine``).  Nothing in the ORM, the Query Builder
or the Repository layer knows that SQLite or DuckDB exist.

Two adapters ship in the box:

==============================  ===============  =====================================
 adapter                        driver id        dependency
==============================  ===============  =====================================
 :class:`~.sqlite.SQLiteEngine`    ``"sqlite"``   standard library ``sqlite3`` (always)
 :class:`~.duckdb.DuckDBEngine`    ``"duckdb"``   optional ``duckdb`` package (lazy)
==============================  ===============  =====================================

The DuckDB driver is *optional*: it is imported lazily inside the adapter, so
``betrayer.data.engines`` imports cleanly even when ``duckdb`` is not
installed (``DuckDBConnection.connect`` raises a structured
``UnsupportedDatabaseError`` instead).

Canonical usage (identical for every adapter)::

    from betrayer.core.config import Config
    from betrayer.data import DatabaseRegistry, DatabaseManager
    from betrayer.data.engines import register_builtin_engines

    config = Config({
        "database.default.driver": "sqlite",
        "database.default.database": "app.db",
        "database.analytics.driver": "duckdb",
        "database.analytics.database": ":memory:",
    })
    registry = DatabaseRegistry(config)
    register_builtin_engines(registry)          # extension point

    engine = registry.engine("default")         # SQLiteEngine
    manager = DatabaseManager(engine)
    manager.connect()
"""

from __future__ import annotations

from typing import Any, Dict

from betrayer.data.engines.duckdb import (
    DuckDBConnection,
    DuckDBDialect,
    DuckDBEngine,
    DuckDBTransaction,
    duckdb_available,
)
from betrayer.data.engines.sqlite import (
    SQLiteConnection,
    SQLiteDialect,
    SQLiteEngine,
)

__all__ = [
    # sqlite
    "SQLiteEngine",
    "SQLiteConnection",
    "SQLiteDialect",
    # duckdb
    "DuckDBEngine",
    "DuckDBConnection",
    "DuckDBDialect",
    "DuckDBTransaction",
    "duckdb_available",
    # registration
    "BUILTIN_ENGINES",
    "register_builtin_engines",
]

#: Driver id -> concrete :class:`~betrayer.data.database.DatabaseEngine` class.
BUILTIN_ENGINES: Dict[str, type] = {
    "sqlite": SQLiteEngine,
    "duckdb": DuckDBEngine,
}


def register_builtin_engines(registry: Any) -> Any:
    """Register every built-in concrete engine on ``registry``.

    This is the *only* place the framework connects a driver id to a concrete
    class.  Applications may register additional engines through the same
    extension point (``registry.register_engine(driver, cls)``).
    """
    for driver, engine_cls in BUILTIN_ENGINES.items():
        registry.register_engine(driver, engine_cls)
    return registry
