"""Queue abstraction for enqueue/dequeue/job execution.

Design decisions:
- ``QueueBackend`` is an abstract interface; concrete backends implement it.
- ``InMemoryQueue`` is the default backend — adequate for dev/testing/single-process.
- Backend can be replaced via Container registration (Redis, SQS, RabbitMQ, etc.).
- Supports priority, TTL, and retry metadata.
- No overlap with ``background_jobs`` — Queue handles message passing, JobRunner
  handles execution lifecycle.
- No distributed queue features unless required.
"""

from __future__ import annotations

import heapq
import json
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from betrayer.infrastructure.exceptions import (
    InfrastructureError,
    QueueError,
)


# ── Data Types ──────────────────────────────────────────────────────


@dataclass
class QueueMessage:
    """A single message on the queue."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    payload: Any = None
    priority: int = 0
    ttl: Optional[float] = None  # seconds from enqueue
    retry_count: int = 0
    max_retries: int = 3
    enqueued_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)


# ── Abstract Backend ────────────────────────────────────────────────


class QueueBackend(ABC):
    """Abstract interface for queue backends."""

    @abstractmethod
    def enqueue(
        self,
        message: QueueMessage,
        *,
        priority: int = 0,
        ttl: Optional[float] = None,
    ) -> str:
        """Enqueue a message and return its ID."""

    @abstractmethod
    def dequeue(self, timeout: Optional[float] = None) -> Optional[QueueMessage]:
        """Dequeue the next available message."""

    @abstractmethod
    def acknowledge(self, message_id: str) -> bool:
        """Acknowledge that a message has been processed."""

    @abstractmethod
    def requeue(self, message: QueueMessage) -> None:
        """Re-queue a failed message for retry."""

    @abstractmethod
    def size(self) -> int:
        """Return the current queue size."""

    @abstractmethod
    def clear(self) -> None:
        """Remove all messages from the queue."""

    @abstractmethod
    def to_dict(self) -> Dict[str, Any]:
        """Return machine-readable metadata."""


# ── In-Memory Backend ───────────────────────────────────────────────


class InMemoryQueue(QueueBackend):
    """In-memory priority queue backend.

    Suitable for development, testing, and single-process applications.
    Uses a heap for priority ordering.
    """

    def __init__(self, name: str = "default") -> None:
        self.name = name
        self._heap: List[Tuple[int, float, str, QueueMessage]] = []
        self._messages: Dict[str, QueueMessage] = {}
        self._counter = 0

    def enqueue(
        self,
        message: QueueMessage,
        *,
        priority: int = 0,
        ttl: Optional[float] = None,
    ) -> str:
        message.priority = priority
        message.ttl = ttl
        self._counter += 1
        entry = (-priority, self._counter, message.id, message)
        heapq.heappush(self._heap, entry)
        self._messages[message.id] = message
        return message.id

    def dequeue(self, timeout: Optional[float] = None) -> Optional[QueueMessage]:
        now = time.time()
        while self._heap:
            _, _, msg_id, message = heapq.heappop(self._heap)
            # Check TTL
            if message.ttl is not None and (now - message.enqueued_at) > message.ttl:
                self._messages.pop(msg_id, None)
                continue
            return message
        return None

    def acknowledge(self, message_id: str) -> bool:
        return self._messages.pop(message_id, None) is not None

    def requeue(self, message: QueueMessage) -> None:
        message.retry_count += 1
        if message.retry_count > message.max_retries:
            raise QueueError(
                f"Message {message.id} exceeded max retries ({message.max_retries})",
                component="queue",
            )
        self.enqueue(message, priority=message.priority, ttl=message.ttl)

    def size(self) -> int:
        return len(self._heap)

    def clear(self) -> None:
        self._heap.clear()
        self._messages.clear()
        self._counter = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "backend": "InMemoryQueue",
            "name": self.name,
            "size": self.size(),
            "messages_in_flight": len(self._messages),
        }


# ── Queue Manager ───────────────────────────────────────────────────


class QueueManager:
    """High-level queue manager integrated with Container.

    ``QueueManager`` owns the backend lifecycle and provides convenience
    methods for common queue operations.
    """

    def __init__(
        self,
        backend: Optional[QueueBackend] = None,
        name: str = "queue",
    ) -> None:
        self.name = name
        self._backend = backend or InMemoryQueue(name=name)
        self._handlers: Dict[str, Callable[[QueueMessage], Any]] = {}

    @property
    def backend(self) -> QueueBackend:
        return self._backend

    def register_handler(
        self, queue_name: str, handler: Callable[[QueueMessage], Any]
    ) -> None:
        """Register a handler for a named queue."""
        self._handlers[queue_name] = handler

    def enqueue(
        self,
        payload: Any,
        *,
        queue_name: str = "default",
        priority: int = 0,
        ttl: Optional[float] = None,
        max_retries: int = 3,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Enqueue a payload to the named queue."""
        message = QueueMessage(
            payload=payload,
            priority=priority,
            ttl=ttl,
            max_retries=max_retries,
            metadata=metadata or {},
        )
        return self._backend.enqueue(message, priority=priority, ttl=ttl)

    def process_one(self, timeout: Optional[float] = None) -> bool:
        """Dequeue and process one message. Returns True if processed."""
        message = self._backend.dequeue(timeout=timeout)
        if message is None:
            return False
        handler = self._handlers.get("default")
        if handler is None:
            self._backend.requeue(message)
            return False
        try:
            handler(message)
            self._backend.acknowledge(message.id)
        except Exception:
            try:
                self._backend.requeue(message)
            except QueueError:
                pass
        return True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "backend": self._backend.to_dict(),
            "handlers": list(self._handlers.keys()),
        }


__all__ = [
    "QueueBackend",
    "InMemoryQueue",
    "QueueManager",
    "QueueMessage",
]