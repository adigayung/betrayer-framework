"""Task 10 - Golden Path end-to-end integration tests.

Proves the canonical Betrayer flow works as one path, not as isolated pieces::

    Project -> Module -> Model -> Migration -> Database
        -> Repository -> Service -> Resource/API -> Run -> Test -> Debug

The suite exercises the *real* framework: the CLI generators, the ORM +
Repository, the migration registry, the SQLite engine, the Resource/API runtime
and a real Flask test client, all over a real SQLite file.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from betrayer import BetrayerApplication
from betrayer.cli.main import main as cli
from betrayer.core.config import Config
from betrayer.data import DatabaseManager, MigrationRegistry
from betrayer.data.bootstrap import build_database_manager, install_database

from example.product_catalog.app import (
    APP_NAME,
    apply_migrations,
    build_application,
    create_flask_app,
)
from example.product_catalog.models import Product


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_module_from_path(path: Path, name: str) -> Any:
    """Import a Python file by path under a synthetic module name."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _json(response: Any) -> dict:
    return json.loads(response.get_data(as_text=True))


def _inspect_table_rows(database_path: Path, table: str = "products") -> list:
    """Open a brand new connection on the same file and read every row."""
    manager = build_database_manager(
        Config(
            {
                "database.default.driver": "sqlite",
                "database.default.database": str(database_path),
            }
        )
    )
    try:
        from betrayer.data import Query

        return Query(table, database=manager).get()
    finally:
        manager.disconnect()


# ---------------------------------------------------------------------------
# 1-4. Project / module / migration generators + database
# ---------------------------------------------------------------------------


def test_project_can_be_bootstrapped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`bet create <name>` produces a bootstrappable application project."""
    monkeypatch.chdir(tmp_path)
    assert cli(["create", "shop"]) == 0
    assert (tmp_path / "shop" / "run.py").is_file()
    assert (tmp_path / "shop" / "shop" / "app.py").is_file()


def test_module_generator_reusable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`bet make module` produces a real Module package."""
    monkeypatch.chdir(tmp_path)
    assert cli(["make", "module", "inventory"]) == 0
    assert (tmp_path / "inventory" / "module.py").is_file()
    assert (tmp_path / "inventory" / "__init__.py").is_file()


def test_migration_generator_creates_runnable_migration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A generated migration is created *and* runs against a real database."""
    monkeypatch.chdir(tmp_path)
    assert cli(["make", "migration", "create_products_table"]) == 0
    files = list((tmp_path / "migrations").glob("*_create_products_table.py"))
    assert len(files) == 1

    from betrayer.data.migration import Migration

    module = _load_module_from_path(files[0], "golden_generated_migration")
    migration_cls = next(
        obj
        for obj in vars(module).values()
        if isinstance(obj, type) and issubclass(obj, Migration) and obj is not Migration
    )
    instance = migration_cls()

    database = build_database_manager(
        Config(
            {
                "database.default.driver": "sqlite",
                "database.default.database": str(tmp_path / "gen.db"),
            }
        )
    )
    try:
        registry = MigrationRegistry()
        registry.register(instance)
        applied = registry.apply(database)
        assert applied == [instance.name]
        rolled_back = registry.rollback(database)
        assert rolled_back == [instance.name]
    finally:
        database.disconnect()


def test_application_wires_database_module_and_schema(tmp_path: Path) -> None:
    """`build_application` connects the DB, registers the module and migrates."""
    db_path = tmp_path / "catalog.db"
    app = build_application(database_path=db_path)

    # Database service is connected and canonical.
    database = app.container.resolve("database")
    assert isinstance(database, DatabaseManager)
    assert database.is_connected is True

    # Module registered its services.
    assert app.core.modules.names() == ["product_catalog"]
    assert "products_repository" in app.container
    assert "products_service" in app.container

    # Migration created the schema (real table in the real file).
    tables = {
        row["name"]
        for row in database.execute("SELECT name FROM sqlite_master").get("rows", [])
    }
    assert "products" in tables


# ---------------------------------------------------------------------------
# 5-7. HTTP CRUD against SQLite via the Resource/API layer
# ---------------------------------------------------------------------------


@pytest.fixture
def catalog(tmp_path: Path) -> tuple:
    """A built catalog app + Flask test client + the SQLite file path."""
    db_path = tmp_path / "catalog.db"
    app = build_application(database_path=db_path)
    flask_app = create_flask_app(app)
    return app, flask_app.test_client(), db_path


def test_http_crud_lifecycle(catalog: tuple) -> None:
    """POST / GET / GET collection / PUT / DELETE all work over HTTP."""
    _app, client, _db = catalog

    created = client.post("/api/products", json={"name": "Widget", "price": 9.5, "stock": 3})
    assert created.status_code == 201
    body = _json(created)
    assert body["success"] is True
    assert body["data"]["name"] == "Widget"
    product_id = body["data"]["id"]

    collection = client.get("/api/products")
    assert collection.status_code == 200
    assert _json(collection)["meta"] == {"count": 1, "resource": "products"}

    single = client.get(f"/api/products/{product_id}")
    assert single.status_code == 200
    assert _json(single)["data"]["price"] == 9.5

    updated = client.put(f"/api/products/{product_id}", json={"price": 12.0, "stock": 5})
    assert updated.status_code == 200
    assert _json(updated)["data"]["price"] == 12.0
    assert _json(updated)["data"]["stock"] == 5

    deleted = client.delete(f"/api/products/{product_id}")
    assert deleted.status_code == 204

    assert client.get(f"/api/products/{product_id}").status_code == 404
    assert _json(client.get("/api/products"))["meta"]["count"] == 0


def test_changes_persist_in_sqlite(catalog: tuple) -> None:
    """Every write really reached the SQLite file (verified on a new connection)."""
    _app, client, db_path = catalog

    body = _json(client.post("/api/products", json={"name": "Persisted", "price": 1.0, "stock": 2}))
    product_id = body["data"]["id"]
    client.put(f"/api/products/{product_id}", json={"stock": 7})

    rows = _inspect_table_rows(db_path)
    assert len(rows) == 1
    assert rows[0]["name"] == "Persisted"
    assert rows[0]["stock"] == 7


def test_validation_and_error_responses(catalog: tuple) -> None:
    """The Resource/API layer answers with its documented, controlled errors."""
    _app, client, _db = catalog

    # 422 - missing required field, raised by the service as ValidationError.
    missing = client.post("/api/products", json={"price": 1})
    assert missing.status_code == 422
    assert _json(missing)["error"]["code"] == "VALIDATION_FAILED"

    # 400 - body is not JSON.
    bad_body = client.post("/api/products", data="nope", content_type="text/plain")
    assert bad_body.status_code == 400
    assert _json(bad_body)["error"]["code"] == "BAD_REQUEST"

    # 404 - missing resource.
    not_found = client.get("/api/products/424242")
    assert not_found.status_code == 404
    assert _json(not_found)["error"]["code"] == "RESOURCE_NOT_FOUND"


# ---------------------------------------------------------------------------
# 8. Generated modules reuse the canonical database service
# ---------------------------------------------------------------------------


def test_generated_resource_module_uses_canonical_database_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`bet make resource` output registers against the canonical "database"."""
    monkeypatch.chdir(tmp_path)
    assert cli(["make", "resource", "article"]) == 0

    sys.path.insert(0, str(tmp_path))
    try:
        module = importlib.import_module("article")
        module_class = module.ArticleResourceModule

        app = BetrayerApplication(
            name="gen-app",
            config=Config(
                {
                    "database.default.driver": "sqlite",
                    "database.default.database": str(tmp_path / "gen.db"),
                }
            ),
        )
        install_database(app)
        app.modules.register(module_class)

        assert "article_repository" in app.container
        repository = app.container.resolve("article_repository")
        assert repository.model_class.__name__ == "ArticleModel"
    finally:
        sys.path.remove(str(tmp_path))
        for name in list(sys.modules):
            if name == "article" or name.startswith("article."):
                sys.modules.pop(name, None)


# ---------------------------------------------------------------------------
# 9. Debug / diagnostics use the existing mechanisms
# ---------------------------------------------------------------------------


def test_diagnostics_use_existing_mechanisms(catalog: tuple) -> None:
    """Diagnosis reuses the existing inspector + error contract, not a new one."""
    app, client, db_path = catalog

    # Existing introspection: application status + core report.
    status = app.status()
    assert status["application"] == APP_NAME
    assert status["state"] == "ready"
    report = app.core.report()
    assert "product_catalog" in report["modules"]["modules"]

    # A database failure is diagnosable through the structured error contract:
    # it comes back as a controlled JSON error (code + message), never a
    # leaked traceback.
    database = app.container.resolve("database")
    database.execute('DROP TABLE "products"')
    response = client.post("/api/products", json={"name": "boom", "price": 1, "stock": 1})
    assert response.status_code == 500
    payload = _json(response)
    assert payload["success"] is False
    assert payload["error"]["code"]
    assert "Traceback" not in response.get_data(as_text=True)


def test_apply_migrations_is_idempotent(tmp_path: Path) -> None:
    """Re-applying the schema migration is safe (IF NOT EXISTS)."""
    db_path = tmp_path / "catalog.db"
    app = build_application(database_path=db_path)
    applied = apply_migrations(app)
    assert applied == ["create_products_table"]
    assert getattr(Product, "table_name")() == "products"
