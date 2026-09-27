"""Betrayer Infrastructure Layer: HTTP client, email, notification, retry, and health check.

Dependency direction (enforced by convention)::

    core  <-  infrastructure  <-  runtime/application/web

Infrastructure Layer depends on **core** (Config, Container, Registry, Lifecycle,
Events, exceptions) but must **not** depend on data, runtime, application,
bootstrap, cli, or Flask/web layer.

Note
----
Scheduler, background jobs, queue, and rate limiting are now in their
canonical packages:

* ``betrayer.jobs``         — jobs, queue, scheduler, runner
* ``betrayer.ratelimit``    — rate limiting

These are **not** re-exported from ``betrayer.infrastructure`` to
avoid duplicate subsystem warnings.  Import them directly from their
canonical packages instead.
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

# Retry
from betrayer.infrastructure.retry import (
    RetryPolicy,
    RetryState,
    retry,
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
    # Retry
    "RetryPolicy",
    "RetryState",
    "retry",
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