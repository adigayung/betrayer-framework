# tests/test_infrastructure.py — Infrastructure Layer Tests (Task 06)
"""Tests for betrayer.infrastructure components.

Covers contract/behavior of remaining infrastructure components:
HTTP client, Email, Notification, Retry, and Health Check.

Note
----
Scheduler, background jobs, queue, and rate limiting have been moved
to their canonical packages (``betrayer.jobs``, ``betrayer.ratelimit``).
Tests for those subsystems live in ``test_events_jobs.py`` and
``test_rate_limiting.py`` respectively.
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
        from betrayer.infrastructure.http_client import HttpClient, HttpClientConfig
        assert HttpClient is not None
        assert HttpClientConfig is not None

    def test_default_config(self):
        from betrayer.infrastructure.http_client import HttpClientConfig
        cfg = HttpClientConfig()
        assert cfg.timeout == 30.0
        assert cfg.base_url is None
        assert cfg.default_headers == {}

    def test_custom_config(self):
        from betrayer.infrastructure.http_client import HttpClientConfig
        cfg = HttpClientConfig(
            timeout=10.0,
            base_url="https://api.example.com",
            default_headers={"Authorization": "Bearer test"},
        )
        assert cfg.timeout == 10.0
        assert cfg.base_url == "https://api.example.com"
        assert cfg.default_headers["Authorization"] == "Bearer test"

    def test_client_can_be_instantiated(self):
        from betrayer.infrastructure.http_client import RequestsHttpClient, HttpClientConfig
        client = RequestsHttpClient(config=HttpClientConfig())
        assert client is not None
        assert client.config is not None

    def test_request_methods_are_defined(self):
        from betrayer.infrastructure.http_client import RequestsHttpClient, HttpClientConfig
        client = RequestsHttpClient(config=HttpClientConfig())
        assert hasattr(client, "get")
        assert hasattr(client, "post")
        assert hasattr(client, "put")
        assert hasattr(client, "delete")
        assert hasattr(client, "head")
        assert hasattr(client, "options")

    def test_client_custom_session(self):
        """HttpClient (RequestsHttpClient) accepts a custom session/backend object."""
        from betrayer.infrastructure.http_client import RequestsHttpClient, HttpClientConfig
        import types
        session = types.ModuleType("fake_session")
        client = RequestsHttpClient(config=HttpClientConfig(), session=session)
        # The session is stored as _session
        assert hasattr(client, "_session")

    def test_client_config_retry_policy(self):
        """HttpClientConfig stores a retry policy reference."""
        from betrayer.infrastructure.http_client import HttpClientConfig
        config = HttpClientConfig(retry_policy={"max_attempts": 3})
        assert config.retry_policy == {"max_attempts": 3}


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
        assert msg.from_address is None
        assert msg.cc is None
        assert msg.bcc is None
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
        # send() completes without error for the console backend
        result = sender.send(msg)
        # ConsoleEmailBackend.send() returns None on success
        assert result is None


# ===================================================================
# Notification
# ===================================================================

class TestNotification:
    """Contract tests for notification abstraction."""

    def test_can_import_notification(self):
        from betrayer.infrastructure.notification import (
            Notification,
            NotificationBackend,
            Notifier,
        )
        assert Notification is not None
        assert NotificationBackend is not None
        assert Notifier is not None

    def test_notification_has_required_fields(self):
        from betrayer.infrastructure.notification import Notification
        n = Notification(
            subject="Alert",
            body="Something happened",
            channels=["log"],
        )
        assert n.subject == "Alert"
        assert n.body == "Something happened"
        assert n.channels == ["log"]
        assert n.priority == "normal"

    def test_notifier_accepts_backends(self):
        from betrayer.infrastructure.notification import (
            LogNotificationBackend,
            Notifier,
        )
        notifier = Notifier(backends=[LogNotificationBackend()])
        assert hasattr(notifier, "notify")
        assert hasattr(notifier, "add_backend")

    def test_notifier_send(self):
        from betrayer.infrastructure.notification import (
            Notification,
            Notifier,
        )
        notifier = Notifier()
        n = Notification(subject="Test", body="Test message", channels=["log"])
        result = notifier.notify(n)
        assert result is True


# ===================================================================
# (Scheduler, Background Jobs, Queue, Rate Limiter moved to
#  canonical packages -- see test_events_jobs.py, test_rate_limiting.py)
# ===================================================================


# ===================================================================
# Retry
# ===================================================================

class TestRetry:
    """Contract tests for retry mechanism."""

    def test_can_import_retry(self):
        from betrayer.infrastructure.retry import (
            retry,
            RetryPolicy,
            RetryState,
        )
        from betrayer.infrastructure.exceptions import RetryError
        assert retry is not None
        assert RetryPolicy is not None
        assert RetryError is not None
        assert RetryState is not None

    def test_retry_config_defaults(self):
        from betrayer.infrastructure.retry import RetryPolicy
        cfg = RetryPolicy()
        assert cfg.attempts == 3
        assert cfg.delay == 1.0
        assert cfg.backoff == 2.0  # exponential backoff by default

    def test_retry_config_custom(self):
        from betrayer.infrastructure.retry import RetryPolicy
        cfg = RetryPolicy(attempts=5, delay=2.0, backoff=3.0)
        assert cfg.attempts == 5
        assert cfg.delay == 2.0
        assert cfg.backoff == 3.0

    def test_retry_success(self):
        """Function succeeds on first try - no retries."""
        from betrayer.infrastructure.retry import retry, RetryPolicy

        call_count = 0

        def succeed():
            nonlocal call_count
            call_count += 1
            return "done"

        result = retry(succeed, policy=RetryPolicy(attempts=3))
        assert result == "done"
        assert call_count == 1

    def test_retry_eventual_success(self):
        """Function fails twice then succeeds."""
        from betrayer.infrastructure.retry import retry, RetryPolicy

        call_count = 0

        def fail_twice():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("transient")
            return "ok"

        result = retry(fail_twice, policy=RetryPolicy(
            attempts=3, delay=0.01,
            retryable_exceptions=[ConnectionError],
        ))
        assert result == "ok"
        assert call_count == 3

    def test_retry_exhausted(self):
        """All attempts fail - raises RetryError."""
        from betrayer.infrastructure.retry import retry, RetryPolicy
        from betrayer.infrastructure.exceptions import RetryableError

        call_count = 0

        def always_fail():
            nonlocal call_count
            call_count += 1
            raise RetryableError("persistent")

        with pytest.raises(RetryableError):
            retry(always_fail, policy=RetryPolicy(attempts=3, delay=0.01))
        assert call_count == 3

    def test_retry_non_retryable_raises_immediately(self):
        """Non-retryable error is raised immediately without retry."""
        from betrayer.infrastructure.retry import retry, RetryPolicy

        call_count = 0

        def always_fail():
            nonlocal call_count
            call_count += 1
            raise ValueError("not retryable")

        with pytest.raises(ValueError):
            retry(always_fail, policy=RetryPolicy(attempts=3, delay=0.01))
        assert call_count == 1

    def test_retry_state_has_attempt_info(self):
        """RetryState captures attempt number and exception info."""
        from betrayer.infrastructure.retry import RetryPolicy, RetryState

        state = RetryState(
            attempt=2,
            exception=ValueError("test"),
            elapsed=0.5,
            policy=RetryPolicy(),
        )
        assert state.attempt == 2
        assert "ValueError" in state.to_dict()["exception"]
        assert state.to_dict()["elapsed"] == 0.5


# ===================================================================
# (Rate Limiter moved to canonical package -- see test_rate_limiting.py)
# ===================================================================


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
        report = checker.summary()
        assert isinstance(report, dict)
        json.dumps(report)

    def test_health_check_with_exception(self):
        """Health check handles check function exceptions gracefully."""
        from betrayer.infrastructure.health import (
            HealthChecker,
            HealthCheckResult,
            HealthStatus,
        )

        def broken_check() -> HealthCheckResult:
            raise RuntimeError("unexpected failure")

        checker = HealthChecker()
        checker.register("broken", broken_check)
        results = checker.check_all()
        assert results["broken"].status == HealthStatus.UNHEALTHY


# ===================================================================
# Integration / Bootstrap
# ===================================================================

class TestInfrastructureIntegration:
    """Tests that infrastructure integrates with existing Betrayer patterns."""

    def test_import_all(self):
        """All infrastructure modules can be imported without error."""
        import betrayer.infrastructure.http_client
        import betrayer.infrastructure.email
        import betrayer.infrastructure.notification
        import betrayer.infrastructure.retry
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