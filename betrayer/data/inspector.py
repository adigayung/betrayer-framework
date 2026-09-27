"""Data Layer inspector: machine-readable metadata for LLM introspection.

The inspector provides a deterministic snapshot of the Data Layer state
including registered databases, models, repositories, migrations, cache
backends, storage backends, and active configuration (secrets masked).
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from betrayer.data.database import DatabaseManager
from betrayer.data.registry import DatabaseRegistry
from betrayer.data.models import Model
from betrayer.data.repository import Repository
from betrayer.data.migration import MigrationRegistry
from betrayer.data.cache import CacheManager
from betrayer.data.storage import StorageManager


class DataInspector:
    """Collects and returns Data Layer metadata for LLM inspection.

    Usage::

        inspector = DataInspector(
            db_manager=...,
            migration_registry=...,
            cache_manager=...,
            storage_manager=...,
        )
        print(inspector.summary())
    """

    def __init__(
        self,
        db_manager: Optional[DatabaseManager] = None,
        db_registry: Optional[DatabaseRegistry] = None,
        migration_registry: Optional[MigrationRegistry] = None,
        cache_manager: Optional[CacheManager] = None,
        storage_manager: Optional[StorageManager] = None,
    ) -> None:
        self._db_manager = db_manager
        self._db_registry = db_registry
        self._migration_registry = migration_registry
        self._cache_manager = cache_manager
        self._storage_manager = storage_manager
        self._models: Dict[str, type] = {}
        self._repositories: Dict[str, Repository] = {}

    def register_model(self, name: str, model_cls: type) -> None:
        """Register a Model class for introspection."""
        self._models[name] = model_cls

    def register_repository(self, name: str, repo: Repository) -> None:
        """Register a Repository instance for introspection."""
        self._repositories[name] = repo

    def to_dict(self) -> Dict[str, Any]:
        """Return deterministic, machine-readable metadata dictionary."""
        db_info = {}
        if self._db_registry is not None:
            db_info["registry"] = self._db_registry.introspect()
        if self._db_manager is not None:
            raw = self._db_manager.to_dict()
            # mask connection secrets
            if "metadata" in raw and isinstance(raw["metadata"], dict):
                meta = dict(raw["metadata"])
                for secret_key in ("password", "dsn", "url", "connection_string"):
                    if secret_key in meta:
                        meta[secret_key] = "****"
                raw["metadata"] = meta
            db_info["manager"] = raw
        db_summary = db_info or None

        models_info = {}
        for name, cls in self._models.items():
            if hasattr(cls, "_fields"):
                fields = [
                    {
                        "name": f.name if hasattr(f, "name") else str(f),
                        "type": getattr(f, "field_type", None),
                        "required": getattr(f, "required", None),
                        "default": getattr(f, "default", None),
                    }
                    for f in cls._fields  # type: ignore[attr-defined]
                ]
            else:
                fields = []
            models_info[name] = {
                "class": f"{cls.__module__}.{cls.__qualname__}",
                "fields": fields,
            }

        repos_info = {}
        for name, repo in self._repositories.items():
            repos_info[name] = {
                "class": f"{type(repo).__module__}.{type(repo).__qualname__}",
                "model": getattr(repo, "_model_cls", None),
            }

        migrations_info = None
        if self._migration_registry is not None:
            migrations_info = {
                "count": len(self._migration_registry._migrations),
                "applied": list(self._migration_registry._applied),
                "pending": list(self._migration_registry._pending),
                "migrations": [
                    {
                        "name": m.name,
                        "sequence": m.sequence,
                        "description": getattr(m, "description", ""),
                    }
                    for m in self._migration_registry._migrations
                ],
            }

        cache_info = None
        if self._cache_manager is not None:
            cache_info = {
                "backend": type(self._cache_manager._backend).__name__,
            }

        storage_info = None
        if self._storage_manager is not None:
            storage_info = {
                "backend": type(self._storage_manager._backend).__name__,
                "base_path": str(self._storage_manager._base_path),
            }

        return {
            "database": db_info,
            "models": models_info,
            "repositories": repos_info,
            "migrations": migrations_info,
            "cache": cache_info,
            "storage": storage_info,
        }

    def summary(self) -> str:
        """Human-readable one-line summary."""
        parts = []
        d = self.to_dict()
        db_info = d.get("database") or {}
        if "manager" in db_info:
            parts.append(f"database:{db_info['manager'].get('engine', '?')}")
        elif "registry" in db_info:
            connections = db_info["registry"].get("connections", {})
            parts.append(
                "database_registry:"
                + ",".join(sorted(connections))
                if connections
                else "database_registry:0"
            )
        if d.get("models"):
            parts.append(f"models:{len(d['models'])}")
        if d.get("repositories"):
            parts.append(f"repositories:{len(d['repositories'])}")
        if d.get("migrations"):
            parts.append(f"migrations:{d['migrations']['count']}")
        if d.get("cache"):
            parts.append(f"cache:{d['cache'].get('backend','?')}")
        if d.get("storage"):
            parts.append(f"storage:{d['storage'].get('backend','?')}")
        return "DataLayer(" + ", ".join(parts) + ")" if parts else "DataLayer(empty)"


__all__ = [
    "DataInspector",
]