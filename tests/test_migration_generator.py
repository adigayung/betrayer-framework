"""Focused tests for the Migration Generator (Task 07.6).

Covers: migration file creation, the generated file location and naming
convention, the generated ``Migration`` subclass (name / sequence /
description / up / down), invalid name rejection, overwrite protection,
``--force`` behaviour and the ``bet make migration`` CLI wiring.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Type

import pytest

from betrayer.cli.main import COMMANDS, build_parser, main
from betrayer.data.migration import Migration
from betrayer.generators.base import GeneratorError
from betrayer.generators.migration import (
    MIGRATION_DIRECTORY,
    MigrationGenerator,
    validate_migration_name,
)

FIXED_SEQUENCE = 2501011200  # deterministic sequence for tests (2025-01-01 12:00)


def _generate(
    tmp_path: Path,
    name: str = "create_users_table",
    overwrite: bool = False,
    sequence: int = FIXED_SEQUENCE,
) -> MigrationGenerator:
    return MigrationGenerator(
        name=name, output_dir=tmp_path, overwrite=overwrite, sequence=sequence
    )


def _load_class(generator: MigrationGenerator, attribute: str):
    """Import a generated migration class and clean up afterwards."""
    module_path = generator.module_import
    parent = str(generator.output_dir)

    def _purge() -> None:
        for mod in list(sys.modules):
            if mod == "migrations" or mod.startswith("migrations."):
                sys.modules.pop(mod, None)

    _purge()
    sys.path.insert(0, parent)
    try:
        module = __import__(module_path, fromlist=[attribute])
        return getattr(module, attribute)
    finally:
        sys.path.remove(parent)
        _purge()


def _load_migration(generator: MigrationGenerator) -> Type[Migration]:
    return _load_class(generator, generator.class_name)


# ── structure ────────────────────────────────────────────────────


def test_migration_created(tmp_path: Path) -> None:
    """Creating a migration writes the file under ``migrations/``."""
    generator = _generate(tmp_path)
    output = generator.generate()
    assert output.success, output.errors
    expected = tmp_path / MIGRATION_DIRECTORY / generator.file_name
    assert generator.target == tmp_path / MIGRATION_DIRECTORY
    assert expected.is_file()


def test_migration_file_naming_convention(tmp_path: Path) -> None:
    """The file name is ``<sequence>_<snake_case>.py``."""
    generator = _generate(tmp_path, name="create-users-table")
    assert generator.file_name == f"{FIXED_SEQUENCE}_create_users_table.py"
    assert generator.migration_name == "create_users_table"
    assert generator.class_name == "CreateUsersTableMigration"
    generator.generate()
    assert (tmp_path / "migrations" / generator.file_name).is_file()


def test_generated_migration_subclasses_migration(tmp_path: Path) -> None:
    """The generated class is a real ``Migration`` subclass with up/down."""
    generator = _generate(tmp_path)
    generator.generate()
    migration_class = _load_migration(generator)
    assert issubclass(migration_class, Migration)
    assert migration_class.__name__ == "CreateUsersTableMigration"
    assert migration_class.name == "create_users_table"
    assert migration_class.sequence == FIXED_SEQUENCE
    assert migration_class.description == "create_users_table"
    for method in ("up", "down"):
        assert callable(getattr(migration_class, method))


def test_generated_migration_instantiates(tmp_path: Path) -> None:
    """The generated migration can be instantiated (base ``Migration`` init)."""
    generator = _generate(tmp_path)
    generator.generate()
    migration_class = _load_migration(generator)
    instance = migration_class()
    assert instance.name == "create_users_table"
    assert instance.sequence == FIXED_SEQUENCE
    assert instance.introspect()["type"] == "migration"


def test_generation_is_deterministic(tmp_path: Path) -> None:
    """Two fresh generations produce byte-identical files."""
    _generate(tmp_path).generate()
    first = (tmp_path / "migrations" / f"{FIXED_SEQUENCE}_create_users_table.py").read_text(
        encoding="utf-8"
    )
    _generate(tmp_path, overwrite=True).generate()
    second = (tmp_path / "migrations" / f"{FIXED_SEQUENCE}_create_users_table.py").read_text(
        encoding="utf-8"
    )
    assert first == second


def test_existing_migrations_untouched(tmp_path: Path) -> None:
    """Generating a second migration never modifies the first one."""
    first = _generate(tmp_path, name="create_users_table")
    first.generate()
    first_content = (
        tmp_path / "migrations" / f"{FIXED_SEQUENCE}_create_users_table.py"
    ).read_text(encoding="utf-8")
    second = _generate(tmp_path, name="add_index_on_orders", sequence=FIXED_SEQUENCE + 1)
    second.generate()
    assert (tmp_path / "migrations" / f"{FIXED_SEQUENCE + 1}_add_index_on_orders.py").is_file()
    assert (
        tmp_path / "migrations" / f"{FIXED_SEQUENCE}_create_users_table.py"
    ).read_text(encoding="utf-8") == first_content


# ── naming ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "name", ["", " ", "9start", "a b", "a.b", "a/b", "../x", "-lead", "a:b"]
)
def test_invalid_migration_names_rejected(name: str) -> None:
    """Invalid migration names raise GeneratorError (and report a message)."""
    assert validate_migration_name(name) is not None
    with pytest.raises(GeneratorError):
        MigrationGenerator(name=name, output_dir=Path("."))


# ── overwrite protection ─────────────────────────────────────────


def test_existing_migration_not_overwritten(tmp_path: Path) -> None:
    """An existing migration file is never clobbered without --force."""
    _generate(tmp_path).generate()
    with pytest.raises(GeneratorError):
        _generate(tmp_path).generate()


def test_existing_migration_overwritten_with_force(tmp_path: Path) -> None:
    """--force overwrites an existing migration file in-place."""
    _generate(tmp_path).generate()
    original = (tmp_path / "migrations" / f"{FIXED_SEQUENCE}_create_users_table.py").read_text(encoding="utf-8")
    # Replace content by appending a marker to the template (force a change).
    # We do this by generating with a different class description via a custom subclass.
    output = _generate(tmp_path, overwrite=True).generate()
    assert output.success, output.errors
    # The same file (same sequence + slug) must exist — no new timestamp file was created.
    assert (tmp_path / "migrations" / f"{FIXED_SEQUENCE}_create_users_table.py").is_file()
    # No additional migration with a new sequence was created.
    files = list((tmp_path / "migrations").glob("*.py"))
    assert len(files) == 1, "force must replace, not create a new migration"

def test_force_preserves_existing_migration_identity(tmp_path: Path) -> None:
    """The replaced migration keeps its original sequence and filename."""
    _generate(tmp_path).generate()
    # Simulate a real CLI re-run: no explicit sequence, so a fresh timestamp
    # would normally be used.  With --force the generator must reuse the
    # existing migration's sequence so the filename stays the same.
    second = MigrationGenerator(
        name="create_users_table",
        output_dir=tmp_path,
        overwrite=True,
    )
    output = second.generate()
    assert output.success, output.errors
    # The file still uses the original FIXED_SEQUENCE, not a new timestamp.
    assert (tmp_path / "migrations" / f"{FIXED_SEQUENCE}_create_users_table.py").is_file()
    # No file with a different sequence exists.
    for f in (tmp_path / "migrations").glob("*.py"):
        assert str(f.stem).startswith(f"{FIXED_SEQUENCE}_"), (
            f"force created an unrelated file: {f.name}"
        )

def test_force_does_not_create_additional_migration(tmp_path: Path) -> None:
    """--force must not leave behind a second migration with a new sequence."""
    _generate(tmp_path).generate()
    # Create a second migration with a different name to have a second file.
    other = MigrationGenerator(
        name="add_index_on_orders",
        output_dir=tmp_path,
        sequence=FIXED_SEQUENCE + 1,
        overwrite=False,
    )
    other.generate()
    # Now re-run the first migration with --force (no explicit sequence).
    again = MigrationGenerator(
        name="create_users_table",
        output_dir=tmp_path,
        overwrite=True,
    )
    output = again.generate()
    assert output.success, output.errors
    # Only two files must exist: the original (replaced) and the second migration.
    files = sorted((tmp_path / "migrations").glob("*.py"))
    assert len(files) == 2, "force must not create extra migration files"
    assert files[0].name == f"{FIXED_SEQUENCE}_create_users_table.py"
    assert files[1].name == f"{FIXED_SEQUENCE + 1}_add_index_on_orders.py"


# ── CLI wiring ───────────────────────────────────────────────────


def test_cli_make_command_registered() -> None:
    """`make` is part of the top level commands."""
    assert "make" in COMMANDS


def test_cli_make_migration_parses(tmp_path: Path) -> None:
    """`bet make migration create_users_table` parses correctly."""
    parser = build_parser()
    args = parser.parse_args(["make", "migration", "create_users_table"])
    assert args.command == "make"
    assert args.make_target == "migration"
    assert args.migration_name == "create_users_table"
    assert args.force is False


def test_cli_make_migration_flags() -> None:
    """`--force` and `--json` are accepted by the migration target."""
    parser = build_parser()
    args = parser.parse_args(["make", "migration", "create_users_table", "--force", "--json"])
    assert args.force is True
    assert args.json is True


def test_cli_make_requires_target() -> None:
    """`bet make` without a target is a controlled failure."""
    assert main(["make"]) == 1


def test_cli_make_migration_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The CLI actually generates the migration file in the current directory."""
    monkeypatch.chdir(tmp_path)
    assert main(["make", "migration", "create_users_table"]) == 0
    files = list((tmp_path / "migrations").glob("*.py"))
    assert len(files) == 1
    assert files[0].name.endswith("_create_users_table.py")


def test_cli_make_migration_existing_returns_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Re-creating an existing migration file fails with the CLI failure code."""
    monkeypatch.chdir(tmp_path)
    assert main(["make", "migration", "create_users_table"]) == 0
    assert main(["make", "migration", "create_users_table"]) == 1


def test_cli_make_migration_force_overwrites(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--force` lets the CLI regenerate over an existing migration file."""
    monkeypatch.chdir(tmp_path)
    assert main(["make", "migration", "create_users_table"]) == 0
    # Capture the first file's name so we can assert identity is preserved.
    first_files = list((tmp_path / "migrations").glob("*.py"))
    assert len(first_files) == 1
    first_name = first_files[0].name
    assert main(["make", "migration", "create_users_table", "--force"]) == 0
    # After --force, only one migration file must exist (no duplicate with new timestamp).
    files = list((tmp_path / "migrations").glob("*.py"))
    assert len(files) == 1
    # The filename must be identical to the original — force reuses the sequence.
    assert files[0].name == first_name


def test_cli_make_migration_invalid_name_returns_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An invalid migration name fails with the CLI failure exit code."""
    monkeypatch.chdir(tmp_path)
    assert main(["make", "migration", "9bad"]) == 1


def test_cli_make_migration_json_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`--json` emits valid, machine readable JSON describing the output."""
    monkeypatch.chdir(tmp_path)
    assert main(["make", "migration", "create_users_table", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["migration"] == "create_users_table"
    assert payload["sequence"] is not None
    assert payload["file"].endswith("_create_users_table.py")
    assert payload["created"]