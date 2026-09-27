# Realtime (WebSocket) Contract

**Version:** 1.0
**Applies to:** Betrayer `>= 0.1.0`

---

## 1. Overview

Betrayer provides a canonical, LLM-friendly realtime (WebSocket) layer. It is
**transport-aware but business-logic agnostic**: a WebSocket channel calls the
*same* Service that the HTTP resource calls. There is **no duplicate business
logic** and **no second event/tracing system**.

```text
HTTP Resource ──────┐
                    ├──> Service ──> Repository ──> Database
WebSocket Channel ──┘
        │
        │ (Service emits an event)
        ▼
EventBus ──> RealtimeManager.handle_event ──> Channel.broadcast
```

The layer lives in `betrayer.web.realtime` and reuses existing primitives:

* `core.events.EventBus` — event fan-out (no second event system).
* `diagnostics.DiagnosticsStore` — request/trace IDs and trace recording.
* `core.exceptions.BetrayerError` — the single error contract.
* `web.FlaskAdapter` — the existing HTTP engine (WebSocket mounts on the same Flask app).

---

## 2. Canonical building blocks

```python
from betrayer.web import (
    Message,          # one realtime message (machine readable)
    Connection,       # one client session (transport agnostic)
    Channel,          # a named realtime room ("/chat", "/products")
    RealtimeManager,  # channel/connection registry + EventBus integration
    FlaskRealtimeAdapter,  # flask_sock transport edge (optional)
)
```

---

## 3. Message contract

One shape, always JSON-serialisable. Reuses the diagnostics `request_id` /
`trace_id` so a message joins the HTTP/Service/Repository/Database trace.

```json
{
  "type": "message",
  "event": "product.created",
  "data": {},
  "request_id": "ab12cd34ef56",
  "trace_id": "ab12cd34ef56ab12",
  "channel": "/products",
  "message_id": "ab12cd34ef56ab12"
}
```

Build and serialise:

```python
from betrayer.web import Message

msg = Message(event="product.created", data={"id": 1}, channel="/products")
payload = msg.to_dict()          # dict
wire    = msg.to_json()          # compact JSON string
same    = Message.from_dict(payload)   # parse/validate
```

`type` is one of `message`, `event`, `error`, `connect`, `disconnect`.
Malformed payloads raise `MessageValidationError` (a `BetrayerError` subclass).

---

## 4. Channel

A channel is a named realtime room. It owns connections and the broadcast logic.

```python
ch = manager.channel("/products")     # create-on-demand, canonical (same object)
conn = ch.connect()                   # a client opens a connection (CONNECT -> READY)
ch.send(conn.id, Message(event="ping", data={}))
ch.broadcast(Message(event="tick", data={}))          # every connection
ch.broadcast_except(conn.id, Message(event="tick", data={}))  # all but one
ch.disconnect(conn.id)                # (DISCONNECT)
ch.connection_count()                 # -> int
ch.connections()                      # -> [Connection]
```

Lifecycle mirrors the application lifecycle (never replaces it):

```text
CONNECT -> READY -> MESSAGE ... -> DISCONNECT
```

A `Connection` tracks its own state (`connecting` / `open` / `closed`). Closed
connections silently drop outbound messages.

---

## 5. RealtimeManager

The single entry point for the realtime layer.

```python
from betrayer.web import RealtimeManager

manager = RealtimeManager(application=app)   # uses app.diagnostics automatically
manager.channel("/products")                 # get/create a channel
conn = manager.connect("/products")          # connect a client
manager.broadcast("/products", message)     # broadcast
manager.connection_count("/products")         # -> int  (or overall when omitted)
manager.remove_channel("/products")
```

### Event integration (Task 14)

```python
manager.on_event("product.created", "/products")
app.events.on("product.created", manager.handle_event)
```

Now every `app.events.emit("product.created", payload)` is broadcast to every
connection on `/products`. No queue, no broker — synchronous, in-process.

---

## 6. Service reuse (the key rule)

The WebSocket inbound handler **calls the same Service** the HTTP resource uses.
There is no `ChatHttpService` / `ChatWebSocketService` split.

```python
# example/product_catalog/product_channel.py
def make_on_message(application, service):
    events = application.events
    def on_message(connection, message):
        if message.event == "product.create":
            product = service.create(**(message.data or {}))  # SAME service
            events.emit("product.created", product.to_dict())  # -> realtime
    return on_message
```

Flow proved by the example:

```text
POST /products ──────> ProductResource ──┐
                                        ├──> ProductService.create ──> Repository
WS   /products ──────> product_channel ──┘
ProductService ──emit──> EventBus ──> RealtimeManager ──> Channel.broadcast
```

---

## 7. WebSocket transport (optional)

`FlaskRealtimeAdapter` mounts channels onto the *same* Flask app via
`flask_sock` (a lightweight, mature layer over Flask/Werkzeug). It is the only
place that speaks the WebSocket transport; the framework never implements a
WebSocket protocol itself.

```python
from betrayer.web import FlaskRealtimeAdapter, build_realtime_app

adapter = FlaskRealtimeAdapter(
    flask_adapter,                 # the FlaskAdapter already serving REST
    manager,
    on_message=make_on_message(app, service),
)
flask_app = adapter.build()        # REST + WS on the same app, /ws/<channel>
```

When `flask_sock` is absent, `FlaskRealtimeAdapter.available()` is `False` and
`build()` raises `SockUnavailableError` (with a `pip install flask-sock` hint).
The in-process `Channel` / `Connection` parts of the layer work without it.

---

## 8. Error handling

Realtime errors reuse the single Betrayer error contract — there is **no second
error shape**. Business errors stay inside the Service; the channel only reports
transport/presentation problems.

```python
from betrayer.web import (
    RealtimeError,          # base -> code "REALTIME_ERROR"
    ChannelError,           # code "CHANNEL_ERROR"
    ChannelNotFoundError,   # code "CHANNEL_NOT_FOUND"
    ConnectionError,        # code "CONNECTION_ERROR"
    ConnectionNotFoundError,# code "CONNECTION_NOT_FOUND"
    MessageValidationError, # code "MESSAGE_VALIDATION_FAILED"
)
```

Transport-level error messages follow the same envelope as the HTTP API:

```json
{
  "type": "error",
  "event": "error",
  "data": {
    "code": "CHANNEL_ERROR",
    "message": "...",
    "context": {}
  }
}
```

Build one with `Message.error_message(code=..., message=..., context=...)`.

---

## 9. Diagnostics integration

The manager forwards activity to the existing
`DiagnosticsStore` (reached from `application.diagnostics`). Each `send` / `connect`
/ `disconnect` / `channel.create` records a `REALTIME_TRACE` entry, and every
`Message` carries the request/trace IDs from the diagnostics module, so a
WebSocket trace joins the HTTP trace end-to-end:

```text
WebSocket -> Channel -> Service -> Repository -> Database
```

No new tracing system is created.

---

## 10. CLI

```bash
bet realtime           # introspect the realtime layer (text)
bet realtime --json    # machine readable
```

Output:

```json
{
  "success": true,
  "channels": [],
  "connections": 0
}
```

No other command is added — the realtime layer is exercised through the existing
`bet test` and `bet validate` commands.

---

## 11. Example

`example/product_catalog/product_channel.py` shows the minimal, realtime pattern:

```python
app = build_application()
manager = build_realtime(app)                 # channel + event route
service = app.container.resolve("products_service")
flask_app = create_realtime_app(app)          # REST + /ws/products
```

Run it with `python example/product_catalog/run.py --realtime`. Creating a
product (over HTTP **or** WebSocket) emits `product.created`, which the manager
broadcasts to every connected client.

---

## 12. LLM quick path

To add a realtime feature, an agent only needs to know four things:

1. **Channel** — `manager.channel("/name")` (or `RealtimeManager(application=app)`).
2. **Service** — reuse the existing Service; call it from the WS `on_message`.
3. **Message** — `Message(event=..., data=..., channel=...)`.
4. **Route event → channel** — `manager.on_event("x.created", "/name")` +
   `app.events.on("x.created", manager.handle_event)`.

No need to read the transport implementation to build a simple channel.

---

## 13. Limitations (current task)

- Single process, in-memory connection registry (no Redis/pubsub backend).
- No distributed WebSocket / horizontal scaling / cluster coordination.
- No presence system beyond per-channel connection lists.
- No authentication layer (reuse the application's existing auth on the HTTP side).
- No custom WebSocket protocol — relies on `flask_sock` / Werkzeug.
- Asynchronous jobs are **not** required for fan-out; events are synchronous.
