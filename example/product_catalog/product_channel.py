"""Realtime (WebSocket) integration for the Product Catalog example.

This file is the *only* place the catalog wires realtime, and it proves the
Task 15 principle of **no duplicated business logic**::

    HTTP Resource ──────┐
                        ├──> ProductService ──> Repository ──> Database
    WS Channel ─────────┘
    ProductService ──emit──> EventBus ──> RealtimeManager ──> Channel.broadcast

* The WebSocket inbound handler calls the *same* ``ProductService`` that the
  REST resource uses — no second implementation of product creation.
* Product creation emits the existing application event ``product.created``;
  the :class:`~betrayer.web.realtime_manager.RealtimeManager` (registered as an
  EventBus listener) fans it out to everyone on the ``/products`` channel.
"""

from __future__ import annotations

from typing import Any

from betrayer.web import (
    FlaskRealtimeAdapter,
    Message,
    RealtimeManager,
)

from example.product_catalog.module import SERVICE_KEY
from example.product_catalog.service import ProductService

__all__ = [
    "PRODUCT_CHANNEL",
    "PRODUCT_CREATED_EVENT",
    "build_realtime",
    "make_on_message",
    "build_websocket_app",
]

#: Realtime channel name for catalog updates.
PRODUCT_CHANNEL = "/products"

#: Application event emitted whenever a product is created.
PRODUCT_CREATED_EVENT = "product.created"


def build_realtime(application: Any) -> RealtimeManager:
    """Attach a :class:`RealtimeManager` to the application and wire events.

    Creates the ``/products`` channel and routes the ``product.created`` event
    to it.  Returns the manager so it can be handed to a WebSocket adapter.
    """
    manager = RealtimeManager(application=application)
    manager.channel(PRODUCT_CHANNEL)
    manager.on_event(PRODUCT_CREATED_EVENT, PRODUCT_CHANNEL)
    application.events.on(PRODUCT_CREATED_EVENT, manager.handle_event)
    return manager


def _to_payload(product: Any) -> Any:
    """Best-effort dict serialisation of a product (ORM model or dict)."""
    if callable(getattr(product, "to_dict", None)):
        return product.to_dict()
    return product


def make_on_message(application: Any, service: ProductService):
    """Return the WebSocket inbound handler that reuses the existing Service.

    A ``product.create`` message is handled exactly like ``POST /products``:
    it delegates to ``ProductService.create`` and then emits ``product.created``
    so the realtime manager broadcasts the result.
    """
    events = application.events

    def on_message(connection: Any, message: Message) -> None:
        if message.event != "product.create":
            return
        product = service.create(**(message.data or {}))
        events.emit(PRODUCT_CREATED_EVENT, _to_payload(product))

    return on_message


def build_websocket_app(application: Any, manager: RealtimeManager, service: ProductService) -> Any:
    """Return the same Flask app with a WebSocket blueprint mounted on it.

    ``application`` is the :class:`~betrayer.web.adapter.FlaskAdapter` already
    serving the REST API; the WebSocket routes are added to the *same* Flask
    app, so there is a single HTTP/WS server.

    The inbound message handler still needs the BetrayerApplication (for the
    EventBus), reachable via the manager's stored application reference.
    """
    betrayer_app = manager._application or application
    adapter = FlaskRealtimeAdapter(
        application,
        manager,
        on_message=make_on_message(betrayer_app, service),
    )
    return adapter.build()
