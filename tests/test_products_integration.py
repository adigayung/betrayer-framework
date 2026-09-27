"""Integration tests for Product Catalog: repository + ORM + SQLite.

Test layer: integration
Dependencies: real SQLite database, ORM, repository, migrations.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from betrayer.core.config import Config
from betrayer.data import BaseRepository
from betrayer.data.bootstrap import build_database_manager
from betrayer.data.migration import create_table_sql

from example.product_catalog.models import Product
from example.product_catalog.repository import ProductRepository


# ── fixture: temporary database with products table ──────────────


@pytest.fixture(scope="function")
def product_database(database_path: Path) -> Any:
    """A connected SQLite database with the products schema applied."""
    config = Config(
        {
            "database.default.driver": "sqlite",
            "database.default.database": str(database_path),
        }
    )
    manager = build_database_manager(config)
    manager.execute(create_table_sql(Product, manager.dialect))
    Product.__connection__ = manager
    yield manager
    try:
        manager.disconnect()
    except Exception:  # noqa: BLE001
        pass


@pytest.fixture
def repository(product_database: Any) -> BaseRepository:
    """A ProductRepository bound to the test database."""
    return ProductRepository(Product)


# ── tests ────────────────────────────────────────────────────────


class TestProductRepository:
    """Integration: real SQLite, real ORM, real repository."""

    def test_create_and_find(self, repository: BaseRepository) -> None:
        created = repository.create({"name": "Widget", "price": 9.99, "stock": 10})
        assert created is not None
        assert created.name == "Widget"
        assert created.price == 9.99  # type: ignore[operator]
        product_id = created.id  # type: ignore[attr-defined]

        found = repository.find(product_id)
        assert found is not None
        assert found.name == "Widget"

    def test_all_returns_all(self, repository: BaseRepository) -> None:
        repository.create({"name": "A", "price": 1.0, "stock": 1})
        repository.create({"name": "B", "price": 2.0, "stock": 2})
        all_products = repository.all()
        assert len(all_products) >= 2
        names = [p.name for p in all_products]
        assert "A" in names
        assert "B" in names

    def test_update(self, repository: BaseRepository) -> None:
        created = repository.create({"name": "Updatable", "price": 5.0, "stock": 5})
        product_id = created.id  # type: ignore[attr-defined]

        affected = repository.update(product_id, {"price": 7.5, "stock": 3})
        assert affected == 1

        updated = repository.find(product_id)
        assert updated.price == 7.5  # type: ignore[operator]
        assert updated.stock == 3  # type: ignore[operator]

    def test_delete(self, repository: BaseRepository) -> None:
        created = repository.create({"name": "Deletable", "price": 1.0, "stock": 1})
        product_id = created.id  # type: ignore[attr-defined]

        affected = repository.delete(product_id)
        assert affected == 1
        assert repository.find(product_id) is None

    def test_count(self, repository: BaseRepository) -> None:
        before = repository.count()
        repository.create({"name": "Countable", "price": 1.0, "stock": 1})
        assert repository.count() == before + 1

    def test_exists(self, repository: BaseRepository) -> None:
        repository.create({"name": "Existable", "price": 1.0, "stock": 1})
        assert repository.exists(name="Existable") is True
        assert repository.exists(name="NonExistent") is False

    def test_find_or_fail(self, repository: BaseRepository) -> None:
        from betrayer.data.exceptions import RepositoryError

        with pytest.raises(RepositoryError):
            repository.find_or_fail(99999)