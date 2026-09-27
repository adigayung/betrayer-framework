"""``ProductRepository`` - the ``Repository`` step of the Golden Path.

It reuses the framework's canonical
:class:`~betrayer.data.base_repository.BaseRepository`, which already provides
``find`` / ``all`` / ``count`` / ``create`` / ``update`` / ``delete`` over the
ORM/Query Builder.  A resource repository therefore only declares the model it
manages; persistence comes from the framework, not from hand-written SQL.
"""

from __future__ import annotations

from betrayer.data import BaseRepository

from example.product_catalog.models import Product

__all__ = ["ProductRepository"]


class ProductRepository(BaseRepository[Product]):
    """CRUD repository for :class:`~example.product_catalog.models.Product`.

    Add resource-specific query methods here as needed; the CRUD surface and
    metadata contract stay identical to every other repository.
    """
