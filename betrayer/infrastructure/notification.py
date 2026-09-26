"""Notification abstraction for sending notifications across channels.

Design decisions:
- ``Notifier`` is an abstract interface; concrete backends implement it.
- ``LogNotifier`` is the default backend for development/testing.
- Notification is *channel-agnostic* — email, SMS, push, webhook are channels.
- This module does NOT overlap with ``email.py``: email is a concrete transport
  that *could* be used as a notification channel, but the abstractions are separate.
- Configuration is explicit.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from betrayer.infrastructure.exceptions import (
    NotificationError,
)

logger = logging.getLogger(__name__)


# ── Data types ────────────────────────────────────────────────────


@dataclass
class Notification:
    """A notification payload."""

    subject: str
    body: str
    channels: List[str] = field(default_factory=lambda: ["log"])
    metadata: Dict[str, Any] = field(default_factory=dict)
    priority: str = "normal"  # low, normal, high, critical


# ── Abstract interface ────────────────────────────────────────────


class NotificationBackend(ABC):
    """Abstract notification backend."""

    @abstractmethod
    def send(self, notification: Notification) -> bool:
        """Send a notification. Return True on success."""
        ...

    @abstractmethod
    def supported_channels(self) -> List[str]:
        """Return list of channels this backend supports."""
        ...


# ── Default backend: log ──────────────────────────────────────────


class LogNotificationBackend(NotificationBackend):
    """Log-based notification backend for development/test."""

    def send(self, notification: Notification) -> bool:
        logger.info(
            "[%s] %s: %s",
            notification.priority.upper(),
            notification.subject,
            notification.body,
        )
        return True

    def supported_channels(self) -> List[str]:
        return ["log"]


# ── Notifier ──────────────────────────────────────────────────────


class Notifier:
    """Main notification service.

    Usage::

        notifier = Notifier(backends=[LogNotificationBackend()])
        notifier.notify(Notification(
            subject="Hello",
            body="World",
            channels=["log"],
        ))
    """

    def __init__(
        self,
        backends: Optional[Sequence[NotificationBackend]] = None,
    ) -> None:
        self._backends: List[NotificationBackend] = (
            list(backends) if backends else [LogNotificationBackend()]
        )
        self._sent_count: int = 0
        self._fail_count: int = 0

    def add_backend(self, backend: NotificationBackend) -> None:
        """Register an additional notification backend."""
        self._backends.append(backend)

    def notify(self, notification: Notification) -> bool:
        """Send a notification through matching backends.

        A backend is selected if any of its supported channels overlap
        with the notification's requested channels.
        """
        overall = True
        for backend in self._backends:
            supported = backend.supported_channels()
            if not set(notification.channels) & set(supported):
                continue
            try:
                ok = backend.send(notification)
                if ok:
                    self._sent_count += 1
                else:
                    self._fail_count += 1
                    overall = False
            except Exception as exc:
                self._fail_count += 1
                overall = False
                raise NotificationError(
                    f"Notification backend {type(backend).__name__} failed: {exc}",
                    cause=exc,
                ) from exc
        return overall

    def notify_many(self, notifications: List[Notification]) -> int:
        """Send multiple notifications. Returns success count."""
        success = 0
        for n in notifications:
            try:
                if self.notify(n):
                    success += 1
            except NotificationError:
                pass
        return success

    def stats(self) -> Dict[str, Any]:
        """Return notification statistics."""
        return {
            "backends": len(self._backends),
            "sent": self._sent_count,
            "failed": self._fail_count,
        }

    def report(self) -> Dict[str, Any]:
        """Machine-readable report for LLM introspection."""
        return {
            "backends": [type(b).__name__ for b in self._backends],
            "stats": self.stats(),
        }

    def __repr__(self) -> str:
        return (
            f"Notifier(backends={len(self._backends)}, "
            f"sent={self._sent_count}, failed={self._fail_count})"
        )


__all__ = [
    "Notification",
    "NotificationBackend",
    "LogNotificationBackend",
    "Notifier",
]