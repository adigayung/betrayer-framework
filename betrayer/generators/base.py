"""Base generator utilities for the Betrayer Framework.

These classes are shared by every generator (project, module, resource, ...).
They deliberately stay small: a generator records what it created via
:class:`GeneratorOutput`, guards writes with overwrite protection, and exposes
small deterministic helpers for naming.  There is no template engine here --
templates are simple, explicit string construction in each generator, so a
generated project is fully deterministic and easy to read.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

__all__ = [
    "GeneratorError",
    "GeneratorOutput",
    "BaseGenerator",
    "TemplateRenderer",
    "snake_case",
    "camel_case",
    "title_case",
    "package_name",
    "validate_project_name",
]

#: Characters allowed in a command line project name.
PROJECT_NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")


class GeneratorError(Exception):
    """Base exception for a controlled generator failure.

    Raising this from a generator is a *controlled* failure (invalid name,
    target already exists, ...).  Callers convert it into the framework error
    contract (``CommandError`` in the CLI) so it never leaks a traceback.
    """


class GeneratorOutput:
    """Tracks files created, updated and skipped during generation."""

    def __init__(self) -> None:
        self.created: List[str] = []
        self.updated: List[str] = []
        self.skipped: List[str] = []
        self.errors: List[Dict[str, Any]] = []

    def add_created(self, path: str) -> None:
        """Record a newly created file (relative path)."""
        if path not in self.created and path not in self.updated:
            self.created.append(path)

    def add_updated(self, path: str) -> None:
        """Record an overwritten file (relative path)."""
        if path not in self.created and path not in self.updated:
            self.updated.append(path)

    def add_skipped(self, path: str) -> None:
        """Record a skipped file (relative path)."""
        if path not in self.skipped:
            self.skipped.append(path)

    def add_error(self, path: str, error: Exception) -> None:
        """Record an error that happened while handling ``path``."""
        self.errors.append(
            {"path": path, "error": type(error).__name__, "message": str(error)}
        )

    def to_dict(self) -> Dict[str, Any]:
        """Dictionary form for JSON reporting."""
        return {
            "created": self.created,
            "updated": self.updated,
            "skipped": self.skipped,
            "errors": self.errors,
        }

    def to_json(self) -> str:
        """Valid, indented JSON form for machine consumption."""
        return json.dumps(self.to_dict(), indent=2)

    @property
    def success(self) -> bool:
        """True when no error was recorded."""
        return len(self.errors) == 0

    def __len__(self) -> int:
        return len(self.created) + len(self.updated) + len(self.skipped)


class BaseGenerator:
    """Base class for all Betrayer generators.

    ``output_dir`` is the directory the generator writes *into*.  A generator
    overrides :meth:`generate` to produce its files with :meth:`_write`, which
    records every outcome on :attr:`output`.
    """

    name: str = "base"
    description: str = "Base generator class"

    def __init__(self, output_dir: Path, overwrite: bool = False) -> None:
        self.output_dir = Path(output_dir).resolve()
        self.overwrite = overwrite
        self.output = GeneratorOutput()

    @property
    def base_path(self) -> Path:
        """The directory generated files are written into."""
        return self.output_dir

    def _ensure_directory(self, path: Path) -> None:
        """Create ``path`` (and parents) when missing."""
        path.mkdir(parents=True, exist_ok=True)

    def _get_relative_path(self, full_path: Path) -> str:
        """Path of ``full_path`` relative to the output directory."""
        try:
            return str(full_path.relative_to(self.output_dir))
        except ValueError:
            return str(full_path)

    def _write(self, relative: str, content: str) -> None:
        """Write ``content`` to ``output_dir / relative`` with overwrite guard.

        Raises :class:`GeneratorError` when the file already exists and
        ``overwrite`` is False.  When ``overwrite`` is True the file is
        replaced and recorded as updated.
        """
        target = self.output_dir / relative
        relative_str = self._get_relative_path(target)
        self._ensure_directory(target.parent)
        existed = target.exists()
        if existed and not self.overwrite:
            raise GeneratorError(f"file already exists (use --force): {relative_str}")
        target.write_text(content, encoding="utf-8")
        if existed:
            self.output.add_updated(relative_str)
        else:
            self.output.add_created(relative_str)

    def generate(self) -> GeneratorOutput:
        """Main entry point; subclasses must implement it."""
        raise NotImplementedError("Subclasses must implement generate()")


class TemplateRenderer:
    """Tiny deterministic template renderer (name substitution only).

    Useful when a generator wants to inline a template without pulling in a
    template engine.  Supported placeholders::

        {{ project_name }}  the directory name
        {{ app_name }}      snake_case package name
        {{ AppName }}       TitleCase display name
    """

    def __init__(self) -> None:
        self.context: Dict[str, str] = {}

    def set_context(self, key: str, value: str) -> None:
        """Set a substitution value."""
        self.context[key] = value

    def render(self, template: str) -> str:
        """Return ``template`` with ``{{ key }}`` placeholders substituted."""
        result = template
        for key, value in self.context.items():
            result = result.replace("{{ " + key + " }}", value)
            result = result.replace("{{" + key + "}}", value)
        return result

    def render_file(self, template_path: Path) -> str:
        """Render a template file path."""
        return self.render(template_path.read_text(encoding="utf-8"))


def snake_case(name: str) -> str:
    """Convert a name to ``snake_case`` (``MyApp`` -> ``my_app``)."""
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    s2 = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1)
    return re.sub(r"[-\s]+", "_", s2).lower()


def camel_case(name: str) -> str:
    """Convert a name to ``camelCase`` (``my_app`` -> ``myApp``)."""
    parts = re.sub(r"[-_\s]+", " ", name).split()
    parts = [p.capitalize() for p in parts]
    return (parts[0].lower() + "".join(parts[1:])) if parts else ""


def title_case(name: str) -> str:
    """Convert a name to ``TitleCase`` (``my_app`` -> ``MyApp``)."""
    parts = re.sub(r"[-_\s]+", " ", name).split()
    return "".join(p.capitalize() for p in parts)


def package_name(name: str) -> str:
    """Return the importable Python package name for ``name``.

    ``name`` is assumed to have passed :func:`validate_project_name`.
    """
    return re.sub(r"[-\s]+", "_", name).lower()


def validate_project_name(name: str) -> Optional[str]:
    """Return a human readable error message, or ``None`` when ``name`` is OK.

    Rules:
        * required and not empty
        * starts with an ASCII letter
        * contains only ASCII letters, digits, ``-`` and ``_``
        * no path separators, no dots, no whitespace
    """
    if not name or not isinstance(name, str):
        return "project name is required"
    if name != name.strip():
        return "project name must not have leading or trailing whitespace"
    if not PROJECT_NAME_PATTERN.match(name):
        return (
            "project name must start with a letter and contain only letters, "
            "digits, '-' or '_'"
        )
    return None