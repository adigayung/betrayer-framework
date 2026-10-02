"""Structured Error Contract for LLM consumption.

This module defines the SINGLE error contract that all Betrayer components
must use when reporting errors to LLMs. The contract is designed to be:

1. Machine-readable (JSON-serializable)
2. Self-contained (no additional search/read needed)
3. Actionable (clear location, cause, and suggested context)

Error Contract Fields
---------------------
error_type: str
    Stable, greppable error code (e.g. "DATABASE_CONNECTION_ERROR")
message: str
    Short, single-line human-readable explanation
location: dict | null
    {file: str, line: int | null, function: str | null}
component: str | null
    Subsystem that raised the error (e.g. "database", "web", "cli")
cause: dict | null
    Original exception details if this error wraps another
details: dict | null
    Additional structured context (validation errors, query info, etc.)
suggested_context: dict | null
    Hints for LLM: related files, modules, or documentation to check
traceback: str | null
    Full traceback when available (truncated for very long traces)
command: dict | null
    CLI command context {command: str, args: list, exit_code: int}

Design Principles
-----------------
* Fields that are unavailable MUST be null/empty - never fabricate data
* The contract is EXTENDED, not replaced - existing BetrayerError remains
* Integration points: CLI output, web responses, test runner, application errors
* No duplicate error subsystems - this module only formats existing errors
"""

from __future__ import annotations

import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence


# Maximum traceback length (characters) before truncation
MAX_TRACEBACK_LENGTH = 8000

# Maximum message length before truncation
MAX_MESSAGE_LENGTH = 1000


@dataclass
class StructuredError:
    """LLM-friendly error representation.

    This is the canonical error structure that ALL Betrayer components
    must produce when reporting errors to LLMs (via --json output,
    API error responses, or test failures).

    Usage::

        # From BetrayerError
        error = StructuredError.from_exception(exc)

        # From any exception
        error = StructuredError.from_exception(exc, component="application")

        # Direct construction
        error = StructuredError(
            error_type="VALIDATION_ERROR",
            message="Invalid input",
            component="web",
            details={"field": "email", "reason": "required"},
        )

        # To JSON
        json_output = error.to_json()
    """

    error_type: str
    message: str
    location: Optional[Dict[str, Any]] = None
    component: Optional[str] = None
    cause: Optional[Dict[str, Any]] = None
    details: Optional[Dict[str, Any]] = None
    suggested_context: Optional[Dict[str, Any]] = None
    traceback: Optional[str] = None
    command: Optional[Dict[str, Any]] = None
    _raw_exception: Optional[BaseException] = field(default=None, repr=False)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict (nulls preserved)."""
        result: Dict[str, Any] = {
            "error_type": self.error_type,
            "message": self.message,
        }

        # Always include these fields, even if null (explicit contract)
        result["location"] = self.location
        result["component"] = self.component
        result["cause"] = self.cause
        result["details"] = self.details
        result["suggested_context"] = self.suggested_context
        result["traceback"] = self.traceback
        result["command"] = self.command

        return result

    def to_json(self, indent: Optional[int] = 2) -> str:
        """JSON string representation."""
        import json

        return json.dumps(self.to_dict(), indent=indent, sort_keys=True, ensure_ascii=False)

    @classmethod
    def from_exception(
        cls,
        exc: BaseException,
        *,
        component: Optional[str] = None,
        command: Optional[Dict[str, Any]] = None,
        include_traceback: bool = True,
        suggested_context: Optional[Dict[str, Any]] = None,
    ) -> "StructuredError":
        """Create StructuredError from any exception.

        This is the PRIMARY factory method for converting exceptions
        into LLM-friendly errors.

        Parameters
        ----------
        exc : BaseException
            The exception to convert
        component : str, optional
            Override component name (default: inferred from exception type)
        command : dict, optional
            CLI command context {command: str, args: list, exit_code: int}
        include_traceback : bool
            Whether to include full traceback (default: True)
        suggested_context : dict, optional
            Additional hints for LLM

        Returns
        -------
        StructuredError
            LLM-friendly error representation
        """
        # Import here to avoid circular dependency
        from betrayer.core.exceptions import BetrayerError

        # Extract base information
        error_type = _extract_error_type(exc)
        message = _extract_message(exc)
        location = _extract_location(exc)
        inferred_component = component or _extract_component(exc)
        cause_info = _extract_cause(exc)
        details = _extract_details(exc)

        # Extract traceback
        tb_str = None
        if include_traceback:
            tb_str = _extract_traceback(exc)

        # Merge suggested context
        final_context = suggested_context or {}
        if isinstance(exc, BetrayerError):
            # BetrayerError may have built-in context hints
            builtin_context = _extract_builtin_context(exc)
            if builtin_context:
                final_context = {**builtin_context, **final_context}

        return cls(
            error_type=error_type,
            message=message,
            location=location,
            component=inferred_component,
            cause=cause_info,
            details=details,
            suggested_context=final_context if final_context else None,
            traceback=tb_str,
            command=command,
            _raw_exception=exc,
        )

    @classmethod
    def from_test_failure(
        cls,
        test_name: str,
        test_file: str,
        test_line: int,
        message: str,
        *,
        traceback_str: Optional[str] = None,
        test_class: Optional[str] = None,
        duration: Optional[float] = None,
    ) -> "StructuredError":
        """Create StructuredError from test failure.

        Parameters
        ----------
        test_name : str
            Name of the failing test function
        test_file : str
            Path to test file
        test_line : int
            Line number of the test
        message : str
            Failure message
        traceback_str : str, optional
            Full traceback string
        test_class : str, optional
            Test class name if using class-based tests
        duration : float, optional
            Test duration in seconds

        Returns
        -------
        StructuredError
            LLM-friendly test failure representation
        """
        location = {
            "file": str(test_file),
            "line": int(test_line),
            "function": test_name,
        }

        if test_class:
            location["class"] = test_class

        details: Dict[str, Any] = {}
        if duration is not None:
            details["duration"] = round(duration, 3)

        return cls(
            error_type="TEST_FAILURE",
            message=message,
            location=location,
            component="test",
            details=details if details else None,
            traceback=traceback_str,
        )


# ---------------------------------------------------------------------------
# Helper functions for extracting error information
# ---------------------------------------------------------------------------


def _extract_error_type(exc: BaseException) -> str:
    """Extract stable error code from exception."""
    # BetrayerError has explicit code
    if hasattr(exc, "code") and exc.code:
        return str(exc.code)

    # Check for http_status (WebError)
    if hasattr(exc, "http_status"):
        status = exc.http_status
        # Map common HTTP status to error codes
        http_code_map = {
            400: "BAD_REQUEST",
            401: "UNAUTHORIZED",
            403: "FORBIDDEN",
            404: "RESOURCE_NOT_FOUND",
            405: "METHOD_NOT_ALLOWED",
            409: "CONFLICT",
            422: "VALIDATION_FAILED",
            429: "RATE_LIMIT_EXCEEDED",
            500: "INTERNAL_ERROR",
        }
        return http_code_map.get(status, f"HTTP_{status}")

    # Fall back to class name
    return type(exc).__name__


def _extract_message(exc: BaseException) -> str:
    """Extract human-readable message from exception."""
    # BetrayerError has explicit message
    if hasattr(exc, "message") and exc.message:
        msg = str(exc.message)
    else:
        msg = str(exc) if str(exc) else type(exc).__name__

    # Truncate if too long
    if len(msg) > MAX_MESSAGE_LENGTH:
        msg = msg[:MAX_MESSAGE_LENGTH] + "..."

    return msg


def _extract_location(exc: BaseException) -> Optional[Dict[str, Any]]:
    """Extract file/line/function from exception traceback."""
    tb = exc.__traceback__
    if tb is None:
        return None

    # Walk to the deepest frame
    deepest = tb
    while deepest.tb_next is not None:
        deepest = deepest.tb_next

    frame = deepest.tb_frame
    location: Dict[str, Any] = {
        "file": _relative_path(frame.f_code.co_filename),
        "line": deepest.tb_lineno,
        "function": frame.f_code.co_name,
    }

    return location


def _extract_component(exc: BaseException) -> Optional[str]:
    """Extract component name from exception type."""
    # BetrayerError has explicit component
    if hasattr(exc, "component") and exc.component:
        return str(exc.component)

    # Infer from module path
    exc_module = type(exc).__module__
    if exc_module.startswith("betrayer."):
        parts = exc_module.split(".")
        if len(parts) >= 2:
            return parts[1]  # e.g. "web", "data", "infrastructure"

    return None


def _extract_cause(exc: BaseException) -> Optional[Dict[str, Any]]:
    """Extract cause exception info."""
    # Check explicit cause attribute (BetrayerError)
    if hasattr(exc, "cause") and exc.cause:
        cause_exc = exc.cause
        return {
            "type": type(cause_exc).__name__,
            "message": str(cause_exc),
            "module": type(cause_exc).__module__,
        }

    # Check __cause__ (from 'raise X from Y')
    if exc.__cause__:
        cause_exc = exc.__cause__
        return {
            "type": type(cause_exc).__name__,
            "message": str(cause_exc),
            "module": type(cause_exc).__module__,
        }

    return None


def _extract_details(exc: BaseException) -> Optional[Dict[str, Any]]:
    """Extract structured details from exception."""
    details: Dict[str, Any] = {}

    # BetrayerError has context
    if hasattr(exc, "context") and exc.context:
        details.update(exc.context)

    # WebError.ValidationError has errors/fields
    if hasattr(exc, "errors") and exc.errors:
        details["errors"] = exc.errors
    if hasattr(exc, "fields") and exc.fields:
        details["fields"] = exc.fields

    # DatabaseError may have operation/driver/database
    for attr in ("operation", "driver", "database", "status_code", "body"):
        if hasattr(exc, attr):
            value = getattr(exc, attr, None)
            if value is not None:
                details[attr] = value

    # RetryError
    if hasattr(exc, "attempts"):
        details["attempts"] = exc.attempts
    if hasattr(exc, "last_exception"):
        details["last_exception"] = str(exc.last_exception)

    # RateLimitError
    if hasattr(exc, "limit"):
        details["limit"] = exc.limit
    if hasattr(exc, "retry_after"):
        details["retry_after"] = exc.retry_after

    return details if details else None


def _extract_traceback(exc: BaseException) -> Optional[str]:
    """Extract formatted traceback string."""
    try:
        tb_list = traceback.format_exception(type(exc), exc, exc.__traceback__)
        tb_str = "".join(tb_list)

        # Truncate if too long
        if len(tb_str) > MAX_TRACEBACK_LENGTH:
            tb_str = tb_str[:MAX_TRACEBACK_LENGTH] + "\n... (truncated)"

        return tb_str
    except Exception:
        return None


def _extract_builtin_context(exc: BaseException) -> Optional[Dict[str, Any]]:
    """Extract built-in context hints from BetrayerError."""
    context: Dict[str, Any] = {}

    # Stage is useful context
    if hasattr(exc, "stage") and exc.stage:
        context["stage"] = exc.stage

    # Component-specific hints
    component = getattr(exc, "component", None)

    if component == "config":
        context["documentation"] = "betrayer/ai/CONFIG.md"
    elif component == "database":
        context["documentation"] = "betrayer/data/DATABASE_CONTRACT.md"
    elif component == "lifecycle":
        context["documentation"] = "betrayer/ai/LIFECYCLE.md"
    elif component == "web":
        context["documentation"] = "betrayer/web/errors.py"

    return context if context else None


def _relative_path(file_path: str) -> str:
    """Convert absolute path to relative path from project root."""
    try:
        path = Path(file_path).resolve()
        cwd = Path.cwd()
        if str(path).startswith(str(cwd)):
            return str(path.relative_to(cwd))
    except Exception:
        pass
    return file_path


# ---------------------------------------------------------------------------
# Public utilities
# ---------------------------------------------------------------------------


def format_error_for_llm(
    exc: BaseException,
    *,
    component: Optional[str] = None,
    command: Optional[Dict[str, Any]] = None,
    include_traceback: bool = True,
    suggested_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Format any exception as LLM-friendly error dict.

    This is a convenience function that creates a StructuredError
    and returns its dict representation.

    Parameters
    ----------
    exc : BaseException
        The exception to format
    component : str, optional
        Override component name
    command : dict, optional
        CLI command context
    include_traceback : bool
        Whether to include traceback (default: True)
    suggested_context : dict, optional
        Additional context hints

    Returns
    -------
    dict
        LLM-friendly error representation
    """
    error = StructuredError.from_exception(
        exc,
        component=component,
        command=command,
        include_traceback=include_traceback,
        suggested_context=suggested_context,
    )
    return error.to_dict()


def format_cli_error(
    exc: BaseException,
    command_name: str,
    args: Optional[Sequence[str]] = None,
    exit_code: int = 1,
) -> Dict[str, Any]:
    """Format CLI command error for LLM.

    Parameters
    ----------
    exc : BaseException
        The exception that caused the failure
    command_name : str
        CLI command name (e.g. "validate", "test")
    args : list, optional
        Command arguments
    exit_code : int
        Exit code (default: 1)

    Returns
    -------
    dict
        LLM-friendly CLI error representation
    """
    command_ctx = {
        "command": command_name,
        "args": list(args) if args else [],
        "exit_code": exit_code,
    }

    return format_error_for_llm(
        exc,
        component="cli",
        command=command_ctx,
        include_traceback=True,
    )


def format_test_failure(
    test_name: str,
    test_file: str,
    test_line: int,
    message: str,
    *,
    traceback_str: Optional[str] = None,
    test_class: Optional[str] = None,
    duration: Optional[float] = None,
) -> Dict[str, Any]:
    """Format test failure for LLM.

    This is a convenience function that creates a StructuredError
    from test failure information and returns its dict representation.

    Parameters
    ----------
    test_name : str
        Name of the failing test
    test_file : str
        Path to test file
    test_line : int
        Line number
    message : str
        Failure message
    traceback_str : str, optional
        Full traceback
    test_class : str, optional
        Test class name
    duration : float, optional
        Test duration in seconds

    Returns
    -------
    dict
        LLM-friendly test failure representation
    """
    error = StructuredError.from_test_failure(
        test_name=test_name,
        test_file=test_file,
        test_line=test_line,
        message=message,
        traceback_str=traceback_str,
        test_class=test_class,
        duration=duration,
    )
    return error.to_dict()


__all__ = [
    "StructuredError",
    "format_error_for_llm",
    "format_cli_error",
    "format_test_failure",
    "MAX_TRACEBACK_LENGTH",
    "MAX_MESSAGE_LENGTH",
]
