"""Channel abstraction: a named realtime room.

A channel is a logical endpoint (``/chat``, ``/products``, ``/notifications``).
It owns a set of :class:`~betrayer.web.connection.Connection` objects and the
broadcast/isolation logic.  It has **no** business logic: it only moves
messages to connections and records transport-level diagnostics.

Lifecycle (mirrors the application lifecycle, never replaces it)::

    CONNECT -> READY -> (MESSAGE ...)* -> DISCONNECT

Business events arrive as :class:`~betrayer.web.message.Message` objects built
by the Service/Event layer; the channel never decides what an event means.

The channel defers diagnostics to the application's
:class:`~betrayer.diagnostics.store.DiagnosticsStore` when one is supplied, so
traces stay in the single existing store (no duplicate tracing system).
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Optional

from betrayer.web.connection import Connection
from betrayer.web.message import Message

__all__ = [
    "CHANNEL_STATE_CONNECT",
    "CHANNEL_STATE_READY",
    "CHANNEL_STATE_DISCONNECT",
    "Channel",
]

#: Channel lifecycle states (mirror the application lifecycle, never replace it).
CHANNEL_STATE_CONNECT = "connect"
CHANNEL_STATE_READY = "ready"
CHANNEL_STATE_DISCONNECT = "disconnect"


class Channel:
    """A named realtime channel grouping connections.

    Public API (the whole surface an application developer needs)::

        channel.connect(conn_id, metadata=...) -> Connection
        channel.disconnect(conn_id)
        channel.send(conn_id, message)
        channel.broadcast(message)
        channel.broadcast_except(conn_id, message)
        channel.connections() -> [Connection]
        channel.connection_count() -> int
    """

    def __init__(
        self,
        name: str,
        *,
        diagnostics: Any = None,
        connection_factory: Any = None,
    ) -> None:
        if not isinstance(name, str) or not name:
            raise ValueError("channel name must be a non-empty string")
        self.name = name
        self._connections: Dict[str, Connection] = {}
        # Optional DiagnosticsStore (DiagnosticsStore from betrayer.diagnostics).
        self._diagnostics = diagnostics
        # Factory lets tests/transports inject custom Connection subclasses.
        self._connection_factory = connection_factory or Connection
        self.state = "connect"
        self.ready_at: Optional[float] = None
        self.message_count: int = 0

    # -- lifecycle ------------------------------------------------------

    def ready(self) -> "Channel":
        """Mark the channel READY (CONNECT -> READY). Idempotent."""
        if self.state != "disconnect":
            self.state = "ready"
            self.ready_at = time.time()
        return self

    def _ensure_ready(self) -> None:
        if self.state == "connect":
            self.ready()

    # -- connection management ------------------------------------------

    def connect(
        self,
        connection_id: Optional[str] = None,
        *,
        metadata: Optional[dict] = None,
    ) -> Connection:
        """Open a new connection on this channel and return it (CONNECT)."""
        self._ensure_ready()
        conn = self._connection_factory(
            connection_id=connection_id,
            channel=self.name,
            metadata=metadata,
        )
        conn.mark_open()
        self._connections[conn.id] = conn
        self._record("connection.open", {"connection": conn.id})
        return conn

    def disconnect(self, connection_id: str) -> bool:
        """Close a connection (DISCONNECT). Returns True when found."""
        conn = self._connections.get(connection_id)
        if conn is None:
            return False
        conn.close()
        self._connections.pop(connection_id, None)
        self._record("connection.close", {"connection": connection_id})
        if not self._connections:
            self.state = "disconnect"
        return True

    def get_connection(self, connection_id: str) -> Optional[Connection]:
        return self._connections.get(connection_id)

    def connections(self) -> List[Connection]:
        """All live connections (snapshot, connection order stable)."""
        return list(self._connections.values())

    def connection_ids(self) -> List[str]:
        return list(self._connections.keys())

    def connection_count(self) -> int:
        return len(self._connections)

    # -- messaging ------------------------------------------------------

    def send(self, connection_id: str, message: Any) -> None:
        """Send ``message`` to a single connection (no-op if it is gone)."""
        conn = self._connections.get(connection_id)
        if conn is None or not conn.is_open():
            return
        self._deliver(conn, message)

    def broadcast(self, message: Any) -> int:
        """Send ``message`` to *every* connection on the channel.

        Returns the number of connections that received it.
        """
        msg = self._as_message(message)
        count = 0
        for conn in list(self._connections.values()):
            if conn.is_open():
                self._deliver(conn, msg)
                count += 1
        return count

    def broadcast_except(self, connection_id: str, message: Any) -> int:
        """Broadcast to every connection *except* ``connection_id``.

        Useful for echo-suppression (a client's own action should not bounce
        back to it).  Returns the number of connections that received it.
        """
        msg = self._as_message(message)
        count = 0
        for conn in list(self._connections.values()):
            if conn.id == connection_id or not conn.is_open():
                continue
            self._deliver(conn, msg)
            count += 1
        return count

    # -- internals ------------------------------------------------------

    def _as_message(self, message: Any) -> Message:
        if isinstance(message, Message):
            return message
        return Message.from_dict(message)

    def _deliver(self, conn: Connection, message: Any) -> None:
        msg = self._as_message(message)
        conn.send(msg)
        self.message_count += 1
        self._record(
            "message.send",
            {
                "connection": conn.id,
                "event": msg.event,
                "type": msg.type,
            },
        )

    def _record(self, event: str, context: dict) -> None:
        if self._diagnostics is not None:
            try:
                self._diagnostics.record(
                    code="REALTIME_TRACE",
                    component="realtime",
                    level="info",
                    message=event,
                    context={"channel": self.name, **context},
                )
            except Exception:  # noqa: BLE001 - diagnostics must never break a send
                pass

    # -- introspection --------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "state": self.state,
            "connections": self.connection_count(),
            "message_count": self.message_count,
            "connection_ids": self.connection_ids(),
        }

    def describe(self) -> dict:
        return self.to_dict()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<Channel name={self.name!r} state={self.state!r} "
            f"connections={self.connection_count()}>"
        )
