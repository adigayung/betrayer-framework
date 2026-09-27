"""The ``Product`` ORM model (the ``Model`` step of the Golden Path).

A single, canonical ORM model - the same ``ORMModel`` / ``ORMField`` API every
Betrayer application uses.  The table name, primary key and columns are declared
declaratively, so the migration, repository and query builder derive everything
from this one source of truth.

Fields: ``id``, ``name``, ``price``, ``stock``.
"""

from __future__ import annotations

from betrayer.data import ORMField, ORMModel

__all__ = ["Product"]


class Product(ORMModel):
    """A product in the catalog."""

    __table__ = "products"

    id = ORMField(int, primary_key=True, description="Primary key")
    name = ORMField(str, required=True, nullable=False, description="Product name")
    price = ORMField(float, default=0.0, nullable=False, description="Unit price")
    stock = ORMField(int, default=0, nullable=False, description="Units in stock")
