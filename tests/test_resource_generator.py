"""Focused tests for the Resource Generator (Task 07.4).

Covers: resource creation, the generated structure, the generated model being a
real ``Model`` subclass, the generated module being a real ``Module`` subclass,
invalid name rejection, overwrite protection, ``--force`` behaviour and the
``bet make resource`` CLI wiring.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Type

import pytest

from betrayer.cli.main import COMMANDS, build_parser, main
from betrayer.core.module import Module
from betrayer.data.models import Model
from betrayer.data.repository import Repository
from betrayer.generators.base import GeneratorError
from betrayer.generators.resource import ResourceGenerator, validate_resource_name

EXPECTED_RESOURCE_FILES = (
    "__init__.py",
    "models.py",
    "repository.py",
    "routes.py",
    "module.py",
)


def _generate(
    tmp_path: Path, name: str = "user", overwrite: bool = False
) -> ResourceGenerator:
    return ResourceGenerator(name=name, output_dir=tmp_path, overwrite=overwrite)


def _load_model(generator: ResourceGenerator) -> Type[Model]:
    """Import the generated Model class, then clean up the import cache."""
    package = generator.resource_name
    parent = str(generator.target.parent)

    def _purge() -> None:
        for mod in list(sys.modules):
            if mod == package or mod.startswith(package + "."):
                sys.modules.pop(mod, None)

    _purge()
    sys.path.insert(0, parent)
    try:
        mod = __import__(package, fromlist=[generator.model_class_name])
        return getattr(mod, generator.model_class_name)
    finally:
        sys.path.remove(parent)
        _purge()


def _load_module(generator: ResourceGenerator) -> Type[Module]:
    """Import the generated Module class, then clean up the import cache."""
    package = generator.resource_name
    parent = str(generator.target.parent)

    def _purge() -> None:
        for mod in list(sys.modules):
            if mod == package or mod.startswith(package + "."):
                sys.modules.pop(mod, None)

    _purge()
    sys.path.insert(0, parent)
    try:
        mod = __import__(package, fromlist=[generator.module_class_name])
        return getattr(mod, generator.module_class_name)
    finally:
        sys.path.remove(parent)
        _purge()


# ── structure ────────────────────────────────────────────────────


def test_resource_created(tmp_path: Path) -> None:
    """Creating a resource writes every expected file under its own package."""
    generator = _generate(tmp_path)
    output = generator.generate()
    assert output.success, output.errors
    assert generator.target == tmp_path / "user"
    assert generator.target.is_dir()
    for relative in EXPECTED_RESOURCE_FILES:
        assert (generator.target / relative).is_file(), f"missing {relative}"


def test_generated_model_subclasses_model(tmp_path: Path) -> None:
    """The generated model class is a real ``Model`` subclass with the right name."""
    generator = _generate(tmp_path)
    generator.generate()
    model_class = _load_model(generator)
    assert issubclass(model_class, Model)
    assert model_class.__name__ == "UserModel"


def test_generated_module_subclasses_module(tmp_path: Path) -> None:
    """The generated module class is a real ``Module`` subclass with the right name."""
    generator = _generate(tmp_path)
    generator.generate()
    module_class = _load_module(generator)
    assert issubclass(module_class, Module)
    assert module_class.__name__ == "UserResourceModule"
    assert module_class.module_name() == "user"


def test_generated_model_has_expected_fields(tmp_path: Path) -> None:
    """The generated model has the standard fields (id, created_at, etc.)."""
    generator = _generate(tmp_path)
    generator.generate()
    model_class = _load_model(generator)
    assert "id" in model_class._fields
    assert "name" in model_class._fields
    assert "description" in model_class._fields
    assert "created_at" in model_class._fields
    assert "updated_at" in model_class._fields


def test_generated_repository_subclasses_repository(tmp_path: Path) -> None:
    """The generated repository class is a real ``Repository`` subclass."""
    from betrayer.generators.resource import ResourceGenerator as RG

    generator = _generate(tmp_path)
    generator.generate()
    # Just verify the module imports cleanly
    package = generator.resource_name
    parent = str(generator.target.parent)
    sys.path.insert(0, parent)
    try:
        mod = __import__(package, fromlist=[generator.repository_class_name])
        repo_class = getattr(mod, generator.repository_class_name)
        assert issubclass(repo_class, Repository)
        assert repo_class.__name__ == "UserRepository"
    finally:
        sys.path.remove(parent)


def test_generation_is_deterministic(tmp_path: Path) -> None:
    """Two fresh generations produce byte-identical files."""
    _generate(tmp_path).generate()
    first = {
        p.name: p.read_text(encoding="utf-8")
        for p in (tmp_path / "user").iterdir()
        if p.is_file()
    }
    _generate(tmp_path, overwrite=True).generate()
    second = {
        p.name: p.read_text(encoding="utf-8")
        for p in (tmp_path / "user").iterdir()
        if p.is_file()
    }
    assert first == second


# ── naming ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "name", ["", " ", "9start", "a b", "a.b", "a/b", "../x", "-lead", "a:b"]
)
def test_invalid_resource_names_rejected(name: str) -> None:
    """Invalid resource names raise GeneratorError (and report a message)."""
    assert validate_resource_name(name) is not None
    with pytest.raises(GeneratorError):
        ResourceGenerator(name=name, output_dir=Path("."))


def test_hyphenated_name_creates_snake_case_package(tmp_path: Path) -> None:
    """`bet make resource blog-post` => package `blog_post`, class BlogPostModel."""
    generator = ResourceGenerator(name="blog-post", output_dir=tmp_path)
    assert generator.resource_name == "blog_post"
    assert generator.model_class_name == "BlogPostModel"
    assert generator.repository_class_name == "BlogPostRepository"
    assert generator.module_class_name == "BlogPostResourceModule"
    generator.generate()
    assert (tmp_path / "blog_post" / "models.py").is_file()


# ── overwrite protection ─────────────────────────────────────────


def test_existing_resource_not_overwritten(tmp_path: Path) -> None:
    """An existing resource is never clobbered without --force."""
    _generate(tmp_path).generate()
    with pytest.raises(GeneratorError):
        _generate(tmp_path).generate()


def test_existing_resource_overwritten_with_force(tmp_path: Path) -> None:
    """--force overwrites the files of an existing resource."""
    _generate(tmp_path).generate()
    output = _generate(tmp_path, overwrite=True).generate()
    assert output.success, output.errors
    assert (tmp_path / "user" / "models.py").is_file()


# ── CLI wiring ───────────────────────────────────────────────────


def test_cli_make_command_registered() -> None:
    """`make` is part of the top level commands."""
    assert "make" in COMMANDS


def test_cli_make_resource_parses(tmp_path: Path) -> None:
    """`bet make resource users` parses into the expected namespace."""
    parser = build_parser()
    args = parser.parse_args(["make", "resource", "users"])
    assert args.command == "make"
    assert args.make_target == "resource"
    assert args.resource_name == "users"
    assert args.force is False


def test_cli_make_resource_flags() -> None:
    """`--force` and `--json` are accepted by the resource target."""
    parser = build_parser()
    args = parser.parse_args(["make", "resource", "users", "--force", "--json"])
    assert args.force is True
    assert args.json is True


def test_cli_make_requires_target() -> None:
    """`bet make` without a target is a controlled failure."""
    assert main(["make"]) == 1


def test_cli_make_resource_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The CLI actually generates the resource in the current directory."""
    monkeypatch.chdir(tmp_path)
    assert main(["make", "resource", "users"]) == 0
    assert (tmp_path / "users" / "models.py").is_file()
    assert (tmp_path / "users" / "repository.py").is_file()
    assert (tmp_path / "users" / "routes.py").is_file()
    assert (tmp_path / "users" / "module.py").is_file()


def test_cli_make_resource_existing_returns_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Re-creating an existing resource fails with the CLI failure exit code."""
    monkeypatch.chdir(tmp_path)
    assert main(["make", "resource", "users"]) == 0
    assert main(["make", "resource", "users"]) == 1


def test_cli_make_resource_force_overwrites(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--force` lets the CLI regenerate over an existing resource."""
    monkeypatch.chdir(tmp_path)
    assert main(["make", "resource", "users"]) == 0
    assert main(["make", "resource", "users", "--force"]) == 0


def test_cli_make_resource_invalid_name_returns_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An invalid resource name fails with the CLI failure exit code."""
    monkeypatch.chdir(tmp_path)
    assert main(["make", "resource", "9bad"]) == 1


def test_cli_make_resource_json_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`--json` emits valid, machine readable JSON describing the output."""
    monkeypatch.chdir(tmp_path)
    assert main(["make", "resource", "users", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["resource"] == "users"
    assert "model_class" in payload
    assert payload["model_class"] == "UsersModel"
    assert payload["repository_class"] == "UsersRepository"
    assert payload["module_class"] == "UsersResourceModule"
    assert payload["created"]