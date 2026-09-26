"""Infrastructure Layer inspector: machine-readable metadata for LLM introspection.

The inspector provides a deterministic snapshot of the Infrastructure Layer state
including registered HTTP clients, email backends, notification backends, schedulers,
background job backends, queue backends, retry configurations, rate limiters, and
health checks.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from betrayer.infrastructure.http_client import HTTPBackend, HTTPClient
from betrayer.infrastructure.email import EmailBackend, EmailService
from betrayer.infrastructure.notification import NotificationBackend, NotificationService
from betrayer.infrastructure.scheduler import SchedulerBackend, Scheduler
from betrayer.infrastructure.background_jobs import JobBackend, BackgroundJobService
from betrayer.infrastructure.queue import QueueBackend, QueueService
from betrayer.infrastructure.retry import RetryPolicy
from betrayer.infrastructure.rate_limiter import RateLimiterBackend, RateLimiter
from betrayer.infrastructure.health import HealthCheck, HealthRegistry


class InfrastructureInspector:
    """Read-only introspection of the Infrastructure Layer.

    Usage::

        inspector = InfrastructureInspector(
            http_client=http_client_instance,
            email_service=email_service_instance,
            notification_service=notification_service_instance,
            scheduler=scheduler_instance,
            background_jobs=background_job_service_instance,
            queue_service=queue_service_instance,
            rate_limiter=rate_limiter_instance,
            health_registry=health_registry_instance,
        )
        snapshot = inspector.to_dict()
    """

    def __init__(
        self,
        http_client: Optional[HTTPClient] = None,
        email_service: Optional[EmailService] = None,
        notification_service: Optional[NotificationService] = None,
        scheduler: Optional[Scheduler] = None,
        background_jobs: Optional[BackgroundJobService] = None,
        queue_service: Optional[QueueService] = None,
        rate_limiter: Optional[RateLimiter] = None,
        health_registry: Optional[HealthRegistry] = None,
    ) -> None:
        self._http_client = http_client
        self._email_service = email_service
        self._notification_service = notification_service
        self._scheduler = scheduler
        self._background_jobs = background_jobs
        self._queue_service = queue_service
        self._rate_limiter = rate_limiter
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
        if self._scheduler is not None:
            result["scheduler"] = self._scheduler.to_dict()
        if self._background_jobs is not None:
            result["background_jobs"] = self._background_jobs.to_dict()
        if self._queue_service is not None:
            result["queue"] = self._queue_service.to_dict()
        if self._rate_limiter is not None:
            result["rate_limiter"] = self._rate_limiter.to_dict()
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
        if self._scheduler is not None:
            parts.append("scheduler")
        if self._background_jobs is not None:
            parts.append("jobs")
        if self._queue_service is not None:
            parts.append("queue")
        if self._rate_limiter is not None:
            parts.append("rate_limiter")
        if self._health_registry is not None:
            parts.append("health")
        return f"InfrastructureLayer({', '.join(parts)})" if parts else "InfrastructureLayer(empty)"

    def __repr__(self) -> str:
        return self.summary()


__all__ = [
    "InfrastructureInspector",
]