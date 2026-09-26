"""Foundation exception hierarchy for Betrayer.

Every framework error carries machine friendly context so an LLM can
diagnose a failure without reading a traceback:

* ``code``      - stable, greppable error code (e.g. ``CONFIG_KEY_MISSING``)
* ``component`` - subsystem that raised (``config``, ``lifecycle``, ...)
* ``stage``     - lifecycle/bootstrap stage when relevant
* ``message``   - short, single line explanation
* ``cause``     - the original exception, if this error wraps another one
* ``context``   - small dict with structured details

Error messages must stay short.  Extra data belongs in ``context``.
"""

from __future__ import annotations

from typing import Any, Optional

__all__ = [
    "BetrayerError",
    "BootstrapError",
    "ConfigurationError",
    "EnvironmentError",
    "DependencyError",
    "EventError",
    "ExtensionError",
    "LifecycleError",
    "ModuleError",
    "RegistryError",
    "RuntimeError",
]


class BetrayerError(Exception):
    """Base class for every error raised by Betrayer."""

    code: str = "BETRAYER_ERROR"
    component: str = "betrayer"

    def __init__(
        self,
        message: str = "",
        code: Optional[str] = None,
        component: Optional[str] = None,
        stage: Optional[str] = None,
        cause: Optional[BaseException] = None,
        context: Optional[dict] = None,
    ) -> None:
        self.message = str(message)
        self.code = code or type(self).code
        self.component = component or type(self).component
        self.stage = stage
        self.cause = cause
        self.context = dict(context or {})
        super().__init__(self.message)

    def __str__(self) -> str:
        parts = [f"[{self.code}]"]
        if self.component:
            parts.append(f"{self.component}:")
        parts.append(self.message)
        if self.stage:
            parts.append(f"(stage={self.stage})")
        if self.cause is not None:
            parts.append(f"(cause={type(self.cause).__name__}: {self.cause})")
        return " ".join(part for part in parts if part).strip()

    def to_dict(self) -> dict:
        """Machine readable representation (safe for JSON output)."""
        return {
            "code": self.code,
            "component": self.component,
            "stage": self.stage,
            "message": self.message,
            "cause": (
                None
                if self.cause is None
                else f"{type(self.cause).__name__}: {self.cause}"
            ),
            "context": dict(self.context),
        }


class BootstrapError(BetrayerError):
    """Raised when a bootstrap stage fails."""

    code = "BOOTSTRAP_ERROR"
    component = "bootstrap"


class ConfigurationError(BetrayerError):
    """Raised for invalid configuration access or mutation."""

    code = "CONFIGURATION_ERROR"
    component = "config"


class EnvironmentError(BetrayerError):
    """Raised when environment detection fails."""

    code = "ENVIRONMENT_ERROR"
    component = "environment"


class LifecycleError(BetrayerError):
    """Raised for invalid lifecycle transitions or handler registration."""

    code = "LIFECYCLE_ERROR"
    component = "lifecycle"


class RuntimeError(BetrayerError):
    """Raised for runtime/context failures.

    Note: this intentionally shadows the builtin ``RuntimeError`` inside
    the framework.  Use ``betrayer.core.exceptions.RuntimeError`` when a
    builtin ``RuntimeError`` could be ambiguous.
    """

    code = "RUNTIME_ERROR"
    component = "runtime"


class RegistryError(BetrayerError):
    """Raised for duplicate or missing registry components."""

    code = "REGISTRY_ERROR"
    component = "registry"


class DependencyError(BetrayerError):
    """Raised when a dependency cannot be registered, resolved or built."""

    code = "DEPENDENCY_ERROR"
    component = "container"


class ModuleError(BetrayerError):
    """Raised for invalid module registration, module dependencies or hooks."""

    code = "MODULE_ERROR"
    component = "modules"


class ExtensionError(BetrayerError):
    """Raised for invalid extension registration, dependencies or hooks."""

    code = "EXTENSION_ERROR"
    component = "extensions"


class EventError(BetrayerError):
    """Raised for invalid event names, handlers or failing subscribers."""

    code = "EVENT_ERROR"
    component = "events"
