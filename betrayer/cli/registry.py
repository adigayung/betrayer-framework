"""Command registry for the Betrayer CLI.

The CLI owns exactly one dispatch table: :class:`CommandRegistry`.  A command
is a small, explicit :class:`Command` record (name, help, handler and optional
argument setup).  The parser builder and the dispatch loop in
:mod:`betrayer.cli.main` only iterate that table, so adding ``create``,
``generate``, ``migrate`` or ``inspect`` later means registering one more
command -- never redesigning the CLI core.

This module is intentionally tiny: it is a plain registry, *not* a new CLI
framework and not a replacement for the framework level
``betrayer.core.registry.Registry`` (which tracks runtime components of an
application).
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Callable, Iterator, Optional

__all__ = ["Command", "CommandError", "CommandRegistry"]

#: Exit code for a controlled command failure (matches the CLI error contract).
FAILURE_EXIT_CODE = 1


class CommandError(Exception):
    """A controlled CLI failure.

    Raising this from a handler makes the CLI print a single ``[FAIL]`` line and
    return :attr:`exit_code` -- it never leaks a traceback to the user.
    """

    def __init__(self, message: str, exit_code: int = FAILURE_EXIT_CODE) -> None:
        super().__init__(message)
        self.exit_code = exit_code


@dataclass(frozen=True)
class Command:
    """A single CLI command.

    ``handler`` receives the parsed :class:`argparse.Namespace` and returns a
    real exit code (``0`` = success).  ``configure`` -- when given -- adds the
    command specific arguments/flags to the command's subparser.
    """

    name: str
    help: str
    handler: Callable[[argparse.Namespace], int]
    configure: Optional[Callable[[argparse.ArgumentParser], None]] = None

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        """Apply this command's argument configuration to ``parser``."""
        if self.configure is not None:
            self.configure(parser)


class CommandRegistry:
    """Ordered ``name -> Command`` table for the CLI.

    The registry is the single place commands are wired up.  It is created
    explicitly (see :func:`betrayer.cli.main.build_command_registry`) so there
    is no hidden import-time magic and no global mutable state beyond the one
    shared CLI table.
    """

    def __init__(self, prog: str) -> None:
        self._prog = prog
        self._commands: dict[str, Command] = {}

    @property
    def prog(self) -> str:
        """Program name used by argparse (e.g. ``"bet"``)."""
        return self._prog

    def register(self, command: Command) -> Command:
        """Register ``command``; raise ``ValueError`` on a duplicate name."""
        if not command.name:
            raise ValueError("command name must not be empty")
        if command.name in self._commands:
            raise ValueError(f"duplicate command: {command.name!r}")
        self._commands[command.name] = command
        return command

    def command(
        self,
        name: str,
        help: str,
        configure: Optional[Callable[[argparse.ArgumentParser], None]] = None,
    ) -> Callable[[Callable[[argparse.Namespace], int]], Callable[[argparse.Namespace], int]]:
        """Decorator form of :meth:`register` for declaring commands in place."""

        def decorator(handler: Callable[[argparse.Namespace], int]) -> Callable[[argparse.Namespace], int]:
            self.register(Command(name=name, help=help, handler=handler, configure=configure))
            return handler

        return decorator

    def get(self, name: str) -> Optional[Command]:
        """Return the command named ``name`` or ``None``."""
        return self._commands.get(name)

    def names(self) -> tuple[str, ...]:
        """Registered command names in registration order."""
        return tuple(self._commands)

    def commands(self) -> tuple[Command, ...]:
        """Registered commands in registration order."""
        return tuple(self._commands.values())

    def __contains__(self, name: object) -> bool:
        return name in self._commands

    def __iter__(self) -> Iterator[Command]:
        return iter(self._commands.values())

    def __len__(self) -> int:
        return len(self._commands)
