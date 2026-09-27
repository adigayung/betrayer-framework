"""Realtime message contract (WebSocket / SSE / Channel payloads).

One message shape for the whole realtime layer.  It is machine readable and
reuses the existing request/trace identifiers from the diagnostics store so a
message can be correlated with the HTTP/Service/Repository/Database trace::

    {
      "type": "message",
      "event": "product.created",
      "data": {...},
      "request_id": "...",     # optional, from DiagnosticsStore
      "trace_id": "...",       # optional, from DiagnosticsStore
      "channel": "/products"
    }

Validation follows the same rule as the rest of the framework: a malformed or
untrusted payload is rejected with a :class:`~betrayer.core.exceptions.BetrayerError`
subclass (``RealtimeError``) that carries a machine readable ``code`` and
``context``; it never invents a second error system.

The message layer has no dependency on any transport (flask, flask_sock, ...),
so it can be unit tested without a running server.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, Optional

from betrayer.core.exceptions import BetrayerError
from betrayer.diagnostics.store import generate_request_id, generate_trace_id

__all__ = [
    "MESSAGE_TYPE_MESSAGE",
    "MESSAGE_TYPE_EVENT",
    "MESSAGE_TYPE_ERROR",
    "MESSAGE_TYPE_CONNECT",
    "MESSAGE_TYPE_DISCONNECT",
    "RealtimeError",
    "MessageValidationError",
    "Message",
]

#: Canonical ``type`` values.
MESSAGE_TYPE_MESSAGE = "message"
MESSAGE_TYPE_EVENT = "event"
MESSAGE_TYPE_ERROR = "error"
MESSAGE_TYPE_CONNECT = "connect"
MESSAGE_TYPE_DISCONNECT = "disconnect"

_VALID_TYPES = frozenset(
    {
        MESSAGE_TYPE_MESSAGE,
        MESSAGE_TYPE_EVENT,
        MESSAGE_TYPE_ERROR,
        MESSAGE_TYPE_CONNECT,
        MESSAGE_TYPE_DISCONNECT,
    }
)

_VALID_EVENT = "event"
_VALID_TYPE = "type"
_VALID_DATA = "data"
_VALID_REQUEST_ID = "request_id"
_VALID_TRACE_ID = "trace_id"
_VALID_CHANNEL = "channel"


class RealtimeError(BetrayerError):
    """Base class for every realtime layer error.

    Reuses the single Betrayer error contract (``code`` / ``component`` /
    ``context`` / ``cause``); the realtime layer never raises a plain
    exception that would bypass the framework error envelope.
    """

    code = "REALTIME_ERROR"
    component = "realtime"


class MessageValidationError(RealtimeError):
    """The raw payload could not be turned into a :class:`Message`."""

    code = "MESSAGE_VALIDATION_FAILED"
    component = "realtime"


class Message:
    """One realtime message.

    Construction is explicit and predictable::

        Message(event="product.created", data={...}, channel="/products")

    ``request_id`` / ``trace_id`` are optional and, when omitted, are taken
    from the active diagnostics thread-local or freshly generated so every
    message stays traceable.
    """

    def __init__(
        self,
        *,
        event: str,
        data: Any = None,
        channel: Optional[str] = None,
        message_type: str = MESSAGE_TYPE_MESSAGE,
        request_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        message_id: Optional[str] = None,
    ) -> None:
        if not isinstance(event, str) or not event:
            raise MessageValidationError(
                message="message event must be a non-empty string",
                code="MESSAGE_EVENT_INVALID",
                context={"event": str(event)},
            )
        if message_type not in _VALID_TYPES:
            raise MessageValidationError(
                message=f"invalid message type: {message_type!r}",
                code="MESSAGE_TYPE_INVALID",
                context={"type": message_type},
            )
        self.event = event
        self.data = data
        self.channel = channel
        self.type = message_type
        # Trace context: explicit wins; otherwise keep the current context so
        # a message inherits the incoming request/trace IDs when available.
        self.request_id = request_id or generate_request_id()
        self.trace_id = trace_id or generate_trace_id()
        self.message_id = message_id or uuid.uuid4().hex[:16]
        self.timestamp = time.time()

    # -- serialization --------------------------------------------------

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "Message":
        """Build a :class:`Message` from a raw dict, validating the shape.

        Raises :class:`MessageValidationError` on missing/invalid fields.
        """
        if not isinstance(payload, dict):
            raise MessageValidationError(
                message="message payload must be a mapping",
                code="MESSAGE_PAYLOAD_INVALID",
                context={"got": type(payload).__name__},
            )

        event = payload.get(_VALID_EVENT)
        if not isinstance(event, str) or not event:
            raise MessageValidationError(
                message="message must contain a non-empty 'event'",
                code="MESSAGE_EVENT_MISSING",
                context={"keys": sorted(payload.keys())},
            )

        message_type = payload.get(_VALID_TYPE, MESSAGE_TYPE_MESSAGE)
        if message_type not in _VALID_TYPES:
            raise MessageValidationError(
                message=f"invalid message type: {message_type!r}",
                code="MESSAGE_TYPE_INVALID",
                context={"type": message_type},
            )

        return cls(
            event=event,
            data=payload.get(_VALID_DATA),
            channel=payload.get(_VALID_CHANNEL),
            message_type=message_type,
            request_id=payload.get(_VALID_REQUEST_ID),
            trace_id=payload.get(_VALID_TRACE_ID),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Machine readable payload (always JSON-serialisable)."""
        return {
            "type": self.type,
            "event": self.event,
            "data": self.data,
            "request_id": self.request_id,
            "trace_id": self.trace_id,
            "channel": self.channel,
            "message_id": self.message_id,
        }

    def to_json(self) -> str:
        """Compact JSON body for transport (flask_sock / SSE wire)."""
        import json as _json

        return _json.dumps(self.to_dict(), default=str, ensure_ascii=False)

    @classmethod
    def error_message(
        cls,
        *,
        code: str,
        message: str,
        channel: Optional[str] = None,
        request_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        context: Optional[dict] = None,
    ) -> "Message":
        """Build a transport-level error message (no Service error is leaked raw).

        Uses the existing error envelope shape so a WebSocket client reads the
        same contract as an HTTP client::

            {"type": "error", "event": "error",
             "data": {"code": ..., "message": ..., "context": ...}}
        """
        return cls(
            event="error",
            data={"code": code, "message": message, "context": dict(context or {})},
            channel=channel,
            message_type=MESSAGE_TYPE_ERROR,
            request_id=request_id,
            trace_id=trace_id,
        )

    def describe(self) -> dict:
        """Introspection view (same key set as :meth:`to_dict`)."""
        return self.to_dict()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<Message type={self.type!r} event={self.event!r} "
            f"channel={self.channel!r}>"
        )
