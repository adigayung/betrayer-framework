"""Migration abstraction: deterministic migration registry.

Migrations are ordered, discoverable operations that transform the database
schema/data.  Each migration has:
- A unique identity (name or version)
- An order/sequence number for deterministic execution
- ``up()`` and ``down()`` methods (or equivalent)
- Programmatic discoverability via registry

Design rules:
- ``Migration`` is an abstract base; concrete migrations subclass it.
- ``MigrationRegistry`` stores registered migrations (ordered by sequence).
- Migrations are discoverable via ``list_migrations()`` for CLI/metadata.
- No complex migration engine — simple, predictable, explicit.
"""

from __future__ import annotations

import abc
from typing import Any, Dict, List, Optional, Sequence

from betrayer.data.database import DatabaseManager
from betrayer.data.exceptions import MigrationError


class Migration(abc.ABC):
    """A single, ordered database migration.

    Parameters
    ----------
    name : str
        Unique human-readable name for this migration.
    sequence : int
        Deterministic order number (lower runs first).
    description : Optional[str]
        Optional human-readable description.
    """

    def __init__(
        self,
        name: str,
        sequence: int,
        description: Optional[str] = None,
    ) -> None:
        if not name or not name.strip():
            raise MigrationError(
                message="Migration name must not be empty",
                stage="init",
            )
        self._name: str = name.strip()
        self._sequence: int = sequence
        self._description: str = description or ""

    # ── Properties ──────────────────────────────────────────────────────

    @property
    def name(self) -> str:
        """Unique migration name."""
        return self._name

    @property
    def sequence(self) -> int:
        """Deterministic order number."""
        return self._sequence

    @property
    def description(self) -> str:
        """Optional description."""
        return self._description

    # ── Abstract hooks ──────────────────────────────────────────────────

    @abc.abstractmethod
    def up(self, database: DatabaseManager) -> None:
        """Apply the migration (schema/data changes)."""
        ...  # pragma: no cover

    @abc.abstractmethod
    def down(self, database: DatabaseManager) -> None:
        """Revert the migration."""
        ...  # pragma: no cover

    # ── Introspection ───────────────────────────────────────────────────

    def introspect(self) -> Dict[str, Any]:
        """Machine readable metadata for LLM inspection."""
        return {
            "type": "migration",
            "name": self._name,
            "sequence": self._sequence,
            "description": self._description,
        }

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"Migration(name={self._name!r}, "
            f"sequence={self._sequence}, "
            f"description={self._description!r})"
        )


class MigrationRegistry:
    """Deterministic registry of database migrations.

    Migrations are ordered by ``sequence``.  Duplicate sequence numbers
    raise ``MigrationError``.  The registry is discoverable for CLI/metadata.
    """

    def __init__(self) -> None:
        self._migrations: Dict[str, Migration] = {}
        self._by_sequence: Dict[int, Migration] = {}

    # ── Registration ────────────────────────────────────────────────────

    def register(self, migration: Migration) -> None:
        """Register a migration.

        Raises ``MigrationError`` on duplicate name or sequence.
        """
        if migration.name in self._migrations:
            raise MigrationError(
                message=f"Migration {migration.name!r} already registered",
                stage="register",
            )
        if migration.sequence in self._by_sequence:
            existing = self._by_sequence[migration.sequence]
            raise MigrationError(
                message=(
                    f"Sequence {migration.sequence} already used by "
                    f"{existing.name!r}"
                ),
                stage="register",
            )
        self._migrations[migration.name] = migration
        self._by_sequence[migration.sequence] = migration

    def unregister(self, name: str) -> None:
        """Remove a migration by name."""
        migration = self._migrations.pop(name, None)
        if migration is not None:
            self._by_sequence.pop(migration.sequence, None)

    # ── Lookup ──────────────────────────────────────────────────────────

    def get(self, name: str) -> Optional[Migration]:
        """Get a migration by name."""
        return self._migrations.get(name)

    def has(self, name: str) -> bool:
        """Check if a migration is registered."""
        return name in self._migrations

    def ordered(self) -> Sequence[Migration]:
        """Return migrations sorted by sequence (ascending)."""
        return sorted(self._migrations.values(), key=lambda m: m.sequence)

    def count(self) -> int:
        """Number of registered migrations."""
        return len(self._migrations)

    def clear(self) -> None:
        """Remove all migrations (for testing)."""
        self._migrations.clear()
        self._by_sequence.clear()

    # ── Introspection ───────────────────────────────────────────────────

    def introspect(self) -> Dict[str, Any]:
        """Machine readable metadata for LLM inspection."""
        return {
            "type": "migration_registry",
            "count": self.count(),
            "migrations": [m.introspect() for m in self.ordered()],
        }

    def __repr__(self) -> str:  # pragma: no cover
        return f"MigrationRegistry(count={self.count()})"


__all__ = [
    "Migration",
    "MigrationRegistry",
]