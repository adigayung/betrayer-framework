"""Database abstraction: connection lifecycle integrated with Config and Container.

This module provides a *connection factory* pattern rather than a full ORM.
Applications register a connection provider (SQLite, PostgreSQL, etc.) and
the framework manages the lifecycle via ``DatabaseManager``.

Design decisions:
- ``DatabaseEngine`` is an abstract interface; concrete backends implement it.
- ``DatabaseManager`` owns engine lifecycle (connect/disconnect) and is
  registered in the Container + Registry for traceability.
- No global state: every manager belongs to an application context.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from betrayer.data.exceptions import DatabaseError


class DatabaseEngine(ABC):
    """Abstract database engine.

    Subclasses implement the actual connection/pool logic for a specific
    database (SQLite via sqlite3, PostgreSQL via psycopg2/asyncpg, etc.).
    """

    @abstractmethod
    def connect(self) -> Any:
        """Open or acquire a connection; return the connection object."""

    @abstractmethod
    def disconnect(self) -> None:
        """Close or release the connection."""

    @abstractmethod
    def execute(self, query: str, params: Any = None) -> Any:
        """Execute a raw query; return backend-specific result."""

    @abstractmethod
    def is_connected(self) -> bool:
        """Return True if the connection is active."""

    def __repr__(self) -> str:  # pragma: no cover
        return f"{type(self).__name__}()"


class DatabaseManager:
    """Lifecycle-aware wrapper around a DatabaseEngine.

    The manager is registered as a service so the Container can inject it
    into repositories, services, and other consumers.

    Usage::

        mgr = DatabaseManager(engine)
        mgr.connect()
        mgr.execute("SELECT 1")
        mgr.disconnect()
    """

    def __init__(self, engine: DatabaseEngine) -> None:
        self._engine = engine
        self._connected = False
        self._metadata: Dict[str, Any] = {}

    @property
    def engine(self) -> DatabaseEngine:
        return self._engine

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def metadata(self) -> Dict[str, Any]:
        return dict(self._metadata)

    def connect(self) -> None:
        """Open the connection; raises DatabaseError on failure."""
        try:
            self._engine.connect()
            self._connected = True
        except Exception as exc:
            raise DatabaseError(
                "Failed to connect to database",
                stage="connect",
                cause=exc,
            ) from exc

    def disconnect(self) -> None:
        """Close the connection; safe to call multiple times."""
        try:
            self._engine.disconnect()
        except Exception as exc:
            raise DatabaseError(
                "Error while disconnecting from database",
                stage="disconnect",
                cause=exc,
            ) from exc
        finally:
            self._connected = False

    def execute(self, query: str, params: Any = None) -> Any:
        """Execute a query through the engine."""
        if not self._connected:
            raise DatabaseError(
                "Database is not connected",
                stage="execute",
            )
        try:
            return self._engine.execute(query, params)
        except Exception as exc:
            raise DatabaseError(
                f"Query execution failed: {query[:80]}",
                stage="execute",
                cause=exc,
            ) from exc

    def introspect(self) -> Dict[str, Any]:
        """Return deterministic metadata for LLM inspection."""
        return {
            "engine": type(self._engine).__name__,
            "connected": self._connected,
            "metadata": self._metadata,
        }


__all__ = [
    "DatabaseEngine",
    "DatabaseManager",
]