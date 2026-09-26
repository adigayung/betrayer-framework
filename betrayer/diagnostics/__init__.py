"""Betrayer diagnostics: read-only inspection and `doctor` checks.

Diagnostics depend on ``core`` and use the public inspection API of the
application.  It never reaches into private attributes and never mutates
the inspected object.
"""

from __future__ import annotations

from betrayer.diagnostics.inspector import Inspector

__all__ = ["Inspector"]
