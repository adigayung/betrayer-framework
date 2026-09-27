"""Migration generator for the Betrayer Framework.

Creates a new database migration file inside an existing Betrayer project.  A
migration is a single, ordered, reversible schema/data change following the
framework's :class:`betrayer.data.migration.Migration` contract: a class with
a unique ``name``, a deterministic ``sequence`` number and ``up()`` / ``down()``
hooks.

The generator writes one ``.py`` file per migration into a top level
``migrations/`` package.  File names are ``<sequence>_<snake_case>.py`` so a
directory listing is already in execution order -- the same deterministic
``snake_case`` convention the framework uses everywhere else.

Example usage::

    bet make migration create_users_table
    bet make migration add_index_on_orders --force
    bet make migration add-email-column --json

Scope: this generator ONLY creates a migration file skeleton.  It reuses the
exact abstractions the framework already provides (``BaseGenerator``,
``GeneratorError``, ``GeneratorOutput``, the naming helpers and the
``Migration`` contract) and never touches existing migrations.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from betrayer.generators.base import (
    BaseGenerator,
    GeneratorError,
    GeneratorOutput,
    package_name,
    validate_project_name,
)

__all__ = ["MigrationGenerator", "validate_migration_name", "MIGRATION_DIRECTORY"]

#: Directory (relative to the project root) migration files are written into.
MIGRATION_DIRECTORY = "migrations"


def validate_migration_name(name: str) -> Optional[str]:
    """Return a human readable error message, or ``None`` when ``name`` is OK.

    Migration names follow the same convention as project / module / resource
    names (letters, digits, ``-`` and ``_``; must start with a letter) so the
    CLI surface stays consistent.  The message is phrased in terms of a
    *migration* though.
    """
    error = validate_project_name(name)
    if error:
        return error.replace("project name", "migration name")
    return None


class MigrationGenerator(BaseGenerator):
    """Generate a new database migration file.

    ``name`` is the name chosen on the command line (for example
    ``create-users-table``); the importable module is
    ``migrations.<sequence>_<snake_case>`` and the generated class is
    ``<TitleCase>Migration``.  The ``sequence`` defaults to a ``YYmmddHHMM``
    timestamp so a fresh migration sorts after every migration generated
    earlier -- pass ``sequence`` explicitly for a deterministic value (tests).
    """

    name = "migration"
    description = "Create a new database migration file in the current project"

    def __init__(
        self,
        name: str,
        output_dir: Path,
        overwrite: bool = False,
        *,
        sequence: Optional[int] = None,
    ) -> None:
        error = validate_migration_name(name)
        if error:
            raise GeneratorError(f"invalid migration name: {error}")
        self.requested_name = name
        self.slug = package_name(name)
        self._sequence = sequence
        super().__init__(output_dir=Path(output_dir), overwrite=overwrite)

    # ── naming ─────────────────────────────────────────────────────

    @property
    def target(self) -> Path:
        """The ``migrations`` directory the new file is created in."""
        return self.output_dir / MIGRATION_DIRECTORY

    @property
    def sequence(self) -> int:
        """Deterministic order number (lower runs first).

        When ``overwrite`` is True and no explicit sequence was provided,
        the existing migration file's sequence is reused so that the
        generator replaces the current migration rather than creating a
        new, unrelated one with a fresh timestamp.
        """
        if self._sequence is not None:
            return self._sequence
        if self.overwrite:
            existing = self._existing_migration_sequence()
            if existing is not None:
                return existing
        return int(datetime.now().strftime("%y%m%d%H%M"))

    def _existing_migration_sequence(self) -> Optional[int]:
        """Return the sequence of an existing migration with the same slug."""
        pattern = f"{self.slug}.py"
        if not self.target.exists():
            return None
        for entry in self.target.iterdir():
            if not entry.name.endswith(".py"):
                continue
            # File names are ``<sequence>_<slug>.py``; strip the suffix
            # to isolate the sequence prefix.
            stem = entry.name[:-3]
            if not stem.endswith(f"_{self.slug}"):
                continue
            sequence_str = stem[: len(stem) - len(self.slug) - 1]
            if sequence_str.isdigit():
                return int(sequence_str)
        return None

    @property
    def migration_name(self) -> str:
        """The migration's unique ``name`` (e.g. ``create_users_table``)."""
        return self.slug

    @property
    def file_name(self) -> str:
        """File name of the generated migration (``<sequence>_<slug>.py``)."""
        return f"{self.sequence}_{self.slug}.py"

    @property
    def class_name(self) -> str:
        """Name of the generated :class:`~betrayer.data.migration.Migration` subclass."""
        title = "".join(part.capitalize() for part in self.slug.split("_"))
        return f"{title}Migration"

    @property
    def module_import(self) -> str:
        """The importable module path (``migrations.<sequence>_<slug>``)."""
        return f"{MIGRATION_DIRECTORY}.{self.file_name[:-3]}"

    # ── structure ──────────────────────────────────────────────────

    def _files(self) -> Dict[str, str]:
        """Deterministic mapping of relative path -> file content."""
        return {
            f"{MIGRATION_DIRECTORY}/{self.file_name}": self._migration_py(),
        }

    def _migration_py(self) -> str:
        class_name = self.class_name
        return f'''"""Migration ``{self.migration_name}``.

Generated by ``bet make migration {self.requested_name}``.

Implements the :class:`betrayer.data.migration.Migration` contract: ``up``
applies the schema/data change, ``down`` reverts it.  Keep this file
deterministic and idempotent -- migrations run once, in ``sequence`` order.
"""

from __future__ import annotations

from betrayer.data.database import DatabaseManager
from betrayer.data.migration import Migration

__all__ = ["{class_name}"]


class {class_name}(Migration):
    """``{self.migration_name}`` migration (sequence {self.sequence})."""

    name = "{self.migration_name}"
    sequence = {self.sequence}
    description = "{self.migration_name}"

    def __init__(self) -> None:
        # ``Migration`` stores its identity in instance attributes, so the
        # class level defaults must be passed through the base constructor.
        super().__init__(
            name=self.name,
            sequence=self.sequence,
            description=self.description,
        )

    def up(self, database: DatabaseManager) -> None:
        """Apply the migration (schema/data changes)."""
        # Example: database.execute("CREATE TABLE ...")

    def down(self, database: DatabaseManager) -> None:
        """Revert the migration."""
        # Example: database.execute("DROP TABLE ...")
'''

    # ── generation ─────────────────────────────────────────────────

    def generate(self) -> GeneratorOutput:
        """Create the migration file (and the ``migrations`` package once).

        Raises :class:`GeneratorError` when the migration file already exists
        and ``overwrite`` is False, so an existing migration is never
        overwritten silently.
        """
        if not self.overwrite and self._target_occupied():
            raise GeneratorError(
                "migration already exists (use --force to overwrite): "
                f"{self.target / self.file_name}"
            )
        self._ensure_directory(self.target)
        for relative, content in self._files().items():
            try:
                self._write(relative, content)
            except GeneratorError as exc:  # pragma: no cover - defensive
                self.output.add_error(relative, exc)
        return self.output

    def _target_occupied(self) -> bool:
        """True when the migration file already exists."""
        return (self.target / self.file_name).exists()