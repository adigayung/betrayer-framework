"""Canonical Queue abstraction.

Wraps the existing infrastructure queue backend with a Job-oriented API::

    queue = Queue()
    queue.push(MyJob(...))
    job = queue.pop()
    queue.clear()
    size = queue.size()
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import betrayer.infrastructure.queue as _infra_queue

_InMemoryQueue = _infra_queue.InMemoryQueue
_QueueMessage = _infra_queue.QueueMessage
from betrayer.jobs.job import Job


class Queue:
    """Canonical queue for Job dispatch.

    Uses the existing ``betrayer.infrastructure.queue.InMemoryQueue`` as
    the default in-memory backend.  A different backend can be injected
    via the ``backend`` parameter (must implement the same interface).
    """

    def __init__(self, name: str = "default", backend: Any = None) -> None:
        self.name = name
        self._backend = backend if backend is not None else _InMemoryQueue(name=name)

    # -- canonical API -------------------------------------------------

    def push(self, job: Job, *, priority: int = 0) -> str:
        """Enqueue a Job.  Returns the job ID."""
        message = _QueueMessage(
            payload=job,
            priority=priority,
        )
        return self._backend.enqueue(message, priority=priority)

    def pop(self) -> Optional[Job]:
        """Dequeue the next available Job, or None when empty."""
        message = self._backend.dequeue()
        if message is None:
            return None
        self._backend.acknowledge(message.id)
        return message.payload if isinstance(message.payload, Job) else None

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


__all__ = ["Queue"]