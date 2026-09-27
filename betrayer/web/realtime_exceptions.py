"""Realtime-specific exceptions.

Every class extends :class:`~betrayer.core.exceptions.BetrayerError` (the one
and only Betrayer error hierarchy) instead of inventing a second error system.
Transport/presentation errors live here; **business** errors stay inside the
Service and are never re-raised as realtime errors (the channel only reports
them as transport-level messages via ``Message.error_message``).
"""

from __future__ import annotations

from typing import Optional

from betrayer.core.exceptions import BetrayerError

__all__ = [
    "RealtimeError",
    "ChannelError",
    "ChannelNotFoundError",
    "ConnectionError",
    "ConnectionNotFoundError",
    "MessageError",
]


class RealtimeError(BetrayerError):
    """Base class for every realtime layer error."""

    code = "REALTIME_ERROR"
    component = "realtime"


class ChannelError(RealtimeError):
    """A problem with a realtime channel (registration, send, lifecycle)."""

    code = "CHANNEL_ERROR"
    component = "realtime"


class ChannelNotFoundError(ChannelError):
    """The requested channel name is not registered with the manager."""

    code = "CHANNEL_NOT_FOUND"
    component = "realtime"


class ConnectionError(RealtimeError):
    """A problem with a single realtime connection (open/close/send)."""

    code = "CONNECTION_ERROR"
    component = "realtime"


class ConnectionNotFoundError(ConnectionError):
    """The referenced connection id is unknown to the channel."""

    code = "CONNECTION_NOT_FOUND"
    component = "realtime"


class MessageError(RealtimeError):
    """A problem serialising or deserialising a realtime message."""

    code = "MESSAGE_ERROR"
    component = "realtime"


def _safe_message(error: BaseException) -> str:
    """Best-effort short message for a transport error report."""
    return str(error) or type(error).__name__
