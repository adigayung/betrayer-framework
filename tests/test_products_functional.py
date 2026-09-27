"""Functional/API tests for Product Catalog: CRUD API over HTTP.

Test layer: functional
Dependencies: full application bootstrap, database, modules, Flask adapter.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from example.product_catalog.app import build_application, create_flask_app


# ── fixture: catalog application + Flask test client ─────────────


@pytest.fixture(scope="function")
def catalog_client(database_path: Path) -> Any:
    """A Flask test client for the full product catalog application."""
    app = build_application(database_path=database_path)
    flask_app = create_flask_app(app)
    return flask_app.test_client()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _json(response: Any) -> dict:
    return json.loads(response.get_data(as_text=True))


# ---------------------------------------------------------------------------
# CRUD API tests
# ---------------------------------------------------------------------------


class TestProductApi:
    """Functional: HTTP CRUD against a real SQLite backend."""

    def test_create_product(self, catalog_client: Any) -> None:
        resp = catalog_client.post(
            "/api/products",
            json={"name": "Created", "price": 1.99, "stock": 5},
        )
        assert resp.status_code == 201, _json(resp)
        body = _json(resp)
        assert body["success"] is True
        assert body["data"]["name"] == "Created"
        assert isinstance(body["data"]["id"], int)

    def test_list_products(self, catalog_client: Any) -> None:
        resp = catalog_client.get("/api/products")
        assert resp.status_code == 200
        body = _json(resp)
        assert body["success"] is True
        assert "meta" in body
        assert isinstance(body["meta"]["count"], int)

    def test_get_product_by_id(self, catalog_client: Any) -> None:
        created = catalog_client.post(
            "/api/products",
            json={"name": "Gettable", "price": 2.5, "stock": 10},
        )
        product_id = _json(created)["data"]["id"]

        resp = catalog_client.get(f"/api/products/{product_id}")
        assert resp.status_code == 200
        body = _json(resp)
        assert body["data"]["name"] == "Gettable"
        assert body["data"]["price"] == 2.5

    def test_get_product_not_found(self, catalog_client: Any) -> None:
        resp = catalog_client.get("/api/products/999999")
        assert resp.status_code == 404
        assert _json(resp)["error"]["code"] == "RESOURCE_NOT_FOUND"

    def test_update_product(self, catalog_client: Any) -> None:
        created = catalog_client.post(
            "/api/products",
            json={"name": "Updatable", "price": 3.0, "stock": 3},
        )
        product_id = _json(created)["data"]["id"]

        resp = catalog_client.put(
            f"/api/products/{product_id}",
            json={"price": 9.99, "stock": 0},
        )
        assert resp.status_code == 200
        body = _json(resp)
        assert body["data"]["price"] == 9.99
        assert body["data"]["stock"] == 0

    def test_delete_product(self, catalog_client: Any) -> None:
        created = catalog_client.post(
            "/api/products",
            json={"name": "Deletable", "price": 0.5, "stock": 1},
        )
        product_id = _json(created)["data"]["id"]

        resp = catalog_client.delete(f"/api/products/{product_id}")
        assert resp.status_code == 204

        get_resp = catalog_client.get(f"/api/products/{product_id}")
        assert get_resp.status_code == 404

    def test_validation_error_on_missing_name(self, catalog_client: Any) -> None:
        resp = catalog_client.post(
            "/api/products",
            json={"price": 1.0, "stock": 1},
        )
        assert resp.status_code == 422
        body = _json(resp)
        assert body["error"]["code"] == "VALIDATION_FAILED"

    def test_validation_error_on_invalid_body(self, catalog_client: Any) -> None:
        resp = catalog_client.post(
            "/api/products",
            data="not json",
            content_type="text/plain",
        )
        assert resp.status_code == 400
        assert _json(resp)["error"]["code"] == "BAD_REQUEST"

    def test_crud_lifecycle(self, catalog_client: Any) -> None:
        """Full CRUD lifecycle in one flow."""
        # Create
        created = catalog_client.post(
            "/api/products",
            json={"name": "Lifecycle", "price": 5.0, "stock": 2},
        )
        product_id = _json(created)["data"]["id"]

        # List
        listing = catalog_client.get("/api/products")
        ids = [item["id"] for item in _json(listing).get("data", [])]
        assert product_id in ids

        # Update
        catalog_client.put(
            f"/api/products/{product_id}",
            json={"stock": 100},
        )
        updated = catalog_client.get(f"/api/products/{product_id}")
        assert _json(updated)["data"]["stock"] == 100

        # Delete
        catalog_client.delete(f"/api/products/{product_id}")
        gone = catalog_client.get(f"/api/products/{product_id}")
        assert gone.status_code == 404