"""``ProductService`` - the ``Service`` step of the Golden Path.

The service sits between the HTTP resource and the repository: the resource
stays thin, the repository stays a data-access object, and the business rules
(write atomicity) live here.

Request validation is **not** repeated here: the Resource/API layer runs the
canonical validation pipeline (``ProductSchema``) before calling the service,
so by the time ``create``/``update`` run the payload is already clean and
typed (see :mod:`betrayer.web.validation`).

* reads delegate straight to the repository;
* writes run inside one framework ``Transaction`` (``database.transaction()``),
  so a request either commits its change to the database or rolls it back.

The service is registered on the container under ``products_service`` and
resolved by the resource through ``WebContext`` (dependency injection through
the existing container).
"""

from __future__ import annotations

from typing import Any, Optional, Sequence

from example.product_catalog.repository import ProductRepository

__all__ = ["ProductService"]


def as_identifier(value: Any) -> Optional[int]:
    """Coerce a path parameter into a primary-key integer (or ``None``)."""
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class ProductService:
    """Business service for the product catalog."""

    name = "products_service"

    def __init__(self, repository: ProductRepository, database: Any) -> None:
        self._repository = repository
        self._database = database

    @property
    def repository(self) -> ProductRepository:
        """The underlying repository (exposed for testing/inspection)."""
        return self._repository

    # -- reads ---------------------------------------------------------

    def list(self) -> Sequence[Any]:
        """Return every product."""
        return self._repository.all()

    def get(self, identifier: Any) -> Optional[Any]:
        """Return one product by id, or ``None`` when it does not exist."""
        product_id = as_identifier(identifier)
        if product_id is None:
            return None
        return self._repository.find(product_id)

    # -- writes (single transaction per operation) ---------------------

    def create(self, **data: Any) -> Any:
        """Create a product, committing the insert.

        ``data`` is the already-validated payload produced by
        ``ProductSchema``; no basic request validation happens here.
        """
        with self._database.transaction():
            return self._repository.create(data)

    def update(self, identifier: Any, **data: Any) -> Optional[Any]:
        """Update a product; returns the updated product or ``None``.

        ``data`` is the validated partial payload (an update may touch a
        single field).
        """
        product_id = as_identifier(identifier)
        if product_id is None or self._repository.find(product_id) is None:
            return None
        if data:
            with self._database.transaction():
                self._repository.update(product_id, data)
        return self._repository.find(product_id)

    def delete(self, identifier: Any) -> bool:
        """Delete a product; returns ``True`` when a row was removed."""
        product_id = as_identifier(identifier)
        if product_id is None:
            return False
        with self._database.transaction():
            affected = self._repository.delete(product_id)
        return bool(affected)
