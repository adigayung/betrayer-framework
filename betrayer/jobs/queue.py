"""Canonical Queue abstraction.

A self-contained in-memory queue for Job dispatch::

    queue = Queue()
    queue.push(MyJob(...))
    job = queue.pop()
    queue.clear()
    size = queue.size()
"""

from __future__ import annotations

import heapq
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from betrayer.jobs.job import Job


@dataclass
class _QueueEntry:
    """Internal queue message wrapper."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    payload: Any = None
    priority: int = 0
    enqueued_at: float = field(default_factory=time.time)


class Queue:
    """Canonical queue for Job dispatch.

    Uses an in-memory priority heap as the default backend.
    """

    def __init__(self, name: str = "default", backend: Any = None) -> None:
        self.name = name
        self._backend = backend if backend is not None else _InMemoryBackend()
        self._counter = 0

    # -- canonical API -------------------------------------------------

    def push(self, job: Job, *, priority: int = 0) -> str:
        """Enqueue a Job.  Returns the job ID."""
        entry = _QueueEntry(payload=job, priority=priority)
        return self._backend.enqueue(entry, priority=priority)

    def pop(self) -> Optional[Job]:
        """Dequeue the next available Job, or None when empty."""
        entry = self._backend.dequeue()
        if entry is None:
            return None
        return entry.payload if isinstance(entry.payload, Job) else None

    def size(self) -> int:
        """Number of jobs currently in the queue."""
        return self._backend.size()

    def clear(self) -> None:
        """Remove all jobs from the queue."""
        self._backend.clear()

    # -- introspection -------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "size": self.size(),
            "backend": type(self._backend).__name__,
        }

    def __len__(self) -> int:
        return self.size()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Queue name={self.name!r} size={self.size()}>"


# ── Internal in-memory backend ────────────────────────────────────────


class _InMemoryBackend:
    """Minimal in-memory priority queue backend."""

    def __init__(self) -> None:
        self._heap: List[tuple] = []
        self._counter = 0

    def enqueue(self, entry: _QueueEntry, *, priority: int = 0) -> str:
        self._counter += 1
        heapq.heappush(self._heap, (-priority, self._counter, entry.id, entry))
        return entry.id

    def dequeue(self) -> Optional[_QueueEntry]:
        while self._heap:
            _, _, _, entry = heapq.heappop(self._heap)
            return entry
        return None

    def size(self) -> int:
        return len(self._heap)

    def clear(self) -> None:
        self._heap.clear()
        self._counter = 0


__all__ = ["Queue"]