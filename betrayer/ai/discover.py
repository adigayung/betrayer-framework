"""LLM-friendly Capability Discovery API.

This is the **primary entry point** for LLM/AETHER to discover Betrayer
capabilities without reading framework source code.

Usage::

    from betrayer.ai import discover

    # List all capabilities (summary level)
    discover.list()

    # Get full capability definition
    discover.get("pagination")

    # Search by keyword
    discover.search("authentication")

    # Get progressive level 1 summary (for LLM context efficiency)
    discover.summary("pagination")

Every result is a structured dict (JSON-serialisable).
"""

from __future__ import annotations

from typing import Any

from betrayer.ai.capabilities import (
    CapabilityDef,
    CapabilityNotFoundError,
    get_capability,
    list_capabilities,
    search_capabilities,
    capability_summary,
)


# Re-export for convenience
__all__ = [
    "list",
    "get",
    "search",
    "summary",
    "CapabilityNotFoundError",
    "CapabilityDef",
]


def list() -> list[dict[str, Any]]:
    """Return a summary of every registered capability.

    Each entry contains ``name``, ``purpose``, ``category``, ``status``,
    and ``package`` — enough for an LLM to decide which capability to
    explore further without reading the full source.
    """
    return list_capabilities()


def get(name: str) -> dict[str, Any]:
    """Return the full definition of a single capability by name.

    Raises ``CapabilityNotFoundError`` if the name is unknown.
    """
    return get_capability(name)


def search(query: str) -> list[dict[str, Any]]:
    """Search capabilities by name, purpose, category, or package.

    Case-insensitive substring matching.  Returns summary level results
    (same shape as ``list()``).
    """
    return search_capabilities(query)


def summary(name: str) -> dict[str, Any]:
    """Progressive-disclosure Level-1 summary of a capability.

    Returns name, purpose, category, status, public API, contract link,
    package, and related capability names — without the full description,
    errors, or examples.  Suitable for LLM context efficiency when the
    agent only needs to know *what* a capability does, not *how*.
    """
    cap = get_capability(name)
    return capability_summary(cap)