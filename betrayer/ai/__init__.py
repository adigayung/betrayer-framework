"""Betrayer LLM-facing surface — capability registry and discovery.

This package provides structured, machine-readable knowledge about
Betrayer capabilities so that LLM/AETHER can discover, understand,
and use the framework without reading large amounts of source code.

Public API (stable)::

    from betrayer.ai import discover

    # List all capabilities (summary)
    discover.list()

    # Get one capability (full definition)
    discover.get("pagination")

    # Search by keyword
    discover.search("authentication")

    # Progressive-disclosure Level-1 summary
    discover.summary("pagination")

The canonical registry lives in :mod:`betrayer.ai.capabilities` (single
source of truth).  The discovery API in :mod:`betrayer.ai.discover` is
the primary LLM-friendly entry point.
"""

from __future__ import annotations

from betrayer.ai import discover

__all__ = [
    "discover",
]