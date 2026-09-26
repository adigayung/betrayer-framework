"""Focused tests for the Resource/API runtime layer (Task 08).

Covers the runtime Resource/API surface built on the existing Betrayer web
layer:

* :class:`~betrayer.web.adapter.FlaskAdapter` -- route registration, serving,
  async + sync handlers, path/query params, JSON bodies, error responses.
* :class:`~betrayer.web.resource.ApiResource` / ``CrudApiResource`` --
  declarative resources and the shared CRUD flow.
* :class:`~betrayer.web.resource.ResourceRegistry` -- several resources
  mounted without route conflicts.
* Error handling -- 400 / 404 / 422 / 500 produced as controlled JSON.
* Resource -> Service -> Repository integration (the documented data flow).
* Generated-router compatibility (``bet make resource`` / ``bet make crud``).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict

import pytest

from betrayer.application import BetrayerApplication
from betrayer.core.container import Container
from betrayer.data.models import Field, Model
from betrayer.data.repository import Repository
from betrayer.web import (
    ApiResource,
    CrudApiResource,
    FlaskAdapter,
    ResourceRegistry,
    Router,
    register_web_router,
)
from betrayer.web import ApiResponse, Request, Response, WebContext  # noqa: F401
from betrayer.web.exceptions import (
    InternalServerError,
    NotFoundError,
    ValidationError,
)


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


# ---------------------------------------------------------------------------
# In-memory data layer + service (stands in for Repository/Data Layer)
# ---------------------------------------------------------------------------


class MemoryRepository(Repository):
    """Concrete Repository over a dict store (no real database needed)."""

    def __init__(self, model_class):
        super().__init__(model_class=model_class, database=_StubDatabase())
        self._store: Dict[Any, Model] = {}
        self._next = 1

    def get(self, identifier: Any):
        try:
            identifier = int(identifier)
        except (TypeError, ValueError):
            return None
        return self._store.get(identifier)

    def list(self):
        return list(self._store.values())

    def create(self, model: Model) -> Model:
        identifier = self._next
        self._next += 1
        model.id = identifier
        self._store[identifier] = model
        return model

    def update(self, model: Model) -> Model:
        self._store[int(model.id)] = model
        return model

    def delete(self, identifier: Any) -> bool:
        try:
            identifier = int(identifier)
        except (TypeError, ValueError):
            return False
        return self._store.pop(identifier, None) is not None


class _StubDatabase:
    """Minimal stand-in for DatabaseManager (never connected)."""

    def __str__(self) -> str:  # pragma: no cover - introspection hook
        return "memory://"


class ItemModel(Model):
    """Data model for the tests."""

    id: int = Field(int, required=False, default=None, description="Primary key (assigned by repository)")
    name: str = Field(str, required=True, description="Item name")
    price: int = Field(int, default=0, description="Price in cents")


class ItemService:
    """Business service layer sitting between handlers and the repository."""

    def __init__(self, repository: MemoryRepository) -> None:
        self._repository = repository

    @property
    def repository(self):
        return self._repository

    # -- CRUD delegation ------------------------------------------------
    def list(self):
        return self._repository.list()

    def get(self, identifier: Any):
        return self._repository.get(identifier)

    def create(self, **data: Any) -> Any:
        missing = [key for key in ("name",) if key not in data]
        if missing:
            raise ValidationError(
                message=f"Missing required field(s): {', '.join(missing)}",
                errors=[{"field": key, "required": True} for key in missing],
            )
        model = self._repository.model_class.from_dict(data)
        return self._repository.create(model)

    def update(self, identifier: Any, **data: Any) -> Any:
        item = self._repository.get(identifier)
        if item is None:
            return None
        for key, value in data.items():
            setattr(item, key, value)
        return self._repository.update(item)

    def delete(self, identifier: Any) -> bool:
        return self._repository.delete(identifier)


def _service() -> ItemService:
    return ItemService(MemoryRepository(ItemModel))


def _app_and_adapter(*routers, name: str = "resource-test") -> tuple:
    """Build an application + adapter with the given routers mounted."""
    application = BetrayerApplication(name=name)
    adapter = FlaskAdapter(application)
    for router in routers:
        adapter.add_router(router)
    adapter.build()
    return application, adapter


def _json(response) -> dict:
    return json.loads(response.get_data(as_text=True))


# ---------------------------------------------------------------------------
# Resource creation & registration
# ---------------------------------------------------------------------------


class HealthResource(ApiResource):
    name = "health"
    prefix = "/api"

    def endpoints(self):
        return [
            ("GET", "/ping", self.ping),
        ]

    async def ping(self, request: Request, context: WebContext) -> Response:
        return ApiResponse.success({"status": "ok"})


def test_resource_can_be_created() -> None:
    """A resource subclass is instantiable and knows its routes."""
    resource = HealthResource()
    assert resource.name == "health"
    assert resource.base_path == "/api/health"
    declared = resource.endpoints()
    assert declared == [("GET", "/ping", resource.ping)]


def test_resource_registers_routes_on_router() -> None:
    """register() adds every declared endpoint to a WebRouter."""
    router = Router(name="test")
    created = HealthResource().register(router)
    assert len(created) == 1
    assert router.routes.exists("/api/health/ping", "GET")


def test_resource_routes_are_accessible() -> None:
    """The adapter serves a registered resource endpoint."""
    resource = HealthResource()
    router = resource.resource_router()
    _app, adapter = _app_and_adapter(router)
    client = adapter.flask_app.test_client()
    response = client.get("/api/health/ping")
    assert response.status_code == 200
    assert _json(response)["data"] == {"status": "ok"}


# ---------------------------------------------------------------------------
# HTTP method / path / query / body handling
# ---------------------------------------------------------------------------


class EchoResource(ApiResource):
    name = "echo"
    prefix = ""

    def endpoints(self):
        return [
            ("GET", "/<item_id>", self.get_item),
            ("GET", "/query", self.query_params),
            ("POST", "/json", self.json_body),
        ]

    async def get_item(self, request: Request, context: WebContext) -> Response:
        item_id = request.param("item_id")
        return ApiResponse.success({"item_id": item_id})

    async def query_params(self, request: Request, context: WebContext) -> Response:
        value = request.get_query("tag", "none")
        return ApiResponse.success({"tag": value})

    async def json_body(self, request: Request, context: WebContext) -> Response:
        return ApiResponse.success({"body": request.json})


def test_http_method_works() -> None:
    """GET / POST are dispatched to the right handler."""
    router = EchoResource().resource_router()
    _app, adapter = _app_and_adapter(router)
    client = adapter.flask_app.test_client()
    assert client.get("/echo/1").status_code == 200
    assert client.post("/echo/json", json={"a": 1}).status_code == 200


def test_path_parameter_works() -> None:
    """Path parameters reach the handler through Request.param()."""
    router = EchoResource().resource_router()
    _app, adapter = _app_and_adapter(router)
    client = adapter.flask_app.test_client()
    payload = _json(client.get("/echo/42"))
    assert payload["data"] == {"item_id": "42"}


def test_query_parameter_works() -> None:
    """Query parameters reach the handler through Request.get_query()."""
    router = EchoResource().resource_router()
    _app, adapter = _app_and_adapter(router)
    client = adapter.flask_app.test_client()
    payload = _json(client.get("/echo/query?tag=blue"))
    assert payload["data"] == {"tag": "blue"}


def test_json_request_body_works() -> None:
    """A JSON body is parsed into Request.json."""
    router = EchoResource().resource_router()
    _app, adapter = _app_and_adapter(router)
    client = adapter.flask_app.test_client()
    payload = _json(client.post("/echo/json", json={"hello": "world"}))
    assert payload["data"]["body"] == {"hello": "world"}


def test_sync_handler_works() -> None:
    """Synchronous handlers are served the same way as async ones."""

    class SyncResource(ApiResource):
        name = "sync"

        def endpoints(self):
            return [("GET", "/value", self.value)]

        def value(self, request, context):  # noqa: ANN001
            return ApiResponse.success({"sync": True})

    router = SyncResource().resource_router()
    _app, adapter = _app_and_adapter(router)
    client = adapter.flask_app.test_client()
    assert _json(client.get("/sync/value"))["data"] == {"sync": True}


# ---------------------------------------------------------------------------
# CRUD / API flow
# ---------------------------------------------------------------------------


class ProductResource(CrudApiResource):
    name = "product"
    prefix = "/api/v1"


def test_crud_get_collection() -> None:
    service = _service()
    service.create(name="widget", price=9)
    router = ProductResource(service=service).resource_router()
    _app, adapter = _app_and_adapter(router)
    client = adapter.flask_app.test_client()
    payload = _json(client.get("/api/v1/product"))
    assert payload["success"] is True
    assert len(payload["data"]) == 1
    assert payload["data"][0]["name"] == "widget"


def test_crud_create() -> None:
    service = _service()
    router = ProductResource(service=service).resource_router()
    _app, adapter = _app_and_adapter(router)
    client = adapter.flask_app.test_client()
    response = client.post("/api/v1/product", json={"name": "widget", "price": 9})
    assert response.status_code == 201
    assert _json(response)["data"]["name"] == "widget"
    assert len(service.list()) == 1


def test_crud_get_item() -> None:
    service = _service()
    service.create(name="widget")
    router = ProductResource(service=service).resource_router()
    _app, adapter = _app_and_adapter(router)
    client = adapter.flask_app.test_client()
    assert client.get("/api/v1/product/1").status_code == 200


def test_crud_update() -> None:
    service = _service()
    service.create(name="widget", price=9)
    router = ProductResource(service=service).resource_router()
    _app, adapter = _app_and_adapter(router)
    client = adapter.flask_app.test_client()
    response = client.put("/api/v1/product/1", json={"price": 12})
    assert response.status_code == 200
    assert _json(response)["data"]["price"] == 12


def test_crud_delete() -> None:
    service = _service()
    service.create(name="widget")
    router = ProductResource(service=service).resource_router()
    _app, adapter = _app_and_adapter(router)
    client = adapter.flask_app.test_client()
    assert client.delete("/api/v1/product/1").status_code == 204
    assert len(service.list()) == 0


# -- Resource -> Service -> Repository integration ----------------


def test_resource_to_service_to_repository_flow() -> None:
    """HTTP request -> Resource -> Service -> Repository -> Response."""
    repository = MemoryRepository(ItemModel)
    service = ItemService(repository)
    router = ProductResource(service=service).resource_router()
    _app, adapter = _app_and_adapter(router)
    client = adapter.flask_app.test_client()

    # create through the API -> hits repository.create
    created = _json(client.post("/api/v1/product", json={"name": "x", "price": 1}))
    assert created["data"]["id"] == 1
    # the repository really stored a Model instance
    assert isinstance(repository.get(1), ItemModel)
    assert repository.get(1).name == "x"
    # list through the API -> hits repository.list
    listed = _json(client.get("/api/v1/product"))
    assert listed["meta"]["count"] == 1
    assert listed["meta"]["resource"] == "product"


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


def test_bad_request_400() -> None:
    """A missing JSON body produces a controlled 400."""
    service = _service()
    router = ProductResource(service=service).resource_router()
    _app, adapter = _app_and_adapter(router)
    client = adapter.flask_app.test_client()
    response = client.post("/api/v1/product", data="not-json", content_type="text/plain")
    assert response.status_code == 400
    payload = _json(response)
    assert payload["success"] is False
    assert payload["error"]["code"] == "BAD_REQUEST"


def test_not_found_404() -> None:
    """A missing item produces a controlled 404 RESOURCE_NOT_FOUND."""
    service = _service()
    router = ProductResource(service=service).resource_router()
    _app, adapter = _app_and_adapter(router)
    client = adapter.flask_app.test_client()
    response = client.get("/api/v1/product/999")
    assert response.status_code == 404
    payload = _json(response)
    assert payload["error"]["code"] == "RESOURCE_NOT_FOUND"


def test_validation_error_422() -> None:
    """A service raising ValidationError propagates as 422."""
    service = _service()
    router = ProductResource(service=service).resource_router()
    _app, adapter = _app_and_adapter(router)
    client = adapter.flask_app.test_client()
    # The service requires "name"; omitting it raises ValidationError.
    response_via_model = client.post("/api/v1/product", json={"price": 1})
    assert response_via_model.status_code == 422
    payload = _json(response_via_model)
    assert payload["error"]["code"] == "VALIDATION_FAILED"


def test_internal_error_500() -> None:
    """A raised InternalServerError produces a controlled 500."""

    async def boom(request, context):  # noqa: ANN001
        raise InternalServerError("kaput")

    router = Router(name="err")
    router.get("/boom", boom)
    _app, adapter = _app_and_adapter(router)
    client = adapter.flask_app.test_client()
    response = client.get("/boom")
    assert response.status_code == 500
    payload = _json(response)
    assert payload["success"] is False
    assert payload["error"]["code"] == "INTERNAL_ERROR"
    assert payload["error"]["message"] == "kaput"


def test_unexpected_exception_does_not_leak_traceback() -> None:
    """An unexpected exception still yields a safe JSON 500, no traceback."""

    async def explode(request, context):  # noqa: ANN001
        raise RuntimeError("boom detail leaked?")

    router = Router(name="err")
    router.get("/explode", explode)
    _app, adapter = _app_and_adapter(router)
    client = adapter.flask_app.test_client()
    response = client.get("/explode")
    assert response.status_code == 500
    body = response.get_data(as_text=True)
    assert "Traceback" not in body
    assert "boom detail leaked?" not in body


def test_validation_error_from_require_fields() -> None:
    """ApiResource.require_fields raises 422 with the missing field list."""

    class StrictResource(ApiResource):
        name = "strict"

        def endpoints(self):
            return [("POST", "/create", self.create)]

        async def create(self, request, context):
            body = self.require_fields(request, "name", "email")
            return ApiResponse.success({"accepted": body})

    router = StrictResource().resource_router()
    _app, adapter = _app_and_adapter(router)
    client = adapter.flask_app.test_client()
    response = client.post("/strict/create", json={"name": "only"})
    assert response.status_code == 422
    payload = _json(response)
    assert payload["error"]["code"] == "VALIDATION_FAILED"


# ---------------------------------------------------------------------------
# Routing / registration
# ---------------------------------------------------------------------------


def test_multiple_resources_live_together() -> None:
    """Several resources mounted through one adapter never conflict."""
    registry = ResourceRegistry()
    registry.add(ProductResource(service=_service()), prefix="")
    registry.add(ProductResource(service=_service()), prefix="/internal")
    _app, adapter = _app_and_adapter()
    registry.merge(adapter)
    client = adapter.flask_app.test_client()
    assert client.get("/api/v1/product").status_code == 200
    assert client.get("/internal/api/v1/product").status_code == 200


def test_register_web_router_mounts_generated_router() -> None:
    """A plain WebRouter (as generated by `bet make resource`) mounts fine."""
    from betrayer.web.routing import WebRouter

    generated_router = WebRouter(name="article")

    async def list_articles(request, context):  # noqa: ANN001
        return ApiResponse.success(data=[], meta={"resource": "article"})

    generated_router.get("/articles", list_articles)

    application = BetrayerApplication(name="compat")
    adapter = FlaskAdapter(application)
    register_web_router(adapter, generated_router)
    adapter.build()
    client = adapter.flask_app.test_client()
    payload = _json(client.get("/articles"))
    assert payload["meta"]["resource"] == "article"


def test_generated_crud_router_service_resolution() -> None:
    """A generated CRUD router resolves its service through WebContext."""
    # Simulate what `bet make crud` generates: handlers resolve the service
    # via context.resolve("<name>_service").
    container = Container(name="app")
    service = _service()
    container.instance("product_service", service)
    application = BetrayerApplication(name="gen-crud")
    # Rewire the application container to the test one.
    application.core.container = container

    from betrayer.web.routing import WebRouter

    router = WebRouter(name="product")

    async def list_products(request, context):  # noqa: ANN001
        resolved = context.resolve("product_service")
        items = [item.to_dict() for item in resolved.list()]
        return ApiResponse.success(data=items, meta={"resource": "product", "count": len(items)})

    router.get("/products", list_products)
    adapter = FlaskAdapter(application, router)
    adapter.build()
    client = adapter.flask_app.test_client()
    response = client.get("/products")
    assert response.status_code == 200
    payload = _json(response)
    assert payload["data"] == []


# ---------------------------------------------------------------------------
# Error handler registration (the pre-existing bug fix)
# ---------------------------------------------------------------------------


def test_sync_error_handler_returns_flask_response() -> None:
    """register_web_error_handlers returns a Flask-compatible response."""
    from betrayer.web.errors import register_web_error_handlers
    from betrayer.web.flask_bridge import import_flask

    flask = import_flask()
    app = flask.Flask("errcheck")
    register_web_error_handlers(app)

    @app.get("/raise404")
    def raise404():
        raise NotFoundError("gone")

    client = app.test_client()
    response = client.get("/raise404")
    assert response.status_code == 404
    payload = _json(response)
    assert payload["error"]["code"] == "RESOURCE_NOT_FOUND"


def test_plain_flask_404_is_json() -> None:
    """An unmatched URL under a mounted adapter returns JSON, not HTML."""
    router = HealthResource().resource_router()
    _app, adapter = _app_and_adapter(router)
    client = adapter.flask_app.test_client()
    response = client.get("/no-such-route")
    assert response.status_code == 404
    body = response.get_data(as_text=True)
    assert "404 Not Found" not in body  # not the HTML default
    payload = json.loads(body)
    assert payload["success"] is False


# ---------------------------------------------------------------------------
# Generator compatibility (bet make resource / bet make crud → runtime layer)
# ---------------------------------------------------------------------------


@pytest.fixture()
def generated_resource_app(tmp_path: Path) -> Any:
    """Generate ``bet make resource pet`` and mount it on a running adapter."""
    from betrayer.generators.resource import ResourceGenerator

    for mod in list(sys.modules):
        if mod == "pet" or mod.startswith("pet."):
            sys.modules.pop(mod, None)
    generator = ResourceGenerator(name="pet", output_dir=tmp_path)
    generator.generate()
    parent = str(tmp_path)
    if parent not in sys.path:
        sys.path.insert(0, parent)
    from pet.routes import register_routes, router as pet_router

    register_routes(pet_router)
    application = BetrayerApplication(name="gen-resource")
    adapter = FlaskAdapter(application, pet_router)
    adapter.build()
    return adapter, pet_router


def test_generated_resource_runs_through_adapter(
    generated_resource_app: Any,
) -> None:
    """A `bet make resource` router serves real requests via FlaskAdapter."""
    adapter, router = generated_resource_app
    client = adapter.flask_app.test_client()
    # GET collection (the generated handler returns meta)
    response = client.get("/pets")
    assert response.status_code == 200, response.get_data(as_text=True)
    payload = _json(response)
    assert payload["meta"]["resource"] == "pet"
    assert payload["meta"]["count"] == 0
    # path parameter flows through
    response = client.get("/pets/42")
    assert response.status_code == 200
    assert _json(response)["data"]["id"] == "42"
    # POST with a JSON body returns 201
    response = client.post("/pets", json={"name": "rex"})
    assert response.status_code == 201, response.get_data(as_text=True)


def test_generated_crud_routes_execute_with_service(tmp_path: Path) -> None:
    """A `bet make crud` router executes the full CRUD flow with a service.

    This exercises the Resource -> Service -> Repository integration through
    the *generated* code (Task 07.5 output) mounted on the runtime layer.
    """
    from betrayer.generators.crud import CrudGenerator

    for mod in list(sys.modules):
        if mod == "product" or mod.startswith("product."):
            sys.modules.pop(mod, None)
    generator = CrudGenerator(name="product", output_dir=tmp_path)
    generator.generate()
    parent = str(tmp_path)
    if parent not in sys.path:
        sys.path.insert(0, parent)
    from product.routes import register_routes, router as product_router

    register_routes(product_router)

    class ItemModel(Model):
        id: int = Field(int, default=None, description="Primary key")
        name: str = Field(str, required=True, description="Item name")
        price: int = Field(int, default=0, description="Price")

    class ItemService:
        """The generated ProductService contract: returns Model instances."""

        def __init__(self):
            self._items = {}
            self._next = 1

        def list(self):
            return list(self._items.values())

        def get(self, identifier):
            return self._items.get(int(identifier))

        def create(self, **data):
            item = ItemModel.from_dict(data)
            item.id = self._next
            self._items[self._next] = item
            self._next += 1
            return item

        def update(self, identifier, **data):
            identifier = int(identifier)
            if identifier not in self._items:
                return None
            for key, value in data.items():
                setattr(self._items[identifier], key, value)
            return self._items[identifier]

        def delete(self, identifier):
            return self._items.pop(int(identifier), None) is not None

    service = ItemService()
    application = BetrayerApplication(name="gen-crud-e2e")
    application.core.container.instance("product_service", service)

    adapter = FlaskAdapter(application, product_router)
    adapter.build()
    client = adapter.flask_app.test_client()

    # create -> list -> get -> update -> delete -> 404
    assert client.post("/products", json={"name": "x", "price": 1}).status_code == 201
    listed = _json(client.get("/products"))
    assert listed["meta"]["count"] == 1
    assert client.get("/products/1").status_code == 200
    updated = _json(client.put("/products/1", json={"price": 9}))
    assert updated["data"]["price"] == 9
    assert client.delete("/products/1").status_code == 204
    assert client.get("/products/1").status_code == 404