"""Data Layer exception hierarchy.

Extends the existing Betrayer exception pattern without adding duplicates.
"""

from __future__ import annotations

from betrayer.core.exceptions import BetrayerError


class DataError(BetrayerError):
    """Base for all Data Layer errors."""

    code = "DATA_ERROR"
    component = "data"


class DatabaseError(DataError):
    """Raised for connection failures, query errors and pool issues."""

    code = "DATABASE_ERROR"
    component = "database"


class ModelError(DataError):
    """Raised for invalid field definitions, serialisation or state."""

    code = "MODEL_ERROR"
    component = "model"


class RepositoryError(DataError):
    """Raised for data access failures inside a repository."""

    code = "REPOSITORY_ERROR"
    component = "repository"


class TransactionError(DataError):
    """Raised for transaction commit/rollback/state violations."""

    code = "TRANSACTION_ERROR"
    component = "transaction"


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
    "ModelError",
    "RepositoryError",
    "TransactionError",
    "MigrationError",
    "CacheError",
    "StorageError",
]