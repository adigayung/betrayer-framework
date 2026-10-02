"""Focused tests for the Vertical-Slice Feature Generator.

Covers: feature creation with various component selections (default, minimal,
full, custom flags), the generated structure, the generated classes being real
subclasses of the existing abstractions, invalid name rejection, overwrite
protection, ``--force`` behaviour and the ``bet make feature`` CLI wiring.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Type

import pytest

from betrayer.cli.main import COMMANDS, build_parser, main
from betrayer.core.container import Container
from betrayer.core.module import Module
from betrayer.data.models import Model
from betrayer.data.repository import Repository
from betrayer.generators.base import GeneratorError
from betrayer.generators.feature import FEATURE_VERSION, FeatureGenerator, validate_feature_name

ALL_COMPONENTS = ("module", "model", "schema", "repository", "service", "routes", "tests")


def _generate(
    tmp_path: Path,
    name: str = "orders",
    overwrite: bool = False,
    **kwargs,
) -> FeatureGenerator:
    return FeatureGenerator(name=name, output_dir=tmp_path, overwrite=overwrite, **kwargs)


def _load_class(generator: FeatureGenerator, attribute: str):
    """Import a generated class and clean up the import cache afterwards."""
    package = generator.feature_name
    parent = str(generator.target.parent)

    def _purge() -> None:
        for mod in list(sys.modules):
            if mod == package or mod.startswith(package + "."):
                sys.modules.pop(mod, None)

    _purge()
    sys.path.insert(0, parent)
    try:
        module = __import__(package, fromlist=[attribute])
        return getattr(module, attribute)
    finally:
        sys.path.remove(parent)
        _purge()


def _load_module(generator: FeatureGenerator) -> Type[Module]:
    return _load_class(generator, generator.module_class_name)


# ── default components ──────────────────────────────────────────


def test_default_components(tmp_path: Path) -> None:
    """Default feature: model + repository + service + routes + tests + module."""
    generator = _generate(tmp_path)
    assert generator.components == {"model", "repository", "service", "routes", "tests", "module"}


def test_default_feature_created_files(tmp_path: Path) -> None:
    """A default feature writes __init__, module, models, repository, service, routes and tests."""
    generator = _generate(tmp_path)
    output = generator.generate()
    assert output.success, output.errors
    for expected in (
        "__init__.py",
        "module.py",
        "models.py",
        "repository.py",
        "service.py",
        "routes.py",
        "tests/__init__.py",
        "tests/test_orders_unit.py",
        "tests/test_orders_integration.py",
    ):
        assert (generator.target / expected).is_file(), f"missing {expected}"


def test_default_feature_no_schema(tmp_path: Path) -> None:
    """Default feature does NOT create schema.py (avoids unnecessary files)."""
    generator = _generate(tmp_path)
    generator.generate()
    assert not (generator.target / "schema.py").exists()


# ── minimal components ─────────────────────────────────────────


def test_minimal_components(tmp_path: Path) -> None:
    """--minimal: only model + repository + module."""
    generator = _generate(tmp_path, minimal=True)
    assert generator.components == {"model", "repository", "module"}
    output = generator.generate()
    assert output.success, output.errors
    assert (generator.target / "models.py").is_file()
    assert (generator.target / "repository.py").is_file()
    assert (generator.target / "module.py").is_file()
    assert not (generator.target / "service.py").exists()
    assert not (generator.target / "routes.py").exists()
    assert not (generator.target / "schema.py").exists()


# ── full components ─────────────────────────────────────────────


def test_full_components(tmp_path: Path) -> None:
    """--full: includes schema + tests on top of the default components."""
    generator = _generate(tmp_path, full=True)
    assert set(ALL_COMPONENTS) == generator.components
    output = generator.generate()
    assert output.success, output.errors
    assert (generator.target / "schema.py").is_file()
    assert (generator.target / "tests/test_orders_unit.py").is_file()


# ── custom flags ────────────────────────────────────────────────


def test_custom_flag_includes_schema(tmp_path: Path) -> None:
    """--with-schema adds the schema component on top of defaults."""
    generator = FeatureGenerator(name="orders", output_dir=tmp_path, with_schema=True)
    assert generator.has("schema")
    output = generator.generate()
    assert output.success, output.errors
    assert (generator.target / "schema.py").is_file()


def test_custom_flag_excludes_routes_and_tests(tmp_path: Path) -> None:
    """Defaults with routes/tests excluded produces the right files."""
    generator = FeatureGenerator(
        name="orders", output_dir=tmp_path, with_routes=False, with_tests=False
    )
    assert not generator.has("routes")
    assert not generator.has("tests")
    output = generator.generate()
    assert output.success, output.errors
    assert not (generator.target / "routes.py").exists()
    assert not (generator.target / "tests").exists()


# ── generated classes ───────────────────────────────────────────


def test_generated_model_subclasses_model(tmp_path: Path) -> None:
    generator = _generate(tmp_path)
    generator.generate()
    model_class = _load_class(generator, generator.model_class_name)
    assert issubclass(model_class, Model)
    assert model_class.__name__ == "OrdersModel"
    assert "id" in model_class._fields
    assert "name" in model_class._fields


def test_generated_repository_subclasses_repository(tmp_path: Path) -> None:
    generator = _generate(tmp_path)
    generator.generate()
    repository_class = _load_class(generator, generator.repository_class_name)
    assert issubclass(repository_class, Repository)
    assert repository_class.__name__ == "OrdersRepository"


def test_generated_service_delegates_crud(tmp_path: Path) -> None:
    generator = _generate(tmp_path)
    generator.generate()
    service_class = _load_class(generator, generator.service_class_name)
    assert service_class.__name__ == "OrdersService"
    assert service_class.name == "orders_service"
    for method in ("get", "find", "list", "create", "update", "delete"):
        assert callable(getattr(service_class, method))


def test_generated_schema_importable(tmp_path: Path) -> None:
    generator = _generate(tmp_path, with_schema=True)
    generator.generate()
    schema_class = _load_class(generator, generator.schema_class_name)
    assert schema_class.__name__ == "OrdersSchema"
    schema = schema_class()
    assert "name" in schema.fields
    assert schema.fields["name"].required is True


def test_generated_module_subclasses_module(tmp_path: Path) -> None:
    generator = _generate(tmp_path)
    generator.generate()
    module_class = _load_module(generator)
    assert issubclass(module_class, Module)
    assert module_class.__name__ == "OrdersFeatureModule"
    assert module_class.module_name() == "orders"
    assert module_class.version == FEATURE_VERSION


def test_generated_module_registers_repository_and_service(tmp_path: Path) -> None:
    generator = _generate(tmp_path)
    generator.generate()
    module_class = _load_module(generator)

    class DummyDatabase:
        def __str__(self) -> str:  # pragma: no cover
            return "dummy-db"

    container = Container(name="demo")
    container.singleton("database", lambda: DummyDatabase())
    module_class().register(SimpleNamespace(container=container))
    assert "orders_repository" in container
    assert "orders_service" in container
    service = container.resolve("orders_service")
    assert type(service).__name__ == "OrdersService"


def test_minimal_module_registers_repository_only(tmp_path: Path) -> None:
    generator = _generate(tmp_path, minimal=True)
    generator.generate()
    module_class = _load_module(generator)

    class DummyDatabase:
        pass

    container = Container(name="demo")
    container.singleton("database", lambda: DummyDatabase())
    module_class().register(SimpleNamespace(container=container))
    assert "orders_repository" in container
    assert "orders_service" not in container


# ── naming ──────────────────────────────────────────────────────


def test_hyphenated_name_creates_snake_case_package(tmp_path: Path) -> None:
    generator = FeatureGenerator(name="blog-post", output_dir=tmp_path)
    assert generator.feature_name == "blog_post"
    assert generator.module_class_name == "BlogPostFeatureModule"
    generator.generate()
    assert (tmp_path / "blog_post" / "models.py").is_file()


@pytest.mark.parametrize(
    "name", ["", " ", "9start", "a b", "a.b", "a/b", "../x", "-lead", "a:b"]
)
def test_invalid_feature_names_rejected(name: str) -> None:
    assert validate_feature_name(name) is not None
    with pytest.raises(GeneratorError):
        FeatureGenerator(name=name, output_dir=Path("."))


# ── overwrite protection ────────────────────────────────────────


def test_existing_feature_not_overwritten(tmp_path: Path) -> None:
    _generate(tmp_path).generate()
    with pytest.raises(GeneratorError):
        _generate(tmp_path).generate()


def test_existing_feature_overwritten_with_force(tmp_path: Path) -> None:
    _generate(tmp_path).generate()
    output = _generate(tmp_path, overwrite=True).generate()
    assert output.success, output.errors


def test_generation_is_deterministic(tmp_path: Path) -> None:
    _generate(tmp_path).generate()
    first = {
        p.name: p.read_text(encoding="utf-8")
        for p in (tmp_path / "orders").iterdir()
        if p.is_file()
    }
    _generate(tmp_path, overwrite=True).generate()
    second = {
        p.name: p.read_text(encoding="utf-8")
        for p in (tmp_path / "orders").iterdir()
        if p.is_file()
    }
    assert first == second


# ── CLI wiring ──────────────────────────────────────────────────


def test_cli_make_command_registered() -> None:
    assert "make" in COMMANDS


def test_cli_make_feature_parses(tmp_path: Path) -> None:
    parser = build_parser()
    args = parser.parse_args(["make", "feature", "orders"])
    assert args.command == "make"
    assert args.make_target == "feature"
    assert args.feature_name == "orders"
    assert args.force is False


def test_cli_make_feature_flags() -> None:
    parser = build_parser()
    args = parser.parse_args(["make", "feature", "orders", "--force", "--json", "--full"])
    assert args.force is True
    assert args.json is True
    assert args.full is True


def test_cli_make_feature_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["make", "feature", "orders"]) == 0
    assert (tmp_path / "orders" / "models.py").is_file()
    assert (tmp_path / "orders" / "repository.py").is_file()
    assert (tmp_path / "orders" / "service.py").is_file()
    assert (tmp_path / "orders" / "routes.py").is_file()
    assert (tmp_path / "orders" / "module.py").is_file()


def test_cli_make_feature_minimal_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["make", "feature", "auth", "--minimal"]) == 0
    assert (tmp_path / "auth" / "models.py").is_file()
    assert (tmp_path / "auth" / "repository.py").is_file()
    assert (tmp_path / "auth" / "module.py").is_file()
    assert not (tmp_path / "auth" / "routes.py").exists()


def test_cli_make_feature_existing_returns_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["make", "feature", "orders"]) == 0
    assert main(["make", "feature", "orders"]) == 1


def test_cli_make_feature_force_overwrites(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["make", "feature", "orders"]) == 0
    assert main(["make", "feature", "orders", "--force"]) == 0


def test_cli_make_feature_invalid_name_returns_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["make", "feature", "9bad"]) == 1


def test_cli_make_feature_json_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["make", "feature", "orders", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["feature"] == "orders"
    assert payload["module_class"] == "OrdersFeatureModule"
    assert payload["model_class"] == "OrdersModel"
    assert payload["service_class"] == "OrdersService"
    assert payload["components"] == ["model", "module", "repository", "routes", "service", "tests"]
    assert "orders" in payload["path"]
    assert payload["created"]


def test_cli_make_feature_minimal_json_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["make", "feature", "auth", "--minimal", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["components"] == ["model", "module", "repository"]
    assert payload["schema_class"] is None
    assert payload["service_class"] is None
    assert payload["model_class"] == "AuthModel"


def test_cli_make_requires_target() -> None:
    assert main(["make"]) == 1
