"""``ProductSchema`` - the canonical request validation schema of the catalog.

Declared once with the framework :class:`~betrayer.web.validation.Schema` API
and shared by the Resource/API layer: the resource validates every create /
update request against it *before* the service is called, so the service never
re-implements basic request validation.

Fields (mirrors :class:`~example.product_catalog.models.Product`)::

    name   str    required
    price  float  optional (default 0.0), must be >= 0
    stock  int    optional (default 0),   must be >= 0
"""

from __future__ import annotations

from betrayer.web import Field, Schema

__all__ = ["ProductSchema"]


class ProductSchema(Schema):
    """Request body contract for creating / updating a product."""

    name = Field(str, required=True, description="Product name")
    price = Field(float, default=0.0, min=0, description="Unit price")
    stock = Field(int, default=0, min=0, description="Units in stock")
