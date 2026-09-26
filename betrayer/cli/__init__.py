"""Betrayer CLI package.

The CLI is a *consumer* of the public framework API.  It must never reach
into ``core`` internals: it uses ``Bootstrap`` to build an application and
``Inspector`` to read state.
"""

from __future__ import annotations

from betrayer.cli.main import build_command_registry, build_parser, main, run_validate
from betrayer.cli.registry import Command, CommandError, CommandRegistry

__all__ = [
    "Command",
    "CommandError",
    "CommandRegistry",
    "build_command_registry",
    "build_parser",
    "main",
    "run_validate",
]
