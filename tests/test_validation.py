"""Focused tests for the canonical validation + request pipeline (Task 11).

Covers:

* the validation API (:class:`~betrayer.web.validation.Schema` /
  :class:`~betrayer.web.validation.Field` / ``validate``) -- valid, required,
  type, value constraints, partial updates and structured errors;
* the request pipeline on ``CrudApiResource`` -- parse once, validate *before*
  the service, structured result on the context, and the service never being
  called when validation fails;
* the HTTP validation error contract (422 ``VALIDATION_FAILED`` with
  ``error.details.fields``);
* dependency injection through the existing container;
* a regression check of the Product Catalog Golden Path.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from betrayer.application import BetrayerApplication
from betrayer.web import (
    ApiResource,
    ApiResponse,
    CrudApiResource,
    Field,
    FlaskAdapter,
    Response,
    Schema,
    ValidationResult,
    validate,
)
from betrayer.web.exceptions import ValidationError


def _flask_available() -> bool:
    try:  # pragma: no cover - import probe
        import flask  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return True


_HAS_FLASK = _flask_available()

pytestmark = pytest.mark.skipif(
    not _HAS_FLASK, reason="Flask is required to serve Betrayer routes"
)


def _json(response: Any) -> dict:
    return json.loads(response.get_data(as_text=True))


# ---------------------------------------------------------------------------
# Shared schema + spy service
# ---------------------------------------------------------------------------


class ProductSchema(Schema):
    """The canonical catalog request contract used across the tests."""

    name = Field(str, required=True)
    price = Field(float, required=True, min=0)
    stock = Field(int, default=0, min=0)


class SpyService:
    """Records every call so tests can assert the pipeline short-circuits."""

    def __init__(self) -> None:
        self.calls = 0
        self.created: list = []
        self.updated: list = []

    def list(self) -> list:
        return []

    def get(self, identifier: Any) -> Any:
        return None

    def create(self, **data: Any) -> Any:
        self.calls += 1
        self.created.append(dict(data))
        payload = dict(data)
        payload.setdefault("id", 1)
        return payload

    def update(self, identifier: Any, **data: Any) -> Any:
        self.calls += 1
        self.updated.append((identifier, dict(data)))
        payload = {"id": identifier}
        payload.update(data)
        return payload

    def delete(self, identifier: Any) -> bool:
        self.calls += 1
        return True


class ProductResource(CrudApiResource):
    name = "products"
    prefix = "/api"
    schema = ProductSchema()


def _adapter(service: SpyService) -> FlaskAdapter:
    """A running adapter whose resource resolves ``service`` from the container."""
    application = BetrayerApplication(name="validation-test")
    application.container.instance("products_service", service)
    adapter = FlaskAdapter(application, ProductResource().resource_router())
    adapter.build()
    return adapter


# ---------------------------------------------------------------------------
# 1. Validation API (schema level)
# ---------------------------------------------------------------------------


def test_valid_data_passes() -> None:
    """A complete, correctly typed body validates and keeps its values."""
    result = ProductSchema().validate({"name": "Chair", "price": 1500000, "stock": 2})
    assert result.valid is True
    assert result.errors == []
    assert result.data == {"name": "Chair", "price": 1500000, "stock": 2}


def test_int_is_accepted_for_float_field() -> None:
    """JSON has one number type: an ``int`` satisfies a ``float`` field."""
    result = ProductSchema().validate({"name": "Chair", "price": 10})
    assert result.valid is True
    assert result.data["price"] == 10


def test_missing_required_field() -> None:
    """A required field that is absent produces a structured required error."""
    result = ProductSchema().validate({"price": 1})
    assert result.valid is False
    assert result.fields == {"name": ["This field is required."]}
    assert result.errors[0].field == "name"
    assert result.errors[0].code == "required"


def test_none_counts_as_missing_for_required_field() -> None:
    """An explicit ``None`` on a required field is rejected as required."""
    result = ProductSchema().validate({"name": None, "price": 1})
    assert result.fields.get("name") == ["This field is required."]


def test_invalid_type() -> None:
    """A wrong type is rejected with a readable type error."""
    result = ProductSchema().validate({"name": "Chair", "price": "cheap"})
    assert result.valid is False
    assert result.fields["price"] == ["Must be a number."]
    # the wrong-typed value never reaches the cleaned payload
    assert "price" not in result.data


def test_invalid_value() -> None:
    """A value constraint (``min``) rejection is structured too."""
    result = ProductSchema().validate({"name": "Chair", "price": -5})
    assert result.valid is False
    assert result.fields["price"] == ["Must be at least 0."]


def test_defaults_applied_on_create() -> None:
    """An absent optional field with a default is injected on a create."""
    result = ProductSchema().validate({"name": "Chair", "price": 1})
    assert result.valid is True
    assert result.data["stock"] == 0


def test_unknown_fields_are_dropped() -> None:
    """Only declared fields survive validation (no arbitrary payload pass-through)."""
    result = ProductSchema().validate({"name": "Chair", "price": 1, "colour": "red"})
    assert result.valid is True
    assert "colour" not in result.data


def test_partial_update_skips_absent_fields() -> None:
    """``partial=True`` validates only the provided fields and adds no defaults."""
    schema = ProductSchema()
    result = schema.validate({"stock": 5}, partial=True)
    assert result.valid is True
    assert result.data == {"stock": 5}


def test_partial_update_still_validates_provided_fields() -> None:
    """A provided field is validated even on a partial update."""
    result = ProductSchema().validate({"price": -1}, partial=True)
    assert result.valid is False
    assert result.fields["price"] == ["Must be at least 0."]


def test_raise_if_invalid_uses_existing_error_contract() -> None:
    """``raise_if_invalid`` raises the framework ``ValidationError`` (422)."""
    result = ProductSchema().validate({"price": 1})
    with pytest.raises(ValidationError) as captured:
        result.raise_if_invalid()
    error = captured.value
    assert error.code == "VALIDATION_FAILED"
    assert error.http_status == 422
    assert error.fields == {"name": ["This field is required."]}
    assert error.details()["fields"]["name"] == ["This field is required."]


def test_validate_helper_accepts_each_schema_form() -> None:
    """``validate`` normalises instance / subclass / mapping / ``None``."""
    body = {"name": "Chair", "price": 1}
    assert validate(ProductSchema(), body).valid is True
    assert validate(ProductSchema, body).valid is True
    assert validate({"name": Field(str, required=True), "price": Field(float)}, body).valid is True
    passthrough = validate(None, body)
    assert passthrough.valid is True
    assert passthrough.data == body


def test_schema_introspection() -> None:
    """A schema describes its fields for LLM introspection."""
    described = ProductSchema().to_dict()
    assert described["name"] == "ProductSchema"
    fields = {field["name"]: field for field in described["fields"]}
    assert fields["name"]["required"] is True
    assert fields["price"]["min"] == 0


# ---------------------------------------------------------------------------
# 2. Request pipeline on the resource (HTTP)
# ---------------------------------------------------------------------------


def test_pipeline_valid_request_reaches_service() -> None:
    """A valid POST is validated then delegated to the service (201)."""
    service = SpyService()
    client = _adapter(service).flask_app.test_client()
    response = client.post(
        "/api/products", json={"name": "Antique Chair", "price": 1500000, "stock": 2}
    )
    assert response.status_code == 201
    assert _json(response)["data"]["name"] == "Antique Chair"
    assert service.created == [
        {"name": "Antique Chair", "price": 1500000, "stock": 2}
    ]


def test_pipeline_missing_required_field_returns_422() -> None:
    """A missing required field yields 422 before the service is called."""
    service = SpyService()
    client = _adapter(service).flask_app.test_client()
    response = client.post("/api/products", json={"price": 1})
    assert response.status_code == 422
    payload = _json(response)
    assert payload["success"] is False
    assert payload["error"]["code"] == "VALIDATION_FAILED"
    assert payload["error"]["details"]["fields"] == {
        "name": ["This field is required."]
    }
    # the service was never called
    assert service.calls == 0
    assert service.created == []


def test_pipeline_invalid_type_returns_422() -> None:
    """A wrong-typed field yields 422 with a structured field error."""
    service = SpyService()
    client = _adapter(service).flask_app.test_client()
    response = client.post("/api/products", json={"name": "Chair", "price": "free"})
    assert response.status_code == 422
    details = _json(response)["error"]["details"]
    assert details["fields"]["price"] == ["Must be a number."]
    assert service.calls == 0


def test_pipeline_invalid_value_returns_422() -> None:
    """A value-constraint rejection yields 422 and skips the service."""
    service = SpyService()
    client = _adapter(service).flask_app.test_client()
    response = client.post("/api/products", json={"name": "Chair", "price": -3})
    assert response.status_code == 422
    assert _json(response)["error"]["details"]["fields"]["price"] == [
        "Must be at least 0."
    ]
    assert service.calls == 0


def test_pipeline_update_validates_partial_body() -> None:
    """PUT validates provided fields only and passes the partial body on."""
    service = SpyService()
    client = _adapter(service).flask_app.test_client()
    response = client.put("/api/products/7", json={"stock": 5})
    assert response.status_code == 200
    assert service.updated == [("7", {"stock": 5})]


def test_pipeline_update_rejects_invalid_value() -> None:
    """An invalid value on PUT is rejected before the service is called."""
    service = SpyService()
    client = _adapter(service).flask_app.test_client()
    response = client.put("/api/products/7", json={"price": -1})
    assert response.status_code == 422
    assert _json(response)["error"]["details"]["fields"]["price"] == [
        "Must be at least 0."
    ]
    assert service.calls == 0


def test_pipeline_extra_fields_not_forwarded() -> None:
    """Only declared fields reach the service (validate-before-service)."""
    service = SpyService()
    client = _adapter(service).flask_app.test_client()
    client.post("/api/products", json={"name": "Chair", "price": 1, "colour": "red"})
    assert service.created == [{"name": "Chair", "price": 1, "stock": 0}]


def test_pipeline_attaches_structured_result_to_context() -> None:
    """The validated result is available on ``WebContext`` for Resource/Service."""

    class InspectResource(ApiResource):
        name = "inspect"
        schema = ProductSchema()

        def endpoints(self):
            return [("POST", "/check", self.check)]

        async def check(self, request: Any, context: Any) -> Response:
            result = self.validate_request(request, context)
            return ApiResponse.success(
                {
                    "data": result.data,
                    "valid": result.valid,
                    "context_data": context.validated_data,
                }
            )

    application = BetrayerApplication(name="inspect-test")
    adapter = FlaskAdapter(application, InspectResource().resource_router())
    adapter.build()
    client = adapter.flask_app.test_client()
    payload = _json(client.post("/inspect/check", json={"name": "Chair", "price": 2}))
    assert payload["data"]["valid"] is True
    assert payload["data"]["data"] == {"name": "Chair", "price": 2, "stock": 0}
    assert payload["data"]["context_data"] == payload["data"]["data"]


def test_resource_without_schema_is_unchanged() -> None:
    """A resource with no schema keeps passing the raw body through."""

    class PlainResource(CrudApiResource):
        name = "plain"
        prefix = "/api"

    service = SpyService()
    application = BetrayerApplication(name="plain-test")
    application.container.instance("plain_service", service)
    adapter = FlaskAdapter(application, PlainResource().resource_router())
    adapter.build()
    client = adapter.flask_app.test_client()
    response = client.post("/api/plain", json={"anything": 1})
    assert response.status_code == 201
    assert service.created == [{"anything": 1}]


# ---------------------------------------------------------------------------
# 3. Dependency injection through the existing container
# ---------------------------------------------------------------------------


def test_dependency_injection_uses_existing_container() -> None:
    """The resource resolves its service from the Task 02 container."""
    service = SpyService()
    application = BetrayerApplication(name="di-test")
    application.container.instance("products_service", service)
    # the same container serves the resource's dependency
    assert application.container.resolve("products_service") is service
    adapter = FlaskAdapter(application, ProductResource().resource_router())
    adapter.build()
    client = adapter.flask_app.test_client()
    client.post("/api/products", json={"name": "Chair", "price": 1})
    # the injected instance (not a copy) received the call
    assert service.calls == 1


def test_service_can_be_injected_directly() -> None:
    """An explicitly injected service bypasses the container (still canonical)."""
    service = SpyService()
    application = BetrayerApplication(name="direct-test")
    resource = ProductResource(service=service)
    adapter = FlaskAdapter(application, resource.resource_router())
    adapter.build()
    client = adapter.flask_app.test_client()
    client.post("/api/products", json={"name": "Chair", "price": 1})
    assert service.calls == 1


# ---------------------------------------------------------------------------
# 4. Golden Path regression (Product Catalog over real SQLite)
# ---------------------------------------------------------------------------


@pytest.fixture()
def catalog(tmp_path: Path) -> tuple:
    """A built catalog application + Flask test client."""
    from example.product_catalog.app import build_application, create_flask_app

    application = build_application(database_path=tmp_path / "catalog.db")
    return application, create_flask_app(application).test_client()


def test_catalog_valid_create_and_read(catalog: tuple) -> None:
    """The catalog still serves a valid create/list/get over the full stack."""
    _app, client = catalog
    created = client.post(
        "/api/products", json={"name": "Antique Chair", "price": 1500000, "stock": 2}
    )
    assert created.status_code == 201
    body = _json(created)
    assert body["success"] is True
    assert body["data"]["name"] == "Antique Chair"
    assert _json(client.get("/api/products"))["meta"]["count"] == 1


def test_catalog_invalid_request_never_touches_service_or_database(catalog: tuple) -> None:
    """An invalid create returns 422 and stores nothing (validation precedes work)."""
    _app, client = catalog
    response = client.post("/api/products", json={"price": 1})
    assert response.status_code == 422
    assert _json(response)["error"]["details"]["fields"] == {
        "name": ["This field is required."]
    }
    # nothing was persisted
    assert _json(client.get("/api/products"))["meta"]["count"] == 0


def test_catalog_wrong_type_returns_422(catalog: tuple) -> None:
    """A wrong-typed price is rejected with the structured error contract."""
    _app, client = catalog
    response = client.post(
        "/api/products", json={"name": "Chair", "price": "expensive"}
    )
    assert response.status_code == 422
    assert _json(response)["error"]["details"]["fields"]["price"] == [
        "Must be a number."
    ]


def test_catalog_update_validation(catalog: tuple) -> None:
    """PUT validates the partial body; a bad value is rejected, a good one applies."""
    _app, client = catalog
    product_id = _json(
        client.post("/api/products", json={"name": "Chair", "price": 10, "stock": 1})
    )["data"]["id"]

    invalid = client.put(f"/api/products/{product_id}", json={"price": -1})
    assert invalid.status_code == 422
    assert _json(invalid)["error"]["details"]["fields"]["price"] == [
        "Must be at least 0."
    ]

    valid = client.put(f"/api/products/{product_id}", json={"price": 12.5, "stock": 4})
    assert valid.status_code == 200
    updated = _json(valid)["data"]
    assert updated["price"] == 12.5
    assert updated["stock"] == 4


def test_catalog_schema_matches_model_shape() -> None:
    """The catalog schema stays in sync with the Product model fields."""
    from example.product_catalog.models import Product
    from example.product_catalog.schemas import ProductSchema

    schema_fields = set(ProductSchema().fields)
    assert {"name", "price", "stock"}.issubset(schema_fields)
    getter = getattr(Product, "orm_fields", None)
    if callable(getter):
        assert {"name", "price", "stock"}.issubset(set(getter()))


def test_validation_result_is_truthy_only_when_valid() -> None:
    """``ValidationResult`` truthiness mirrors validity (small ergonomic aid)."""
    assert bool(ValidationResult(data={"a": 1})) is True
