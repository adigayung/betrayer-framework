"""Focused tests for the CRUD Generator (Task 07.5).

Covers: CRUD resource creation, the generated structure, the generated model /
repository / service / module classes being real subclasses of the existing
abstractions, invalid name rejection, overwrite protection, ``--force``
behaviour and the ``bet make crud`` CLI wiring.
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
from betrayer.generators.crud import CRUD_VERSION, CrudGenerator, validate_crud_name

EXPECTED_CRUD_FILES = (
    "__init__.py",
    "models.py",
    "repository.py",
    "service.py",
    "routes.py",
    "module.py",
)


def _generate(
    tmp_path: Path, name: str = "product", overwrite: bool = False
) -> CrudGenerator:
    return CrudGenerator(name=name, output_dir=tmp_path, overwrite=overwrite)


def _load_class(generator: CrudGenerator, attribute: str):
    """Import a generated class and clean up the import cache afterwards."""
    package = generator.resource_name
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


def _load_model(generator: CrudGenerator) -> Type[Model]:
    return _load_class(generator, generator.model_class_name)


def _load_repository(generator: CrudGenerator) -> Type[Repository]:
    return _load_class(generator, generator.repository_class_name)


def _load_service(generator: CrudGenerator):
    return _load_class(generator, generator.service_class_name)


def _load_module(generator: CrudGenerator) -> Type[Module]:
    return _load_class(generator, generator.module_class_name)


# ── structure ────────────────────────────────────────────────────


def test_crud_created(tmp_path: Path) -> None:
    """Creating a CRUD resource writes every expected file under its package."""
    generator = _generate(tmp_path)
    output = generator.generate()
    assert output.success, output.errors
    assert generator.target == tmp_path / "product"
    assert generator.target.is_dir()
    for relative in EXPECTED_CRUD_FILES:
        assert (generator.target / relative).is_file(), f"missing {relative}"


def test_generated_model_subclasses_model(tmp_path: Path) -> None:
    """The generated model class is a real ``Model`` subclass with the right name."""
    generator = _generate(tmp_path)
    generator.generate()
    model_class = _load_model(generator)
    assert issubclass(model_class, Model)
    assert model_class.__name__ == "ProductModel"
    assert "id" in model_class._fields
    assert "name" in model_class._fields


def test_generated_repository_subclasses_repository(tmp_path: Path) -> None:
    """The generated repository class is a real ``Repository`` subclass."""
    generator = _generate(tmp_path)
    generator.generate()
    repository_class = _load_repository(generator)
    assert issubclass(repository_class, Repository)
    assert repository_class.__name__ == "ProductRepository"


def test_generated_service_importable(tmp_path: Path) -> None:
    """The generated service class is importable and exposes CRUD delegation."""
    generator = _generate(tmp_path)
    generator.generate()
    service_class = _load_service(generator)
    assert service_class.__name__ == "ProductService"
    assert service_class.name == "product_service"
    # CRUD methods delegate to the repository abstraction
    for method in ("get", "find", "list", "create", "update", "delete"):
        assert callable(getattr(service_class, method))


def test_generated_module_subclasses_module(tmp_path: Path) -> None:
    """The generated module class is a real ``Module`` subclass."""
    generator = _generate(tmp_path)
    generator.generate()
    module_class = _load_module(generator)
    assert issubclass(module_class, Module)
    assert module_class.__name__ == "ProductCrudModule"
    assert module_class.module_name() == "product"


def test_generated_module_registers_repository_and_service(tmp_path: Path) -> None:
    """The generated module registers repository + service on a container."""
    generator = _generate(tmp_path)
    generator.generate()
    module_class = _load_module(generator)

    class DummyDatabase:
        def __str__(self) -> str:  # pragma: no cover - introspection hook
            return "dummy-db"

    container = Container(name="demo")
    container.singleton("database", lambda: DummyDatabase())
    module_class().register(SimpleNamespace(container=container))
    assert "product_repository" in container
    assert "product_service" in container
    service = container.resolve("product_service")
    assert type(service).__name__ == "ProductService"
    assert service.repository.model_class.__name__ == "ProductModel"


def test_generated_routes_registered(tmp_path: Path) -> None:
    """The generated routes module exposes a router with 5 CRUD endpoints."""
    generator = _generate(tmp_path)
    generator.generate()
    package = generator.resource_name
    parent = str(generator.target.parent)
    sys.path.insert(0, parent)
    try:
        from product.routes import register_routes, router

        assert len(router.routes) == 0
        register_routes(router)
        methods = sorted((route.method, route.path) for route in router.routes)
        assert methods == [
            ("DELETE", "/products/<id>"),
            ("GET", "/products"),
            ("GET", "/products/<id>"),
            ("POST", "/products"),
            ("PUT", "/products/<id>"),
        ]
    finally:
        sys.path.remove(parent)


def test_generation_is_deterministic(tmp_path: Path) -> None:
    """Two fresh generations produce byte-identical files."""
    _generate(tmp_path).generate()
    first = {
        p.name: p.read_text(encoding="utf-8")
        for p in (tmp_path / "product").iterdir()
        if p.is_file()
    }
    _generate(tmp_path, overwrite=True).generate()
    second = {
        p.name: p.read_text(encoding="utf-8")
        for p in (tmp_path / "product").iterdir()
        if p.is_file()
    }
    assert first == second


# ── naming ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "name", ["", " ", "9start", "a b", "a.b", "a/b", "../x", "-lead", "a:b"]
)
def test_invalid_crud_names_rejected(name: str) -> None:
    """Invalid CRUD resource names raise GeneratorError (and report a message)."""
    assert validate_crud_name(name) is not None
    with pytest.raises(GeneratorError):
        CrudGenerator(name=name, output_dir=Path("."))


def test_hyphenated_name_creates_snake_case_package(tmp_path: Path) -> None:
    """`bet make crud blog-post` => package `blog_post`, class BlogPostModel."""
    generator = CrudGenerator(name="blog-post", output_dir=tmp_path)
    assert generator.resource_name == "blog_post"
    assert generator.model_class_name == "BlogPostModel"
    assert generator.repository_class_name == "BlogPostRepository"
    assert generator.service_class_name == "BlogPostService"
    assert generator.module_class_name == "BlogPostCrudModule"
    generator.generate()
    assert (tmp_path / "blog_post" / "models.py").is_file()
    assert (tmp_path / "blog_post" / "service.py").is_file()


# ── overwrite protection ─────────────────────────────────────────


def test_existing_crud_not_overwritten(tmp_path: Path) -> None:
    """An existing CRUD resource is never clobbered without --force."""
    _generate(tmp_path).generate()
    with pytest.raises(GeneratorError):
        _generate(tmp_path).generate()


def test_existing_crud_overwritten_with_force(tmp_path: Path) -> None:
    """--force overwrites the files of an existing CRUD resource."""
    _generate(tmp_path).generate()
    output = _generate(tmp_path, overwrite=True).generate()
    assert output.success, output.errors
    assert (tmp_path / "product" / "service.py").is_file()


# ── CLI wiring ───────────────────────────────────────────────────


def test_cli_make_command_registered() -> None:
    """`make` is part of the top level commands."""
    assert "make" in COMMANDS


def test_cli_make_crud_parses(tmp_path: Path) -> None:
    """`bet make crud product` parses into the expected namespace."""
    parser = build_parser()
    args = parser.parse_args(["make", "crud", "product"])
    assert args.command == "make"
    assert args.make_target == "crud"
    assert args.resource_name == "product"
    assert args.force is False


def test_cli_make_crud_flags() -> None:
    """`--force` and `--json` are accepted by the crud target."""
    parser = build_parser()
    args = parser.parse_args(["make", "crud", "product", "--force", "--json"])
    assert args.force is True
    assert args.json is True


def test_cli_make_requires_target() -> None:
    """`bet make` without a target is a controlled failure."""
    assert main(["make"]) == 1


def test_cli_make_crud_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The CLI actually generates the CRUD resource in the current directory."""
    monkeypatch.chdir(tmp_path)
    assert main(["make", "crud", "products"]) == 0
    assert (tmp_path / "products" / "models.py").is_file()
    assert (tmp_path / "products" / "repository.py").is_file()
    assert (tmp_path / "products" / "service.py").is_file()
    assert (tmp_path / "products" / "routes.py").is_file()
    assert (tmp_path / "products" / "module.py").is_file()


def test_cli_make_crud_existing_returns_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Re-creating an existing CRUD resource fails with the CLI failure code."""
    monkeypatch.chdir(tmp_path)
    assert main(["make", "crud", "products"]) == 0
    assert main(["make", "crud", "products"]) == 1


def test_cli_make_crud_force_overwrites(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--force` lets the CLI regenerate over an existing CRUD resource."""
    monkeypatch.chdir(tmp_path)
    assert main(["make", "crud", "products"]) == 0
    assert main(["make", "crud", "products", "--force"]) == 0


def test_cli_make_crud_invalid_name_returns_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An invalid CRUD resource name fails with the CLI failure exit code."""
    monkeypatch.chdir(tmp_path)
    assert main(["make", "crud", "9bad"]) == 1


def test_cli_make_crud_json_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`--json` emits valid, machine readable JSON describing the output."""
    monkeypatch.chdir(tmp_path)
    assert main(["make", "crud", "products", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["resource"] == "products"
    assert payload["model_class"] == "ProductsModel"
    assert payload["repository_class"] == "ProductsRepository"
    assert payload["service_class"] == "ProductsService"
    assert payload["module_class"] == "ProductsCrudModule"
    assert payload["created"]