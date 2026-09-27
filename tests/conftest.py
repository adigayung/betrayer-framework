"""Canonical Betrayer test fixtures.

Reuses pytest's fixture mechanism.  These are the *only* shared fixtures
provided by the framework; every project can add project-specific fixtures
in a local ``conftest.py``.

Available fixtures
------------------
application
    A READY BetrayerApplication (no database, no modules).
database_path
    Path to a temporary SQLite file (deleted after the test).
database_config
    Config pointing to a temporary SQLite database.
database_manager
    A connected DatabaseManager over a temporary SQLite file.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, Generator

import pytest

from betrayer import BetrayerApplication, Bootstrap, Config


# ── application ──────────────────────────────────────────────────


@pytest.fixture(scope="function")
def application() -> Generator[BetrayerApplication, None, None]:
    """A READY Betrayer application (no database, no modules)."""
    app = BetrayerApplication(name="test-app")
    Bootstrap(app).build()
    yield app
    try:
        app.shutdown()
    except Exception:  # noqa: BLE001 - best-effort cleanup
        pass


# ── database (temporary SQLite) ──────────────────────────────────


@pytest.fixture(scope="function")
def database_path() -> Generator[Path, None, None]:
    """Path to a temporary SQLite file (deleted after the test)."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = Path(f.name)
    yield path
    try:
        path.unlink(missing_ok=True)
    except Exception:  # noqa: BLE001 - best-effort cleanup
        pass


@pytest.fixture(scope="function")
def database_config(database_path: Path) -> Config:
    """Config that points to a temporary SQLite database."""
    return Config(
        {
            "app.name": "test-app",
            "app.debug": True,
            "database.default.driver": "sqlite",
            "database.default.database": str(database_path),
        }
    )


@pytest.fixture(scope="function")
def database_manager(database_config: Config) -> Any:
    """A connected DatabaseManager over a temporary SQLite file.

    The connection is closed (best-effort) after the test.
    """
    from betrayer.data.bootstrap import build_database_manager

    manager = build_database_manager(database_config)
    yield manager
    try:
        manager.disconnect()
    except Exception:  # noqa: BLE001 - best-effort cleanup
        pass