"""Trace middleware: request/trace ID integration for the web pipeline.

Middleware is the single seam for trace injection: every HTTP request
gets a ``request_id`` and ``trace_id`` before the handler runs, and
a trace step is recorded for each layer (``resource``, ``service``,
``repository``, ``orm``, ``database``) when the handler reports it.

Integration
-----------
The adapter (``FlaskAdapter._make_view``) creates the ``Request`` and
``WebContext``.  The :class:`TraceMiddleware` is the **only** place that
generates and attaches trace IDs to the ``WebContext``.

Use::

    adapter = FlaskAdapter(application, router)
    adapter.middleware.add(TraceMiddleware())

Environment variables (optional)::

    BETRAYER_TRACE_HEADER  - header name to read trace_id from (default:
                             ``X-Trace-Id``).
    BETRAYER_REQUEST_HEADER - header name to read request_id from (default:
                              ``X-Request-Id``).
"""

from __future__ import annotations

import os
import time
from typing import Any, Optional

from betrayer.diagnostics.store import (
    DiagnosticsStore,
    generate_request_id,
    generate_trace_id,
)
from betrayer.web.middleware import Middleware

__all__ = [
    "TraceMiddleware",
    "get_current_request_id",
    "get_current_trace_id",
]

#: Thread-local storage for the current request/trace IDs.
_tls: Any = __import__("threading").local()

_TRACE_HEADER: str = os.environ.get("BETRAYER_TRACE_HEADER", "X-Trace-Id")
_REQUEST_HEADER: str = os.environ.get("BETRAYER_REQUEST_HEADER", "X-Request-Id")


class TraceMiddleware(Middleware):
    """Middleware that injects request/trace IDs into every HTTP request.

    The middleware runs ``before_request`` to generate IDs and attach them
    to the ``WebContext``, and ``after_request`` to record the trace step.
    """

    name: str = "trace"
    priority: int = -100  # run before other middleware

    def before_request(self, request: Any, context: Any) -> None:
        """Generate and attach request/trace IDs."""
        request_id = request.header(_REQUEST_HEADER) or generate_request_id()
        trace_id = request.header(_TRACE_HEADER) or generate_trace_id()

        # Store on context for handler consumption.
        context.request_id = request_id
        context.trace_id = trace_id

        # Store on thread local for out-of-band access.
        _tls.request_id = request_id
        _tls.trace_id = trace_id

        # Start trace in the diagnostics store.
        diagnostics = _get_diagnostics_store(context)
        if diagnostics is not None:
            diagnostics.trace_request(request_id, trace_id)
            diagnostics.add_trace_step(
                request_id,
                layer="http",
                component="TraceMiddleware",
                status="ok",
                detail=f"{request.method} {request.path}",
            )

    def after_request(self, request: Any, response: Any, context: Any) -> Any:
        """Record the response trace step."""
        request_id = getattr(context, "request_id", None)
        if request_id:
            diagnostics = _get_diagnostics_store(context)
            if diagnostics is not None:
                diagnostics.add_trace_step(
                    request_id,
                    layer="http",
                    component="response",
                    status="ok",
                    detail=f"status={getattr(response, 'status', 200)}",
                )

    def on_error(self, request: Any, error: BaseException, context: Any) -> Any:
        """Record an error trace step."""
        request_id = getattr(context, "request_id", None)
        if request_id:
            diagnostics = _get_diagnostics_store(context)
            if diagnostics is not None:
                diagnostics.record(
                    code="REQUEST_ERROR",
                    component="web",
                    level="error",
                    message=f"{type(error).__name__}: {error}",
                    request_id=request_id,
                    trace_id=getattr(context, "trace_id", None),
                )
        return None


def _get_diagnostics_store(context: Any) -> Optional[DiagnosticsStore]:
    """Resolve the diagnostics store from context."""
    application = getattr(context, "application", None)
    if application is None:
        return None
    return getattr(application, "diagnostics", None)


# ── public accessors ──────────────────────────────────────────────────


def get_current_request_id() -> Optional[str]:
    """Return the current request ID (thread-local), or ``None``."""
    return getattr(_tls, "request_id", None)


def get_current_trace_id() -> Optional[str]:
    """Return the current trace ID (thread-local), or ``None``."""
    return getattr(_tls, "trace_id", None)