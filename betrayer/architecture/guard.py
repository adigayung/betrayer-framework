"""Architecture Guard convenience module.

Provides the ``guard.check()`` API referenced in the architecture contract::

    from betrayer.architecture import guard

    result = guard.check()
"""

from __future__ import annotations

from betrayer.architecture.checker import ArchitectureChecker, ArchitectureResult


def check() -> ArchitectureResult:
    """Run all architecture rules and return a structured result."""
    return ArchitectureChecker().check()


__all__ = [
    "check",
    "ArchitectureChecker",
    "ArchitectureResult",
]