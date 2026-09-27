"""Migrations for the product catalog (the ``Migration`` step).

``MIGRATIONS`` is the ordered list the application registers on a
:class:`~betrayer.data.migration.MigrationRegistry` before applying them.
"""

from __future__ import annotations

from typing import Tuple

from betrayer.data.migration import Migration

from example.product_catalog.migrations.create_products_table import (
    CreateProductsTableMigration,
)

__all__ = ["CreateProductsTableMigration", "MIGRATIONS"]

#: Migrations in ``sequence`` order (the registry also sorts by sequence).
MIGRATIONS: Tuple[Migration, ...] = (CreateProductsTableMigration(),)
