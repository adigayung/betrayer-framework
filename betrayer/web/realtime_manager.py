"""Realtime manager: registry + lifecycle for channels and connections.

The manager is the canonical entry point for the realtime layer.  It is
**thin** and business agnostic: it creates channels, tracks connections and
exposes ``connect`` / ``disconnect`` / ``get_channel`` / ``broadcast`` /
``connection_count``.  It does **not** know about Services — those are wired in
by application code (the channel only forwards the messages they produce).

Event integration (Task 14): register ``on_event`` as an EventBus listener and
the manager will broadcast matching events to their channel.  There is no
second event system; it reuses :class:`~betrayer.core.events.EventBus`.

    manager.on_event("product.created", "products")

Now every ``event_bus.emit("product.created", payload)`` fans out to everyone
subscribed to the ``/products`` channel.

Diagnostics reuse: the manager forwards activity to the existing
:class:`~betrayer.diagnostics.store.DiagnosticsStore` when one is provided, so
realtime traces live in the single canonical store.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from betrayer.web.channel import Channel
from betrayer.web.connection import Connection
from betrayer.web.message import Message
from betrayer.web.realtime_exceptions import ChannelNotFoundError

__all__ = ["RealtimeManager"]


class RealtimeManager:
    """Owns every realtime channel for one application.

    Usage::

        manager = RealtimeManager(application=app)        # uses app.diagnostics
        channel = manager.channel("/products")           # create/return
        conn = channel.connect()                          # a client connects
        channel.broadcast(Message(event="product.created", data={...}))

        manager.on_event("product.created", "/products")  # Service->Event->realtime
        app.events.on("product.created", manager.handle_event)
    """

    def __init__(
        self,
        *,
        application: Any = None,
        diagnostics: Any = None,
        connection_factory: Any = None,
    ) -> None:
        self._application = application
        self._channels: Dict[str, Channel] = {}
        # Prefer a diagnostics store that was passed explicitly, otherwise the
        # one owned by the application (set during bootstrap).
        self._diagnostics = diagnostics
        if self._diagnostics is None and application is not None:
            self._diagnostics = getattr(application, "diagnostics", None)
        self._connection_factory = connection_factory or Connection
        # event name -> list of channel names that should receive it.
        self._event_routes: Dict[str, List[str]] = {}

    # -- channel registry ----------------------------------------------

    def channel(self, name: str, *, create: bool = True) -> Channel:
        """Return the channel ``name`` (canonical, predictable).

        With ``create=True`` (default) an unknown name is created; with
        ``create=False`` an unknown name raises :class:`ChannelNotFoundError`.
        """
        existing = self._channels.get(name)
        if existing is not None:
            return existing
        if not create:
            raise ChannelNotFoundError(
                message=f"channel {name!r} is not registered",
                context={"channel": name},
            )
        channel = Channel(
            name,
            diagnostics=self._diagnostics,
            connection_factory=self._connection_factory,
        )
        self._channels[name] = channel
        self._record("channel.create", {"channel": name})
        return channel

    def has_channel(self, name: str) -> bool:
        return name in self._channels

    def channels(self) -> List[Channel]:
        return list(self._channels.values())

    def channel_names(self) -> List[str]:
        return list(self._channels.keys())

    def remove_channel(self, name: str) -> bool:
        channel = self._channels.pop(name, None)
        if channel is None:
            return False
        for conn in channel.connections():
            try:
                channel.disconnect(conn.id)
            except Exception:  # noqa: BLE001 - best effort cleanup
                pass
        self._record("channel.remove", {"channel": name})
        return True

    # -- connection lifecycle (convenience over channel()) -------------

    def connect(
        self,
        channel_name: str,
        connection_id: Optional[str] = None,
        *,
        metadata: Optional[dict] = None,
    ) -> Connection:
        """Open a connection on ``channel_name`` (creates the channel if new)."""
        return self.channel(channel_name).connect(
            connection_id=connection_id, metadata=metadata
        )

    def disconnect(self, channel_name: str, connection_id: str) -> bool:
        """Close a connection; returns True when it existed."""
        channel = self._channels.get(channel_name)
        if channel is None:
            return False
        return channel.disconnect(connection_id)

    def connection_count(self, channel_name: Optional[str] = None) -> int:
        """Total open connections, overall or for one channel."""
        if channel_name is None:
            return sum(ch.connection_count() for ch in self._channels.values())
        channel = self._channels.get(channel_name)
        return channel.connection_count() if channel else 0

    # -- messaging ------------------------------------------------------

    def send(
        self,
        channel_name: str,
        connection_id: str,
        message: Any,
    ) -> None:
        """Send ``message`` to one connection on a channel."""
        self.channel(channel_name, create=False).send(connection_id, message)

    def broadcast(self, channel_name: str, message: Any) -> int:
        """Broadcast ``message`` to every connection on ``channel_name``."""
        return self.channel(channel_name, create=False).broadcast(message)

    def broadcast_except(
        self,
        channel_name: str,
        connection_id: str,
        message: Any,
    ) -> int:
        """Broadcast to every connection on ``channel_name`` except one."""
        return self.channel(channel_name, create=False).broadcast_except(
            connection_id, message
        )

    # -- event integration (Task 14) -----------------------------------

    def on_event(self, event: str, channel_name: str) -> "RealtimeManager":
        """Route an event name to a channel so ``handle_event`` can fan it out.

        Idempotent for the same (event, channel) pair.
        """
        self._event_routes.setdefault(event, [])
        if channel_name not in self._event_routes[event]:
            self._event_routes[event].append(channel_name)
        return self

    def handle_event(self, event: Any) -> None:
        """EventBus listener: broadcast an emitted event to routed channels.

        ``event`` is an :class:`~betrayer.core.events.Event` (or anything with
        ``name`` / ``payload``).  This is the only realtime<-event seam; it
        reuses the existing EventBus and never queues or brokers anything.
        """
        name = getattr(event, "name", None) or event.get("name") if isinstance(event, dict) else getattr(event, "name", None)
        payload = getattr(event, "payload", None)
        if name is None:
            return
        for channel_name in self._event_routes.get(name, ()):
            channel = self._channels.get(channel_name)
            if channel is None:
                continue
            message = Message(
                event=name,
                data=payload,
                channel=channel_name,
                message_type="event",
                request_id=getattr(event, "request_id", None),
                trace_id=getattr(event, "trace_id", None),
            )
            channel.broadcast(message)

    # -- diagnostics ----------------------------------------------------

    def _record(self, event: str, context: dict) -> None:
        if self._diagnostics is not None:
            try:
                self._diagnostics.record(
                    code="REALTIME_TRACE",
                    component="realtime",
                    level="info",
                    message=event,
                    context=context,
                )
            except Exception:  # noqa: BLE001 - diagnostics must never break a send
                pass

    # -- introspection --------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "channels": [ch.to_dict() for ch in self._channels.values()],
            "channel_count": len(self._channels),
            "connections": self.connection_count(),
            "event_routes": {k: list(v) for k, v in self._event_routes.items()},
        }

    def describe(self) -> dict:
        return self.to_dict()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<RealtimeManager channels={len(self._channels)} "
            f"connections={self.connection_count()}>"
        )
