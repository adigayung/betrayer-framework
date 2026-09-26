"""Runtime state for a single Betrayer application run.

``RuntimeState`` is a small, explicit, *instance* scoped value object -
never a module level singleton.  It answers "what is this run doing right
now" for diagnostics without carrying business logic.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class RuntimeState:
    """Mutable runtime bookkeeping owned by one application."""

    name: str = "betrayer"
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    stopped_at: Optional[float] = None
    metadata: dict = field(default_factory=dict)

    def mark_started(self) -> "RuntimeState":
        self.started_at = time.time()
        return self

    def mark_stopped(self) -> "RuntimeState":
        self.stopped_at = time.time()
        return self

    def set(self, key: str, value: Any) -> "RuntimeState":
        self.metadata[key] = value
        return self

    def get(self, key: str, default: Any = None) -> Any:
        return self.metadata.get(key, default)

    @property
    def is_started(self) -> bool:
        return self.started_at is not None

    def uptime(self) -> Optional[float]:
        if self.started_at is None:
            return None
        end = self.stopped_at if self.stopped_at is not None else time.time()
        return round(end - self.started_at, 6)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "stopped_at": self.stopped_at,
            "started": self.is_started,
            "uptime": self.uptime(),
            "metadata": dict(self.metadata),
        }


__all__ = ["RuntimeState"]
