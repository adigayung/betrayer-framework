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
    from betrayer.data import (
        DatabaseEngine,      # engine contract
        Connection,          # connection contract
        SQLDialect,          # dialect contract
        DatabaseRegistry,    # canonical engine registry
    )
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
from betrayer.data.compiler import CompiledQuery, QueryCompiler
from betrayer.data.database import (
    Connection,
    DatabaseEngine,
    DatabaseManager,
    SQLDialect,
)
from betrayer.data.exceptions import (
    CacheError,
    ConnectionError,
    DataError,
    DatabaseConfigurationError,
    DatabaseError,
    MigrationError,
    ModelError,
    QueryError,
    RepositoryError,
    StorageError,
    TransactionError,
    UnsupportedDatabaseError,
)
from betrayer.data.inspector import DataInspector
from betrayer.data.migration import (
    Migration,
    MigrationRegistry,
    create_table_sql,
    drop_table_sql,
)
from betrayer.data.bootstrap import (
    DATABASE_REGISTRY_SERVICE,
    DATABASE_SERVICE,
    build_database_manager,
    build_database_registry,
    install_database,
)
from betrayer.data.models import Field, Model, ModelMeta
from betrayer.data.orm import ORMField, ORMModel, ORMeta
from betrayer.data.query import Query, execute_compiled
from betrayer.data.relationships import (
    BelongsTo,
    BoundRelationship,
    HasMany,
    HasOne,
    ManyToMany,
    Relationship,
)
from betrayer.data.registry import DatabaseRegistry
from betrayer.data.repository import FindSpec, Repository
from betrayer.data.base_repository import BaseRepository
from betrayer.data.storage import LocalStorageBackend, StorageBackend, StorageManager
from betrayer.data.transaction import Transaction, TransactionState
from betrayer.data.value import ValueMapper

__all__ = [
    # database contracts
    "DatabaseEngine",
    "Connection",
    "SQLDialect",
    "DatabaseRegistry",
    # manager
    "DatabaseManager",
    # model
    "Model",
    "ModelMeta",
    "Field",
    # orm (Task 09.2)
    "ORMModel",
    "ORMField",
    "ORMeta",
    "Query",
    "QueryCompiler",
    "CompiledQuery",
    "ValueMapper",
    # relationships (Task 09.3)
    "Relationship",
    "BoundRelationship",
    "BelongsTo",
    "HasOne",
    "HasMany",
    "ManyToMany",
    # repository
    "BaseRepository",
    "Repository",
    "FindSpec",
    # transaction
    "Transaction",
    "TransactionState",
    # migration
    "Migration",
    "MigrationRegistry",
    "create_table_sql",
    "drop_table_sql",
    # bootstrap (wire the data layer into an application container)
    "DATABASE_SERVICE",
    "DATABASE_REGISTRY_SERVICE",
    "build_database_registry",
    "build_database_manager",
    "install_database",
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
    # inspector
    "DataInspector",
]