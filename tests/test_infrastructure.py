# tests/test_infrastructure.py — Infrastructure Layer Tests (Task 06)
"""Tests for betrayer.infrastructure components.

Covers contract/behavior of each component: HTTP client, Email,
Notification, Scheduler, Background Jobs, Queue, Retry, Rate Limiter,
and Health Check.
"""

import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_runtime_context():
    """Return a minimal RuntimeContext stub so components can initialise."""
    from unittest.mock import MagicMock
    ctx = MagicMock()
    ctx.config = {"infrastructure": {}}
    return ctx


# ===================================================================
# HTTP Client
# ===================================================================

class TestHttpClient:
    """Contract tests for the HTTP client abstraction."""

    def test_can_import_http_client(self):
        from betrayer.infrastructure.http import HttpClient, HttpClientConfig
        assert HttpClient is not None
        assert HttpClientConfig is not None

    def test_default_config(self):
        from betrayer.infrastructure.http import HttpClientConfig
        cfg = HttpClientConfig()
        assert cfg.timeout == 30.0
        assert cfg.base_url == ""
        assert cfg.headers == {}

    def test_custom_config(self):
        from betrayer.infrastructure.http import HttpClientConfig
        cfg = HttpClientConfig(
            timeout=10.0,
            base_url="https://api.example.com",
            headers={"Authorization": "Bearer test"},
        )
        assert cfg.timeout == 10.0
        assert cfg.base_url == "https://api.example.com"
        assert cfg.headers["Authorization"] == "Bearer test"

    def test_client_can_be_instantiated(self):
        from betrayer.infrastructure.http import HttpClient, HttpClientConfig
        client = HttpClient(config=HttpClientConfig())
        assert client is not None
        assert client.config is not None

    def test_request_methods_are_defined(self):
        from betrayer.infrastructure.http import HttpClient, HttpClientConfig
        client = HttpClient(config=HttpClientConfig())
        assert hasattr(client, "request")
        assert hasattr(client, "get")
        assert hasattr(client, "post")
        assert hasattr(client, "put")
        assert hasattr(client, "delete")

    def test_client_custom_session(self):
        """HttpClient accepts a custom session/backend object."""
        from betrayer.infrastructure.http import HttpClient, HttpClientConfig
        session = {"custom": True}
        client = HttpClient(config=HttpClientConfig(), session=session)
        assert client.session is session

    def test_client_retry_hook(self):
        """HttpClient has a reference to retry config if integrated."""
        from betrayer.infrastructure.http import HttpClient, HttpClientConfig
        from betrayer.infrastructure.retry import RetryConfig
        client = HttpClient(
            config=HttpClientConfig(),
            retry_config=RetryConfig(max_attempts=3),
        )
        # The client stores retry_config or exposes it
        assert hasattr(client, "retry_config")
        assert client.retry_config.max_attempts == 3


# ===================================================================
# Email
# ===================================================================

class TestEmail:
    """Contract tests for email abstraction."""

    def test_can_import_email(self):
        from betrayer.infrastructure.email import (
            EmailMessage,
            EmailSender,
            EmailConfig,
        )
        assert EmailMessage is not None
        assert EmailSender is not None
        assert EmailConfig is not None

    def test_email_message_defaults(self):
        from betrayer.infrastructure.email import EmailMessage
        msg = EmailMessage(
            to=["user@example.com"],
            subject="Hello",
            body="Test body",
        )
        assert msg.to == ["user@example.com"]
        assert msg.subject == "Hello"
        assert msg.body == "Test body"
        assert msg.from_ is None
        assert msg.cc == []
        assert msg.bcc == []
        assert msg.content_type == "text/plain"

    def test_email_message_html(self):
        from betrayer.infrastructure.email import EmailMessage
        msg = EmailMessage(
            to=["user@example.com"],
            subject="HTML Email",
            body="<h1>Hello</h1>",
            content_type="text/html",
        )
        assert msg.content_type == "text/html"

    def test_sender_accepts_config(self):
        from betrayer.infrastructure.email import EmailSender, EmailConfig
        cfg = EmailConfig(
            backend="console",
            from_address="noreply@example.com",
        )
        sender = EmailSender(config=cfg)
        assert sender.config.backend == "console"
        assert sender.config.from_address == "noreply@example.com"

    def test_sender_send_returns_result(self):
        from betrayer.infrastructure.email import EmailSender, EmailConfig, EmailMessage
        cfg = EmailConfig(backend="console")
        sender = EmailSender(config=cfg)
        msg = EmailMessage(
            to=["user@example.com"],
            subject="Test",
            body="Testing",
        )
        result = sender.send(msg)
        # Must return something truthy / structured
        assert result is not None
        assert hasattr(result, "success") or isinstance(result, dict)


# ===================================================================
# Notification
# ===================================================================

class TestNotification:
    """Contract tests for notification abstraction."""

    def test_can_import_notification(self):
        from betrayer.infrastructure.notification import (
            Notification,
            NotificationChannel,
            NotificationConfig,
            NotificationManager,
        )
        assert Notification is not None
        assert NotificationChannel is not None
        assert NotificationConfig is not None
        assert NotificationManager is not None

    def test_notification_has_required_fields(self):
        from betrayer.infrastructure.notification import Notification
        n = Notification(
            title="Alert",
            message="Something happened",
            channel="email",
        )
        assert n.title == "Alert"
        assert n.message == "Something happened"
        assert n.channel == "email"
        assert n.priority == "normal"

    def test_notification_manager_accepts_channels(self):
        from betrayer.infrastructure.notification import (
            NotificationConfig,
            NotificationManager,
        )
        cfg = NotificationConfig(default_channel="email")
        mgr = NotificationManager(config=cfg)
        assert mgr.config.default_channel == "email"
        assert hasattr(mgr, "send")
        assert hasattr(mgr, "register_channel")

    def test_notification_manager_send(self):
        from betrayer.infrastructure.notification import (
            Notification,
            NotificationConfig,
            NotificationManager,
        )
        mgr = NotificationManager(config=NotificationConfig())
        n = Notification(title="Test", message="Test message")
        result = mgr.send(n)
        assert result is not None


# ===================================================================
# Scheduler
# ===================================================================

class TestScheduler:
    """Contract tests for scheduler abstraction."""

    def test_can_import_scheduler(self):
        from betrayer.infrastructure.scheduler import (
            Scheduler,
            ScheduledJob,
            SchedulerConfig,
        )
        assert Scheduler is not None
        assert ScheduledJob is not None
        assert SchedulerConfig is not None

    def test_scheduler_not_running_by_default(self):
        """Scheduler must not run implicitly on import."""
        from betrayer.infrastructure.scheduler import Scheduler, SchedulerConfig
        sched = Scheduler(config=SchedulerConfig())
        assert not sched.running

    def test_scheduler_add_job(self):
        from betrayer.infrastructure.scheduler import Scheduler, SchedulerConfig

        def my_task():
            pass

        sched = Scheduler(config=SchedulerConfig())
        sched.add_job("test_job", my_task, schedule="every 5 minutes")
        assert "test_job" in sched.list_jobs()

    def test_scheduler_job_has_schedule(self):
        from betrayer.infrastructure.scheduler import Scheduler, SchedulerConfig

        def my_task():
            pass

        sched = Scheduler(config=SchedulerConfig())
        sched.add_job("test_job", my_task, schedule="every 5 minutes")
        jobs = sched.list_jobs()
        assert jobs["test_job"]["schedule"] == "every 5 minutes"
        assert jobs["test_job"]["enabled"] is True


# ===================================================================
# Background Jobs
# ===================================================================

class TestBackgroundJobs:
    """Contract tests for background job abstraction."""

    def test_can_import_background_jobs(self):
        from betrayer.infrastructure.jobs import (
            BackgroundJob,
            JobRunner,
            JobConfig,
            JobStatus,
        )
        assert BackgroundJob is not None
        assert JobRunner is not None
        assert JobConfig is not None
        assert JobStatus is not None

    def test_background_job_lifecycle(self):
        from betrayer.infrastructure.jobs import BackgroundJob, JobStatus

        def my_task():
            return 42

        job = BackgroundJob(name="test_job", fn=my_task)
        assert job.name == "test_job"
        assert job.status == JobStatus.PENDING

    def test_job_runner_execute(self):
        from betrayer.infrastructure.jobs import BackgroundJob, JobRunner, JobConfig

        results = []

        def my_task():
            results.append(1)

        runner = JobRunner(config=JobConfig())
        job = BackgroundJob(name="test_job", fn=my_task)
        runner.execute(job)
        assert len(results) == 1
        assert job.status in (JobStatus.COMPLETED, JobStatus.SUCCESS)

    def test_job_failure_state(self):
        from betrayer.infrastructure.jobs import BackgroundJob, JobRunner, JobConfig, JobStatus

        def failing_task():
            raise ValueError("oops")

        runner = JobRunner(config=JobConfig())
        job = BackgroundJob(name="fail_job", fn=failing_task)
        runner.execute(job)
        assert job.status == JobStatus.FAILED
        assert job.error is not None


# ===================================================================
# Queue
# ===================================================================

class TestQueue:
    """Contract tests for queue abstraction."""

    def test_can_import_queue(self):
        from betrayer.infrastructure.queue import (
            Queue,
            QueueMessage,
            QueueConfig,
            QueueBackend,
        )
        assert Queue is not None
        assert QueueMessage is not None
        assert QueueConfig is not None
        assert QueueBackend is not None

    def test_queue_enqueue_dequeue(self):
        from betrayer.infrastructure.queue import Queue, QueueConfig
        q = Queue(config=QueueConfig())
        q.enqueue("test_queue", {"key": "value"})
        msg = q.dequeue("test_queue")
        assert msg is not None
        assert msg.payload == {"key": "value"}

    def test_queue_size(self):
        from betrayer.infrastructure.queue import Queue, QueueConfig
        q = Queue(config=QueueConfig())
        assert q.size("test_queue") == 0
        q.enqueue("test_queue", "item1")
        q.enqueue("test_queue", "item2")
        assert q.size("test_queue") == 2

    def test_queue_multiple_queues(self):
        from betrayer.infrastructure.queue import Queue, QueueConfig
        q = Queue(config=QueueConfig())
        q.enqueue("q1", "a")
        q.enqueue("q2", "b")
        assert q.size("q1") == 1
        assert q.size("q2") == 1


# ===================================================================
# Retry
# ===================================================================

class TestRetry:
    """Contract tests for retry mechanism."""

    def test_can_import_retry(self):
        from betrayer.infrastructure.retry import (
            retry,
            RetryConfig,
            RetryError,
            should_retry,
        )
        assert retry is not None
        assert RetryConfig is not None
        assert RetryError is not None
        assert should_retry is not None

    def test_retry_config_defaults(self):
        from betrayer.infrastructure.retry import RetryConfig
        cfg = RetryConfig()
        assert cfg.max_attempts == 3
        assert cfg.delay == 1.0
        assert cfg.backoff == 1.0  # no exponential by default

    def test_retry_config_custom(self):
        from betrayer.infrastructure.retry import RetryConfig
        cfg = RetryConfig(max_attempts=5, delay=2.0, backoff=2.0)
        assert cfg.max_attempts == 5
        assert cfg.delay == 2.0
        assert cfg.backoff == 2.0

    def test_retry_success(self):
        """Function succeeds on first try - no retries."""
        from betrayer.infrastructure.retry import retry, RetryConfig

        call_count = 0

        def succeed():
            nonlocal call_count
            call_count += 1
            return "done"

        result = retry(succeed, config=RetryConfig(max_attempts=3))
        assert result == "done"
        assert call_count == 1

    def test_retry_eventual_success(self):
        """Function fails twice then succeeds."""
        from betrayer.infrastructure.retry import retry, RetryConfig

        call_count = 0

        def fail_twice():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("transient")
            return "ok"

        result = retry(fail_twice, config=RetryConfig(max_attempts=3, delay=0.01))
        assert result == "ok"
        assert call_count == 3

    def test_retry_exhausted(self):
        """All attempts fail - raises RetryError."""
        from betrayer.infrastructure.retry import retry, RetryConfig, RetryError

        call_count = 0

        def always_fail():
            nonlocal call_count
            call_count += 1
            raise ValueError("persistent")

        with pytest.raises(RetryError):
            retry(always_fail, config=RetryConfig(max_attempts=3, delay=0.01))
        assert call_count == 3

    def test_should_retry_positive(self):
        from betrayer.infrastructure.retry import should_retry
        assert should_retry(ConnectionError("timeout"))
        assert should_retry(TimeoutError("timeout"))

    def test_should_retry_negative(self):
        from betrayer.infrastructure.retry import should_retry
        assert not should_retry(ValueError("invalid"))
        assert not should_retry(TypeError("type"))


# ===================================================================
# Rate Limiter
# ===================================================================

class TestRateLimiter:
    """Contract tests for rate limiter abstraction."""

    def test_can_import_rate_limiter(self):
        from betrayer.infrastructure.rate_limiter import (
            RateLimiter,
            RateLimiterConfig,
            RateLimitResult,
        )
        assert RateLimiter is not None
        assert RateLimiterConfig is not None
        assert RateLimitResult is not None

    def test_rate_limiter_config(self):
        from betrayer.infrastructure.rate_limiter import RateLimiterConfig
        cfg = RateLimiterConfig(max_requests=10, window_seconds=60)
        assert cfg.max_requests == 10
        assert cfg.window_seconds == 60

    def test_rate_limiter_allow(self):
        from betrayer.infrastructure.rate_limiter import RateLimiter, RateLimiterConfig
        limiter = RateLimiter(config=RateLimiterConfig(max_requests=5, window_seconds=60))
        for _ in range(5):
            result = limiter.allow("test_key")
            assert result.allowed is True
            assert result.remaining >= 0

    def test_rate_limiter_block(self):
        from betrayer.infrastructure.rate_limiter import RateLimiter, RateLimiterConfig
        limiter = RateLimiter(config=RateLimiterConfig(max_requests=2, window_seconds=60))
        limiter.allow("key")
        limiter.allow("key")
        result = limiter.allow("key")
        assert result.allowed is False
        assert result.remaining == 0

    def test_rate_limiter_reset(self):
        from betrayer.infrastructure.rate_limiter import RateLimiter, RateLimiterConfig
        limiter = RateLimiter(config=RateLimiterConfig(max_requests=1, window_seconds=1))
        limiter.allow("key")
        blocked = limiter.allow("key")
        assert blocked.allowed is False
        limiter.reset("key")
        result = limiter.allow("key")
        assert result.allowed is True


# ===================================================================
# Health Check
# ===================================================================

class TestHealthCheck:
    """Contract tests for health check abstraction."""

    def test_can_import_health_check(self):
        from betrayer.infrastructure.health import (
            HealthChecker,
            HealthCheckResult,
            HealthStatus,
            HealthCheckRegistry,
        )
        assert HealthChecker is not None
        assert HealthCheckResult is not None
        assert HealthStatus is not None
        assert HealthCheckRegistry is not None

    def test_health_result_structured(self):
        from betrayer.infrastructure.health import (
            HealthCheckResult,
            HealthStatus,
        )
        result = HealthCheckResult(
            name="database",
            status=HealthStatus.HEALTHY,
            details={"connected": True},
        )
        assert result.name == "database"
        assert result.status == HealthStatus.HEALTHY
        assert result.details == {"connected": True}

    def test_health_checker_register_and_check(self):
        from betrayer.infrastructure.health import (
            HealthChecker,
            HealthCheckResult,
            HealthStatus,
        )

        def check_db() -> HealthCheckResult:
            return HealthCheckResult(
                name="database",
                status=HealthStatus.HEALTHY,
                details={"connected": True},
            )

        checker = HealthChecker()
        checker.register("database", check_db)
        results = checker.check_all()
        assert "database" in results
        assert results["database"].status == HealthStatus.HEALTHY

    def test_health_check_failure(self):
        from betrayer.infrastructure.health import (
            HealthChecker,
            HealthCheckResult,
            HealthStatus,
        )

        def check_fail() -> HealthCheckResult:
            return HealthCheckResult(
                name="broken",
                status=HealthStatus.UNHEALTHY,
                details={"error": "timeout"},
            )

        checker = HealthChecker()
        checker.register("broken", check_fail)
        results = checker.check_all()
        assert results["broken"].status == HealthStatus.UNHEALTHY

    def test_health_result_to_dict(self):
        """Health results must be serialisable for Agent consumption."""
        from betrayer.infrastructure.health import (
            HealthCheckResult,
            HealthStatus,
        )
        result = HealthCheckResult(
            name="cache",
            status=HealthStatus.HEALTHY,
            details={"latency_ms": 2},
        )
        d = result.to_dict()
        assert isinstance(d, dict)
        assert d["name"] == "cache"
        assert d["status"] == "healthy"
        assert d["details"]["latency_ms"] == 2
        # Must be JSON-serialisable
        json.dumps(d)

    def test_health_checker_serialisable(self):
        """Checker results as a whole must be JSON-serialisable."""
        from betrayer.infrastructure.health import (
            HealthChecker,
            HealthCheckResult,
            HealthStatus,
        )

        def check_ok() -> HealthCheckResult:
            return HealthCheckResult(
                name="ok", status=HealthStatus.HEALTHY, details={}
            )

        checker = HealthChecker()
        checker.register("ok", check_ok)
        report = checker.get_report()
        assert isinstance(report, dict)
        json.dumps(report)

    def test_health_check_with_timeout(self):
        """Health check supports timeout configuration."""
        from betrayer.infrastructure.health import (
            HealthChecker,
            HealthCheckResult,
            HealthStatus,
        )

        def slow_check() -> HealthCheckResult:
            time.sleep(0.1)
            return HealthCheckResult(
                name="slow", status=HealthStatus.HEALTHY, details={}
            )

        checker = HealthChecker(timeout=0.05)
        checker.register("slow", slow_check)
        results = checker.check_all()
        # Should either be UNHEALTHY or TIMEOUT status
        assert results["slow"].status in (
            HealthStatus.UNHEALTHY,
            HealthStatus.TIMEOUT,
        )


# ===================================================================
# Integration / Bootstrap
# ===================================================================

class TestInfrastructureIntegration:
    """Tests that infrastructure integrates with existing Betrayer patterns."""

    def test_import_all(self):
        """All infrastructure modules can be imported without error."""
        import betrayer.infrastructure.http
        import betrayer.infrastructure.email
        import betrayer.infrastructure.notification
        import betrayer.infrastructure.scheduler
        import betrayer.infrastructure.jobs
        import betrayer.infrastructure.queue
        import betrayer.infrastructure.retry
        import betrayer.infrastructure.rate_limiter
        import betrayer.infrastructure.health
        assert True

    def test_infrastructure_package_exposes_api(self):
        """The infrastructure __init__ exposes key components."""
        import betrayer.infrastructure
        assert hasattr(betrayer.infrastructure, "__all__")
        assert betrayer.infrastructure.__all__ is not None

    def test_health_check_http_integration(self):
        """Health checker can wrap an HTTP client check."""
        from betrayer.infrastructure.health import (
            HealthChecker,
            HealthCheckResult,
            HealthStatus,
        )

        def check_http() -> HealthCheckResult:
            # Simulate checking HTTP client connectivity
            return HealthCheckResult(
                name="http_client",
                status=HealthStatus.HEALTHY,
                details={"reachable": True},
            )

        checker = HealthChecker()
        checker.register("http_client", check_http)
        results = checker.check_all()
        assert results["http_client"].status == HealthStatus.HEALTHY