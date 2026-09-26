"""Runtime context: the single place to ask "what is running".

A ``RuntimeContext`` is bound to one application instance.  It is
deliberately *not* a global singleton - two applications produce two
independent contexts, which keeps the framework testable.

Future subsystems (database, cache, queue, ...) receive the context and
pull the collaborators they need from it:

    ctx.config.get("database.host")
    ctx.registry.get("db")
    ctx.lifecycle.state
    ctx.environment.project_root
"""

from __future__ import annotations

from typing import Any, Optional

from betrayer.runtime.state import RuntimeState


class RuntimeContext:
    """Explicit access point for runtime information."""

    def __init__(
        self,
        application: Any = None,
        *,
        environment: Any = None,
        config: Any = None,
        lifecycle: Any = None,
        registry: Any = None,
        state: Optional[RuntimeState] = None,
    ) -> None:
        self._application = application
        self._environment = environment
        self._config = config
        self._lifecycle = lifecycle
        self._registry = registry
        self.state = state if state is not None else RuntimeState(name=getattr(application, "name", "betrayer"))

    # -- collaborators (live lookups when an application is attached) --
    @property
    def application(self) -> Any:
        return self._application

    @property
    def environment(self) -> Any:
        if self._environment is not None:
            return self._environment
        return getattr(self._application, "environment", None)

    @property
    def config(self) -> Any:
        if self._config is not None:
            return self._config
        return getattr(self._application, "config", None)

    @property
    def lifecycle(self) -> Any:
        if self._lifecycle is not None:
            return self._lifecycle
        return getattr(self._application, "lifecycle", None)

    @property
    def registry(self) -> Any:
        if self._registry is not None:
            return self._registry
        return getattr(self._application, "registry", None)

    @property
    def lifecycle_state(self) -> Any:
        lifecycle = self.lifecycle
        return getattr(lifecycle, "state", None)

    # ── core architecture (Task 02) ──────────────────────────────
    def _core_attr(self, name: str) -> Any:
        core = getattr(self.application, "core", None)
        return getattr(core, name, None) if core is not None else None

    @property
    def core(self) -> Any:
        """Composed core system, when the application owns one."""
        return getattr(self.application, "core", None)

    @property
    def container(self) -> Any:
        """Dependency injection container (service -> provider -> lifetime)."""
        return self._core_attr("container")

    @property
    def modules(self) -> Any:
        """Application module registry (structural units)."""
        return self._core_attr("modules")

    @property
    def extensions(self) -> Any:
        """Extension registry (capabilities, enabled/disabled state)."""
        return self._core_attr("extensions")

    @property
    def events(self) -> Any:
        """Synchronous event bus (on/emit/off)."""
        return self._core_attr("events")

    # -- snapshots ----------------------------------------------------
    def status(self) -> dict:
        """Compact, JSON friendly snapshot of what is running right now.

        Used by the bootstrap runtime stage and by ``betrayer status``; it
        is deliberately cheap - only live lookups, no introspection magic.
        """
        lifecycle = self.lifecycle
        registry = self.registry
        environment = self.environment
        config = self.config
        state = getattr(lifecycle, "state", None)
        keys = config.keys() if config is not None and hasattr(config, "keys") else []
        project_root = getattr(environment, "project_root", None)
        return {
            "application": getattr(self._application, "name", None),
            "lifecycle_state": getattr(state, "value", None),
            "previous_state": getattr(
                getattr(lifecycle, "previous_state", None), "value", None
            ),
            "ready": bool(getattr(lifecycle, "is_ready", False)),
            "failed": bool(getattr(lifecycle, "is_failed", False)),
            "environment": getattr(environment, "mode", None),
            "python_version": getattr(environment, "python_version", None),
            "project_root": str(project_root) if project_root is not None else None,
            "config_keys": len(keys),
            "registry": list(registry.list_all())
            if registry is not None and hasattr(registry, "list_all")
            else [],
            "runtime": self.state.to_dict(),
        }

    # -- convenience --------------------------------------------------
    def get(self, name: str, default: Any = None) -> Any:
        """Look up a registered component (``None`` when absent)."""
        registry = self.registry
        if registry is None or not hasattr(registry, "has"):
            return default
        return registry.get(name) if registry.has(name) else default

    def describe(self) -> dict:
        lifecycle = self.lifecycle
        registry = self.registry
        return {
            "application": getattr(self._application, "name", None),
            "state": getattr(getattr(lifecycle, "state", None), "value", None),
            "environment": getattr(getattr(self.environment, "mode", None), None),
            "registry": registry.list_all() if registry is not None and hasattr(registry, "list_all") else [],
            "runtime": self.state.to_dict(),
        }

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"<RuntimeContext application={getattr(self._application, 'name', None)!r}>"


__all__ = ["RuntimeContext"]
