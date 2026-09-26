"""Focused tests for the Module Generator (Task 07.3).

Covers: module creation, the generated structure, the generated module being a
real ``Module`` subclass, invalid name rejection, overwrite protection,
``--force`` behaviour and the ``bet make module`` CLI wiring.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from typing import Type

import pytest

from betrayer.cli.main import COMMANDS, build_parser, main
from betrayer.core.module import Module
from betrayer.generators.base import GeneratorError
from betrayer.generators.module import ModuleGenerator, validate_module_name

EXPECTED_MODULE_FILES = ("__init__.py", "module.py")


def _generate(
    tmp_path: Path, name: str = "users", overwrite: bool = False
) -> ModuleGenerator:
    return ModuleGenerator(name=name, output_dir=tmp_path, overwrite=overwrite)


def _load_module(generator: ModuleGenerator) -> Type[Module]:
    """Import the generated module class, then clean up the import cache."""
    package = generator.module_name
    parent = str(generator.target.parent)

    def _purge() -> None:
        for mod in list(sys.modules):
            if mod == package or mod.startswith(package + "."):
                sys.modules.pop(mod, None)

    _purge()
    sys.path.insert(0, parent)
    try:
        module = importlib.import_module(package)
        return getattr(module, generator.class_name)
    finally:
        sys.path.remove(parent)
        _purge()


# ── structure ────────────────────────────────────────────────────


def test_module_created(tmp_path: Path) -> None:
    """creating a module writes every expected file under its own package."""
    generator = _generate(tmp_path)
    output = generator.generate()
    assert output.success, output.errors
    assert generator.target == tmp_path / "users"
    assert generator.target.is_dir()
    for relative in EXPECTED_MODULE_FILES:
        assert (generator.target / relative).is_file(), f"missing {relative}"


def test_generated_module_subclasses_module(tmp_path: Path) -> None:
    """The generated class is a real ``Module`` subclass with the right name."""
    generator = _generate(tmp_path)
    generator.generate()
    module_class = _load_module(generator)
    assert issubclass(module_class, Module)
    assert module_class.module_name() == "users"
    assert module_class.__name__ == "UsersModule"


def test_generated_module_registers_on_application(tmp_path: Path) -> None:
    """The generated module registers cleanly on an application."""
    from betrayer import BetrayerApplication

    generator = _generate(tmp_path)
    generator.generate()
    module_class = _load_module(generator)
    app = BetrayerApplication(name="demo")
    app.modules.register(module_class)
    assert app.modules.names() == ["users"]


def test_generation_is_deterministic(tmp_path: Path) -> None:
    """Two fresh generations produce byte-identical files."""
    _generate(tmp_path).generate()
    first = {
        p.name: p.read_text(encoding="utf-8")
        for p in (tmp_path / "users").iterdir()
        if p.is_file()
    }
    _generate(tmp_path, overwrite=True).generate()
    second = {
        p.name: p.read_text(encoding="utf-8")
        for p in (tmp_path / "users").iterdir()
        if p.is_file()
    }
    assert first == second


# ── naming ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "name", ["", " ", "9start", "a b", "a.b", "a/b", "../x", "-lead", "a:b"]
)
def test_invalid_module_names_rejected(name: str) -> None:
    """Invalid module names raise GeneratorError (and report a message)."""
    assert validate_module_name(name) is not None
    with pytest.raises(GeneratorError):
        ModuleGenerator(name=name, output_dir=Path("."))


def test_hyphenated_name_creates_snake_case_package(tmp_path: Path) -> None:
    """`bet make module audit-log` => package `audit_log`, class AuditLogModule."""
    generator = ModuleGenerator(name="audit-log", output_dir=tmp_path)
    assert generator.module_name == "audit_log"
    assert generator.class_name == "AuditLogModule"
    generator.generate()
    assert (tmp_path / "audit_log" / "module.py").is_file()


# ── overwrite protection ─────────────────────────────────────────


def test_existing_module_not_overwritten(tmp_path: Path) -> None:
    """An existing module is never clobbered without --force."""
    _generate(tmp_path).generate()
    with pytest.raises(GeneratorError):
        _generate(tmp_path).generate()


def test_existing_module_overwritten_with_force(tmp_path: Path) -> None:
    """--force overwrites the files of an existing module."""
    _generate(tmp_path).generate()
    output = _generate(tmp_path, overwrite=True).generate()
    assert output.success, output.errors
    assert (tmp_path / "users" / "module.py").is_file()


# ── CLI wiring ───────────────────────────────────────────────────


def test_cli_make_command_registered() -> None:
    """`make` is part of the CLI command surface."""
    assert "make" in COMMANDS


def test_cli_make_module_parses() -> None:
    """`bet make module users` parses into the expected namespace."""
    parser = build_parser()
    args = parser.parse_args(["make", "module", "users"])
    assert args.command == "make"
    assert args.make_target == "module"
    assert args.module_name == "users"
    assert args.force is False


def test_cli_make_module_flags() -> None:
    """`--force` and `--json` are accepted by the module target."""
    parser = build_parser()
    args = parser.parse_args(["make", "module", "users", "--force", "--json"])
    assert args.force is True
    assert args.json is True


def test_cli_make_requires_target() -> None:
    """`bet make` without a target is a controlled failure."""
    assert main(["make"]) == 1


def test_cli_make_module_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The CLI actually generates the module in the current directory."""
    monkeypatch.chdir(tmp_path)
    assert main(["make", "module", "users"]) == 0
    assert (tmp_path / "users" / "module.py").is_file()


def test_cli_make_module_existing_returns_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Re-creating an existing module fails with the CLI failure exit code."""
    monkeypatch.chdir(tmp_path)
    assert main(["make", "module", "users"]) == 0
    assert main(["make", "module", "users"]) == 1


def test_cli_make_module_force_overwrites(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--force` lets the CLI regenerate over an existing module."""
    monkeypatch.chdir(tmp_path)
    assert main(["make", "module", "users"]) == 0
    assert main(["make", "module", "users", "--force"]) == 0


def test_cli_make_module_invalid_name_returns_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An invalid module name fails with the CLI failure exit code."""
    monkeypatch.chdir(tmp_path)
    assert main(["make", "module", "9bad"]) == 1


def test_cli_make_module_json_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`--json` emits valid, machine readable JSON describing the output."""
    monkeypatch.chdir(tmp_path)
    assert main(["make", "module", "users", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["module"] == "users"
    assert payload["created"]
