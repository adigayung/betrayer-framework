"""Data Layer bootstrap: bind the existing database stack to an application.

This module adds **no new database abstraction**.  It is the single, documented
seam between the Data Layer (``DatabaseRegistry`` + concrete engines +
``DatabaseManager`` from Stages 09.1-09.4) and the application container
(Task 02), so an application goes from configuration to a connected,
container-resolvable database in one call instead of repeating the same manual
wiring in every entry point::

    from betrayer import BetrayerApplication, Bootstrap, Config
    from betrayer.data.bootstrap import install_database

    app = BetrayerApplication(name="catalog", config=Config({
        "database.default.driver": "sqlite",
        "database.default.database": "catalog.db",
    }))
    Bootstrap(app).build()

    manager = install_database(app)              # container service "database"
    assert app.container.resolve("database") is manager

``database`` is the canonical service key: generated resource / CRUD modules
resolve ``context.container.resolve("database")`` for their repository, and the
ORM binds its connection with ``Model.__connection__ =
container.resolve("database")``.

Only *composition* happens here - engine registration and resolution keep using
the existing :class:`~betrayer.data.registry.DatabaseRegistry` extension point.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from betrayer.core.config import Config
from betrayer.data.database import DatabaseManager
from betrayer.data.engines import register_builtin_engines
from betrayer.data.registry import DEFAULT_CONNECTION, DatabaseRegistry

__all__ = [
    "DATABASE_SERVICE",
    "DATABASE_REGISTRY_SERVICE",
    "build_database_registry",
    "build_database_manager",
    "install_database",
]

#: Canonical container key for the connected :class:`DatabaseManager`.
DATABASE_SERVICE = "database"

#: Canonical container key for the :class:`DatabaseRegistry` (introspection).
DATABASE_REGISTRY_SERVICE = "database.registry"


def build_database_registry(
    config: Config,
    *,
    engines: Optional[Mapping[str, type]] = None,
) -> DatabaseRegistry:
    """Return a registry with the built-in engines (``sqlite``, ``duckdb``).

    Additional engines (``{driver_id: engine_class}``) are registered through
    the same :meth:`DatabaseRegistry.register_engine` extension point.
    """
    registry = DatabaseRegistry(config)
    register_builtin_engines(registry)
    for driver, engine_cls in (engines or {}).items():
        registry.register_engine(driver, engine_cls)
    return registry


def build_database_manager(
    config: Config,
    name: str = DEFAULT_CONNECTION,
    *,
    registry: Optional[DatabaseRegistry] = None,
    connect: bool = True,
    **options: Any,
) -> DatabaseManager:
    """Resolve connection ``name`` from ``config`` and return a manager.

    ``connect=False`` builds the manager without opening the connection (useful
    when a caller wants to connect explicitly later).
    """
    registry = registry or build_database_registry(config)
    manager = DatabaseManager(registry.engine(name, **options))
    if connect:
        manager.connect()
    return manager


def install_database(
    application: Any,
    *,
    name: str = DEFAULT_CONNECTION,
    config: Optional[Config] = None,
    connect: bool = True,
    replace: bool = True,
    **options: Any,
) -> DatabaseManager:
    """Wire a connected database into ``application``'s container.

    The connected :class:`DatabaseManager` is registered under ``"database"``
    and the :class:`DatabaseRegistry` under ``"database.registry"``, so routes
    and modules resolve the database through ``WebContext`` / ``context``.
    Returns the manager.

    Idempotent: re-installing replaces the previous services (``replace=True``
    by default), so calling it twice never raises a duplicate-service error.
    """
    source = config if config is not None else application.config
    registry = build_database_registry(source)
    manager = build_database_manager(
        source, name, registry=registry, connect=connect, **options
    )
    container = application.container
    container.instance(DATABASE_SERVICE, manager, replace=replace)
    container.instance(DATABASE_REGISTRY_SERVICE, registry, replace=replace)
    return manager
