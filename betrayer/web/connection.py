"""Realtime connection abstraction.

A :class:`Connection` is one client socket/session attached to a channel.  The
base class is **transport agnostic**: it tracks lifecycle state and buffers
outbound messages in memory, which is exactly what the manager, the channel and
the unit tests need (no network required).

A real transport (for example the ``flask_sock`` backed connection in
:mod:`betrayer.web.adapter`) overrides :meth:`Connection._deliver` to push the
message onto the wire instead of buffering it; the rest of the lifecycle stays
the same.  This keeps the connection contract small and predictable::

    conn = Connection(channel="/chat")
    conn.mark_open()            # CONNECT -> READY
    conn.send(Message(...))     # MESSAGE
    conn.close()                # DISCONNECT
"""

from __future__ import annotations

import time
import uuid
from typing import Any, List, Optional

from betrayer.web.message import Message

__all__ = [
    "CONNECTION_STATE_CONNECTING",
    "CONNECTION_STATE_OPEN",
    "CONNECTION_STATE_CLOSED",
    "Connection",
]

CONNECTION_STATE_CONNECTING = "connecting"
CONNECTION_STATE_OPEN = "open"
CONNECTION_STATE_CLOSED = "closed"


class Connection:
    """A single realtime connection to a channel.

    The base implementation keeps an in-memory receive buffer so the realtime
    manager/channel work without a live socket.  A transport adapter overrides
    :meth:`_deliver` to actually send bytes; everything else (state, ids,
    metadata, close handling) is shared.
    """

    def __init__(
        self,
        connection_id: Optional[str] = None,
        *,
        channel: Optional[Any] = None,
        metadata: Optional[dict] = None,
    ) -> None:
        self.id: str = connection_id or uuid.uuid4().hex[:12]
        # ``channel`` may be the channel name (str) or the Channel object.
        self.channel = channel
        self.metadata: dict = dict(metadata or {})
        self.state: str = CONNECTION_STATE_CONNECTING
        self.connected_at: Optional[float] = None
        self.closed_at: Optional[float] = None
        # Outbound buffer (used by the default in-process transport).
        self._buffer: List[Message] = []

    # -- lifecycle ------------------------------------------------------

    def mark_open(self) -> "Connection":
        """Move CONNECTING -> OPEN (READY). Idempotent once open."""
        if self.state == CONNECTION_STATE_CLOSED:
            return self
        self.state = CONNECTION_STATE_OPEN
        self.connected_at = time.time()
        return self

    def is_open(self) -> bool:
        return self.state == CONNECTION_STATE_OPEN

    def close(self) -> None:
        """Move to CLOSED (DISCONNECT). Safe to call more than once."""
        if self.state == CONNECTION_STATE_CLOSED:
            return
        self.state = CONNECTION_STATE_CLOSED
        self.closed_at = time.time()
        self._on_close()

    def _on_close(self) -> None:
        """Hook for transports to release the underlying socket. No-op here."""

    # -- transport ------------------------------------------------------

    def send(self, message: Any) -> None:
        """Queue a message for this connection.

        Accepts a :class:`~betrayer.web.message.Message` or a raw dict and
        normalises it before delivery.  Closed connections silently drop the
        message (the channel is responsible for not sending to them).
        """
        if self.state == CONNECTION_STATE_CLOSED:
            return
        msg = message if isinstance(message, Message) else Message.from_dict(message)
        self._deliver(msg)

    def _deliver(self, message: Message) -> None:
        """Deliver ``message``.  Default transport buffers it in memory."""
        self._buffer.append(message)

    def received(self) -> List[Message]:
        """Return the buffered (outbound) messages for inspection/tests."""
        return list(self._buffer)

    # -- introspection --------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "channel": self.channel if isinstance(self.channel, str) else None,
            "state": self.state,
            "connected_at": self.connected_at,
            "closed_at": self.closed_at,
            "metadata": dict(self.metadata),
            "buffered": len(self._buffer),
        }

    def describe(self) -> dict:
        return self.to_dict()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Connection id={self.id!r} channel={self.channel!r} state={self.state!r}>"
