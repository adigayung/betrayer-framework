"""Email abstraction for sending emails.

Design decisions:
- ``AbstractEmailBackend`` defines the interface; concrete backends implement it.
- ``ConsoleEmailBackend`` is the default backend for development/testing (logs to console).
- ``SmtpEmailBackend`` sends via SMTP.
- Configuration is explicit via ``EmailConfig``.
- Backend can be replaced via Container registration.
- The module does NOT overlap with Notification — email is a specific channel.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Dict, List, Optional

from betrayer.infrastructure.exceptions import EmailError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class EmailConfig:
    """Configuration for email sending.

    Attributes:
        backend: Backend name (``"console"``, ``"smtp"``).
        from_address: Default sender address.
        smtp_host: SMTP server hostname (smtp backend only).
        smtp_port: SMTP server port (smtp backend only).
        smtp_user: SMTP username (optional).
        smtp_password: SMTP password (optional).
        smtp_use_tls: Enable TLS (default True).
        smtp_timeout: SMTP connection timeout in seconds (default 30).
    """

    backend: str = "console"
    from_address: str = "noreply@example.com"
    smtp_host: str = "localhost"
    smtp_port: int = 587
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None
    smtp_use_tls: bool = True
    smtp_timeout: int = 30

    def to_dict(self) -> Dict[str, Any]:
        return {
            "backend": self.backend,
            "from_address": self.from_address,
            "smtp_host": self.smtp_host,
            "smtp_port": self.smtp_port,
            "smtp_user": self.smtp_user,
            "smtp_use_tls": self.smtp_use_tls,
            "smtp_timeout": self.smtp_timeout,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> EmailConfig:
        return cls(
            backend=data.get("backend", "console"),
            from_address=data.get("from_address", "noreply@example.com"),
            smtp_host=data.get("smtp_host", "localhost"),
            smtp_port=data.get("smtp_port", 587),
            smtp_user=data.get("smtp_user"),
            smtp_password=data.get("smtp_password"),
            smtp_use_tls=data.get("smtp_use_tls", True),
            smtp_timeout=data.get("smtp_timeout", 30),
        )


# ---------------------------------------------------------------------------
# Message
# ---------------------------------------------------------------------------


@dataclass
class EmailMessage:
    """Represents an email message to be sent.

    Attributes:
        to: List of recipient addresses.
        subject: Email subject line.
        body: Email body content.
        content_type: Content type (``"text/plain"`` or ``"text/html"``).
        cc: CC recipients (optional).
        bcc: BCC recipients (optional).
        from_address: Override sender address (optional).
    """

    to: List[str]
    subject: str
    body: str
    content_type: str = "text/plain"
    cc: Optional[List[str]] = None
    bcc: Optional[List[str]] = None
    from_address: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "to": self.to,
            "subject": self.subject,
            "body": self.body,
            "content_type": self.content_type,
            "cc": self.cc,
            "bcc": self.bcc,
            "from_address": self.from_address,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> EmailMessage:
        return cls(
            to=data["to"],
            subject=data["subject"],
            body=data["body"],
            content_type=data.get("content_type", "text/plain"),
            cc=data.get("cc"),
            bcc=data.get("bcc"),
            from_address=data.get("from_address"),
        )


# ---------------------------------------------------------------------------
# Abstract backend
# ---------------------------------------------------------------------------


class AbstractEmailBackend(ABC):
    """Abstract interface for email sending backends."""

    @abstractmethod
    def send(self, message: EmailMessage, config: EmailConfig) -> None:
        """Send an email message.

        Args:
            message: The email message to send.
            config: Email configuration.

        Raises:
            EmailError: If sending fails.
        """
        ...

    @abstractmethod
    def to_dict(self) -> Dict[str, Any]:
        """Return backend metadata for introspection."""
        ...


# ---------------------------------------------------------------------------
# Console backend (logs to console, for dev/testing)
# ---------------------------------------------------------------------------


class ConsoleEmailBackend(AbstractEmailBackend):
    """Email backend that logs messages to the console instead of sending."""

    def send(self, message: EmailMessage, config: EmailConfig) -> None:
        """Log the email message to console."""
        logger.info(
            "Email sent (console backend): to=%s subject=%s body=%s",
            message.to,
            message.subject,
            message.body[:200],
        )

    def to_dict(self) -> Dict[str, Any]:
        return {"type": "console"}


# ---------------------------------------------------------------------------
# SMTP backend
# ---------------------------------------------------------------------------


class SmtpEmailBackend(AbstractEmailBackend):
    """Email backend that sends via SMTP."""

    def __init__(self, config: EmailConfig) -> None:
        self._config = config

    def send(self, message: EmailMessage, config: EmailConfig) -> None:
        """Send email via SMTP."""
        from_addr = message.from_address or config.from_address
        recipients = list(message.to) + (message.cc or []) + (message.bcc or [])

        if message.content_type == "text/html":
            msg = MIMEText(message.body, "html")
        else:
            msg = MIMEText(message.body, "plain")

        msg["Subject"] = message.subject
        msg["From"] = from_addr
        msg["To"] = ", ".join(message.to)

        if message.cc:
            msg["Cc"] = ", ".join(message.cc)

        try:
            context = ssl.create_default_context() if config.smtp_use_tls else None
            with smtplib.SMTP(
                config.smtp_host, config.smtp_port, timeout=config.smtp_timeout
            ) as server:
                if config.smtp_use_tls:
                    server.starttls(context=context)
                if config.smtp_user:
                    server.login(config.smtp_user, config.smtp_password or "")
                server.sendmail(from_addr, recipients, msg.as_string())
        except (smtplib.SMTPException, OSError) as e:
            raise EmailError(
                f"SMTP send failed: {e}",
                component="email",
                details={"host": config.smtp_host, "port": config.smtp_port},
            ) from e

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "smtp",
            "host": self._config.smtp_host,
            "port": self._config.smtp_port,
            "use_tls": self._config.smtp_use_tls,
        }


# ---------------------------------------------------------------------------
# EmailSender (high-level API)
# ---------------------------------------------------------------------------


class EmailSender:
    """High-level email sender.

    Provides a simple API for sending emails, delegating to the configured
    backend internally.

    Usage::

        sender = EmailSender(config=EmailConfig(backend="console"))
        sender.send(EmailMessage(
            to=["user@example.com"],
            subject="Hello",
            body="Test message",
        ))
    """

    def __init__(self, config: Optional[EmailConfig] = None) -> None:
        self._config = config or EmailConfig()
        self._backend = self._create_backend()

    @property
    def config(self) -> EmailConfig:
        """Return the current configuration."""
        return self._config

    def _create_backend(self) -> AbstractEmailBackend:
        backend_name = self._config.backend
        if backend_name == "console":
            return ConsoleEmailBackend()
        elif backend_name == "smtp":
            return SmtpEmailBackend(self._config)
        else:
            raise EmailError(
                f"Unknown email backend: {backend_name!r}",
                component="email",
            )

    def send(self, message: EmailMessage) -> None:
        """Send an email message using the configured backend.

        Args:
            message: The email message to send.

        Raises:
            EmailError: If sending fails.
        """
        self._backend.send(message, self._config)

    def to_dict(self) -> Dict[str, Any]:
        """Return sender metadata for introspection."""
        return {
            "backend": self._backend.to_dict(),
            "config": self._config.to_dict(),
        }


# ---------------------------------------------------------------------------
# Factory helper
# ---------------------------------------------------------------------------


def create_email_sender(config: Optional[EmailConfig] = None) -> EmailSender:
    """Create an ``EmailSender`` with the given configuration.

    Args:
        config: Email configuration (defaults to ``EmailConfig()``).

    Returns:
        A configured ``EmailSender`` instance.
    """
    return EmailSender(config=config or EmailConfig())


__all__ = [
    "EmailConfig",
    "EmailMessage",
    "AbstractEmailBackend",
    "ConsoleEmailBackend",
    "SmtpEmailBackend",
    "EmailSender",
    "create_email_sender",
]