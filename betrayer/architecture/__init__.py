"""Betrayer Architecture Guard — canonical architecture enforcement.

The guard detects architecture violations that make the framework harder for
LLM/AETHER to understand, maintain, or use.  It is **not** a general-purpose
linter and **not** a static analyser that tries to understand all Python.

Usage::

    from betrayer.architecture import guard

    result = guard.check()

    # or via the CLI
    # bet validate --json   (includes "architecture" section)

Every violation carries:
    - rule_id (e.g. ``BET-ARCH-001``)
    - severity (``error`` | ``warning``)
    - message
    - location (file:line)
    - remediation (actionable short text)

Architecture Guard depends only on **core** (no web, no AETHER, no Flask).
"""

from __future__ import annotations

from betrayer.architecture.checker import ArchitectureChecker, ArchitectureResult
from betrayer.architecture.rules import ArchitectureRule, RULES, rule_by_id

__all__ = [
    "ArchitectureChecker",
    "ArchitectureResult",
    "ArchitectureRule",
    "RULES",
    "rule_by_id",
    "check",
    "ARCHITECTURE_VERSION",
]

ARCHITECTURE_VERSION = "1.0.0"


def check() -> ArchitectureResult:
    """Run all architecture rules against the current Betrayer framework.

    Returns a structured ``ArchitectureResult`` (JSON-serialisable dict).
    """
    checker = ArchitectureChecker()
    return checker.check()