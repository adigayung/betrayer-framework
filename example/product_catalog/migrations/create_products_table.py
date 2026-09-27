"""``create_products_table`` migration - the ``Migration`` step of the Golden Path.

The DDL is derived from the ORM model and the connected dialect through
:func:`betrayer.data.create_table_sql`, so the migration is database-agnostic
and stays in sync with :class:`example.product_catalog.models.Product`.  It is
idempotent (``CREATE TABLE IF NOT EXISTS``), so applying it twice is safe.
"""

from __future__ import annotations

from betrayer.data import DatabaseManager
from betrayer.data.migration import Migration, create_table_sql, drop_table_sql

from example.product_catalog.models import Product

__all__ = ["CreateProductsTableMigration"]


class CreateProductsTableMigration(Migration):
    """Create the ``products`` table."""

    name = "create_products_table"
    sequence = 1
    description = "create the products table"

    def __init__(self) -> None:
        super().__init__(
            name=self.name,
            sequence=self.sequence,
            description=self.description,
        )

    def up(self, database: DatabaseManager) -> None:
        """Create the ``products`` table from the Product model."""
        database.execute(create_table_sql(Product, database.dialect))

    def down(self, database: DatabaseManager) -> None:
        """Drop the ``products`` table."""
        database.execute(drop_table_sql(Product, database.dialect))
