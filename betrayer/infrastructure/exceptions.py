"""Infrastructure Layer exception hierarchy.

Extends the existing Betrayer exception pattern without adding duplicates.
"""

from __future__ import annotations

from betrayer.core.exceptions import BetrayerError


class InfrastructureError(BetrayerError):
    """Base for all Infrastructure Layer errors."""

    code = "INFRASTRUCTURE_ERROR"
    component = "infrastructure"


class HTTPClientError(InfrastructureError):
    """Raised for HTTP client connection failures, timeouts, or protocol errors."""

    code = "HTTP_CLIENT_ERROR"
    component = "infrastructure.http_client"


class HTTPConnectionError(HTTPClientError):
    """Raised when a connection cannot be established (timeout, DNS, refused)."""

    code = "HTTP_CONNECTION_ERROR"
    component = "http_client"


class HTTPResponseError(HTTPClientError):
    """Raised when the HTTP response indicates a failure (4xx/5xx).

    Contains the status code and response body for inspection.
    """

    code = "HTTP_RESPONSE_ERROR"
    component = "infrastructure.http_client"

    def __init__(
        self,
        message: str = "",
        *,
        status_code: int = 0,
        body: str = "",
        cause: Exception | None = None,
    ) -> None:
        super().__init__(message, cause=cause)
        self.status_code = status_code
        self.body = body


class HTTPTimeoutError(HTTPClientError):
    """Raised when an HTTP request times out."""

    code = "HTTP_TIMEOUT"
    component = "infrastructure.http_client"

    def __init__(
        self,
        message: str = "",
        *,
        details: dict | None = None,
        cause: Exception | None = None,
    ) -> None:
        super().__init__(message, context=details or None, cause=cause)


class HTTPStatusError(HTTPClientError):
    """Raised when the HTTP response status indicates an error (4xx/5xx).

    Contains the HTTP response object for inspection.
    """

    code = "HTTP_STATUS_ERROR"
    component = "infrastructure.http_client"

    def __init__(
        self,
        message: str = "",
        *,
        details: dict | None = None,
        cause: Exception | None = None,
        response: Any = None,
    ) -> None:
        super().__init__(message, context=details or None, cause=cause)
        self.response = response


class EmailError(InfrastructureError):
    """Raised for email sending failures."""

    code = "EMAIL_ERROR"
    component = "infrastructure.email"


class NotificationError(InfrastructureError):
    """Raised for notification delivery failures."""

    code = "NOTIFICATION_ERROR"
    component = "infrastructure.notification"


class SchedulerError(InfrastructureError):
    """Raised for scheduler registration or execution failures."""

    code = "SCHEDULER_ERROR"
    component = "infrastructure.scheduler"


class BackgroundJobError(InfrastructureError):
    """Raised for background job lifecycle or execution errors."""

    code = "BACKGROUND_JOB_ERROR"
    component = "infrastructure.background_jobs"


class QueueError(InfrastructureError):
    """Raised for queue enqueue/dequeue/execution failures."""

    code = "QUEUE_ERROR"
    component = "infrastructure.queue"


class RetryError(InfrastructureError):
    """Raised when all retry attempts are exhausted."""

    code = "RETRY_ERROR"
    component = "infrastructure.retry"

    def __init__(
        self,
        message: str = "",
        *,
        attempts: int = 0,
        last_exception: Exception | None = None,
        cause: Exception | None = None,
    ) -> None:
        super().__init__(message, cause=cause)
        self.attempts = attempts
        self.last_exception = last_exception


class RateLimitError(InfrastructureError):
    """Raised when a rate limit is exceeded."""

    code = "RATE_LIMIT_ERROR"
    component = "infrastructure.rate_limiter"

    def __init__(
        self,
        message: str = "",
        *,
        limit: int = 0,
        window_seconds: float = 0.0,
        retry_after: float = 0.0,
        cause: Exception | None = None,
    ) -> None:
        super().__init__(message, cause=cause)
        self.limit = limit
        self.window_seconds = window_seconds
        self.retry_after = retry_after


class RetryableError(InfrastructureError):
    """Error that can be retried automatically."""

    code = "RETRYABLE_ERROR"
    component = "infrastructure.retry"


class HealthCheckError(InfrastructureError):
    """Raised when a health check probe fails."""

    code = "HEALTH_CHECK_ERROR"
    component = "infrastructure.health_check"


__all__ = [
    "InfrastructureError",
    "HTTPClientError",
    "HTTPConnectionError",
    "HTTPResponseError",
    "HTTPTimeoutError",
    "HTTPStatusError",
    "EmailError",
    "NotificationError",
    "SchedulerError",
    "BackgroundJobError",
    "QueueError",
    "RetryError",
    "RetryableError",
    "RateLimitError",
    "HealthCheckError",
]