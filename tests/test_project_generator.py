"""Tests for the Project Generator (Task 07.2).

Covers: valid project creation, deterministic structure, invalid name
rejection, and overwrite protection (no silent clobber of existing dirs).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from betrayer.generators.base import GeneratorError, validate_project_name
from betrayer.generators.project import ProjectGenerator

EXPECTED_STUCTURE_FILES = (
    "run.py",
    "demo/__init__.py",
    "demo/app.py",
    "tests/__init__.py",
    "tests/test_app.py",
    "pyproject.toml",
    ".betrayer/project.json",
    "README.md",
    ".gitignore",
)


def _generate(tmp_path: Path, name: str = "demo", overwrite: bool = False):
    return ProjectGenerator(name=name, output_dir=tmp_path, overwrite=overwrite)


def test_valid_project_structure(tmp_path: Path) -> None:
    """Creating a project writes every expected file under its own directory."""
    generator = _generate(tmp_path)
    output = generator.generate()
    assert output.success, output.errors
    target = tmp_path / "demo"
    assert target.is_dir()
    for relative in EXPECTED_STUCTURE_FILES:
        assert (target / relative).is_file(), f"missing {relative}"


def test_generated_project_is_inspectable(tmp_path: Path) -> None:
    """The generated app package builds a real BetrayerApplication."""
    import sys

    generator = _generate(tmp_path)
    generator.generate()
    target = tmp_path / "demo"
    sys.path.insert(0, str(target))
    try:
        from demo.app import build_application

        app = build_application()
        assert app.config.get("app.name") == "demo"
        assert app.name == "demo"
    finally:
        sys.path.remove(str(target))


@pytest.mark.parametrize(
    "name",
    ["", " ", "9start", "a b", "a.b", "a/b", "../x", "-lead", "a:b"],
)
def test_invalid_names_rejected(name: str) -> None:
    """Invalid project names raise GeneratorError."""
    assert validate_project_name(name) is not None
    from pathlib import Path as _P

    with pytest.raises(GeneratorError):
        ProjectGenerator(name=name, output_dir=_P("."))


def test_existing_nonempty_dir_not_overwritten(tmp_path: Path) -> None:
    """An existing, non-empty target fails unless overwrite is requested."""
    first = _generate(tmp_path)
    first.generate()
    second = _generate(tmp_path)
    with pytest.raises(GeneratorError):
        second.generate()


def test_existing_nonempty_dir_overwritten_with_force(tmp_path: Path) -> None:
    """Overwrite (--force) succeeds against an existing, non-empty target."""
    first = _generate(tmp_path)
    first.generate()
    second = _generate(tmp_path, overwrite=True)
    output = second.generate()
    assert output.success, output.errors
    assert (tmp_path / "demo" / "run.py").is_file()


def test_hyphenated_name_creates_snake_case_package(tmp_path: Path) -> None:
    """`bet create my-app` => directory `my-app` with package `my_app`."""
    generator = ProjectGenerator(name="my-app", output_dir=tmp_path, overwrite=False)
    assert generator.package == "my_app"
    generator.generate()
    assert (tmp_path / "my-app" / "my_app" / "app.py").is_file()


def test_generation_is_deterministic(tmp_path: Path) -> None:
    """Two fresh generations produce byte-identical trees."""
    first = _generate(tmp_path)
    first.generate()
    files_a = {
        p.relative_to(tmp_path / "demo").as_posix(): p.read_text(encoding="utf-8")
        for p in (tmp_path / "demo").rglob("*")
        if p.is_file()
    }
    second = _generate(tmp_path, overwrite=True)
    second.generate()
    files_b = {
        p.relative_to(tmp_path / "demo").as_posix(): p.read_text(encoding="utf-8")
        for p in (tmp_path / "demo").rglob("*")
        if p.is_file()
    }
    assert files_a == files_b