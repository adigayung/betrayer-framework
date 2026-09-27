"""Canonical diagnostics store for Betrayer.

One store, one format.  The store is the single source of truth for
``bet check``, ``bet doctor``, and ``bet debug``.  It never creates
a second logging or tracing subsystem — it just records what happens.

Design
------
* A single in-memory ``DiagnosticsStore`` per application.
* Structured records (not free-form log lines).
* Every record carries at least ``{"timestamp", "code", "component",
  "message", "level"}``.
* Errors carry ``request_id``, ``trace_id``, ``context``,
  ``suggested_actions``.
* Secrets are masked: ``diagnostics.masked(value)`` replaces secrets
  with ``"****"``.
* No LLM/AI inside diagnostics.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, ClassVar, Dict, List, Optional, Set

from betrayer.core.config import is_secret_key

__all__ = [
    "DiagnosticsStore",
    "TraceRecord",
    "DiagnosticRecord",
    "CHECK_STATUS_PASS",
    "CHECK_STATUS_WARNING",
    "CHECK_STATUS_ERROR",
    "LEVEL_INFO",
    "LEVEL_WARNING",
    "LEVEL_ERROR",
    "LEVEL_DEBUG",
]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CHECK_STATUS_PASS: str = "PASS"
CHECK_STATUS_WARNING: str = "WARNING"
CHECK_STATUS_ERROR: str = "ERROR"

LEVEL_INFO: str = "info"
LEVEL_WARNING: str = "warning"
LEVEL_ERROR: str = "error"
LEVEL_DEBUG: str = "debug"

#: Keys whose values are always masked in structured output.
_SECRET_KEYS: Set[str] = {
    "password",
    "secret",
    "token",
    "api_key",
    "api_secret",
    "dsn",
    "connection_string",
    "private_key",
    "access_key",
}


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class TraceRecord:
    """A single step in a request trace.

    ``layer`` is one of ``"http"``, ``"resource"``, ``"validation"``,
    ``"service"``, ``"repository"``, ``"orm"``, ``"database"``
    (or any other component name).
    """

    layer: str
    component: str
    status: str  # "ok" | "error" | "skipped"
    duration_ms: float = 0.0
    detail: str = ""
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "layer": self.layer,
            "component": self.component,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "detail": self.detail,
            "error": self.error,
        }


@dataclass
class DiagnosticRecord:
    """A single diagnostic event (error, warning, or info)."""

    timestamp: float = field(default_factory=time.time)
    code: str = "DIAGNOSTIC"
    component: str = "betrayer"
    level: str = LEVEL_INFO
    message: str = ""
    request_id: Optional[str] = None
    trace_id: Optional[str] = None
    context: dict = field(default_factory=dict)
    suggested_actions: List[str] = field(default_factory=list)
    trace: List[TraceRecord] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Structured output, always with masked secrets."""
        context = dict(self.context)
        # Mask secrets in context values.
        for key in list(context):
            if is_secret_key(key) or key.lower() in _SECRET_KEYS:
                context[key] = "****"
        result: dict = {
            "timestamp": self.timestamp,
            "code": self.code,
            "component": self.component,
            "level": self.level,
            "message": self.message,
            "request_id": self.request_id,
            "trace_id": self.trace_id,
            "context": context,
            "suggested_actions": list(self.suggested_actions),
            "trace": [t.to_dict() for t in self.trace],
        }
        return result


# ---------------------------------------------------------------------------
# The store
# ---------------------------------------------------------------------------


class DiagnosticsStore:
    """Canonical in-memory diagnostics store.

    Thread-safe.  One instance per application, reachable through
    ``app.diagnostics`` (set by the bootstrap pipeline).

    Public API::

        store.record(code, component, level, message, ...)
        store.trace_request(request_id, trace_id)
        store.add_trace_step(request_id, layer, component, status, ...)
        store.get_request(request_id) -> dict | None
        store.errors() -> list[dict]
        store.recent(limit=10) -> list[dict]
        store.clear()
    """

    MAX_REQUESTS: ClassVar[int] = 500
    MAX_RECORDS: ClassVar[int] = 2000

    def __init__(self, name: str = "default") -> None:
        self.name = name
        self._lock = threading.Lock()
        self._records: List[DiagnosticRecord] = []
        self._requests: Dict[str, DiagnosticRecord] = {}  # request_id -> latest
        self._traces: Dict[str, List[TraceRecord]] = {}  # request_id -> steps

    # -- recording --------------------------------------------------------

    def record(
        self,
        code: str = "DIAGNOSTIC",
        component: str = "betrayer",
        level: str = LEVEL_INFO,
        message: str = "",
        *,
        request_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        context: Optional[dict] = None,
        suggested_actions: Optional[List[str]] = None,
    ) -> DiagnosticRecord:
        """Append a structured diagnostic record."""
        record = DiagnosticRecord(
            code=code,
            component=component,
            level=level,
            message=message,
            request_id=request_id,
            trace_id=trace_id,
            context=dict(context or {}),
            suggested_actions=list(suggested_actions or []),
        )
        with self._lock:
            self._records.append(record)
            if len(self._records) > self.MAX_RECORDS:
                self._records = self._records[-self.MAX_RECORDS // 2 :]
            if request_id:
                self._requests[request_id] = record
            # Keep max requests bounded
            if len(self._requests) > self.MAX_REQUESTS:
                # Prune old entries
                keys = list(self._requests.keys())
                for k in keys[: len(keys) // 2]:
                    self._requests.pop(k, None)
                    self._traces.pop(k, None)
        return record

    # -- tracing ----------------------------------------------------------

    def trace_request(self, request_id: str, trace_id: str) -> None:
        """Start a new request trace with the given identifiers."""
        with self._lock:
            self._traces[request_id] = []

    def add_trace_step(
        self,
        request_id: str,
        layer: str,
        component: str,
        status: str = "ok",
        *,
        duration_ms: float = 0.0,
        detail: str = "",
        error: Optional[str] = None,
    ) -> None:
        """Record one step in a request trace."""
        step = TraceRecord(
            layer=layer,
            component=component,
            status=status,
            duration_ms=duration_ms,
            detail=detail,
            error=error,
        )
        with self._lock:
            trace = self._traces.get(request_id)
            if trace is not None:
                trace.append(step)

    # -- query ------------------------------------------------------------

    def get_request(self, request_id: str) -> Optional[dict]:
        """Return structured info for one request, or ``None``."""
        with self._lock:
            record = self._requests.get(request_id)
            trace = list(self._traces.get(request_id) or [])
        if record is None:
            return None
        result = record.to_dict()
        result["trace"] = [t.to_dict() for t in trace]
        return result

    def get_trace(self, request_id: str) -> Optional[List[dict]]:
        """Return the trace steps for one request, or ``None``."""
        with self._lock:
            trace = self._traces.get(request_id)
        if trace is None:
            return None
        return [t.to_dict() for t in trace]

    def errors(
        self,
        limit: int = 50,
        *,
        component: Optional[str] = None,
    ) -> List[dict]:
        """Recent error records, newest first."""
        with self._lock:
            matching = [
                r
                for r in reversed(self._records)
                if r.level == LEVEL_ERROR
                and (component is None or r.component == component)
            ]
        return [r.to_dict() for r in matching[:limit]]

    def recent(self, limit: int = 10, *, level: Optional[str] = None) -> List[dict]:
        """Most recent records (newest first)."""
        with self._lock:
            matching = [
                r
                for r in reversed(self._records)
                if level is None or r.level == level
            ]
        return [r.to_dict() for r in matching[:limit]]

    def clear(self) -> None:
        """Clear all records and traces."""
        with self._lock:
            self._records.clear()
            self._requests.clear()
            self._traces.clear()

    # -- introspection ----------------------------------------------------

    def summary(self) -> dict:
        """Aggregate statistics."""
        with self._lock:
            total = len(self._records)
            errors_count = sum(1 for r in self._records if r.level == LEVEL_ERROR)
            warnings_count = sum(1 for r in self._records if r.level == LEVEL_WARNING)
            request_count = len(self._requests)
            trace_count = len(self._traces)
        return {
            "name": self.name,
            "total_records": total,
            "errors": errors_count,
            "warnings": warnings_count,
            "requests_tracked": request_count,
            "traces_recorded": trace_count,
        }

    def to_dict(self) -> dict:
        """Full serializable snapshot."""
        return {
            "name": self.name,
            "summary": self.summary(),
            "recent": self.recent(limit=20),
            "errors": self.errors(limit=20),
        }


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def generate_request_id() -> str:
    """Return a short, readable request identifier."""
    return uuid.uuid4().hex[:12]


def generate_trace_id() -> str:
    """Return a short, readable trace identifier."""
    return uuid.uuid4().hex[:16]


def masked(value: Any) -> str:
    """Replace a value with ``\"****\"`` (for secret masking)."""
    return "****"