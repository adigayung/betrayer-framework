"""Base generator classes and utilities for Betrayer Framework.

Provides common functionality for all generators:
- File generation with overwrite protection
- Template rendering with Jinja2 (or simple string replacement)
- Output collection for reporting
- Safety checks to avoid destructive operations
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional


class GeneratorError(Exception):
    """Base exception for generator errors."""
    pass


class FileExistsError(GeneratorError):
    """Raised when a file already exists and overwrite is not allowed."""
    def __init__(self, path: Path, message: str = None):
        self.path = path
        msg = message or f"File already exists: {path}"
        super().__init__(msg)


class OverwriteNotAllowedError(GeneratorError):
    """Raised when a generator attempts to overwrite a file without explicit permission."""
    pass


class GeneratorOutput:
    """Tracks files created, updated, skipped during generation."""

    def __init__(self):
        self.created: List[str] = []
        self.updated: List[str] = []
        self.skipped: List[str] = []
        self.errors: List[Dict[str, Any]] = []

    def add_created(self, path: str) -> None:
        """Record a newly created file."""
        if path not in self.created:
            self.created.append(path)

    def add_updated(self, path: str) -> None:
        """Record an updated file."""
        if path not in self.updated:
            self.updated.append(path)

    def add_skipped(self, path: str) -> None:
        """Record a skipped file (already exists, no overwrite)."""
        if path not in self.skipped:
            self.skipped.append(path)

    def add_error(self, path: str, error: Exception) -> None:
        """Record an error during generation."""
        self.errors.append({
            "path": path,
            "error": type(error).__name__,
            "message": str(error),
        })

    def to_dict(self) -> Dict[str, Any]:
        """Convert output to dictionary for JSON reporting."""
        return {
            "created": self.created,
            "updated": self.updated,
            "skipped": self.skipped,
            "errors": self.errors,
        }

    def to_json(self) -> str:
        """Convert output to JSON string."""
        return json.dumps(self.to_dict(), indent=2)

    @property
    def success(self) -> bool:
        """Return True if no errors occurred during generation."""
        return len(self.errors) == 0


class BaseGenerator:
    """Base class for all Betrayer generators.

    Provides common functionality:
    - Output tracking via GeneratorOutput
    - File existence checking
    - JSON reporting support
    """

    name: str = "base"
    description: str = "Base generator class"

    def __init__(self, project_root: Path, overwrite: bool = False):
        self.project_root = project_root.resolve()
        self.overwrite = overwrite
        self.output = GeneratorOutput()

    @property
    def base_path(self) -> Path:
        """Return the base directory for generated files."""
        return self.project_root

    def _ensure_directory(self, path: Path) -> None:
        """Ensure a directory exists, creating it if necessary."""
        path.mkdir(parents=True, exist_ok=True)

    def _get_relative_path(self, full_path: Path) -> str:
        """Get path relative to project root."""
        try:
            return str(full_path.relative_to(self.project_root))
        except ValueError:
            return str(full_path)

    def _write_file_safe(self, path: Path, content: str) -> None:
        """Write file safely with overwrite protection."""
        relative = self._get_relative_path(path)
        if path.exists():
            if self.overwrite:
                path.write_text(content, encoding="utf-8")
                self.output.add_updated(relative)
            else:
                self.output.add_skipped(relative)
                raise FileExistsError(path, f"File already exists: {relative}")
        else:
            self._ensure_directory(path.parent)
            path.write_text(content, encoding="utf-8")
            self.output.add_created(relative)

    def generate(self) -> GeneratorOutput:
        """Main entry point for generation. Override in subclasses."""
        raise NotImplementedError("Subclasses must implement generate()")

    def report(self, json_output: bool = False) -> str:
        """Generate a human-readable or JSON report."""
        if json_output:
            return self.output.to_json()

        lines = []
        if self.output.created:
            lines.append("Created:")
            for path in self.output.created:
                lines.append(f"  {path}")

        if self.output.updated:
            lines.append("\nUpdated:")
            for path in self.output.updated:
                lines.append(f"  {path}")

        if self.output.skipped:
            lines.append("\nSkipped:")
            for path in self.output.skipped:
                lines.append(f"  {path}")

        if self.output.errors:
            lines.append("\nErrors:")
            for error in self.output.errors:
                lines.append(f"  {error['path']}: {error['error']} - {error['message']}")

        total = len(self.output.created) + len(self.output.updated)
        lines.append(f"\n{total} file{'s' if total != 1 else ''} processed.")

        return "\n".join(lines)


class TemplateRenderer:
    """Simple template renderer for Betrayer generators.

    Supports basic Jinja2-like syntax or simple string replacement.
    Uses environment variables for common substitutions:
      {{ project_name }} - Project directory name
      {{ app_name }}     - Application/snake_case name
      {{ AppName }}     - TitleCase/PascalCase name
      {{ module_name }} - Module identifier
    """

    def __init__(self):
        self.context: Dict[str, str] = {}

    def set_context(self, key: str, value: str) -> None:
        """Set a context variable."""
        self.context[key] = value

    def render(self, template: str) -> str:
        """Render template with context variables."""
        result = template
        for key, value in self.context.items():
            placeholder = "{{ " + key + " }}"
            if placeholder in result:
                result = result.replace(placeholder, value)
            # Also try without spaces for convenience
            compact_placeholder = "{{" + key + "}}"
            if compact_placeholder in result:
                result = result.replace(compact_placeholder, value)
        return result

    def render_file(self, template_path: Path) -> str:
        """Read and render a template file."""
        template = template_path.read_text(encoding="utf-8")
        return self.render(template)


def snake_case(name: str) -> str:
    """Convert a name to snake_case."""
    import re
    # Handle PascalCase/CamelCase
    s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
    s2 = re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1)
    # Replace spaces and hyphens with underscores
    result = re.sub(r"[-\s]+", "_", s2)
    return result.lower()


def camel_case(name: str) -> str:
    """Convert a name to camelCase."""
    import re
    parts = re.sub(r"[-_\s]+", " ", name).split()
    parts = [p.capitalize() for p in parts]
    return (parts[0].lower() + "".join(parts[1:]) if parts else "")


def title_case(name: str) -> str:
    """Convert a name to TitleCase/PascalCase."""
    import re
    parts = re.sub(r"[-_\s]+", " ", name).split()
    return "".join(p.capitalize() for p in parts)
