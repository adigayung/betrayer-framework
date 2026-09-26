"""Betrayer Infrastructure Layer: HTTP client, email, notification, scheduler,
background jobs, queue, retry, rate limiter, and health check.

Dependency direction (enforced by convention)::

    core  <-  infrastructure  <-  runtime/application/web

Infrastructure Layer depends on **core** (Config, Container, Registry, Lifecycle,
Events, exceptions) but must **not** depend on data, runtime, application,
bootstrap, cli, or Flask/web layer.

Every public symbol is importable from ``betrayer.infrastructure`` for convenience:

.. code-block:: python

    from betrayer.infrastructure import (
        HttpClient,
        EmailSender,
        NotificationManager,
        DefaultScheduler,
        JobRunner,
        InMemoryQueue,
        RetryPolicy,
        InMemoryRateLimiter,
        HealthRegistry,
    )
"""

from __future__ import annotations

# HTTP client
from betrayer.infrastructure.http_client import (
    AbstractHttpClient,
    HttpClientConfig,
    HttpClientResponse,
    HttpClient,
)

# Email
from betrayer.infrastructure.email import (
    AbstractEmailBackend,
    ConsoleEmailBackend,
    EmailMessage,
    EmailSender,
    SmtpEmailBackend,
)

# Notification
from betrayer.infrastructure.notification import (
    AbstractNotificationChannel,
    Notification,
    NotificationManager,
)

# Scheduler
from betrayer.infrastructure.scheduler import (
    AbstractSchedulerBackend,
    DefaultScheduler,
    ScheduledJob,
    Scheduler,
)

# Background jobs
from betrayer.infrastructure.background_jobs import (
    AbstractJobRunner,
    BackgroundJob,
    InMemoryJobRunner,
    JobResult,
    JobRunner,
)

# Queue
from betrayer.infrastructure.queue import (
    AbstractQueueBackend,
    InMemoryQueue,
    QueueMessage,
    Queue,
)

# Retry
from betrayer.infrastructure.retry import (
    RetryHandler,
    RetryPolicy,
    retry,
)

# Rate limiter
from betrayer.infrastructure.rate_limiter import (
    AbstractRateLimiter,
    InMemoryRateLimiter,
    RateLimitRule,
    RateLimiter,
)

# Health check
from betrayer.infrastructure.health import (
    AbstractHealthCheck,
    HealthCheckResult,
    HealthRegistry,
    HealthStatus,
)

# Inspector
from betrayer.infrastructure.inspector import InfrastructureInspector

# Exceptions
from betrayer.infrastructure.exceptions import (
    BackgroundJobError,
    EmailError,
    HealthCheckError,
    HTTPClientError,
    HTTPConnectionError,
    HTTPStatusError,
    HTTPTimeoutError,
    InfrastructureError,
    NotificationError,
    QueueError,
    RateLimitError,
    RetryError,
    SchedulerError,
)

__all__ = [
    # HTTP client
    "AbstractHttpClient",
    "HttpClientConfig",
    "HttpClientResponse",
    "HttpClient",
    # Email
    "AbstractEmailBackend",
    "ConsoleEmailBackend",
    "EmailMessage",
    "EmailSender",
    "SmtpEmailBackend",
    # Notification
    "AbstractNotificationChannel",
    "Notification",
    "NotificationManager",
    # Scheduler
    "AbstractSchedulerBackend",
    "DefaultScheduler",
    "ScheduledJob",
    "Scheduler",
    # Background jobs
    "AbstractJobRunner",
    "BackgroundJob",
    "InMemoryJobRunner",
    "JobResult",
    "JobRunner",
    # Queue
    "AbstractQueueBackend",
    "InMemoryQueue",
    "QueueMessage",
    "Queue",
    # Retry
    "RetryHandler",
    "RetryPolicy",
    "retry",
    # Rate limiter
    "AbstractRateLimiter",
    "InMemoryRateLimiter",
    "RateLimitRule",
    "RateLimiter",
    # Health check
    "AbstractHealthCheck",
    "HealthCheckResult",
    "HealthRegistry",
    "HealthStatus",
    # Inspector
    "InfrastructureInspector",
    # Exceptions
    "BackgroundJobError",
    "EmailError",
    "HealthCheckError",
    "HTTPClientError",
    "HTTPConnectionError",
    "HTTPTimeoutError",
    "HTTPStatusError",
    "InfrastructureError",
    "NotificationError",
    "QueueError",
    "RateLimitError",
    "RetryError",
    "SchedulerError",
]