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
        Notification,
        Notifier,
        SimpleScheduler,
        SimpleJobRunner,
        InMemoryQueue,
        RetryPolicy,
        InMemoryRateLimiter,
        HealthCheckRegistry,
    )
"""

from __future__ import annotations

# HTTP client
from betrayer.infrastructure.http_client import (
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
    Notification,
    Notifier,
    NotificationBackend,
    LogNotificationBackend,
)

# Scheduler
from betrayer.infrastructure.scheduler import (
    Scheduler,
    SimpleScheduler,
    SchedulerConfig,
    ScheduleTask,
    ScheduledJob,
)

# Background jobs
from betrayer.infrastructure.background_jobs import (
    JobState,
    Job,
    BackgroundJobConfig,
    JobRunner,
    SimpleJobRunner,
)

# Queue
from betrayer.infrastructure.queue import (
    QueueBackend,
    InMemoryQueue,
    QueueMessage,
    QueueManager,
)

# Retry
from betrayer.infrastructure.retry import (
    RetryPolicy,
    RetryState,
    retry,
)

# Rate limiter
from betrayer.infrastructure.rate_limiter import (
    RateLimiter,
    InMemoryRateLimiter,
    RateLimitExceeded,
)

# Health check
from betrayer.infrastructure.health import (
    HealthCheck,
    HealthCheckResult,
    HealthCheckRegistry,
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
    "Notification",
    "Notifier",
    "NotificationBackend",
    "LogNotificationBackend",
    # Scheduler
    "Scheduler",
    "SimpleScheduler",
    "SchedulerConfig",
    "ScheduleTask",
    "ScheduledJob",
    # Background jobs
    "JobState",
    "Job",
    "BackgroundJobConfig",
    "JobRunner",
    "SimpleJobRunner",
    # Queue
    "QueueBackend",
    "InMemoryQueue",
    "QueueMessage",
    "QueueManager",
    # Retry
    "RetryPolicy",
    "RetryState",
    "retry",
    # Rate limiter
    "RateLimiter",
    "InMemoryRateLimiter",
    "RateLimitExceeded",
    # Health check
    "HealthCheck",
    "HealthCheckResult",
    "HealthCheckRegistry",
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