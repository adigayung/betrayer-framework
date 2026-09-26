"""Betrayer runtime: per-run context and state.

Runtime depends on ``core`` only.  It must never create a global mutable
singleton - every object here is bound to an explicit owner.
"""

from __future__ import annotations

from betrayer.runtime.context import RuntimeContext
from betrayer.runtime.state import RuntimeState

__all__ = ["RuntimeContext", "RuntimeState"]
