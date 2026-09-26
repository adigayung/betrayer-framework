"""Core architecture system: one wired home for the five Task 02 parts.

``CoreSystem`` does not replace anything from the foundation - it *composes*
what already exists so an LLM can answer "what does this application consist
of?" with a single introspection call::

    app.core.report() ->
        {
          "name": "betrayer.core",
          "registry":   {...},   # where everything is registered
          "container":  {...},   # services -> provider -> lifetime
          "modules":    {...},   # names, dependencies, states
          "extensions": {...},   # names, versions, states
          "events":     {...},   # event names + handlers
          "lifecycle":  {...},   # loop progress for module/extension hooks
        }

The system is instance scoped (no global singleton) and is created by
:class:`~betrayer.application.BetrayerApplication`, which exposes
``registry``, ``container``, ``modules``, ``extensions`` and ``events`` as
properties so application code and the CLI never have to dig into internals.

Lifecycle integration
---------------------
The loop itself lives in :mod:`betrayer.core.loop`; this class only owns the
state and the collaborators, so there is exactly one lifecycle and one
runtime context in the framework.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

from betrayer.core.container import Container
from betrayer.core.events import EventBus
from betrayer.core.exceptions import (
    BetrayerError,
    ExtensionError,
    LifecycleError,
    ModuleError,
)
from betrayer.core.extension import ExtensionRegistry
from betrayer.core.module import ModuleRegistry
from betrayer.core.registry import Registry

__all__ = ["CoreSystem", "LOOP_STAGES", "LOOP_STATES"]

#: Ordered lifecycle stages performed by ``CoreSystem.run_stage``.
LOOP_STAGES = (
    "register",
    "initialize",
    "ready",
    "start",
    "stop",
    "shutdown",
)

#: States of the module/extension loop.
LOOP_STATES = ("created", "registered", "initialized", "started", "stopped")


class CoreSystem:
    """Wired registry, container, module registry, extensions and events."""

    def __init__(
        self,
        name: str = "betrayer.core",
        *,
        application: Any = None,
        registry: Optional[Registry] = None,
        container: Optional[Container] = None,
        events: Optional[EventBus] = None,
    ) -> None:
        self.name = name
        self._application = application
        self.registry = registry if registry is not None else Registry(name=name)
        self.container = container if container is not None else Container(name=name)
        self.events = events if events is not None else EventBus(name=name)
        self.modules = ModuleRegistry(
            application=self._application,
            registry=self.registry,
            container=self.container,
            events=self.events,
            name=f"{name}.modules",
        )
        self.extensions = ExtensionRegistry(
            application=self._application,
            registry=self.registry,
            container=self.container,
            events=self.events,
            name=f"{name}.extensions",
        )
        self._stages: list[str] = []
        self._state = LOOP_STATES[0]
        self._failures: list[dict] = []
        self._applied_modules: list[str] = []
        self._applied_extensions: list[str] = []

    # -- application wiring -------------------------------------------
    @property
    def application(self) -> Any:
        return self._application

    def context(self) -> Any:
        """Runtime context handed to module/extension hooks."""
        return context_of(self._application)

    # -- collaborator helpers -----------------------------------------
    def module(self, name: str):
        return self.modules.get(name)

    def extension(self, name: str):
        return self.extensions.get(name)

    def services(self) -> list[str]:
        """Names of every service the container can resolve."""
        return self.container.names()

    def service(self, name: str) -> Any:
        return self.container.resolve(name)

    # -- lifecycle loop ------------------------------------------------
    def run_stage(self, stage: str, *, application: Any = None) -> dict:
        """Run one loop stage and return a machine readable report.

        ``stage`` is one of :data:`LOOP_STAGES`.  Repeating a stage is
        deterministic: already applied modules/extensions are skipped, which
        keeps a foundation lifecycle replay (``initialize`` then ``start``)
        from running user hooks twice.
        """
        if stage not in LOOP_STAGES:
            raise LifecycleError(
                message=f"Unknown loop stage: {stage}",
                code="LOOP_STAGE_UNKNOWN",
                component="lifecycle",
                stage=stage,
                context={"stage": stage, "available": list(LOOP_STAGES)},
            )
        if application is not None:
            self._application = application
        context = self.context()
        sections: list[dict] = []
        if stage in ("register", "initialize"):
            sections.append(self._apply("module", self.modules.ordered(), stage, context))
            sections.append(
                self._apply("extension", self.extensions.enabled(), stage, context)
            )
        elif stage in ("ready", "start", "stop", "shutdown"):
            sections.append(self._apply("module", self.modules.ordered(), stage, context))
            sections.append(
                self._apply("extension", self.extensions.enabled(), stage, context)
            )
        self._stages.append(stage)
        current = {"register": "registered", "initialize": "initialized", "start": "started", "stop": "stopped", "shutdown": "stopped"}
        if stage in current:
            self._state = current[stage]
        report = {
            "stage": stage,
            "state": self._state,
            "application": getattr(self._application, "name", None),
            "modules": sections[0] if sections else {"count": 0, "applied": [], "failed": []},
            "extensions": sections[1] if len(sections) > 1 else {"count": 0, "applied": [], "failed": []},
        }
        if stage not in ("register", "initialize"):
            self.events.emit(
                f"core.{stage}",
                {"stage": stage, "state": self._state, "report": report},
            )
        return report

    def run_lifecycle(self, *, application: Any = None) -> dict:
        """Apply every loop stage in foundation order."""
        reports = {}
        for stage in ("register", "initialize", "ready", "start"):
            reports[stage] = self.run_stage(stage, application=application)
        return {
            "name": self.name,
            "state": self._state,
            "stages": list(self._stages),
            "applied_modules": list(self._applied_modules),
            "applied_extensions": list(self._applied_extensions),
            "reports": reports,
            "failures": list(self._failures),
        }

    def shutdown(self) -> dict:
        """Run ``stop`` + ``shutdown`` hooks and deregister everything."""
        stop = self.run_stage("stop")
        shutdown = self.run_stage("shutdown")
        self._failures = list(self._failures)
        return {
            "stop": stop,
            "shutdown": shutdown,
            "state": self._state,
            "failures": list(self._failures),
        }

    def reset(self) -> None:
        """Forget modules, extensions and loop progress (services survive)."""
        self.modules.clear()
        self.extensions.clear()
        self._stages = []
        self._failures = []
        self._applied_modules = []
        self._applied_extensions = []
        self._state = LOOP_STATES[0]

    # -- hook application ----------------------------------------------
    def _apply(self, kind: str, units: Iterable[Any], stage: str, context: Any) -> dict:
        applied: list[str] = []
        failed: list[dict] = []
        for unit in units:
            if stage == "register":
                if unit.name in self._applied_modules or unit.name in self._applied_extensions:
                    continue
            try:
                if kind == "module":
                    handler = getattr(self.modules, f"call_{'register' if stage == 'register' else stage}", None)
                    if stage == "register":
                        self.modules.call_register(unit, context)
                    elif stage == "initialize":
                        self.modules.call_initialize(unit, context)
                    else:
                        self.modules.call_stage(unit, stage, context)
                    if stage == "register":
                        self._applied_modules.append(unit.name)
                else:
                    if stage == "register":
                        self.extensions.call_register(unit, context)
                        self._applied_extensions.append(unit.name)
                    elif stage == "initialize":
                        self.extensions.call_initialize(unit, context)
                    else:
                        self.extensions.call_stage(unit, stage, context)
                applied.append(unit.name)
            except BetrayerError as error:
                self._record_failure(kind, unit, stage, error)
                failed.append(self._failure_entry(unit, error))
            except Exception as error:  # unexpected hook failure
                wrapped = self._wrap(kind, unit, stage, error)
                self._record_failure(kind, unit, stage, wrapped)
                failed.append(self._failure_entry(unit, wrapped))
        return {"count": len(applied), "applied": applied, "failed": failed}

    def _wrap(self, kind: str, unit: Any, stage: str, error: Exception) -> BetrayerError:
        error_type = ModuleError if kind == "module" else ExtensionError
        return error_type(
            message=f"{kind} {unit.name!r} failed during {stage}: {type(error).__name__}: {error}",
            code="MODULE_HOOK_FAILED" if kind == "module" else "EXTENSION_HOOK_FAILED",
            stage=stage,
            component="modules" if kind == "module" else "extensions",
            cause=error,
            context={"name": unit.name, "type": type(unit).__name__},
        )

    def _record_failure(self, kind: str, unit: Any, stage: str, error: BetrayerError) -> None:
        self._failures.append(
            {
                "kind": kind,
                "name": unit.name,
                "stage": stage,
                "error": error.to_dict(),
            }
        )
        if hasattr(unit, "mark_failed"):
            unit.mark_failed(error)

    def _failure_entry(self, unit: Any, error: BetrayerError) -> dict:
        return {
            "name": unit.name,
            "type": type(unit).__name__,
            "state": getattr(unit, "state", None),
            "error": error.to_dict(),
        }

    # -- introspection -------------------------------------------------
    def stages(self) -> list[str]:
        """Loop stages already executed, in order."""
        return list(self._stages)

    @property
    def state(self) -> str:
        return self._state

    def failures(self) -> list[dict]:
        return [dict(entry) for entry in self._failures]

    def report(self) -> dict:
        return {
            "name": self.name,
            "application": getattr(self._application, "name", None),
            "state": self._state,
            "stages": list(self._stages),
            "registry": self.registry.describe_categories(),
            "container": self.container.describe(),
            "modules": self.modules.describe(),
            "extensions": self.extensions.describe(),
            "events": self.events.describe(),
            "loop": {
                "stages_available": list(LOOP_STAGES),
                "stages_applied": list(self._stages),
                "applied_modules": list(self._applied_modules),
                "applied_extensions": list(self._applied_extensions),
                "failures": list(self._failures),
            },
        }

    def describe(self) -> dict:
        return self.report()

    to_dict = report

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"CoreSystem(name={self.name!r}, state={self._state!r}, "
            f"modules={len(self.modules)}, extensions={len(self.extensions)}, "
            f"services={len(self.container)})"
        )


def context_of(application_or_system: Any) -> Any:
    """Return the runtime context for an application (or ``None``)."""
    if application_or_system is None:
        return None
    for attribute in ("runtime_context", "context"):
        context = getattr(application_or_system, attribute, None)
        if context is not None:
            return context
    return None
