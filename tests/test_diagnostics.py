"""Tests for the diagnostics subsystem (Task 13).

Tests cover: DiagnosticsStore, TraceMiddleware, bet check, bet doctor,
bet debug, request/trace ID, secret masking, JSON output, exit codes.
"""

from __future__ import annotations

import json
import time
from typing import Any, Generator

import pytest

from betrayer.diagnostics.store import (
    CHECK_STATUS_ERROR,
    CHECK_STATUS_PASS,
    CHECK_STATUS_WARNING,
    LEVEL_ERROR,
    LEVEL_INFO,
    LEVEL_WARNING,
    DiagnosticsStore,
    generate_request_id,
    generate_trace_id,
    masked,
)
from betrayer.diagnostics.trace import (
    TraceMiddleware,
    get_current_request_id,
    get_current_trace_id,
)


# ---------------------------------------------------------------------------
# DiagnosticsStore tests
# ---------------------------------------------------------------------------


class TestDiagnosticsStore:
    def test_create_store(self) -> None:
        store = DiagnosticsStore("test")
        assert store.name == "test"
        assert store.summary()["total_records"] == 0

    def test_record_info(self) -> None:
        store = DiagnosticsStore("test")
        record = store.record(
            code="TEST_CODE",
            component="test",
            level=LEVEL_INFO,
            message="test message",
        )
        assert record.code == "TEST_CODE"
        assert record.message == "test message"
        assert record.level == LEVEL_INFO
        assert record.request_id is None

        summary = store.summary()
        assert summary["total_records"] == 1
        assert summary["errors"] == 0

    def test_record_error(self) -> None:
        store = DiagnosticsStore("test")
        store.record(
            code="TEST_ERROR",
            component="test",
            level=LEVEL_ERROR,
            message="error occurred",
            request_id="abc123",
            trace_id="trace456",
            context={"key": "value"},
            suggested_actions=["Fix it", "Check logs"],
        )
        errors = store.errors()
        assert len(errors) == 1
        assert errors[0]["code"] == "TEST_ERROR"
        assert errors[0]["request_id"] == "abc123"
        assert errors[0]["trace_id"] == "trace456"
        assert errors[0]["suggested_actions"] == ["Fix it", "Check logs"]

    def test_record_with_request_id(self) -> None:
        store = DiagnosticsStore("test")
        store.record("REQ", "test", LEVEL_ERROR, "req error", request_id="req1")
        store.record("REQ2", "test", LEVEL_INFO, "req ok", request_id="req2")

        req1 = store.get_request("req1")
        assert req1 is not None
        assert req1["code"] == "REQ"

        assert store.get_request("unknown") is None

    def test_trace_request(self) -> None:
        store = DiagnosticsStore("test")
        store.trace_request("req1", "trace1")
        store.add_trace_step("req1", "http", "middleware", "ok")
        store.add_trace_step("req1", "service", "ProductService", "ok", duration_ms=1.2)

        trace = store.get_trace("req1")
        assert trace is not None
        assert len(trace) == 2
        assert trace[0]["layer"] == "http"
        assert trace[1]["component"] == "ProductService"

    def test_get_request_with_trace(self) -> None:
        store = DiagnosticsStore("test")
        store.record(
            "REQUEST_ERROR", "web", LEVEL_ERROR,
            "Not found", request_id="req_trace",
        )
        store.trace_request("req_trace", "trace1")
        store.add_trace_step("req_trace", "http", "middleware", "ok")

        info = store.get_request("req_trace")
        assert info is not None
        assert info["code"] == "REQUEST_ERROR"
        assert len(info["trace"]) == 1

    def test_recent_records(self) -> None:
        store = DiagnosticsStore("test")
        for i in range(5):
            store.record(f"MSG{i}", "test", LEVEL_INFO, f"message {i}")
        recent = store.recent(limit=3)
        assert len(recent) == 3
        assert recent[0]["code"] == "MSG4"  # newest first

    def test_recent_level_filter(self) -> None:
        store = DiagnosticsStore("test")
        store.record("E1", "test", LEVEL_ERROR, "error1")
        store.record("I1", "test", LEVEL_INFO, "info1")
        store.record("E2", "test", LEVEL_ERROR, "error2")

        errors = store.recent(level=LEVEL_ERROR)
        assert len(errors) == 2

        infos = store.recent(level=LEVEL_INFO)
        assert len(infos) == 1

    def test_clear(self) -> None:
        store = DiagnosticsStore("test")
        store.record("X", "test", LEVEL_INFO, "x")
        store.trace_request("r1", "t1")
        assert store.summary()["total_records"] == 1
        store.clear()
        assert store.summary()["total_records"] == 0

    def test_summary(self) -> None:
        store = DiagnosticsStore("test")
        store.record("A", "test", LEVEL_INFO, "a")
        store.record("B", "test", LEVEL_WARNING, "b")
        store.record("C", "test", LEVEL_ERROR, "c", request_id="r1")
        store.trace_request("r1", "t1")

        s = store.summary()
        assert s["total_records"] == 3
        assert s["errors"] == 1
        assert s["warnings"] == 1
        assert s["requests_tracked"] == 1
        assert s["traces_recorded"] == 1

    def test_to_dict(self) -> None:
        store = DiagnosticsStore("test")
        store.record("A", "test", LEVEL_INFO, "a")
        d = store.to_dict()
        assert d["name"] == "test"
        assert d["summary"]["total_records"] == 1
        assert len(d["recent"]) == 1

    def test_errors_limit(self) -> None:
        store = DiagnosticsStore("test")
        for i in range(10):
            store.record(f"E{i}", "test", LEVEL_ERROR, f"error {i}")
        errors = store.errors(limit=3)
        assert len(errors) == 3

    def test_errors_component_filter(self) -> None:
        store = DiagnosticsStore("test")
        store.record("A", "web", LEVEL_ERROR, "web error")
        store.record("B", "db", LEVEL_ERROR, "db error")
        web_errors = store.errors(component="web")
        assert len(web_errors) == 1
        assert web_errors[0]["component"] == "web"


# ---------------------------------------------------------------------------
# ID generation tests
# ---------------------------------------------------------------------------


class TestIDGeneration:
    def test_generate_request_id(self) -> None:
        rid = generate_request_id()
        assert isinstance(rid, str)
        assert len(rid) == 12

    def test_generate_trace_id(self) -> None:
        tid = generate_trace_id()
        assert isinstance(tid, str)
        assert len(tid) == 16

    def test_unique_ids(self) -> None:
        ids = {generate_request_id() for _ in range(100)}
        assert len(ids) == 100


# ---------------------------------------------------------------------------
# Masking tests
# ---------------------------------------------------------------------------


class TestMasking:
    def test_masked_returns_asterisks(self) -> None:
        assert masked("secret123") == "****"
        assert masked("") == "****"
        assert masked(None) == "****"


# ---------------------------------------------------------------------------
# TraceMiddleware tests (unit, no Flask)
# ---------------------------------------------------------------------------


class FakeContext:
    """A mock WebContext for testing."""

    def __init__(self) -> None:
        self.request_id: str | None = None
        self.trace_id: str | None = None
        self.application = FakeApplication()


class FakeApplication:
    def __init__(self) -> None:
        self.diagnostics = DiagnosticsStore("test")


class FakeRequest:
    """A mock Request for testing."""

    def __init__(self, method: str = "GET", path: str = "/") -> None:
        self._method = method
        self._path = path
        self._headers: dict[str, str] = {}

    def header(self, name: str, default: str | None = None) -> str | None:
        return self._headers.get(name, default)

    @property
    def method(self) -> str:
        return self._method

    @property
    def path(self) -> str:
        return self._path


class TestTraceMiddleware:
    def test_before_request_generates_ids(self) -> None:
        mw = TraceMiddleware()
        request = FakeRequest("GET", "/test")
        context = FakeContext()

        result = mw.before_request(request, context)
        assert result is None
        assert context.request_id is not None
        assert context.trace_id is not None
        assert len(context.request_id) == 12
        assert len(context.trace_id) == 16

    def test_before_request_records_trace(self) -> None:
        mw = TraceMiddleware()
        request = FakeRequest("POST", "/api/products")
        context = FakeContext()

        mw.before_request(request, context)
        store = context.application.diagnostics
        trace = store.get_trace(context.request_id)
        assert trace is not None
        assert len(trace) >= 1
        assert trace[0]["layer"] == "http"

    def test_after_request(self) -> None:
        mw = TraceMiddleware()
        request = FakeRequest()
        context = FakeContext()
        mw.before_request(request, context)

        response = FakeResponse(200)
        mw.after_request(request, response, context)

        store = context.application.diagnostics
        trace = store.get_trace(context.request_id)
        assert trace is not None
        assert trace[-1]["component"] == "response"

    def test_on_error_records_diagnostic(self) -> None:
        mw = TraceMiddleware()
        request = FakeRequest()
        context = FakeContext()
        mw.before_request(request, context)

        mw.on_error(request, ValueError("test error"), context)

        store = context.application.diagnostics
        errors = store.errors()
        assert len(errors) >= 1
        assert "test error" in errors[0]["message"]


class FakeResponse:
    def __init__(self, status: int = 200) -> None:
        self.status = status


# ---------------------------------------------------------------------------
# CLI command tests (via the CommandRegistry and direct handler calls)
# ---------------------------------------------------------------------------


class TestCLICheckCommand:
    def test_check_output_is_deterministic(self, application: Any) -> None:
        """Verify _cmd_check produces structured output."""
        from betrayer.cli.main import _cmd_check

        class FakeArgs:
            json = False

        exit_code = _cmd_check(FakeArgs())
        assert exit_code == 0  # no errors (only warnings)

    def test_check_json(self, application: Any) -> None:
        from betrayer.cli.main import _cmd_check
        import io
        import sys

        class FakeArgs:
            json = True

        # Capture stdout
        captured = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured
        try:
            exit_code = _cmd_check(FakeArgs())
        finally:
            sys.stdout = old_stdout

        assert exit_code == 0
        output = json.loads(captured.getvalue())
        assert "checks" in output
        assert "success" in output
        assert "status" in output


class TestCLIDoctorCommand:
    def test_doctor(self, application: Any) -> None:
        from betrayer.cli.main import _cmd_doctor

        class FakeArgs:
            json = False

        exit_code = _cmd_doctor(FakeArgs())
        assert exit_code == 0

    def test_doctor_json(self, application: Any) -> None:
        from betrayer.cli.main import _cmd_doctor
        import io
        import sys

        class FakeArgs:
            json = True

        captured = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured
        try:
            exit_code = _cmd_doctor(FakeArgs())
        finally:
            sys.stdout = old_stdout

        assert exit_code == 0
        output = json.loads(captured.getvalue())
        assert output["ok"] is True
        assert output["status"] == "pass"


class TestCLIDebugCommand:
    def test_debug_summary(self, application: Any) -> None:
        from betrayer.cli.main import _cmd_debug

        class FakeArgs:
            json = False
            debug_action = None

        exit_code = _cmd_debug(FakeArgs())
        assert exit_code == 0

    def test_debug_summary_json(self, application: Any) -> None:
        from betrayer.cli.main import _cmd_debug
        import io
        import sys

        class FakeArgs:
            json = True
            debug_action = None

        captured = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured
        try:
            exit_code = _cmd_debug(FakeArgs())
        finally:
            sys.stdout = old_stdout

        assert exit_code == 0
        output = json.loads(captured.getvalue())
        assert "name" in output
        assert "total_records" in output

    def test_debug_last(self, application: Any) -> None:
        from betrayer.cli.main import _cmd_debug

        class FakeArgs:
            json = False
            debug_action = "last"

        exit_code = _cmd_debug(FakeArgs())
        assert exit_code == 0

    def test_debug_errors(self, application: Any) -> None:
        from betrayer.cli.main import _cmd_debug

        class FakeArgs:
            json = False
            debug_action = "errors"

        exit_code = _cmd_debug(FakeArgs())
        assert exit_code == 0


# ---------------------------------------------------------------------------
# Secret masking in diagnostic records
# ---------------------------------------------------------------------------


class TestSecretMasking:
    def test_secret_masked_in_context(self) -> None:
        store = DiagnosticsStore("test")
        store.record(
            "DB", "database", LEVEL_ERROR,
            "connection failed",
            context={"password": "supersecret", "user": "admin"},
        )
        errors = store.errors()
        assert errors[0]["context"]["password"] == "****"
        assert errors[0]["context"]["user"] == "admin"  # not a secret key

    def test_secret_keys_are_masked(self) -> None:
        """Verify that common secret key names are masked."""
        from betrayer.diagnostics.store import _SECRET_KEYS
        assert "password" in _SECRET_KEYS
        assert "token" in _SECRET_KEYS
        assert "secret" in _SECRET_KEYS
        assert "api_key" in _SECRET_KEYS


# ---------------------------------------------------------------------------
# Structured diagnostic format tests
# ---------------------------------------------------------------------------


class TestStructuredFormat:
    def test_record_to_dict_full(self) -> None:
        store = DiagnosticsStore("test")
        store.record(
            "TEST", "web", LEVEL_ERROR,
            "test error",
            request_id="req1",
            trace_id="trace1",
            context={"key": "val"},
            suggested_actions=["Action 1"],
        )
        store.trace_request("req1", "trace1")
        store.add_trace_step("req1", "http", "middleware", "ok")

        record = store.get_request("req1")
        assert record is not None
        assert record["code"] == "TEST"
        assert record["level"] == "error"
        assert record["component"] == "web"
        assert record["request_id"] == "req1"
        assert record["trace_id"] == "trace1"
        assert record["context"]["key"] == "val"
        assert record["suggested_actions"] == ["Action 1"]
        assert len(record["trace"]) == 1
        assert "timestamp" in record

    def test_check_format_contract(self) -> None:
        """Verify check output matches the documented contract."""
        from betrayer.cli.main import _cmd_check
        import io
        import sys

        class FakeArgs:
            json = True

        captured = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured
        try:
            _cmd_check(FakeArgs())
        finally:
            sys.stdout = old_stdout

        output = json.loads(captured.getvalue())
        assert "success" in output
        assert "status" in output
        assert "checks" in output
        assert "summary" in output

        for check in output["checks"]:
            assert "name" in check
            assert "status" in check
            assert check["status"] in ("PASS", "WARNING", "ERROR")


# ---------------------------------------------------------------------------
# Exit code tests
# ---------------------------------------------------------------------------


class TestExitCodes:
    def test_check_exit_code_pass(self) -> None:
        from betrayer.cli.main import _cmd_check

        class FakeArgs:
            json = False

        code = _cmd_check(FakeArgs())
        assert code == 0  # no errors, only warnings

    def test_doctor_exit_code_pass(self) -> None:
        from betrayer.cli.main import _cmd_doctor

        class FakeArgs:
            json = False

        code = _cmd_doctor(FakeArgs())
        assert code == 0

    def test_debug_exit_code(self) -> None:
        from betrayer.cli.main import _cmd_debug

        class FakeArgs:
            json = False
            debug_action = None

        code = _cmd_debug(FakeArgs())
        assert code == 0


# ---------------------------------------------------------------------------
# JSON output validity
# ---------------------------------------------------------------------------


class TestJSONOutput:
    def test_check_json_is_valid(self) -> None:
        from betrayer.cli.main import _cmd_check
        import io
        import sys

        class FakeArgs:
            json = True

        captured = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured
        try:
            code = _cmd_check(FakeArgs())
        finally:
            sys.stdout = old_stdout

        assert code == 0
        # Must parse as valid JSON
        parsed = json.loads(captured.getvalue())
        assert isinstance(parsed, dict)

    def test_doctor_json_is_valid(self) -> None:
        from betrayer.cli.main import _cmd_doctor
        import io
        import sys

        class FakeArgs:
            json = True

        captured = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured
        try:
            code = _cmd_doctor(FakeArgs())
        finally:
            sys.stdout = old_stdout

        assert code == 0
        parsed = json.loads(captured.getvalue())
        assert isinstance(parsed, dict)

    def test_debug_json_is_valid(self) -> None:
        from betrayer.cli.main import _cmd_debug
        import io
        import sys

        class FakeArgs:
            json = True
            debug_action = None

        captured = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured
        try:
            code = _cmd_debug(FakeArgs())
        finally:
            sys.stdout = old_stdout

        assert code == 0
        parsed = json.loads(captured.getvalue())
        assert isinstance(parsed, dict)