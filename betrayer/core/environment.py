"""Environment inspection for Betrayer.

The environment is *detected*, never mutated.  Windows is a first class
target: no POSIX assumptions, no hardcoded ``/`` path handling - all path
work goes through :mod:`pathlib`.

``Environment`` is a frozen dataclass, so a detected environment is an
immutable snapshot that is safe to share and easy to compare in tests.
"""

from __future__ import annotations

import os
import platform
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

PROJECT_MARKERS = ("pyproject.toml", "setup.py", ".betrayer", ".git")
DEFAULT_MODE = "development"
MODE_ENV_KEYS = ("BETRAYER_MODE", "BETRAYER_ENV")
CHECKED_DEPENDENCIES = ("betrayer", "pytest", "setuptools")


def detect_project_root(start: Path) -> Path:
    """Walk upwards from *start* until a project marker is found."""
    current = Path(start).resolve()
    for candidate in (current, *current.parents):
        for marker in PROJECT_MARKERS:
            if (candidate / marker).exists():
                return candidate
    return current


@dataclass(frozen=True)
class Environment:
    """Immutable snapshot of the execution environment."""

    python_version: str
    python_implementation: str
    os_name: str
    os_release: str
    architecture: str
    executable: str
    virtualenv: Optional[str]
    in_virtualenv: bool
    cwd: Path
    project_root: Path
    mode: str
    shell: str
    is_windows: bool
    dependencies: tuple = ()

    # -- construction -------------------------------------------------
    @classmethod
    def detect(
        cls,
        *,
        project_root: Optional[Path] = None,
        mode: Optional[str] = None,
        environ: Optional[dict] = None,
        cwd: Optional[Path] = None,
    ) -> "Environment":
        """Detect the current environment. Read-only: never mutates state."""
        env = dict(os.environ if environ is None else environ)
        working_dir = Path(cwd) if cwd is not None else Path.cwd()
        root = Path(project_root) if project_root is not None else detect_project_root(working_dir)
        in_virtualenv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
        resolved_mode = mode
        if resolved_mode is None:
            for key in MODE_ENV_KEYS:
                value = env.get(key)
                if value:
                    resolved_mode = value.strip().lower()
                    break
        if resolved_mode is None:
            resolved_mode = DEFAULT_MODE
        shell = env.get("COMSPEC") or env.get("SHELL") or env.get("ComSpec") or ""
        return cls(
            python_version=platform.python_version(),
            python_implementation=platform.python_implementation(),
            os_name=platform.system() or os.name,
            os_release=platform.release(),
            architecture=platform.machine() or "unknown",
            executable=sys.executable or "",
            virtualenv=sys.prefix if in_virtualenv else None,
            in_virtualenv=in_virtualenv,
            cwd=working_dir,
            project_root=Path(root),
            mode=resolved_mode,
            shell=shell,
            is_windows=os.name == "nt",
            dependencies=detect_dependencies(),
        )

    # -- inspection ---------------------------------------------------
    @property
    def platform_label(self) -> str:
        """Human readable ``OS release`` label."""
        return f"{self.os_name} {self.os_release}".strip()

    @property
    def is_development(self) -> bool:
        return self.mode == "development"

    def to_dict(self) -> dict:
        """Machine readable, JSON safe representation."""
        return {
            "python_version": self.python_version,
            "python_implementation": self.python_implementation,
            "os_name": self.os_name,
            "os_release": self.os_release,
            "architecture": self.architecture,
            "executable": self.executable,
            "virtualenv": self.virtualenv,
            "in_virtualenv": self.in_virtualenv,
            "cwd": str(self.cwd),
            "project_root": str(self.project_root),
            "mode": self.mode,
            "shell": self.shell,
            "is_windows": self.is_windows,
            "dependencies": [{"name": name, "version": version} for name, version in self.dependencies],
        }


def detect_dependencies(names: tuple = CHECKED_DEPENDENCIES) -> tuple:
    """Return ``((name, version), ...)`` for installed distributions.

    Missing packages are skipped silently - the environment inspector must
    never fail because an optional dependency is absent.
    """
    found = []
    try:
        from importlib import metadata
    except ImportError:  # pragma: no cover - importlib.metadata is stdlib on 3.8+
        return ()
    for name in names:
        try:
            found.append((name, metadata.version(name)))
        except Exception:
            continue
    return tuple(found)


__all__ = ["Environment", "detect_project_root", "detect_dependencies", "PROJECT_MARKERS"]
