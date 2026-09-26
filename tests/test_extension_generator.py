"""Focused tests for the Extension Generator (Task 07.6).

Covers: extension skeleton creation, the generated directory/file structure,
the generated ``Extension`` subclass (name / version / hooks), invalid name
rejection, overwrite protection, ``--force`` behaviour and the
``bet make extension`` CLI wiring.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Type

import pytest

from betrayer.cli.main import COMMANDS, build_parser, main
from betrayer.core.extension import Extension, ExtensionRegistry
from betrayer.generators.base import GeneratorError
from betrayer.generators.extension import (
    EXTENSION_DIRECTORY,
    EXTENSION_VERSION,
    ExtensionGenerator,
    validate_extension_name,
)

EXPECTED_EXTENSION_FILES = ("__init__.py", "extension.py")


def _generate(
    tmp_path: Path, name: str = "payments", overwrite: bool = False
) -> ExtensionGenerator:
    return ExtensionGenerator(name=name, output_dir=tmp_path, overwrite=overwrite)


def _load_class(generator: ExtensionGenerator, attribute: str):
    """Import a generated extension class and clean up afterwards."""
    package = f"{EXTENSION_DIRECTORY}.{generator.extension_name}"
    # ``extensions/`` lives directly under the project root (output_dir), so
    # ``tmp_path`` is ``target.parent.parent`` (e.g. tmp/extensions/payments).
    parent = str(generator.output_dir.parent.parent)

    def _purge() -> None:
        for mod in list(sys.modules):
            if mod.startswith("extensions."):
                sys.modules.pop(mod, None)

    _purge()
    sys.path.insert(0, parent)
    try:
        module = __import__(package, fromlist=[attribute])
        return getattr(module, attribute)
    finally:
        sys.path.remove(parent)
        _purge()


def _load_extension(generator: ExtensionGenerator) -> Type[Extension]:
    return _load_class(generator, generator.class_name)


# ── structure ────────────────────────────────────────────────────


def test_extension_created(tmp_path: Path) -> None:
    """Creating an extension writes every expected file under its package."""
    generator = _generate(tmp_path)
    output = generator.generate()
    assert output.success, output.errors
    assert generator.target == tmp_path / EXTENSION_DIRECTORY / "payments"
    assert generator.target.is_dir()
    for relative in EXPECTED_EXTENSION_FILES:
        assert (generator.target / relative).is_file(), f"missing {relative}"


def test_extension_skeleton_structure_directories(tmp_path: Path) -> None:
    """The ``extensions/<name>`` directory layout is created."""
    generator = _generate(tmp_path, name="metrics-export")
    generator.generate()
    assert (tmp_path / EXTENSION_DIRECTORY).is_dir()
    assert (tmp_path / EXTENSION_DIRECTORY / "metrics_export" / "extension.py").is_file()


def test_extension_class_name_convention(tmp_path: Path) -> None:
    """`bet make extension metrics-export` => class MetricsExportExtension."""
    generator = _generate(tmp_path, name="metrics-export")
    assert generator.extension_name == "metrics_export"
    assert generator.class_name == "MetricsExportExtension"
    generator.generate()
    assert (tmp_path / EXTENSION_DIRECTORY / "metrics_export" / "extension.py").is_file()


def test_generated_extension_subclasses_extension(tmp_path: Path) -> None:
    """The generated class is a real ``Extension`` subclass with hooks."""
    generator = _generate(tmp_path)
    generator.generate()
    extension_class = _load_extension(generator)
    assert issubclass(extension_class, Extension)
    assert extension_class.__name__ == "PaymentsExtension"
    assert extension_class.name == "payments"
    assert extension_class.version == EXTENSION_VERSION
    assert extension_class.dependencies == ()
    for hook in ("register", "verify", "initialize", "shutdown"):
        assert callable(getattr(extension_class, hook))


def test_generated_extension_registers_on_registry(tmp_path: Path) -> None:
    """The generated extension can be registered on an ExtensionRegistry."""
    generator = _generate(tmp_path)
    generator.generate()
    extension_class = _load_extension(generator)
    registry = ExtensionRegistry()
    extension = registry.register(extension_class)
    assert extension.extension_name() == "payments"
    assert "payments" in registry.names()
    assert registry.describe()["count"] == 1


def test_generation_is_deterministic(tmp_path: Path) -> None:
    """Two fresh generations produce byte-identical files."""
    _generate(tmp_path).generate()
    first = {
        p.name: p.read_text(encoding="utf-8")
        for p in (tmp_path / EXTENSION_DIRECTORY / "payments").iterdir()
        if p.is_file()
    }
    _generate(tmp_path, overwrite=True).generate()
    second = {
        p.name: p.read_text(encoding="utf-8")
        for p in (tmp_path / EXTENSION_DIRECTORY / "payments").iterdir()
        if p.is_file()
    }
    assert first == second


# ── naming ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "name", ["", " ", "9start", "a b", "a.b", "a/b", "../x", "-lead", "a:b"]
)
def test_invalid_extension_names_rejected(name: str) -> None:
    """Invalid extension names raise GeneratorError (and report a message)."""
    assert validate_extension_name(name) is not None
    with pytest.raises(GeneratorError):
        ExtensionGenerator(name=name, output_dir=Path("."))


# ── overwrite protection ─────────────────────────────────────────


def test_existing_extension_not_overwritten(tmp_path: Path) -> None:
    """An existing extension is never clobbered without --force."""
    _generate(tmp_path).generate()
    with pytest.raises(GeneratorError):
        _generate(tmp_path).generate()


def test_existing_extension_overwritten_with_force(tmp_path: Path) -> None:
    """--force overwrites the files of an existing extension."""
    _generate(tmp_path).generate()
    output = _generate(tmp_path, overwrite=True).generate()
    assert output.success, output.errors
    assert (tmp_path / EXTENSION_DIRECTORY / "payments" / "extension.py").is_file()


# ── CLI wiring ───────────────────────────────────────────────────


def test_cli_make_command_registered() -> None:
    """`make` is part of the top level commands."""
    assert "make" in COMMANDS


def test_cli_make_extension_parses(tmp_path: Path) -> None:
    """`bet make extension payments` parses correctly."""
    parser = build_parser()
    args = parser.parse_args(["make", "extension", "payments"])
    assert args.command == "make"
    assert args.make_target == "extension"
    assert args.extension_name == "payments"
    assert args.force is False


def test_cli_make_extension_flags() -> None:
    """`--force` and `--json` are accepted by the extension target."""
    parser = build_parser()
    args = parser.parse_args(["make", "extension", "payments", "--force", "--json"])
    assert args.force is True
    assert args.json is True


def test_cli_make_requires_target() -> None:
    """`bet make` without a target is a controlled failure."""
    assert main(["make"]) == 1


def test_cli_make_extension_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The CLI actually generates the extension in the current directory."""
    monkeypatch.chdir(tmp_path)
    assert main(["make", "extension", "payments"]) == 0
    assert (tmp_path / EXTENSION_DIRECTORY / "payments" / "extension.py").is_file()
    assert (tmp_path / EXTENSION_DIRECTORY / "payments" / "__init__.py").is_file()


def test_cli_make_extension_existing_returns_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Re-creating an existing extension fails with the CLI failure code."""
    monkeypatch.chdir(tmp_path)
    assert main(["make", "extension", "payments"]) == 0
    assert main(["make", "extension", "payments"]) == 1


def test_cli_make_extension_force_overwrites(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--force` lets the CLI regenerate over an existing extension."""
    monkeypatch.chdir(tmp_path)
    assert main(["make", "extension", "payments"]) == 0
    assert main(["make", "extension", "payments", "--force"]) == 0


def test_cli_make_extension_invalid_name_returns_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An invalid extension name fails with the CLI failure exit code."""
    monkeypatch.chdir(tmp_path)
    assert main(["make", "extension", "9bad"]) == 1


def test_cli_make_extension_json_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`--json` emits valid, machine readable JSON describing the output."""
    monkeypatch.chdir(tmp_path)
    assert main(["make", "extension", "payments", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["extension"] == "payments"
    assert payload["extension_class"] == "PaymentsExtension"
    assert payload["created"]