"""Realtime (WebSocket) unit tests — Task 15.

Layer: unit
Covers the realtime building blocks without a live server:
- Message contract: serialize / deserialize / validate / malformed
- Connection: lifecycle, open/close, send buffering
- Channel: send / receive / broadcast / multiple connections / isolation
- RealtimeManager: connect / disconnect / get_channel / broadcast / count
- Broadcasting: send / broadcast / broadcast_except
- Diagnostics: request_id / trace_id propagation
- Error contract: RealtimeError hierarchy reuses BetrayerError

These run under the canonical ``python -m betrayer test`` runner (pytest).
"""

from __future__ import annotations

from typing import Any, List

import pytest

from betrayer.core.exceptions import BetrayerError
from betrayer.diagnostics.store import DiagnosticsStore
from betrayer.web import (
    Connection,
    CONNECTION_STATE_CONNECTING,
    CONNECTION_STATE_OPEN,
    CONNECTION_STATE_CLOSED,
    Channel,
    CHANNEL_STATE_CONNECT,
    CHANNEL_STATE_READY,
    CHANNEL_STATE_DISCONNECT,
    Message,
    MessageValidationError,
    RealtimeManager,
    RealtimeError,
    ChannelNotFoundError,
    flask_sock_available,
)
from betrayer.web.realtime import MESSAGE_TYPE_EVENT


# ──────────────────────────────────────────────────────────────────
# Message contract
# ──────────────────────────────────────────────────────────────────


class TestMessageContract:
    def test_build_and_serialize(self):
        msg = Message(event="product.created", data={"id": 1}, channel="/products")
        assert msg.event == "product.created"
        assert msg.data == {"id": 1}
        assert msg.channel == "/products"
        assert msg.type == "message"
        assert msg.request_id and msg.trace_id  # auto-generated trace ids

        as_dict = msg.to_dict()
        assert as_dict["event"] == "product.created"
        assert as_dict["type"] == "message"

    def test_round_trip_dict(self):
        payload = {
            "type": "event",
            "event": "product.created",
            "data": {"id": 2},
            "request_id": "req-1",
            "trace_id": "trc-1",
            "channel": "/products",
        }
        msg = Message.from_dict(payload)
        assert msg.type == "event"
        assert msg.request_id == "req-1"
        assert msg.trace_id == "trc-1"
        assert msg.to_dict()["data"] == {"id": 2}

    def test_to_json_is_parseable(self):
        import json

        msg = Message(event="ping", data={"x": 1}, channel="/chat")
        parsed = json.loads(msg.to_json())
        assert parsed["event"] == "ping"
        assert parsed["type"] == "message"

    def test_missing_event_rejected(self):
        with pytest.raises(MessageValidationError):
            Message.from_dict({"data": {}})

    def test_empty_event_rejected(self):
        with pytest.raises(MessageValidationError):
            Message(event="", data={})

    def test_invalid_type_rejected(self):
        with pytest.raises(MessageValidationError):
            Message.from_dict({"event": "x", "type": "weird"})

    def test_non_dict_rejected(self):
        with pytest.raises(MessageValidationError):
            Message.from_dict("not-a-dict")

    def test_error_message_contract(self):
        msg = Message.error_message(
            code="CHANNEL_ERROR",
            message="boom",
            channel="/chat",
            context={"reason": "x"},
        )
        assert msg.type == "error"
        assert msg.data["code"] == "CHANNEL_ERROR"
        assert msg.data["message"] == "boom"
        assert msg.data["context"] == {"reason": "x"}


# ──────────────────────────────────────────────────────────────────
# Connection lifecycle
# ──────────────────────────────────────────────────────────────────


class TestConnectionLifecycle:
    def test_initial_state_connecting(self):
        conn = Connection(channel="/chat")
        assert conn.state == CONNECTION_STATE_CONNECTING
        assert not conn.is_open()

    def test_open_transition(self):
        conn = Connection(channel="/chat")
        conn.mark_open()
        assert conn.state == CONNECTION_STATE_OPEN
        assert conn.is_open()

    def test_close_transition(self):
        conn = Connection(channel="/chat")
        conn.mark_open()
        conn.close()
        assert conn.state == CONNECTION_STATE_CLOSED
        assert not conn.is_open()

    def test_id_is_set(self):
        conn = Connection(connection_id="abc")
        assert conn.id == "abc"

    def test_send_buffers_when_open(self):
        conn = Connection(channel="/chat")
        conn.mark_open()
        conn.send(Message(event="ping", data={}))
        assert len(conn.received()) == 1
        assert conn.received()[0].event == "ping"

    def test_send_ignored_when_closed(self):
        conn = Connection(channel="/chat")
        conn.mark_open()
        conn.close()
        conn.send(Message(event="ping", data={}))
        assert len(conn.received()) == 0

    def test_send_accepts_raw_dict(self):
        conn = Connection(channel="/chat")
        conn.mark_open()
        conn.send({"event": "ping", "data": {"a": 1}})
        assert conn.received()[0].event == "ping"


# ──────────────────────────────────────────────────────────────────
# Channel: send / receive / broadcast / isolation
# ──────────────────────────────────────────────────────────────────


class TestChannel:
    def test_create_connect_ready(self):
        ch = Channel("/chat")
        assert ch.state == CHANNEL_STATE_CONNECT
        conn = ch.connect()
        assert ch.state == CHANNEL_STATE_READY
        assert conn.is_open()

    def test_connection_count(self):
        ch = Channel("/chat")
        c1 = ch.connect()
        c2 = ch.connect()
        assert ch.connection_count() == 2
        ch.disconnect(c1.id)
        assert ch.connection_count() == 1

    def test_send_to_one_connection(self):
        ch = Channel("/chat")
        c1 = ch.connect()
        c2 = ch.connect()
        ch.send(c1.id, Message(event="hi", data={}))
        assert len(c1.received()) == 1
        assert len(c2.received()) == 0

    def test_broadcast_all(self):
        ch = Channel("/chat")
        c1 = ch.connect()
        c2 = ch.connect()
        n = ch.broadcast(Message(event="tick", data={}))
        assert n == 2
        assert len(c1.received()) == 1
        assert len(c2.received()) == 1

    def test_broadcast_except(self):
        ch = Channel("/chat")
        c1 = ch.connect()
        c2 = ch.connect()
        n = ch.broadcast_except(c1.id, Message(event="tick", data={}))
        assert n == 1
        assert len(c1.received()) == 0
        assert len(c2.received()) == 1

    def test_channel_isolation(self):
        chat = Channel("/chat")
        news = Channel("/news")
        cc = chat.connect()
        nc = news.connect()
        chat.broadcast(Message(event="a", data={}))
        assert len(cc.received()) == 1
        assert len(nc.received()) == 0  # isolated

    def test_send_to_unknown_connection_is_noop(self):
        ch = Channel("/chat")
        ch.connect()
        ch.send("does-not-exist", Message(event="a", data={}))
        assert ch.message_count == 0

    def test_disconnect_returns_false_for_unknown(self):
        ch = Channel("/chat")
        assert ch.disconnect("nope") is False


# ──────────────────────────────────────────────────────────────────
# RealtimeManager
# ──────────────────────────────────────────────────────────────────


class TestRealtimeManager:
    def test_channel_registry(self):
        mgr = RealtimeManager()
        ch = mgr.channel("/products")
        assert mgr.has_channel("/products")
        assert mgr.channel("/products") is ch  # canonical, same object

    def test_get_channel_missing_raises(self):
        mgr = RealtimeManager()
        with pytest.raises(ChannelNotFoundError):
            mgr.channel("/missing", create=False)

    def test_connect_disconnect(self):
        mgr = RealtimeManager()
        conn = mgr.connect("/products")
        assert mgr.connection_count("/products") == 1
        assert mgr.disconnect("/products", conn.id) is True
        assert mgr.connection_count("/products") == 0

    def test_total_connection_count(self):
        mgr = RealtimeManager()
        mgr.connect("/a")
        mgr.connect("/a")
        mgr.connect("/b")
        assert mgr.connection_count() == 3

    def test_broadcast_via_manager(self):
        mgr = RealtimeManager()
        c1 = mgr.connect("/products")
        c2 = mgr.connect("/products")
        mgr.broadcast("/products", Message(event="product.created", data={"id": 1}))
        assert len(c1.received()) == 1
        assert len(c2.received()) == 1

    def test_remove_channel(self):
        mgr = RealtimeManager()
        mgr.connect("/products")
        assert mgr.remove_channel("/products") is True
        assert not mgr.has_channel("/products")


# ──────────────────────────────────────────────────────────────────
# Diagnostics integration (request_id / trace_id)
# ──────────────────────────────────────────────────────────────────


class TestDiagnosticsIntegration:
    def test_trace_ids_recorded_in_store(self):
        store = DiagnosticsStore()
        mgr = RealtimeManager(diagnostics=store)
        ch = mgr.channel("/products")
        ch.connect()
        ch.broadcast(Message(event="product.created", data={"id": 1}))
        records = store.recent()
        codes = {r["code"] for r in records}
        assert "REALTIME_TRACE" in codes

    def test_message_carries_request_and_trace_id(self):
        store = DiagnosticsStore()
        mgr = RealtimeManager(diagnostics=store)
        ch = mgr.channel("/products")
        conn = ch.connect()
        msg = Message(
            event="x",
            data={},
            channel="/products",
            request_id="REQ-1",
            trace_id="TRC-1",
        )
        ch.send(conn.id, msg)
        assert conn.received()[0].request_id == "REQ-1"
        assert conn.received()[0].trace_id == "TRC-1"

    def test_error_record_has_trace_context(self):
        store = DiagnosticsStore()
        store.record(
            code="CHANNEL_ERROR",
            component="realtime",
            level="error",
            message="boom",
            request_id="REQ-9",
            trace_id="TRC-9",
        )
        rec = store.errors()[0]
        assert rec["request_id"] == "REQ-9"
        assert rec["trace_id"] == "TRC-9"


# ──────────────────────────────────────────────────────────────────
# Error contract (reuses BetrayerError)
# ──────────────────────────────────────────────────────────────────


class TestErrorContract:
    def test_realtime_error_is_betrayer_error(self):
        err = RealtimeError(message="boom")
        assert isinstance(err, BetrayerError)
        assert err.code == "REALTIME_ERROR"
        assert err.component == "realtime"

    def test_channel_not_found_carries_code(self):
        err = ChannelNotFoundError(message="missing", context={"channel": "/x"})
        assert err.code == "CHANNEL_NOT_FOUND"
        assert err.context.get("channel") == "/x"


# ──────────────────────────────────────────────────────────────────
# Transport availability (no live socket needed)
# ──────────────────────────────────────────────────────────────────


class TestTransportAvailability:
    def test_flask_sock_availability_flag(self):
        # Whatever the environment, the flag must be a bool and never raise.
        assert isinstance(flask_sock_available(), bool)
