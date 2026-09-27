"""Betrayer realtime (WebSocket) layer.

The realtime layer is deliberately small and reuses the framework's existing
primitives:

* **Channel**         - a named realtime room (``/chat``, ``/products``...)
* **Connection**      - one client session, transport agnostic
* **Message**         - one machine-readable message (reuses trace ids)
* **RealtimeManager** - channel/connection registry + EventBus integration
* **FlaskRealtimeAdapter** - the ``flask_sock`` transport edge

It does **not** own business logic.  A WebSocket channel calls the *same*
Service that the HTTP resource calls; the flow is::

    HTTP Resource ──────┐
                        ├──> Service ──> Repository ──> Database
    WebSocket Channel ──┘

or, with events::

    Service ──emit──> EventBus ──> RealtimeManager.handle_event ──> Channel.broadcast

Public API::

    from betrayer.web.realtime import (
        Message, Channel, Connection, RealtimeManager,
        FlaskRealtimeAdapter, RealtimeError,
    )
"""

from __future__ import annotations

from betrayer.web.message import (
    MESSAGE_TYPE_CONNECT,
    MESSAGE_TYPE_DISCONNECT,
    MESSAGE_TYPE_ERROR,
    MESSAGE_TYPE_EVENT,
    MESSAGE_TYPE_MESSAGE,
    Message,
    MessageValidationError,
    RealtimeError,
)
from betrayer.web.connection import (
    CONNECTION_STATE_CLOSED,
    CONNECTION_STATE_CONNECTING,
    CONNECTION_STATE_OPEN,
    Connection,
)
from betrayer.web.channel import (
    CHANNEL_STATE_CONNECT,
    CHANNEL_STATE_DISCONNECT,
    CHANNEL_STATE_READY,
    Channel,
)
from betrayer.web.realtime_manager import RealtimeManager
from betrayer.web.ws_adapter import (
    FlaskRealtimeAdapter,
    SockUnavailableError,
    WebSocketConnection,
    flask_sock_available,
)
from betrayer.web.realtime_exceptions import (
    ChannelError,
    ChannelNotFoundError,
    ConnectionError,
    ConnectionNotFoundError,
    MessageError,
)

__all__ = [
    # message
    "Message",
    "MessageValidationError",
    "RealtimeError",
    "MESSAGE_TYPE_MESSAGE",
    "MESSAGE_TYPE_EVENT",
    "MESSAGE_TYPE_ERROR",
    "MESSAGE_TYPE_CONNECT",
    "MESSAGE_TYPE_DISCONNECT",
    # connection
    "Connection",
    "CONNECTION_STATE_CONNECTING",
    "CONNECTION_STATE_OPEN",
    "CONNECTION_STATE_CLOSED",
    # channel
    "Channel",
    "CHANNEL_STATE_CONNECT",
    "CHANNEL_STATE_READY",
    "CHANNEL_STATE_DISCONNECT",
    # manager
    "RealtimeManager",
    # transport
    "FlaskRealtimeAdapter",
    "WebSocketConnection",
    "SockUnavailableError",
    "flask_sock_available",
    # exceptions
    "ChannelError",
    "ChannelNotFoundError",
    "ConnectionError",
    "ConnectionNotFoundError",
    "MessageError",
]
