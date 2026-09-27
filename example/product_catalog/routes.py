"""HTTP resource for the catalog - the ``Resource/API`` step of the Golden Path.

It reuses the framework's shared :class:`~betrayer.web.resource.CrudApiResource`,
which declares the standard REST endpoints and delegates every operation to the
service resolved from the container (``products_service``).  No per-resource
copy of the CRUD flow is written.

Endpoints (paths are relative to ``prefix + name``)::

    GET    /api/products        -> list products
    GET    /api/products/<id>   -> one product (404 when missing)
    POST   /api/products        -> create a product (201, 422 when invalid)
    PUT    /api/products/<id>   -> update a product (404 when missing)
    DELETE /api/products/<id>   -> delete a product (204, 404 when missing)
"""

from __future__ import annotations

from betrayer.web import CrudApiResource

from example.product_catalog.schemas import ProductSchema

__all__ = ["ProductResource"]


class ProductResource(CrudApiResource):
    """REST CRUD resource for the product catalog.

    ``schema`` turns on the canonical validation pipeline: ``POST`` validates
    the whole body and ``PUT`` validates the partial body, both against
    :class:`~example.product_catalog.schemas.ProductSchema`, before the service
    is resolved/called.  An invalid body becomes a ``422 VALIDATION_FAILED``
    response with structured ``error.details.fields``.
    """

    name = "products"
    prefix = "/api"
    schema = ProductSchema()
