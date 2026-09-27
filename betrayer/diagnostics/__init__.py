"""Betrayer diagnostics: inspection, check, doctor, debug, and trace.

The diagnostics subsystem is the single canonical place for:

* **Inspector** — read-only framework/application inspection.
* **DiagnosticsStore** — structured diagnostic records (errors, warnings).
* **TraceMiddleware** — request/trace ID injection for HTTP requests.
* **check** / **doctor** / **debug** commands (consumed through the CLI).

It depends on ``core`` and uses the public inspection API of the
application.  It never reaches into private attributes and never mutates
the inspected object.
"""

from __future__ import annotations

from betrayer.diagnostics.inspector import Inspector
from betrayer.diagnostics.store import (
    CHECK_STATUS_ERROR,
    CHECK_STATUS_PASS,
    CHECK_STATUS_WARNING,
    LEVEL_DEBUG,
    LEVEL_ERROR,
    LEVEL_INFO,
    LEVEL_WARNING,
    DiagnosticRecord,
    DiagnosticsStore,
    TraceRecord,
    generate_request_id,
    generate_trace_id,
    masked,
)
from betrayer.diagnostics.trace import (
    TraceMiddleware,
    get_current_request_id,
    get_current_trace_id,
)

__all__ = [
    "Inspector",
    "DiagnosticsStore",
    "DiagnosticRecord",
    "TraceRecord",
    "TraceMiddleware",
    "CHECK_STATUS_PASS",
    "CHECK_STATUS_WARNING",
    "CHECK_STATUS_ERROR",
    "LEVEL_INFO",
    "LEVEL_WARNING",
    "LEVEL_ERROR",
    "LEVEL_DEBUG",
    "generate_request_id",
    "generate_trace_id",
    "masked",
    "get_current_request_id",
    "get_current_trace_id",
]
