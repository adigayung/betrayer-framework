"""WebSocket / SSE adapter for Flask.

This module is the *only* place that speaks the WebSocket transport.  It uses
``flask_sock`` (a lightweight, mature layer on top of Flask/Werkzeug) so the
framework never implements a WebSocket protocol itself.  When ``flask_sock`` is
not installed the adapter degrades gracefully: ``available()`` is ``False`` and
``build`` raises a single, actionable :class:`SockUnavailableError`.

The adapter is intentionally small.  It:

* mounts one ``Sock`` route that maps a *channel path* (``/ws/<channel>``) to a
  :class:`~betrayer.web.channel.Channel` owned by the
  :class:`~betrayer.web.realtime_manager.RealtimeManager`;
* wraps every connected socket in a :class:`WebSocketConnection` (a real
  transport :class:`~betrayer.web.connection.Connection`);
* hands inbound messages to ``on_message(conn, message)`` — the application
  supplies this hook and is expected to call the *same* Service that the HTTP
  resource uses (no duplicated business logic);
* reuses the diagnostics store for request/trace ids so the WS trace joins the
  HTTP/Service/Repository/Database trace in the single canonical store.

Nothing here changes the existing HTTP architecture: the synchronous REST routes
are still served by :class:`~betrayer.web.adapter.FlaskAdapter`; we only add a
WebSocket blueprint to the *same* Flask app.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Optional

from betrayer.web.connection import Connection
from betrayer.web.message import Message, MessageValidationError
from betrayer.web.realtime_exceptions import RealtimeError

__all__ = [
    "SockUnavailableError",
    "WebSocketConnection",
    "FlaskRealtimeAdapter",
    "flask_sock_available",
]


class SockUnavailableError(RealtimeError):
    """Raised when ``flask_sock`` is needed but not installed."""

    code = "SOCK_UNAVAILABLE"
    component = "realtime"


def flask_sock_available() -> bool:
    """Return ``True`` when ``flask_sock`` can be imported (never raises)."""
    try:  # pragma: no cover - trivial import probe
        import flask_sock  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return True


def _import_sock() -> Any:
    """Return the ``flask_sock`` module or raise :class:`SockUnavailableError`."""
    try:
        import flask_sock
    except Exception as exc:  # noqa: BLE001
        raise SockUnavailableError(
            message="flask_sock is not installed; install it with: pip install flask-sock",
            cause=exc,
        ) from exc
    return flask_sock


class WebSocketConnection(Connection):
    """A real transport connection backed by a ``flask_sock`` socket.

    Overrides :meth:`Connection._deliver` to push bytes onto the wire instead
    of buffering them, keeping the whole :class:`Connection` lifecycle intact.
    """

    def __init__(self, sock: Any, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._sock = sock

    def _deliver(self, message: Message) -> None:
        if self._sock is None:
            return
        try:
            self._sock.send(message.to_json())
        except Exception:  # noqa: BLE001 - never crash the read loop on a write
            pass

    def _on_close(self) -> None:
        try:
            if self._sock is not None:
                self._sock.close()
        except Exception:  # noqa: BLE001
            pass


class FlaskRealtimeAdapter:
    """Mount :class:`RealtimeManager` channels onto a Flask app via ``flask_sock``."""

    def __init__(
        self,
        application: Any,
        manager: Any,
        *,
        url_prefix: str = "/ws",
        sock: Any = None,
        on_message: Optional[Callable[[Connection, Message], None]] = None,
    ) -> None:
        self.application = application
        self.manager = manager
        self.url_prefix = url_prefix.rstrip("/") or "/ws"
        self._sock = sock
        # Application hook: inbound message -> Service. Default is None; the
        # application overrides this to call its existing Service and let the
        # channel broadcast the result (no duplicated business logic).
        self.on_message = on_message
        self._flask_app = None
        self._mounted = False

    # -- public surface -------------------------------------------------

    @property
    def flask_app(self) -> Any:
        if self._flask_app is None:
            self._flask_app = self.build()
        return self._flask_app

    def available(self) -> bool:
        """Whether the WebSocket transport can be used in this environment."""
        return flask_sock_available()

    def build(self) -> Any:
        """Attach a ``flask_sock`` blueprint to the Flask app and return it."""
        flask = _import_flask()
        sock = self._sock or _import_sock().Sock()
        target = (
            self.application.flask_app
            if hasattr(self.application, "flask_app")
            else self.application
        )
        if self._flask_app is None:
            self._flask_app = target

        manager = self.manager
        on_message = self.on_message
        url_prefix = self.url_prefix

        @sock.route(f"{url_prefix}/<channel_name>")
        def _ws_channel(ws: Any, channel_name: str) -> None:  # pragma: no cover - needs live socket
            channel = manager.channel(f"/{channel_name}")
            conn = WebSocketConnection(sock=ws, channel=channel.name)
            channel._connections[conn.id] = conn
            conn.mark_open()
            manager._record("ws.open", {"channel": channel.name, "connection": conn.id})
            try:
                self._handle_connection(channel, conn, ws)
            finally:
                channel.disconnect(conn.id)
                manager._record(
                    "ws.close", {"channel": channel.name, "connection": conn.id}
                )

    def _handle_connection(self, channel: Any, conn: Any, ws: Any) -> None:
        """Run the per-connection read loop for one socket.

        Extracted from the route handler so it is unit-testable without a live
        server: any object exposing ``receive()`` / ``send()`` works as ``ws``.
        """
        manager = self.manager
        on_message = self.on_message
        try:
            while True:
                raw = ws.receive()
                if raw is None:
                    break
                try:
                    message = Message.from_dict(_coerce_json(raw))
                except MessageValidationError as exc:
                    ws.send(
                        Message.error_message(
                            code=exc.code,
                            message=exc.message,
                            channel=channel.name,
                        ).to_json()
                    )
                    continue
                if on_message is not None:
                    on_message(conn, message)
        finally:
            # The route handler performs the disconnect; this guard keeps the
            # method safe to call standalone in tests.
            if conn.is_open():
                channel.disconnect(conn.id)

    def to_dict(self) -> dict:
        return {
            "adapter": "FlaskRealtimeAdapter",
            "url_prefix": self.url_prefix,
            "available": self.available(),
            "mounted": self._mounted,
        }


def _import_flask() -> Any:
    from betrayer.web.flask_bridge import import_flask

    return import_flask()


def _coerce_json(raw: Any) -> Any:
    """Parse a raw socket payload into a message dict (str/JSON/bytes)."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", "replace")
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except Exception:
            return {"event": "message", "data": raw}
    return {"event": "message", "data": raw}
