"""Catalog module - the ``Module`` step of the Golden Path.

One :class:`~betrayer.core.module.Module` wires the whole vertical slice: it
binds the ORM model to the application database and registers the repository and
service on the container so the HTTP resource can resolve them.

Registration order in the application is fixed and canonical::

    install_database(app)                     # container service "database"
    app.modules.register(ProductCatalogModule) # repository + service
    app.modules.initialize_all()
"""

from __future__ import annotations

from typing import Any, Tuple

from betrayer.core.module import Module

from example.product_catalog.models import Product
from example.product_catalog.repository import ProductRepository
from example.product_catalog.service import ProductService

__all__ = ["ProductCatalogModule", "REPOSITORY_KEY", "SERVICE_KEY"]

#: Container keys the module registers (also the resource's service key).
REPOSITORY_KEY = "products_repository"
SERVICE_KEY = "products_service"

#: Canonical container key for the connected database (see ``betrayer.data``).
DATABASE_SERVICE = "database"


class ProductCatalogModule(Module):
    """Structural unit for the product catalog."""

    name = "product_catalog"
    version = "0.1.0"
    dependencies: Tuple[str, ...] = ()
    services: Tuple[str, ...] = (REPOSITORY_KEY, SERVICE_KEY)
    metadata = {
        "description": "the product catalog domain module",
        "model": "Product",
        "repository": "ProductRepository",
        "service": "ProductService",
    }

    def register(self, context: Any) -> None:
        """Bind the database, then register the repository and service."""
        container = context.container
        database = container.resolve(DATABASE_SERVICE)

        # The ORM model talks to the application database.
        Product.__connection__ = database

        container.singleton(
            REPOSITORY_KEY, lambda: ProductRepository(Product)
        )
        container.singleton(
            SERVICE_KEY,
            lambda: ProductService(container.resolve(REPOSITORY_KEY), database),
        )

    def initialize(self, context: Any) -> None:
        """No post-registration work is required for the catalog."""

    def shutdown(self, context: Any) -> None:
        """No resources to release for the catalog."""
