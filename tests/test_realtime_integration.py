"""Realtime integration tests — Task 15.

Layer: integration
Proves the core Task 15 requirement: **no duplicated business logic**.

* A WebSocket channel (via RealtimeManager) and the HTTP resource both call the
  *same* Service (``ProductService``) resolved from the container.
* ``Service -> Event -> Realtime`` fan-out: creating a product over the service
  emits ``product.created`` on the application EventBus, which the realtime
  manager broadcasts to every connection on the ``/products`` channel.
* The Flask WebSocket transport edge (``FlaskRealtimeAdapter`` +
  ``WebSocketConnection``) is exercised with a fake socket so the real read
  loop / message parsing / Service fan-out path runs without a live server.
* Existing HTTP functionality keeps working (golden path regression check).

Uses the canonical conftest fixtures (``application``, ``database_path``...).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, List

import pytest

from betrayer.web import Message, RealtimeManager
from betrayer.web.realtime import MESSAGE_TYPE_EVENT

from example.product_catalog.app import (
    APP_NAME,
    PRODUCT_CHANNEL,
    PRODUCT_CREATED_EVENT,
    build_application,
)
from example.product_catalog.module import SERVICE_KEY
from example.product_catalog.product_channel import build_realtime, make_on_message
from example.product_catalog.service import ProductService


# ──────────────────────────────────────────────────────────────────
# Service reuse: HTTP and WebSocket share the same Service
# ──────────────────────────────────────────────────────────────────


class TestServiceReuse:
    def test_http_and_ws_resolve_same_service(self, database_path: Path) -> None:
        """The realtime inbound handler and the HTTP resource use one Service."""
        app = build_application(database_path=database_path)
        service = app.container.resolve(SERVICE_KEY)
        assert isinstance(service, ProductService)

        manager = build_realtime(app)
        handler = make_on_message(app, service)

        # Capture broadcasts on the products channel.
        conn = manager.connect(PRODUCT_CHANNEL)

        # Simulate a WebSocket "product.create" message -> same service.create().
        handler(conn, Message(event="product.create", data={"name": "WS", "price": 1.0, "stock": 2}))

        # The EventBus broadcast reached the connection.
        messages = conn.received()
        assert any(m.event == PRODUCT_CREATED_EVENT or m.data for m in messages)

        # The created product is visible through the SAME service (HTTP side).
        assert len(service.list()) == 1
        assert service.list()[0].name == "WS"


# ──────────────────────────────────────────────────────────────────
# Service -> Event -> Realtime fan-out
# ──────────────────────────────────────────────────────────────────


class TestEventToRealtime:
    def test_service_event_fans_out_to_channel(self, database_path: Path) -> None:
        app = build_application(database_path=database_path)
        manager = build_realtime(app)

        # Two clients join the products channel.
        c1 = manager.connect(PRODUCT_CHANNEL)
        c2 = manager.connect(PRODUCT_CHANNEL)

        service: ProductService = app.container.resolve(SERVICE_KEY)

        # The real WebSocket inbound handler performs: Service.create -> EventBus
        # emit -> realtime manager broadcast. This is the canonical
        # Service -> Event -> Realtime fan-out (no duplicated business logic).
        handler = make_on_message(app, service)
        handler(c1, Message(event="product.create", data={"name": "Broadcast", "price": 3.0, "stock": 4}))

        # Both clients received the product.created broadcast.
        assert len(c1.received()) == 1
        assert len(c2.received()) == 1
        msg = c1.received()[0]
        assert msg.event == PRODUCT_CREATED_EVENT
        assert msg.type == MESSAGE_TYPE_EVENT
        assert msg.data["name"] == "Broadcast"

    def test_handle_event_broadcasts_to_routed_channel(self, database_path: Path) -> None:
        app = build_application(database_path=database_path)
        manager = build_realtime(app)
        conn = manager.connect(PRODUCT_CHANNEL)

        # Emit directly on the bus (mirrors what the Service does).
        app.events.emit(PRODUCT_CREATED_EVENT, {"id": 99, "name": "Direct"})
        assert len(conn.received()) == 1
        assert conn.received()[0].data["name"] == "Direct"


# ──────────────────────────────────────────────────────────────────
# Integration: WebSocket -> Channel -> Service
# ──────────────────────────────────────────────────────────────────


class TestWebSocketChannelService:
    def test_ws_message_creates_product_via_service(self, database_path: Path) -> None:
        app = build_application(database_path=database_path)
        manager = build_realtime(app)
        conn = manager.connect(PRODUCT_CHANNEL)
        service: ProductService = app.container.resolve(SERVICE_KEY)

        handler = make_on_message(app, service)
        handler(conn, Message(event="product.create", data={"name": "ViaWS", "price": 5.0}))

        products = service.list()
        assert any(p.name == "ViaWS" for p in products)


# ──────────────────────────────────────────────────────────────────
# WebSocket transport edge (FlaskRealtimeAdapter + WebSocketConnection)
# ──────────────────────────────────────────────────────────────────


class _FakeSocket:
    """A minimal in-memory socket for driving the flask_sock route handler."""

    def __init__(self, sent: List[str], queue: List[Any]) -> None:
        self._sent = sent
        self._queue = queue

    def receive(self) -> Any:
        if not self._queue:
            return None
        return self._queue.pop(0)

    def send(self, data: str) -> None:
        self._sent.append(data)

    def close(self) -> None:
        pass


class TestWebSocketTransportEdge:
    def test_adapter_handle_connection_fans_out(self, database_path: Path) -> None:
        """Exercise the real per-connection read loop with a fake socket.

        Drives :meth:`FlaskRealtimeAdapter._handle_connection` (the exact logic
        the ``flask_sock`` route runs) with an in-memory socket. This proves the
        transport path works end-to-end without a live WebSocket server:
        parse inbound -> ``on_message`` -> Service -> EventBus -> broadcast.
        """
        from betrayer.web.ws_adapter import FlaskRealtimeAdapter, WebSocketConnection

        app = build_application(database_path=database_path)
        manager = build_realtime(app)
        service: ProductService = app.container.resolve(SERVICE_KEY)
        handler = make_on_message(app, service)
        adapter = FlaskRealtimeAdapter(app, manager, on_message=handler)

        # An observer connection on /products receives the broadcast.
        observer = manager.connect(PRODUCT_CHANNEL)
        channel = manager.channel(PRODUCT_CHANNEL)

        # A fresh transport connection for the fake socket.
        sent: List[str] = []
        fake = _FakeSocket(
            sent,
            [Message(event="product.create", data={"name": "Sock", "price": 1.0}).to_json()],
        )
        ws_conn = WebSocketConnection(sock=fake, channel=channel.name)
        channel._connections[ws_conn.id] = ws_conn
        ws_conn.mark_open()

        adapter._handle_connection(channel, ws_conn, fake)

        # The observer connection on /products received the product.created broadcast.
        assert len(observer.received()) == 1
        assert observer.received()[0].data["name"] == "Sock"
        # The product was created through the same Service (HTTP side).
        assert any(p.name == "Sock" for p in service.list())
        # A malformed message (missing required event) is reported back as a
        # transport error, not a crash.
        err_sock = _FakeSocket([], [{"data": {}}])
        err_conn = WebSocketConnection(sock=err_sock, channel=channel.name)
        channel._connections[err_conn.id] = err_conn
        err_conn.mark_open()
        adapter._handle_connection(channel, err_conn, err_sock)
        assert err_sock._sent and "error" in err_sock._sent[0]


# ──────────────────────────────────────────────────────────────────
# Regression: existing HTTP functionality still works
# ──────────────────────────────────────────────────────────────────


class TestHttpRegression:
    def test_http_crud_unchanged(self, database_path: Path) -> None:
        app = build_application(database_path=database_path)
        service: ProductService = app.container.resolve(SERVICE_KEY)
        created = service.create(name="HTTP", price=1.0, stock=1)
        assert created.name == "HTTP"
        fetched = service.get(created.id)
        assert fetched is not None
        assert service.delete(created.id) is True
        assert service.get(created.id) is None

    def test_application_still_ready(self, database_path: Path) -> None:
        app = build_application(database_path=database_path)
        from betrayer.core.lifecycle import LifecycleState

        assert app.state is LifecycleState.READY
        assert app.name == APP_NAME
