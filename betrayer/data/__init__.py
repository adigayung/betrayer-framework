"""Betrayer Data Layer: database, model, repository, transaction, migration, cache, storage.

Dependency direction (enforced by convention)::

    core  <-  data  <-  runtime/application/web

Data Layer depends on **core** (Config, Container, Registry, Lifecycle, Events,
exceptions) but must **not** depend on runtime, application, bootstrap, cli,
or Flask/web layer.

Every public symbol is importable from ``betrayer.data`` for convenience:

.. code-block:: python

    from betrayer.data import Model, Field, Repository, Transaction
    from betrayer.data import DatabaseManager, MigrationRegistry
    from betrayer.data import CacheManager, MemoryCacheBackend
    from betrayer.data import StorageManager, LocalStorageBackend
    from betrayer.data import DataInspector
"""

from __future__ import annotations

from betrayer.data.cache import (
    CacheBackend,
    CacheManager,
    MemoryCacheBackend,
)
from betrayer.data.database import DatabaseEngine, DatabaseManager
from betrayer.data.exceptions import (
    CacheError,
    DatabaseError,
    DataError,
    MigrationError,
    ModelError,
    RepositoryError,
    StorageError,
    TransactionError,
)
from betrayer.data.inspector import DataInspector
from betrayer.data.migration import Migration, MigrationRegistry
from betrayer.data.models import Field, Model, ModelMeta
from betrayer.data.repository import FindSpec, Repository
from betrayer.data.storage import LocalStorageBackend, StorageBackend, StorageManager
from betrayer.data.transaction import Transaction, TransactionState

__all__ = [
    # database
    "DatabaseEngine",
    "DatabaseManager",
    # model
    "Model",
    "ModelMeta",
    "Field",
    # repository
    "Repository",
    "FindSpec",
    # transaction
    "Transaction",
    "TransactionState",
    # migration
    "Migration",
    "MigrationRegistry",
    # cache
    "CacheBackend",
    "CacheManager",
    "MemoryCacheBackend",
    # storage
    "StorageBackend",
    "StorageManager",
    "LocalStorageBackend",
    # errors
    "DataError",
    "DatabaseError",
    "ModelError",
    "RepositoryError",
    "TransactionError",
    "MigrationError",
    "CacheError",
    "StorageError",
    # inspector
    "DataInspector",
]