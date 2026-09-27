"""Product Catalog - the canonical Betrayer Golden Path example.

This package is the single, runnable proof of the Betrayer end-to-end flow::

    Project -> Module -> Model -> Migration -> Database
        -> Repository -> Service -> Resource/API -> Run -> Test -> Debug

Public API::

    build_config          configuration for the catalog (SQLite by default)
    build_application     bootstrap the application + database + module
    create_flask_app      a Flask app serving the HTTP API
    APP_NAME              the application name

Run it over HTTP with ``python example/product_catalog/run.py``.
"""

from __future__ import annotations

from example.product_catalog.app import (
    APP_NAME,
    build_application,
    build_config,
    create_flask_app,
)

__all__ = [
    "APP_NAME",
    "build_application",
    "build_config",
    "create_flask_app",
]
