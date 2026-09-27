"""Data Layer exception hierarchy.

Extends the existing Betrayer exception pattern without adding duplicates.

Error contract rules (Task 09.1):
* every database error extends :class:`DatabaseError` (or a sibling below).
* ``cause`` preserves the original exception when available.
* ``context`` may carry ``operation``/``driver``/``database`` identifiers,
  but **never** passwords, API keys, credentials or secrets.
"""

from __future__ import annotations

from typing import Any, Optional

from betrayer.core.exceptions import BetrayerError


class DataError(BetrayerError):
    """Base for all Data Layer errors."""

    code = "DATA_ERROR"
    component = "data"


class DatabaseError(DataError):
    """Raised for connection failures, query errors and pool issues."""

    code = "DATABASE_ERROR"
    component = "database"

    def __init__(
        self,
        message: str = "",
        code: Optional[str] = None,
        component: Optional[str] = None,
        stage: Optional[str] = None,
        cause: Optional[BaseException] = None,
        context: Optional[dict] = None,
        operation: Optional[str] = None,
        driver: Optional[str] = None,
        database: Optional[str] = None,
    ) -> None:
        base_context = dict(context or {})
        if operation is not None:
            base_context.setdefault("operation", operation)
        if driver is not None:
            base_context.setdefault("driver", driver)
        if database is not None:
            base_context.setdefault("database", database)
        super().__init__(
            message=message,
            code=code,
            component=component,
            stage=stage,
            cause=cause,
            context=base_context,
        )


class ConnectionError(DatabaseError):
    """Raised when a connection cannot be opened or closed.

    ``driver``/``database`` context identifiers are allowed; credentials are
    never included.
    """

    code = "DATABASE_CONNECTION_ERROR"
    stage = "connect"


class TransactionError(DatabaseError):
    """Raised for transaction commit/rollback/state violations."""

    code = "DATABASE_TRANSACTION_ERROR"
    component = "transaction"


class DatabaseConfigurationError(DatabaseError):
    """Raised when the database configuration is invalid or incomplete."""

    code = "DATABASE_CONFIGURATION_ERROR"
    component = "config"


class UnsupportedDatabaseError(DatabaseError):
    """Raised when a driver cannot be resolved to a registered engine."""

    code = "DATABASE_UNSUPPORTED_ERROR"
    component = "database"


class ModelError(DataError):
    """Raised for invalid field definitions, serialisation or state."""

    code = "MODEL_ERROR"
    component = "model"


class QueryError(DataError):
    """Raised for invalid query construction, compilation or result handling.

    Covers Query Builder / SQL compiler problems (unknown operator, invalid
    identifier, update/delete without a where clause, unsupported result
    shape).  Execution failures are wrapped as ``DatabaseError`` (stage
    ``"execute"``) so the existing 09.1 error contract stays the single
    boundary for driver errors.
    """

    code = "QUERY_ERROR"
    component = "query"


class RepositoryError(DataError):
    """Raised for data access failures inside a repository."""

    code = "REPOSITORY_ERROR"
    component = "repository"


class MigrationError(DataError):
    """Raised when a migration is missing, out of order, or fails."""

    code = "MIGRATION_ERROR"
    component = "migration"


class CacheError(DataError):
    """Raised for cache backend failures."""

    code = "CACHE_ERROR"
    component = "cache"


class StorageError(DataError):
    """Raised for file storage backend failures."""

    code = "STORAGE_ERROR"
    component = "storage"


__all__ = [
    "DataError",
    "DatabaseError",
    "ConnectionError",
    "TransactionError",
    "DatabaseConfigurationError",
    "UnsupportedDatabaseError",
    "ModelError",
    "RepositoryError",
    "MigrationError",
    "CacheError",
    "StorageError",
    "QueryError",
]