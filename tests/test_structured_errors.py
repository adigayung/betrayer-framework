"""Tests for the Structured Error System (canonical LLM error contract).

These tests lock the contract defined in ``betrayer/core/error_contract.py``
so an LLM can rely on a stable, consistent error shape across CLI, web,
database, validation and the test runner.
"""

from __future__ import annotations

import json

import pytest

from betrayer.core.error_contract import (
    StructuredError,
    format_cli_error,
    format_error_for_llm,
    format_test_failure,
)
from betrayer.core.exceptions import BetrayerError, ConfigurationError


# ── Contract shape ──────────────────────────────────────────────


REQUIRED_FIELDS = (
    "error_type",
    "message",
    "location",
    "component",
    "cause",
    "details",
    "suggested_context",
)


def test_contract_always_includes_required_fields():
    """Every structured error carries the full contract (nulls preserved)."""
    error = StructuredError(error_type="TEST", message="boom")
    payload = error.to_dict()
    for field in REQUIRED_FIELDS:
        assert field in payload
    # Unavailable fields must be null/empty - never fabricated.
    assert payload["location"] is None
    assert payload["cause"] is None
    assert payload["details"] is None


def test_contract_is_json_serializable():
    """The contract round-trips through JSON unchanged."""
    error = StructuredError(
        error_type="TEST",
        message="boom",
        component="unit",
        details={"k": "v"},
    )
    payload = json.loads(error.to_json())
    assert payload["error_type"] == "TEST"
    assert payload["component"] == "unit"
    assert payload["details"] == {"k": "v"}


# ── From BetrayerError ──────────────────────────────────────────


def test_from_exception_extracts_code_and_component():
    """BetrayerError.code/component become error_type/component."""
    exc = ConfigurationError(message="missing key", context={"key": "app.name"})
    error = StructuredError.from_exception(exc)
    assert error.error_type == "CONFIGURATION_ERROR"
    assert error.component == "config"
    assert error.message == "missing key"
    assert error.details == {"key": "app.name"}


def test_from_exception_records_location():
    """A raised exception yields a file/line/function location."""
    try:
        raise ConfigurationError(message="here")
    except ConfigurationError as exc:
        error = StructuredError.from_exception(exc)

    assert error.location is not None
    assert error.location["file"].endswith("test_structured_errors.py")
    assert error.location["function"] == "test_from_exception_records_location"
    assert isinstance(error.location["line"], int)


def test_from_exception_preserves_cause():
    """A wrapped cause is surfaced without losing the original."""
    original = ValueError("root cause")
    exc = BetrayerError(message="wrapped", cause=original)
    error = StructuredError.from_exception(exc)
    assert error.cause is not None
    assert error.cause["type"] == "ValueError"
    assert error.cause["message"] == "root cause"


def test_from_exception_includes_traceback():
    """Traceback text is captured for LLM analysis."""
    try:
        raise BetrayerError(message="trace me")
    except BetrayerError as exc:
        error = StructuredError.from_exception(exc)
    assert error.traceback is not None
    assert "trace me" in error.traceback


def test_from_exception_can_omit_traceback():
    """include_traceback=False keeps the payload small."""
    try:
        raise BetrayerError(message="quiet")
    except BetrayerError as exc:
        error = StructuredError.from_exception(exc, include_traceback=False)
    assert error.traceback is None


def test_component_override_wins():
    """An explicit component overrides inference."""
    exc = BetrayerError(message="x")
    error = StructuredError.from_exception(exc, component="custom")
    assert error.component == "custom"


# ── Plain exceptions ────────────────────────────────────────────


def test_from_plain_exception_uses_class_name():
    """Non-Betrayer exceptions degrade to their class name as error_type."""
    exc = KeyError("missing")
    error = StructuredError.from_exception(exc)
    assert error.error_type == "KeyError"
    assert error.component is None  # never fabricated


def test_error_dict_stays_in_sync_with_contract():
    """BetrayerError.to_dict() exposes the canonical contract fields."""
    exc = BetrayerError(message="combined", code="COMBINED", context={"a": 1})
    payload = exc.to_dict()
    for field in REQUIRED_FIELDS:
        assert field in payload
    # Legacy keys are preserved for existing consumers.
    assert payload["code"] == "COMBINED"
    assert payload["context"] == {"a": 1}


# ── Test failures ───────────────────────────────────────────────


def test_test_failure_preserves_failing_test_and_traceback():
    """Test failures keep test name, file, line and traceback."""
    payload = format_test_failure(
        test_name="test_thing",
        test_file="tests/test_thing.py",
        test_line=42,
        message="AssertionError: nope",
        traceback_str="Traceback (most recent call last):\n...",
        test_class="TestThing",
    )
    assert payload["error_type"] == "TEST_FAILURE"
    assert payload["component"] == "test"
    assert payload["location"]["file"] == "tests/test_thing.py"
    assert payload["location"]["line"] == 42
    assert payload["location"]["function"] == "test_thing"
    assert payload["location"]["class"] == "TestThing"
    assert "Traceback" in payload["traceback"]


# ── CLI failures ────────────────────────────────────────────────


def test_cli_error_captures_command_context():
    """CLI failures carry the command, args and exit code."""
    exc = ConfigurationError(message="bad config")
    payload = format_cli_error(exc, "validate", ["validate", "--json"], exit_code=1)
    assert payload["command"]["command"] == "validate"
    assert payload["command"]["args"] == ["validate", "--json"]
    assert payload["command"]["exit_code"] == 1
    assert payload["component"] == "cli"


# ── Convenience helper ──────────────────────────────────────────


def test_format_error_for_llm_returns_plain_dict():
    """The convenience helper returns a plain JSON-ready dict."""
    payload = format_error_for_llm(BetrayerError(message="ready"))
    assert isinstance(payload, dict)
    assert payload["error_type"] == "BETRAYER_ERROR"
    json.dumps(payload)  # must not raise


def test_suggested_context_included_when_provided():
    """Extra hints ride along in suggested_context."""
    payload = format_error_for_llm(
        BetrayerError(message="x"),
        suggested_context={"next": "read docs"},
    )
    assert payload["suggested_context"]["next"] == "read docs"
