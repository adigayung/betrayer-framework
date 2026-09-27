"""Database Registry: canonical, instance scoped, engine-agnostic.

The registry stores named database engines and resolves them from the
existing Betrayer configuration system.  This is the single registry for
database engines; database names are scoped per instance, so an application
can host ``default``, ``analytics`` and ``storage`` connections at the same
time without global mutable state.

Design rules (Task 09.1):

* No global mutable state - a registry belongs to one application.
* Engines are resolved by looking up ``DATABASE.<name>.driver`` in the
  existing :class:`~betrayer.core.config.Config`; the driver value is an
  **implementation identifier**, never a hardcoded reference to a specific
  database.
* Concrete engines are registered through the extension point
  (``register_engine``); the core never hardcodes ``sqlite``/``postgres``/...
* Credentials in configuration are never copied into errors or metadata.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from betrayer.core.config import Config
from betrayer.data.database import DatabaseEngine
from betrayer.data.exceptions import (
    DatabaseConfigurationError,
    UnsupportedDatabaseError,
)

__all__ = [
    "DatabaseRegistry",
    "DEFAULT_CONNECTION",
    "DATABASE_CONFIG_PREFIX",
    "DRIVER_KEY",
]

#: Default connection name when none is specified.
DEFAULT_CONNECTION = "default"

#: Configuration prefix for the whole database section.
DATABASE_CONFIG_PREFIX = "database"

#: Configuration key holding the driver identifier under a connection.
DRIVER_KEY = "driver"


class DatabaseRegistry:
    """Stores and resolves named database engines.

    Usage::

        registry = DatabaseRegistry(config)
        registry.register_engine("custom", CustomDatabaseEngine)
        engine = registry.engine("default")   # resolves driver from config
        engine = registry.get("default")      # same lookup
        registry.names()                      # ["analytics", "default", "storage"]
    """

    def __init__(self, config: Optional[Config] = None) -> None:
        self._config = config
        # name -> engine class
        self._engines: Dict[str, type] = {}

    # ── Configuration ────────────────────────────────────────────────────

    @property
    def config(self) -> Optional[Config]:
        """The configuration source used to resolve connections."""
        return self._config

    def set_config(self, config: Config) -> None:
        """Attach/refresh the configuration source for this registry."""
        self._config = config

    def _connection_config(self, name: str) -> Dict[str, Any]:
        """Return the raw configuration block for ``name`` (never secrets).

        The existing ``Config`` flattens nested mappings to dotted keys, so
        ``DATABASE.default.driver`` is stored as the key
        ``database.default.driver``.  This method re-assembles the block from
        every key prefixed with ``database.<name>.``.
        """
        if self._config is None:
            raise DatabaseConfigurationError(
                message="No configuration attached to the database registry",
                stage="resolve",
                context={"database": name},
            )
        prefix = f"{DATABASE_CONFIG_PREFIX}.{name}"
        subprefix = f"{prefix}."
        # A scalar at ``database.<name>`` means the block is not a mapping.
        direct = self._config.get(prefix)
        if direct is not None and not isinstance(direct, dict):
            raise DatabaseConfigurationError(
                message=f"Database configuration for {name!r} must be a mapping",
                stage="resolve",
                context={"database": name},
            )
        block: Dict[str, Any] = {}
        found = False
        for key in self._config.keys():
            if key.startswith(subprefix):
                found = True
                block[key[len(subprefix):]] = self._config.get(key)
        if not found:
            if direct is None:
                raise DatabaseConfigurationError(
                    message=f"No database configuration found for {name!r}",
                    stage="resolve",
                    context={
                        "database": name,
                        "available": self.configured_names(),
                    },
                )
            block = dict(direct)
        return block

    def configured_names(self) -> list[str]:
        """Sorted names of connections present in the configuration."""
        if self._config is None:
            return []
        prefix = f"{DATABASE_CONFIG_PREFIX}."
        names: set[str] = set()
        for key in self._config.keys():
            if key.startswith(prefix):
                rest = key[len(prefix):]
                first = rest.split(".", 1)[0]
                if first:
                    names.add(first)
        return sorted(names)

    # ── Engine extension point ───────────────────────────────────────────

    def register_engine(self, driver: str, engine_cls: type) -> None:
        """Register a concrete engine implementation for ``driver``.

        ``driver`` is the implementation identifier used in configuration
        (``DATABASE.<name>.driver``).  The core never inspects the concrete
        engine: it only has to satisfy the :class:`DatabaseEngine` contract.

        Re-registering a driver replaces the previous registration (idempotent
        by design - an application owns its registry instance).
        """
        if not isinstance(driver, str) or not driver.strip():
            raise DatabaseConfigurationError(
                message="Driver name must be a non-empty string",
                stage="register",
            )
        if not (isinstance(engine_cls, type)) and not callable(engine_cls):
            raise DatabaseConfigurationError(
                message=f"Engine for {driver!r} must be a class or factory",
                stage="register",
                context={"driver": driver},
            )
        self._engines[driver.strip()] = engine_cls

    # Backward compatible alias (registry-style wording).
    register = register_engine

    def unregister_engine(self, driver: str) -> None:
        """Remove a registered engine implementation (returns ``None``)."""
        self._engines.pop(driver, None)

    def registered_drivers(self) -> list[str]:
        """Sorted list of registered driver identifiers."""
        return sorted(self._engines)

    # ── Engine resolution ───────────────────────────────────────────────

    def engine(self, name: str = DEFAULT_CONNECTION, **options: Any) -> DatabaseEngine:
        """Resolve and build the engine for the named connection.

        Lookup path:

            Configuration -> registry -> registered implementation

        Raises ``DatabaseConfigurationError`` for missing/invalid
        configuration and ``UnsupportedDatabaseError`` when the configured
        driver is not registered.
        """
        block = self._connection_config(name)
        driver = block.get(DRIVER_KEY)
        if driver is None:
            raise DatabaseConfigurationError(
                message=f"Database configuration for {name!r} has no {DRIVER_KEY!r}",
                stage="resolve",
                context={"database": name},
            )
        engine_cls = self._engines.get(str(driver))
        if engine_cls is None:
            raise UnsupportedDatabaseError(
                message=(
                    f"Driver {driver!r} is not registered; "
                    f"register it via Database.register_engine(...)"
                ),
                stage="resolve",
                context={
                    "database": name,
                    "driver": str(driver),
                    "registered": self.registered_drivers(),
                },
            )
        try:
            engine = engine_cls(name=name, config=block, **options)
        except TypeError:
            # Driver factory with a different signature: give it a chance.
            engine = engine_cls(**block, **options)
        if not hasattr(engine, "connect") or not hasattr(engine, "dialect"):
            raise UnsupportedDatabaseError(
                message=f"Registered driver {driver!r} does not implement the "
                        "DatabaseEngine contract",
                stage="resolve",
                context={"database": name, "driver": str(driver)},
            )
        return engine

    # Alias: ``get`` mirrors the conceptual ``Database.engine(name)``.
    get = engine
    resolve = engine

    # ── Introspection ────────────────────────────────────────────────────

    def has(self, name: str) -> bool:
        """True when the named connection has configuration + registered driver."""
        try:
            block = self._connection_config(name)
        except DatabaseConfigurationError:
            return False
        return str(block.get(DRIVER_KEY)) in self._engines

    def names(self) -> list[str]:
        """Sorted connection names available in the configuration."""
        return self.configured_names()

    def introspect(self) -> Dict[str, Any]:
        """Machine readable metadata for LLM inspection (secrets never leak)."""
        connections: Dict[str, Any] = {}
        for name in self.configured_names():
            try:
                block = self._connection_config(name)
            except DatabaseConfigurationError:
                continue
            driver = block.get(DRIVER_KEY)
            connections[name] = {
                "name": name,
                "driver": str(driver) if driver is not None else None,
                "registered": str(driver) in self._engines,
            }
        return {
            "type": "database_registry",
            "connections": connections,
            "registered_drivers": self.registered_drivers(),
            "config_attached": self._config is not None,
        }

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"DatabaseRegistry(names={self.names()!r}, "
            f"drivers={self.registered_drivers()!r})"
        )