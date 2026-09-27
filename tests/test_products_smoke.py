"""Smoke test for Product Catalog: full application bootstrap + CRUD + persistence.

Test layer: smoke
Verifies the entire stack boots and serves a request end-to-end.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from example.product_catalog.app import build_application, create_flask_app

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class TestProductCatalogSmoke:
    """Smoke: full bootstrap, one CRUD cycle, persistence verified."""

    def test_catalog_smoke(self, tmp_path: Path) -> None:
        """Boot the full catalog, create and retrieve one product."""
        db_path = tmp_path / "smoke.db"
        app = build_application(database_path=db_path)
        flask_app = create_flask_app(app)
        client = flask_app.test_client()

        # Create
        created = client.post(
            "/api/products",
            json={"name": "SmokeTest", "price": 1.0, "stock": 1},
        )
        assert created.status_code == 201
        body = json.loads(created.get_data(as_text=True))
        product_id = body["data"]["id"]
        assert body["success"] is True

        # Retrieve
        retrieved = client.get(f"/api/products/{product_id}")
        assert retrieved.status_code == 200
        body = json.loads(retrieved.get_data(as_text=True))
        assert body["data"]["name"] == "SmokeTest"

        # Persistence verified (new connection reads the same data)
        from betrayer.core.config import Config
        from betrayer.data.bootstrap import build_database_manager
        from betrayer.data.query import Query

        checker = build_database_manager(
            Config(
                {
                    "database.default.driver": "sqlite",
                    "database.default.database": str(db_path),
                }
            )
        )
        try:
            rows = Query("products", database=checker).get()
            assert len(rows) == 1
            assert rows[0]["name"] == "SmokeTest"
        finally:
            checker.disconnect()

    def test_framework_smoke(self) -> None:
        """The foundation smoke test still passes (cold start → stopped)."""
        from tests.smoke_test import _run_smoke

        result = _run_smoke()
        expected = ["bootstrap", "initialize", "ready", "start", "stop", "shutdown"]
        assert result["events"] == expected
        assert result["state"] == "stopped"