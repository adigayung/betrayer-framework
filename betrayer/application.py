"""The central Betrayer application object.

``BetrayerApplication`` owns *structure*, never business logic.  It is
the composition root for the foundation:

* configuration  (``Config``)
* environment    (``Environment``)
* registry       (``Registry``)
* lifecycle      (``Lifecycle``)
* runtime state  (``RuntimeContext``)
* bootstrap/shutdown convenience methods

Everything else in the framework is discovered through this object, so an
LLM only needs one entry point to reason about a Betrayer project.
"""

from __future__ import annotations

from typing import Any, Optional

from betrayer.core.config import Config
from betrayer.core.environment import Environment
from betrayer.core.lifecycle import Lifecycle, LifecycleState
from betrayer.core.registry import Registry
from betrayer.core.system import CoreSystem
from betrayer.runtime.context import RuntimeContext

__all__ = ["BetrayerApplication"]

DEFAULT_NAME = "betrayer"


class BetrayerApplication:
    """Composition root of a Betrayer run."""

    def __init__(
        self,
        name: str = DEFAULT_NAME,
        *,
        config: Optional[Config] = None,
        environment: Optional[Environment] = None,
        registry: Optional[Registry] = None,
    ) -> None:
        self.name = name
        if config is None:
            config = Config(defaults={"app.name": name, "app.debug": False})
        else:
            config.ensure("app.name", name)
        if environment is None:
            environment = Environment.detect()
        self._config = config
        self._environment = environment
        self._registry = registry if registry is not None else Registry(name=f"{name}.registry")
        self._lifecycle = Lifecycle(name=name, application=self)
        self._runtime_context = RuntimeContext(application=self)
        self._core = CoreSystem(
            f"{self.name}.core",
            registry=self._registry,
            application=self,
        )

    # ── collaborators ────────────────────────────────────────────

    @property
    def config(self) -> Config:
        return self._config

    @property
    def environment(self) -> Environment:
        return self._environment

    @property
    def registry(self) -> Registry:
        return self._registry

    @property
    def lifecycle(self) -> Lifecycle:
        return self._lifecycle

    @property
    def runtime_context(self) -> RuntimeContext:
        return self._runtime_context

    # ── state ────────────────────────────────────────────────────

    @property
    def state(self) -> LifecycleState:
        return self._lifecycle.state

    @property
    def previous_state(self) -> Optional[LifecycleState]:
        return self._lifecycle.previous_state

    def is_ready(self) -> bool:
        return self._lifecycle.state in (LifecycleState.READY, LifecycleState.RUNNING)

    # ── lifecycle steps (deterministic, always explicit) ─────────

    def bootstrap(self) -> "BetrayerApplication":
        """CREATED -> BOOTSTRAPPING."""
        self._lifecycle.transition(LifecycleState.BOOTSTRAPPING)
        return self

    def initialize(self) -> "BetrayerApplication":
        """BOOTSTRAPPING -> READY."""
        self._lifecycle.transition(LifecycleState.READY)
        return self

    def ready(self) -> "BetrayerApplication":
        """Ensure READY; a no-op when the application is already READY."""
        if self._lifecycle.state is not LifecycleState.READY:
            self._lifecycle.transition(LifecycleState.READY)
        return self

    def start(self) -> "BetrayerApplication":
        """READY -> RUNNING."""
        self._lifecycle.transition(LifecycleState.RUNNING)
        return self

    def stop(self) -> "BetrayerApplication":
        """RUNNING -> STOPPING."""
        self._lifecycle.transition(LifecycleState.STOPPING)
        return self

    def shutdown(self) -> "BetrayerApplication":
        """STOPPING -> STOPPED."""
        self._lifecycle.transition(LifecycleState.STOPPED)
        return self

    def run(self) -> "BetrayerApplication":
        """Bring the application to RUNNING, whatever the entry state."""
        state = self._lifecycle.state
        if state is LifecycleState.CREATED:
            self.bootstrap()
            state = self._lifecycle.state
        if state is LifecycleState.BOOTSTRAPPING:
            self.initialize()
            state = self._lifecycle.state
        if state is LifecycleState.READY:
            self.start()
        return self

    # ── hooks for subsystems ─────────────────────────────────────

    def on(self, state: LifecycleState, handler: Any) -> Any:
        """Register a lifecycle handler (``handler(state, application)``)."""
        return self._lifecycle.register_handler(state, handler)

    # ── introspection ────────────────────────────────────────────

    def inspect(self) -> dict:
        """Full read-only snapshot; see :class:`~betrayer.diagnostics.inspector.Inspector`."""
        from betrayer.diagnostics.inspector import Inspector

        return Inspector(self).inspect()

    def status(self) -> dict:
        from betrayer.diagnostics.inspector import Inspector

        return Inspector(self).status()

    # ── core architecture (Task 02) ──────────────────────────────
    @property
    def core(self) -> CoreSystem:
        """Composed core system (container, modules, extensions, events)."""
        return self._core

    @property
    def container(self) -> Any:
        """Dependency injection container owned by the core system."""
        return self._core.container

    @property
    def modules(self) -> Any:
        """Application module registry owned by the core system."""
        return self._core.modules

    @property
    def extensions(self) -> Any:
        """Extension registry owned by the core system."""
        return self._core.extensions

    @property
    def events(self) -> Any:
        """Event bus owned by the core system (synchronous, deterministic)."""
        return self._core.events

    def to_dict(self) -> dict:
        """Compact, JSON-serialisable description of the application."""
        return {
            "name": self.name,
            "state": self.state.value,
            "previous_state": None if self.previous_state is None else self.previous_state.value,
            "environment": self._environment.mode,
            "project_root": str(self._environment.project_root),
            "components": self._registry.list_all(),
            "core": self._core.report(),
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<BetrayerApplication name={self.name!r} state={self.state.value!r}>"
