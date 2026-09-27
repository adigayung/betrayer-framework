"""Unit tests for the Product Catalog service logic.

Test layer: unit
Dependencies: none (pure service logic, no database).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from example.product_catalog.service import ProductService, as_identifier


# ── as_identifier ────────────────────────────────────────────────


class TestAsIdentifier:
    def test_valid_int_string(self) -> None:
        assert as_identifier("42") == 42

    def test_valid_int(self) -> None:
        assert as_identifier(1) == 1

    def test_none_returns_none(self) -> None:
        assert as_identifier(None) is None

    def test_bool_returns_none(self) -> None:
        assert as_identifier(True) is None
        assert as_identifier(False) is None

    def test_invalid_string_returns_none(self) -> None:
        assert as_identifier("abc") is None

    def test_float_string_returns_int(self) -> None:
        assert as_identifier("3.14") is None


# ── ProductService ───────────────────────────────────────────────


@pytest.fixture
def mock_repository() -> MagicMock:
    return MagicMock()


@pytest.fixture
def mock_database() -> MagicMock:
    db = MagicMock()
    db.transaction.return_value.__enter__ = MagicMock(return_value=None)
    db.transaction.return_value.__exit__ = MagicMock(return_value=None)
    return db


@pytest.fixture
def service(mock_repository: MagicMock, mock_database: MagicMock) -> ProductService:
    return ProductService(mock_repository, mock_database)


class TestProductServiceList:
    def test_list_delegates_to_repository_all(
        self, service: ProductService, mock_repository: MagicMock
    ) -> None:
        mock_repository.all.return_value = ["p1", "p2"]
        result = service.list()
        assert result == ["p1", "p2"]
        mock_repository.all.assert_called_once_with()


class TestProductServiceGet:
    def test_get_by_id(self, service: ProductService, mock_repository: MagicMock) -> None:
        mock_repository.find.return_value = {"id": 1, "name": "Widget"}
        result = service.get("1")
        assert result == {"id": 1, "name": "Widget"}
        mock_repository.find.assert_called_once_with(1)

    def test_get_none_when_not_found(
        self, service: ProductService, mock_repository: MagicMock
    ) -> None:
        mock_repository.find.return_value = None
        result = service.get("999")
        assert result is None

    def test_get_invalid_id_returns_none(self, service: ProductService, mock_repository: MagicMock) -> None:
        result = service.get("not-a-number")
        assert result is None
        mock_repository.find.assert_not_called()


class TestProductServiceCreate:
    def test_create_delegates_to_repository(
        self, service: ProductService, mock_repository: MagicMock
    ) -> None:
        mock_repository.create.return_value = {"id": 1, "name": "New"}
        result = service.create(name="New", price=10.0, stock=5)
        assert result == {"id": 1, "name": "New"}
        mock_repository.create.assert_called_once_with({"name": "New", "price": 10.0, "stock": 5})


class TestProductServiceUpdate:
    def test_update_existing(
        self, service: ProductService, mock_repository: MagicMock
    ) -> None:
        mock_repository.find.return_value = {"id": 1}
        mock_repository.update.return_value = 1
        mock_repository.find.return_value = {"id": 1, "name": "Updated"}
        result = service.update(1, name="Updated")
        assert result == {"id": 1, "name": "Updated"}

    def test_update_non_existing_returns_none(
        self, service: ProductService, mock_repository: MagicMock
    ) -> None:
        mock_repository.find.return_value = None
        result = service.update(1, name="Ghost")
        assert result is None

    def test_update_no_data_returns_same(
        self, service: ProductService, mock_repository: MagicMock
    ) -> None:
        mock_repository.find.return_value = {"id": 1, "name": "Same"}
        result = service.update(1)
        assert result == {"id": 1, "name": "Same"}


class TestProductServiceDelete:
    def test_delete_existing(
        self, service: ProductService, mock_repository: MagicMock
    ) -> None:
        mock_repository.delete.return_value = 1
        result = service.delete(1)
        assert result is True

    def test_delete_non_existing(
        self, service: ProductService, mock_repository: MagicMock
    ) -> None:
        mock_repository.delete.return_value = 0
        result = service.delete(1)
        assert result is False

    def test_delete_invalid_id(self, service: ProductService, mock_repository: MagicMock) -> None:
        result = service.delete("bad")
        assert result is False
        mock_repository.delete.assert_not_called()