"""Product Catalog application - the composition root of the Golden Path.

Every Golden Path step is here, in order, using only existing Betrayer APIs::

    Config            configure the app + SQLite database
    Bootstrap         deterministic start-up
    install_database  connect SQLite and register the "database" service
    Module            register the repository + service
    Migration         create the schema
    FlaskAdapter      serve the resource over HTTP

``build_application`` returns a READY application; ``create_flask_app`` returns a
real Flask app serving the REST API.  Run it over HTTP with
``python example/product_catalog/run.py``.
"""

from __future__ import annotations

from typing import Any, Optional

from betrayer import BetrayerApplication, Bootstrap, Config
from betrayer.data import MigrationRegistry
from betrayer.data.bootstrap import install_database
from betrayer.web import FlaskAdapter

from example.product_catalog.migrations import MIGRATIONS
from example.product_catalog.module import ProductCatalogModule, SERVICE_KEY
from example.product_catalog.product_channel import (
    PRODUCT_CHANNEL,
    PRODUCT_CREATED_EVENT,
    build_realtime,
    build_websocket_app,
)
from example.product_catalog.routes import ProductResource

__all__ = [
    "APP_NAME",
    "DEFAULT_DATABASE",
    "PRODUCT_CHANNEL",
    "PRODUCT_CREATED_EVENT",
    "build_config",
    "build_application",
    "migration_registry",
    "apply_migrations",
    "create_flask_app",
    "create_realtime_app",
]

#: Application name reported by ``app.status()`` / introspection.
APP_NAME = "product_catalog"

#: Default SQLite file (relative to the current working directory).
DEFAULT_DATABASE = "product_catalog.db"


def build_config(database_path: Optional[str] = None) -> Config:
    """Return the catalog configuration (SQLite by default)."""
    return Config(
        {
            "app.name": APP_NAME,
            "app.debug": True,
            "database.default.driver": "sqlite",
            "database.default.database": str(database_path or DEFAULT_DATABASE),
        }
    )


def migration_registry() -> MigrationRegistry:
    """A registry holding the catalog migrations in ``sequence`` order."""
    registry = MigrationRegistry()
    for migration in MIGRATIONS:
        registry.register(migration)
    return registry


def apply_migrations(application: BetrayerApplication) -> list:
    """Apply the catalog migrations to the application database."""
    database = application.container.resolve("database")
    return migration_registry().apply(database)


def build_application(
    database_path: Optional[str] = None,
    *,
    run_migrations: bool = True,
) -> BetrayerApplication:
    """Bootstrap the catalog application, database, module and schema.

    Canonical order (see the module docstring).  Returns the READY application
    so it can be inspected (``app.status()``, ``app.core.report()``) or served.
    """
    application = BetrayerApplication(name=APP_NAME, config=build_config(database_path))
    Bootstrap(application).build()

    # Database first: the module resolves it during registration.
    install_database(application)

    # Module: binds the ORM model and registers repository + service.
    application.modules.register(ProductCatalogModule)
    application.modules.initialize_all()

    # Schema: migrations create the tables the repository writes to.
    if run_migrations:
        apply_migrations(application)

    return application


def create_flask_app(
    application: Optional[BetrayerApplication] = None,
    *,
    database_path: Optional[str] = None,
) -> Any:
    """Return a Flask app serving the catalog REST API.

    The HTTP engine stays the thin edge: the resource is mounted through the
    framework :class:`~betrayer.web.adapter.FlaskAdapter`.
    """
    application = application or build_application(database_path=database_path)
    resource = ProductResource()
    adapter = FlaskAdapter(application, resource.resource_router())
    return adapter.build()


def create_realtime_app(
    application: Optional[BetrayerApplication] = None,
    *,
    database_path: Optional[str] = None,
) -> Any:
    """Return the Flask app with the WebSocket blueprint mounted.

    The REST API (via :class:`~betrayer.web.adapter.FlaskAdapter`) and the
    realtime channel (via :class:`~betrayer.web.ws_adapter.FlaskRealtimeAdapter`)
    share the *same* Flask app.  Inbound WebSocket messages reuse the same
    ``ProductService`` as the HTTP resource, so no business logic is duplicated.
    """
    application = application or build_application(database_path=database_path)
    # REST first (builds the underlying Flask app).
    flask_app = create_flask_app(application)
    # Realtime manager + WebSocket blueprint on the same app.
    manager = build_realtime(application)
    service = application.container.resolve(SERVICE_KEY)
    return build_websocket_app(flask_app, manager, service)
