"""Lifecycle state machine for Betrayer.

The lifecycle owns the single source of truth for the application state
and dispatches *handlers* registered per target state.  Subsystems extend
the framework by registering handlers - the core never needs to change.

States and legal transitions (deterministic, asserted by the tests)::

    CREATED      -> BOOTSTRAPPING
    BOOTSTRAPPING-> READY
    READY        -> RUNNING | STOPPING
    RUNNING      -> STOPPING
    STOPPING     -> STOPPED
    STOPPED      -> (terminal)
    any          -> FAILED      (handler failure or explicit failure)

When a handler raises, the lifecycle records *which stage* failed, the
error, the previous state and the state at failure, then moves to FAILED.
"""

from __future__ import annotations

import time
from enum import Enum
from typing import Any, Callable, Optional

from betrayer.core.exceptions import LifecycleError
from betrayer.core.exceptions import RuntimeError as BetrayerRuntimeError

Handler = Callable[["LifecycleState", Any], None]


class LifecycleState(str, Enum):
    """Ordered lifecycle states."""

    CREATED = "created"
    BOOTSTRAPPING = "bootstrapping"
    READY = "ready"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


VALID_TRANSITIONS: dict = {
    LifecycleState.CREATED: (LifecycleState.BOOTSTRAPPING, LifecycleState.FAILED),
    LifecycleState.BOOTSTRAPPING: (LifecycleState.READY, LifecycleState.FAILED),
    LifecycleState.READY: (LifecycleState.RUNNING, LifecycleState.STOPPING, LifecycleState.FAILED),
    LifecycleState.RUNNING: (LifecycleState.STOPPING, LifecycleState.FAILED),
    LifecycleState.STOPPING: (LifecycleState.STOPPED, LifecycleState.FAILED),
    LifecycleState.STOPPED: (LifecycleState.FAILED,),
    LifecycleState.FAILED: (),
}


class Lifecycle:
    """Deterministic lifecycle manager with extensible handlers."""

    def __init__(self, name: str = "betrayer", application: Any = None) -> None:
        self.name = name
        self._application = application
        self._state = LifecycleState.CREATED
        self._previous_state: Optional[LifecycleState] = None
        self._handlers: dict = {state: [] for state in LifecycleState}
        self._history: list = [LifecycleState.CREATED]
        self._error: Optional[BetrayerRuntimeError] = None
        self._started_at: Optional[float] = None
        self._stopped_at: Optional[float] = None

    # -- binding ------------------------------------------------------
    def bind(self, application: Any) -> "Lifecycle":
        """Attach the application handed to lifecycle handlers."""
        self._application = application
        return self

    # -- state --------------------------------------------------------
    @property
    def state(self) -> LifecycleState:
        return self._state

    @property
    def previous_state(self) -> Optional[LifecycleState]:
        return self._previous_state

    @property
    def history(self) -> list:
        return list(self._history)

    @property
    def error(self) -> Optional[BetrayerRuntimeError]:
        return self._error

    @property
    def is_ready(self) -> bool:
        return self._state in (LifecycleState.READY, LifecycleState.RUNNING)

    @property
    def is_running(self) -> bool:
        return self._state is LifecycleState.RUNNING

    @property
    def is_failed(self) -> bool:
        return self._state is LifecycleState.FAILED

    def can_transition(self, target: "LifecycleState") -> bool:
        target = self.coerce_state(target)
        if target is self._state:
            return True
        return target in VALID_TRANSITIONS.get(self._state, ())

    @staticmethod
    def coerce_state(value: Any) -> LifecycleState:
        if isinstance(value, LifecycleState):
            return value
        if isinstance(value, str):
            try:
                return LifecycleState(value.strip().lower())
            except ValueError:
                pass
        raise LifecycleError(
            message=f"Unknown lifecycle state: {value!r}",
            code="LIFECYCLE_INVALID_STATE",
            stage="lifecycle",
            context={"value": repr(value)},
        )

    # -- handlers -----------------------------------------------------
    def register_handler(self, state: Any, handler: Handler, *, name: Optional[str] = None) -> Handler:
        """Register *handler* for *state*. Handlers run in registration order."""
        resolved = self.coerce_state(state)
        if not callable(handler):
            raise LifecycleError(
                message="Lifecycle handler must be callable",
                code="LIFECYCLE_INVALID_HANDLER",
                stage=resolved.value,
                context={"handler": repr(handler)},
            )
        self._handlers[resolved].append(handler)
        return handler

    # Named registration helpers: the public vocabulary of the framework.
    def on_bootstrap(self, handler: Handler) -> Handler:
        return self.register_handler(LifecycleState.BOOTSTRAPPING, handler)

    def on_initialize(self, handler: Handler) -> Handler:
        return self.register_handler(LifecycleState.READY, handler)

    def on_ready(self, handler: Handler) -> Handler:
        return self.register_handler(LifecycleState.READY, handler)

    def on_start(self, handler: Handler) -> Handler:
        return self.register_handler(LifecycleState.RUNNING, handler)

    def on_stop(self, handler: Handler) -> Handler:
        return self.register_handler(LifecycleState.STOPPING, handler)

    def on_shutdown(self, handler: Handler) -> Handler:
        return self.register_handler(LifecycleState.STOPPED, handler)

    def on_error(self, handler: Handler) -> Handler:
        return self.register_handler(LifecycleState.FAILED, handler)

    def handler_counts(self) -> dict:
        return {state.value: len(handlers) for state, handlers in self._handlers.items() if handlers}

    # -- transitions --------------------------------------------------
    def transition(self, target: Any) -> LifecycleState:
        """Transition to *target*, running its handlers.

        Raises ``LifecycleError`` for illegal transitions and
        ``RuntimeError`` (framework) when a handler fails - in that case the
        lifecycle ends up in ``FAILED``.
        """
        resolved = self.coerce_state(target)
        if resolved is self._state:
            return self._state
        if resolved not in VALID_TRANSITIONS.get(self._state, ()):
            raise LifecycleError(
                message=f"Invalid lifecycle transition: {self._state.value} -> {resolved.value}",
                code="LIFECYCLE_INVALID_TRANSITION",
                stage=self._state.value,
                context={"from": self._state.value, "to": resolved.value},
            )

        previous = self._state
        self._previous_state = previous
        self._state = resolved
        self._history.append(resolved)

        try:
            self._run_handlers(resolved)
        except Exception as exc:  # noqa: BLE001 - deliberate: framework boundary
            error = self._record_failure(previous, resolved, exc)
            raise error from exc

        if resolved is LifecycleState.RUNNING and self._started_at is None:
            self._started_at = time.time()
        if resolved is LifecycleState.STOPPED:
            self._stopped_at = time.time()
        return self._state

    def fail(self, stage: Any, cause: Exception) -> BetrayerRuntimeError:
        """Force the lifecycle into FAILED and return the recorded error."""
        previous = self._state
        resolved_stage = self.coerce_state(stage)
        error = self._record_failure(previous, resolved_stage, cause)
        return error

    def _run_handlers(self, state: LifecycleState) -> None:
        for handler in list(self._handlers[state]):
            handler(state, self._application)

    def _record_failure(self, previous: LifecycleState, stage: LifecycleState, cause: Exception) -> BetrayerRuntimeError:
        state_at_failure = self._state
        self._previous_state = previous
        self._state = LifecycleState.FAILED
        self._history.append(LifecycleState.FAILED)
        error = BetrayerRuntimeError(
            message=f"Lifecycle stage '{stage.value}' failed: {cause}",
            code="LIFECYCLE_HANDLER_FAILED",
            component="lifecycle",
            stage=stage.value,
            cause=cause,
            context={
                "previous_state": previous.value,
                "state_at_failure": state_at_failure.value,
                "state": LifecycleState.FAILED.value,
            },
        )
        self._error = error
        for handler in list(self._handlers[LifecycleState.FAILED]):
            try:
                handler(LifecycleState.FAILED, self._application)
            except Exception:  # noqa: BLE001 - error handlers must never mask the original error
                pass
        return error

    # -- introspection ------------------------------------------------
    def uptime(self) -> Optional[float]:
        if self._started_at is None:
            return None
        end = self._stopped_at if self._stopped_at is not None else time.time()
        return round(end - self._started_at, 6)

    def describe(self) -> dict:
        """Machine readable lifecycle snapshot."""
        return {
            "name": self.name,
            "state": self._state.value,
            "previous_state": self._previous_state.value if self._previous_state else None,
            "history": [state.value for state in self._history],
            "started": self._started_at is not None,
            "stopped": self._stopped_at is not None,
            "uptime": self.uptime(),
            "failed": self._error is not None,
            "error": self._error.to_dict() if self._error is not None else None,
            "handlers": self.handler_counts(),
        }

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"<Lifecycle name={self.name!r} state={self._state.value}>"


__all__ = ["Lifecycle", "LifecycleState", "VALID_TRANSITIONS", "Handler"]
