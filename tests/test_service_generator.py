"""Focused tests for the Service Generator (Task 07.5).

Covers: service creation, the generated structure, the generated service class
being importable, the generated module being a real ``Module`` subclass that
registers the service on a container, invalid name rejection, overwrite
protection, ``--force`` behaviour and the ``bet make service`` CLI wiring.
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
from betrayer.generators.base import GeneratorError
from betrayer.generators.service import SERVICE_VERSION, ServiceGenerator, validate_service_name

EXPECTED_SERVICE_FILES = ("__init__.py", "service.py", "module.py")


def _generate(
    tmp_path: Path, name: str = "user", overwrite: bool = False
) -> ServiceGenerator:
    return ServiceGenerator(name=name, output_dir=tmp_path, overwrite=overwrite)


def _load_class(generator: ServiceGenerator, attribute: str):
    """Import a generated class and clean up the import cache afterwards."""
    package = generator.service_name
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


def _load_service(generator: ServiceGenerator):
    return _load_class(generator, generator.service_class_name)


def _load_module(generator: ServiceGenerator) -> Type[Module]:
    return _load_class(generator, generator.module_class_name)


# ── structure ────────────────────────────────────────────────────


def test_service_created(tmp_path: Path) -> None:
    """Creating a service writes every expected file under its own package."""
    generator = _generate(tmp_path)
    output = generator.generate()
    assert output.success, output.errors
    assert generator.target == tmp_path / "user_service"
    assert generator.target.is_dir()
    for relative in EXPECTED_SERVICE_FILES:
        assert (generator.target / relative).is_file(), f"missing {relative}"


def test_generated_service_class_importable(tmp_path: Path) -> None:
    """The generated service class is importable with the right name."""
    generator = _generate(tmp_path)
    generator.generate()
    service_class = _load_service(generator)
    assert service_class.__name__ == "UserService"
    assert service_class.name == "user_service"


def test_generated_module_subclasses_module(tmp_path: Path) -> None:
    """The generated module class is a real ``Module`` subclass."""
    generator = _generate(tmp_path)
    generator.generate()
    module_class = _load_module(generator)
    assert issubclass(module_class, Module)
    assert module_class.__name__ == "UserServiceModule"
    assert module_class.module_name() == "user_service"


def test_generated_module_registers_service(tmp_path: Path) -> None:
    """The generated module registers the service on a container."""
    generator = _generate(tmp_path)
    generator.generate()
    module_class = _load_module(generator)
    container = Container(name="demo")
    module_class().register(SimpleNamespace(container=container))
    assert "user_service" in container
    service = container.resolve("user_service")
    assert type(service).__name__ == "UserService"
    assert service.introspect()["name"] == "user_service"


def test_generation_is_deterministic(tmp_path: Path) -> None:
    """Two fresh generations produce byte-identical files."""
    _generate(tmp_path).generate()
    first = {
        p.name: p.read_text(encoding="utf-8")
        for p in (tmp_path / "user_service").iterdir()
        if p.is_file()
    }
    _generate(tmp_path, overwrite=True).generate()
    second = {
        p.name: p.read_text(encoding="utf-8")
        for p in (tmp_path / "user_service").iterdir()
        if p.is_file()
    }
    assert first == second


# ── naming ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "name", ["", " ", "9start", "a b", "a.b", "a/b", "../x", "-lead", "a:b"]
)
def test_invalid_service_names_rejected(name: str) -> None:
    """Invalid service names raise GeneratorError (and report a message)."""
    assert validate_service_name(name) is not None
    with pytest.raises(GeneratorError):
        ServiceGenerator(name=name, output_dir=Path("."))


def test_hyphenated_name_creates_snake_case_package(tmp_path: Path) -> None:
    """`bet make service audit-log` => package `audit_log_service`, class AuditLogService."""
    generator = ServiceGenerator(name="audit-log", output_dir=tmp_path)
    assert generator.service_name == "audit_log_service"
    assert generator.service_class_name == "AuditLogService"
    assert generator.module_class_name == "AuditLogServiceModule"
    assert generator.service_key == "audit_log_service"
    generator.generate()
    assert (tmp_path / "audit_log_service" / "service.py").is_file()


# ── overwrite protection ─────────────────────────────────────────


def test_existing_service_not_overwritten(tmp_path: Path) -> None:
    """An existing service is never clobbered without --force."""
    _generate(tmp_path).generate()
    with pytest.raises(GeneratorError):
        _generate(tmp_path).generate()


def test_existing_service_overwritten_with_force(tmp_path: Path) -> None:
    """--force overwrites the files of an existing service."""
    _generate(tmp_path).generate()
    output = _generate(tmp_path, overwrite=True).generate()
    assert output.success, output.errors
    assert (tmp_path / "user_service" / "service.py").is_file()


# ── CLI wiring ───────────────────────────────────────────────────


def test_cli_make_command_registered() -> None:
    """`make` is part of the top level commands."""
    assert "make" in COMMANDS


def test_cli_make_service_parses(tmp_path: Path) -> None:
    """`bet make service user` parses into the expected namespace."""
    parser = build_parser()
    args = parser.parse_args(["make", "service", "user"])
    assert args.command == "make"
    assert args.make_target == "service"
    assert args.service_name == "user"
    assert args.force is False


def test_cli_make_service_flags() -> None:
    """`--force` and `--json` are accepted by the service target."""
    parser = build_parser()
    args = parser.parse_args(["make", "service", "user", "--force", "--json"])
    assert args.force is True
    assert args.json is True


def test_cli_make_requires_target() -> None:
    """`bet make` without a target is a controlled failure."""
    assert main(["make"]) == 1


def test_cli_make_service_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The CLI actually generates the service in the current directory."""
    monkeypatch.chdir(tmp_path)
    assert main(["make", "service", "users"]) == 0
    assert (tmp_path / "users_service" / "service.py").is_file()
    assert (tmp_path / "users_service" / "module.py").is_file()


def test_cli_make_service_existing_returns_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Re-creating an existing service fails with the CLI failure exit code."""
    monkeypatch.chdir(tmp_path)
    assert main(["make", "service", "users"]) == 0
    assert main(["make", "service", "users"]) == 1


def test_cli_make_service_force_overwrites(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--force` lets the CLI regenerate over an existing service."""
    monkeypatch.chdir(tmp_path)
    assert main(["make", "service", "users"]) == 0
    assert main(["make", "service", "users", "--force"]) == 0


def test_cli_make_service_invalid_name_returns_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An invalid service name fails with the CLI failure exit code."""
    monkeypatch.chdir(tmp_path)
    assert main(["make", "service", "9bad"]) == 1


def test_cli_make_service_json_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`--json` emits valid, machine readable JSON describing the output."""
    monkeypatch.chdir(tmp_path)
    assert main(["make", "service", "users", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["service"] == "users_service"
    assert payload["service_class"] == "UsersService"
    assert payload["module_class"] == "UsersServiceModule"
    assert payload["created"]