"""Infrastructure Layer inspector: machine-readable metadata for LLM introspection.

The inspector provides a deterministic snapshot of the Infrastructure Layer state
including registered HTTP clients, email backends, notification backends, retry
configurations, and health checks.

Note
----
Scheduler, background jobs, queue, and rate limiter are **not** inspected here.
They live in their canonical packages (``betrayer.jobs``, ``betrayer.ratelimit``).
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from betrayer.infrastructure.http_client import HttpClient
from betrayer.infrastructure.email import EmailSender
from betrayer.infrastructure.notification import Notifier
from betrayer.infrastructure.retry import RetryPolicy
from betrayer.infrastructure.health import HealthCheck, HealthCheckRegistry


class InfrastructureInspector:
    """Read-only introspection of the Infrastructure Layer.

    Usage::

        inspector = InfrastructureInspector(
            http_client=http_client_instance,
            email_service=email_service_instance,
            notification_service=notification_service_instance,
            health_registry=health_registry_instance,
        )
        snapshot = inspector.to_dict()
    """

    def __init__(
        self,
        http_client: Optional[HttpClient] = None,
        email_service: Optional[EmailSender] = None,
        notification_service: Optional[Notifier] = None,
        health_registry: Optional[HealthCheckRegistry] = None,
    ) -> None:
        self._http_client = http_client
        self._email_service = email_service
        self._notification_service = notification_service
        self._health_registry = health_registry

    def to_dict(self) -> Dict[str, Any]:
        """Return a deterministic JSON-serializable snapshot."""
        result: Dict[str, Any] = {}
        if self._http_client is not None:
            result["http_client"] = self._http_client.to_dict()
        if self._email_service is not None:
            result["email"] = self._email_service.to_dict()
        if self._notification_service is not None:
            result["notification"] = self._notification_service.to_dict()
        if self._health_registry is not None:
            result["health"] = self._health_registry.to_dict()
        return result

    def summary(self) -> str:
        """Short, human-readable summary of registered components."""
        parts = []
        if self._http_client is not None:
            parts.append("http")
        if self._email_service is not None:
            parts.append("email")
        if self._notification_service is not None:
            parts.append("notification")
        if self._health_registry is not None:
            parts.append("health")
        return f"InfrastructureLayer({', '.join(parts)})" if parts else "InfrastructureLayer(empty)"

    def __repr__(self) -> str:
        return self.summary()


__all__ = [
    "InfrastructureInspector",
]