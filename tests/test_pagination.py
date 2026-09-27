"""Task 16.3 — Pagination tests.

Covers the canonical page-based pagination API:

* :class:`~betrayer.web.pagination.PaginationParams` -- default/custom values,
  offset calculation, construction-time guards.
* :class:`~betrayer.web.pagination.PaginationMetadata` -- total/total_pages
  calculation, empty collection.
* :func:`~betrayer.web.pagination.parse_pagination` -- request parsing,
  defaults, structured validation errors (page/per_page invalid).
* :func:`~betrayer.web.pagination.paginate_sequence` / ``paginate_query`` --
  in-memory and data-layer pagination.
* ``CrudApiResource.pagination = True`` -- collection Resource integration,
  response metadata, existing envelope, unpaginated regression.
* ``Query.paginate`` -- repository/query integration against a real SQLite
  database.
"""

from __future__ import annotations

import json
from typing import Any, Dict

import pytest

from betrayer.core.config import Config
from betrayer.data import DatabaseManager, ORMField, ORMModel, Query
from betrayer.data.bootstrap import build_database_manager
from betrayer.data.registry import DatabaseRegistry
from betrayer.data.engines import register_builtin_engines
from betrayer.web import (
    ApiResponse,
    CrudApiResource,
    MAX_PER_PAGE,
    PaginatedResult,
    PaginationMetadata,
    PaginationParams,
    Request,
    Response,
    WebContext,
    paginate_query,
    paginate_sequence,
    parse_pagination,
)
from betrayer.web.exceptions import ValidationError


def _flask_available() -> bool:
    try:  # pragma: no cover - import probe
        import flask  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return True


_HAS_FLASK = _flask_available()


class _FakeRequest(Request):
    """A Request that serves query params from a plain dict (no Flask)."""

    def __init__(self, query: Dict[str, Any]) -> None:
        super().__init__(raw=None)
        self._query_dict = dict(query)

    @property
    def query(self) -> Dict[str, Any]:
        return dict(self._query_dict)

    def get_query(self, name: str, default: Any = None) -> Any:
        return self._query_dict.get(name, default)


# ---------------------------------------------------------------------------
# Request parsing
# ---------------------------------------------------------------------------


def test_default_pagination() -> None:
    """Absent parameters fall back to page=1, per_page=20."""
    params = parse_pagination(_FakeRequest({}))
    assert params.page == 1
    assert params.per_page == 20
    assert params.offset == 0


def test_custom_page_and_per_page() -> None:
    """page / per_page are parsed and validated from the query string."""
    params = parse_pagination(_FakeRequest({"page": "2", "per_page": "50"}))
    assert params.page == 2
    assert params.per_page == 50
    assert params.offset == 50  # (2-1) * 50


def test_page_key_can_be_renamed() -> None:
    params = parse_pagination(_FakeRequest({"p": "3", "size": "5"}), page_key="p", per_page_key="size")
    assert params.page == 3
    assert params.per_page == 5


def test_pagination_params_frozen() -> None:
    params = PaginationParams(page=1, per_page=20)
    with pytest.raises(Exception):
        params.page = 2  # type: ignore[misc]


def test_pagination_params_construction_guards() -> None:
    with pytest.raises(ValueError):
        PaginationParams(page=0, per_page=20)
    with pytest.raises(ValueError):
        PaginationParams(page=-2, per_page=20)
    with pytest.raises(ValueError):
        PaginationParams(page=1, per_page=0)
    with pytest.raises(ValueError):
        PaginationParams(page=1, per_page=-1)
    with pytest.raises(ValueError):
        PaginationParams(page=1, per_page=MAX_PER_PAGE + 1)
    with pytest.raises(TypeError):
        PaginationParams(page="1", per_page=20)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        PaginationParams(page=1, per_page=True)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Validation errors (existing pipeline)
# ---------------------------------------------------------------------------

_VALIDATION_CASES = [
    ({"page": "abc"}, "page"),
    ({"page": "0"}, "page"),
    ({"page": "-1"}, "page"),
    ({"page": "2.5"}, "page"),
    ({"per_page": "abc"}, "per_page"),
    ({"per_page": "0"}, "per_page"),
    ({"per_page": "-1"}, "per_page"),
    ({"per_page": "101"}, "per_page"),
    ({"per_page": "20.5"}, "per_page"),
]


@pytest.mark.parametrize("query,field", _VALIDATION_CASES)
def test_invalid_pagination_raises_validation_error(query: Dict[str, str], field: str) -> None:
    """Non-integer / out-of-range parameters raise 422 ValidationError."""
    with pytest.raises(ValidationError) as exc_info:
        parse_pagination(_FakeRequest(query))
    error = exc_info.value
    assert error.code == "VALIDATION_FAILED"
    assert error.http_status == 422
    assert field in error.fields
    assert error.errors  # structured field list rides along


def test_per_page_maximum_is_allowed() -> None:
    """per_page == MAX_PER_PAGE is valid (the exact cap)."""
    params = parse_pagination(_FakeRequest({"page": "1", "per_page": str(MAX_PER_PAGE)}))
    assert params.per_page == MAX_PER_PAGE


def test_per_page_one_is_allowed() -> None:
    params = parse_pagination(_FakeRequest({"page": "1", "per_page": "1"}))
    assert params.per_page == 1


# ---------------------------------------------------------------------------
# Metadata / page calculation
# ---------------------------------------------------------------------------


def test_metadata_total_pages() -> None:
    meta = PaginationMetadata.from_params(PaginationParams(page=1, per_page=20), 135)
    assert meta.to_dict() == {
        "page": 1,
        "per_page": 20,
        "total": 135,
        "total_pages": 7,
    }


def test_metadata_total_pages_exact_multiple() -> None:
    meta = PaginationMetadata.from_params(PaginationParams(page=1, per_page=20), 40)
    assert meta.total_pages == 2


def test_metadata_empty_collection() -> None:
    meta = PaginationMetadata.from_params(PaginationParams(page=1, per_page=20), 0)
    assert meta.total == 0
    assert meta.total_pages == 0


def test_metadata_last_page() -> None:
    meta = PaginationMetadata.from_params(PaginationParams(page=7, per_page=20), 135)
    assert meta.page == 7
    assert meta.total_pages == 7


# ---------------------------------------------------------------------------
# In-memory / sequence pagination
# ---------------------------------------------------------------------------


def test_paginate_sequence_first_page() -> None:
    items = list(range(5))
    result = paginate_sequence(items, PaginationParams(page=1, per_page=2))
    assert result.items == [0, 1]
    assert result.metadata.total == 5
    assert result.metadata.total_pages == 3


def test_paginate_sequence_last_page_partial() -> None:
    result = paginate_sequence(list(range(5)), PaginationParams(page=3, per_page=2))
    assert result.items == [4]
    assert result.metadata.total == 5
    assert result.metadata.total_pages == 3


def test_paginate_sequence_empty() -> None:
    result = paginate_sequence([], PaginationParams(page=1, per_page=20))
    assert result.items == []
    assert result.metadata.total == 0
    assert result.metadata.total_pages == 0


def test_paginate_sequence_out_of_range_page() -> None:
    """A page beyond the last page is an empty slice, metadata stays true."""
    result = paginate_sequence(list(range(5)), PaginationParams(page=99, per_page=2))
    assert result.items == []
    assert result.metadata.page == 99
    assert result.metadata.total_pages == 3


# ---------------------------------------------------------------------------
# Data-layer pagination (real SQLite)
# ---------------------------------------------------------------------------


@pytest.fixture
def sqlite_query() -> Any:
    """A connected SQLite DatabaseManager with a seeded ``items`` table."""
    config = Config(
        {
            "database.default.driver": "sqlite",
            "database.default.database": ":memory:",
        }
    )
    registry = DatabaseRegistry(config)
    register_builtin_engines(registry)
    manager = DatabaseManager(registry.engine("default"))
    manager.connect()
    manager.execute('CREATE TABLE "items" ("id" INTEGER PRIMARY KEY, "name" TEXT)')
    for i in range(1, 11):
        manager.execute('INSERT INTO "items" ("name") VALUES (?)', [f"item-{i}"])
    try:
        yield Query("items", database=manager)
    finally:
        manager.disconnect()


def test_paginate_query(sqlite_query: Any) -> None:
    params = PaginationParams(page=2, per_page=4)
    result = paginate_query(sqlite_query, params)
    assert len(result.items) == 4
    assert result.items[0]["id"] == 5  # offset 4 -> ids 5..8
    assert result.metadata.total == 10
    assert result.metadata.total_pages == 3


def test_paginate_query_out_of_range(sqlite_query: Any) -> None:
    result = paginate_query(sqlite_query, PaginationParams(page=10, per_page=5))
    assert result.items == []
    assert result.metadata.total == 10
    assert result.metadata.total_pages == 2


# ---------------------------------------------------------------------------
# Query.paginate (minimal data-layer extension)
# ---------------------------------------------------------------------------


def test_query_paginate(sqlite_query: Any) -> None:
    result = sqlite_query.paginate(page=2, per_page=3)
    assert result["total"] == 10
    assert len(result["items"]) == 3
    assert result["items"][0]["id"] == 4


def test_query_paginate_guards(sqlite_query: Any) -> None:
    with pytest.raises(Exception):
        sqlite_query.paginate(page=0, per_page=3)
    with pytest.raises(Exception):
        sqlite_query.paginate(page=1, per_page=0)


# ---------------------------------------------------------------------------
# ORM repository integration
# ---------------------------------------------------------------------------


class Product(ORMModel):
    __table__ = "products"

    id = ORMField(int, primary_key=True)
    name = ORMField(str, required=True)


@pytest.fixture
def orm_manager() -> Any:
    config = Config(
        {
            "database.default.driver": "sqlite",
            "database.default.database": ":memory:",
        }
    )
    registry = DatabaseRegistry(config)
    register_builtin_engines(registry)
    manager = DatabaseManager(registry.engine("default"))
    manager.connect()
    manager.execute('CREATE TABLE "products" ("id" INTEGER PRIMARY KEY, "name" TEXT)')
    Product.__connection__ = manager
    try:
        yield manager
    finally:
        manager.disconnect()


def test_repository_query_paginate(orm_manager: Any) -> None:
    from betrayer.data import BaseRepository

    for i in range(1, 8):
        Product.create(name=f"p-{i}")
    repo = BaseRepository(Product)
    result = repo.query().paginate(page=2, per_page=3)
    assert result["total"] == 7
    assert len(result["items"]) == 3
    assert result["items"][0].name == "p-4"


# ---------------------------------------------------------------------------
# Resource integration (CrudApiResource.pagination = True)
# ---------------------------------------------------------------------------


class Item:
    def __init__(self, identifier: int, name: str) -> None:
        self.id = identifier
        self.name = name

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name}


class ItemService:
    """Service with a canonical list() (no paginate) -> fallback path."""

    def __init__(self, items: dict) -> None:
        self._items = dict(items)

    def list(self):
        return list(self._items.values())


class PaginatedProductResource(CrudApiResource):
    name = "product"
    prefix = "/api"
    pagination = True


class PlainProductResource(CrudApiResource):
    name = "product"
    prefix = "/api"
    pagination = False


@pytest.mark.skipif(not _HAS_FLASK, reason="Flask is required to serve routes")
def _app_and_adapter(resource: CrudApiResource, service: Any) -> Any:
    from betrayer.application import BetrayerApplication
    from betrayer.web.adapter import FlaskAdapter

    application = BetrayerApplication(name="pagination-test")
    adapter = FlaskAdapter(application)
    adapter.add_router(resource(service=service).resource_router())
    adapter.build()
    return adapter


def _json(response: Any) -> dict:
    return json.loads(response.get_data(as_text=True))


def _items(count: int) -> dict:
    return {i: Item(i, f"item-{i}") for i in range(1, count + 1)}


@pytest.mark.skipif(not _HAS_FLASK, reason="Flask is required to serve routes")
def test_collection_resource_paginated() -> None:
    """GET /api/product?page=2&per_page=2 returns data + meta.pagination."""
    adapter = _app_and_adapter(PaginatedProductResource, ItemService(_items(5)))
    client = adapter.flask_app.test_client()
    response = client.get("/api/product?page=2&per_page=2")
    assert response.status_code == 200
    payload = _json(response)
    assert payload["success"] is True
    assert payload["data"] == [{"id": 3, "name": "item-3"}, {"id": 4, "name": "item-4"}]
    assert payload["meta"]["count"] == 2
    assert payload["meta"]["resource"] == "product"
    assert payload["meta"]["pagination"] == {
        "page": 2,
        "per_page": 2,
        "total": 5,
        "total_pages": 3,
    }


@pytest.mark.skipif(not _HAS_FLASK, reason="Flask is required to serve routes")
def test_collection_resource_default_pagination() -> None:
    """No query params -> defaults (page=1, per_page=20), full collection."""
    adapter = _app_and_adapter(PaginatedProductResource, ItemService(_items(3)))
    client = adapter.flask_app.test_client()
    payload = _json(client.get("/api/product"))
    assert payload["meta"]["pagination"]["page"] == 1
    assert payload["meta"]["pagination"]["per_page"] == 20
    assert payload["meta"]["pagination"]["total"] == 3
    assert payload["meta"]["pagination"]["total_pages"] == 1  # ceil(3/20)
    assert len(payload["data"]) == 3


@pytest.mark.skipif(not _HAS_FLASK, reason="Flask is required to serve routes")
def test_collection_resource_empty() -> None:
    adapter = _app_and_adapter(PaginatedProductResource, ItemService({}))
    client = adapter.flask_app.test_client()
    payload = _json(client.get("/api/product"))
    assert payload["data"] == []
    assert payload["meta"]["pagination"]["total"] == 0
    assert payload["meta"]["pagination"]["total_pages"] == 0


@pytest.mark.skipif(not _HAS_FLASK, reason="Flask is required to serve routes")
def test_collection_resource_out_of_range_page() -> None:
    adapter = _app_and_adapter(PaginatedProductResource, ItemService(_items(5)))
    client = adapter.flask_app.test_client()
    payload = _json(client.get("/api/product?page=9&per_page=2"))
    assert payload["data"] == []
    assert payload["meta"]["pagination"]["page"] == 9
    assert payload["meta"]["pagination"]["total_pages"] == 3


@pytest.mark.skipif(not _HAS_FLASK, reason="Flask is required to serve routes")
def test_collection_resource_invalid_params_422() -> None:
    adapter = _app_and_adapter(PaginatedProductResource, ItemService(_items(5)))
    client = adapter.flask_app.test_client()
    response = client.get("/api/product?page=0")
    assert response.status_code == 422
    payload = _json(response)
    assert payload["success"] is False
    assert payload["error"]["code"] == "VALIDATION_FAILED"

    response = client.get("/api/product?per_page=500")
    assert response.status_code == 422
    assert _json(response)["error"]["code"] == "VALIDATION_FAILED"


@pytest.mark.skipif(not _HAS_FLASK, reason="Flask is required to serve routes")
def test_unpaginated_resource_regression() -> None:
    """A resource with pagination=False keeps its exact previous envelope."""
    adapter = _app_and_adapter(PlainProductResource, ItemService(_items(3)))
    client = adapter.flask_app.test_client()
    # Even with pagination query params present, the handler ignores them.
    payload = _json(client.get("/api/product?page=2&per_page=1"))
    assert payload["data"] == [
        {"id": 1, "name": "item-1"},
        {"id": 2, "name": "item-2"},
        {"id": 3, "name": "item-3"},
    ]
    assert payload["meta"] == {"count": 3, "resource": "product"}
    assert "pagination" not in payload["meta"]


@pytest.mark.skipif(not _HAS_FLASK, reason="Flask is required to serve routes")
def test_paginated_resource_paginate_service_method() -> None:
    """A service exposing paginate() is preferred over list()."""

    class PaginatedService(ItemService):
        def paginate(self, page=1, per_page=20):
            all_items = self.list()
            start = (page - 1) * per_page
            return all_items[start : start + per_page], len(all_items)

    adapter = _app_and_adapter(PaginatedProductResource, PaginatedService(_items(5)))
    client = adapter.flask_app.test_client()
    payload = _json(client.get("/api/product?page=2&per_page=2"))
    assert payload["data"] == [{"id": 3, "name": "item-3"}, {"id": 4, "name": "item-4"}]
    assert payload["meta"]["pagination"]["total"] == 5
    assert payload["meta"]["pagination"]["total_pages"] == 3


@pytest.mark.skipif(not _HAS_FLASK, reason="Flask is required to serve routes")
def test_paginated_result_service_method() -> None:
    """A service.paginate() returning a PaginatedResult is accepted."""

    class ResultService(ItemService):
        def paginate(self, page=1, per_page=20):
            all_items = self.list()
            start = (page - 1) * per_page
            slice_ = all_items[start : start + per_page]
            meta = PaginationMetadata.from_params(
                PaginationParams(page=page, per_page=per_page), len(all_items)
            )
            return PaginatedResult(items=slice_, metadata=meta)

    adapter = _app_and_adapter(PaginatedProductResource, ResultService(_items(4)))
    client = adapter.flask_app.test_client()
    payload = _json(client.get("/api/product?page=1&per_page=2"))
    assert payload["meta"]["pagination"]["total"] == 4
    assert payload["meta"]["pagination"]["total_pages"] == 2


@pytest.mark.skipif(not _HAS_FLASK, reason="Flask is required to serve routes")
def test_existing_envelope_preserved() -> None:
    """The success/error envelope shape is unchanged by pagination."""
    adapter = _app_and_adapter(PaginatedProductResource, ItemService(_items(1)))
    client = adapter.flask_app.test_client()
    payload = _json(client.get("/api/product"))
    assert set(payload) == {"success", "data", "error", "meta"}
    assert payload["success"] is True
    assert payload["error"] is None
    assert set(payload["meta"]) == {"count", "resource", "pagination"}


@pytest.mark.skipif(not _HAS_FLASK, reason="Flask is required to serve routes")
def test_paginated_error_pipeline_existing() -> None:
    """Invalid pagination goes through the existing 422 error pipeline."""
    adapter = _app_and_adapter(PaginatedProductResource, ItemService(_items(1)))
    client = adapter.flask_app.test_client()
    response = client.get("/api/product?page=1&per_page=999")
    assert response.status_code == 422
    payload = _json(response)
    assert payload["success"] is False
    assert payload["error"]["code"] == "VALIDATION_FAILED"
    assert "fields" in payload["error"]["details"]