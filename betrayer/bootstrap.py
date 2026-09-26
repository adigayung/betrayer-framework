"""Bootstrap orchestration for Betrayer.

Bootstrap is the deterministic entry sequence::

    START
      -> Bootstrap
      -> Environment detection
      -> Load configuration
      -> Dependency check      (extension point for future installers)
      -> Initialize runtime
      -> Initialize application
      -> READY                    (RUN / SHUTDOWN happen later)

Every stage is recorded with a status and a short detail string, so a
failed bootstrap tells an LLM *which* stage broke and *why*.
"""

from __future__ import annotations

import importlib
import time
from typing import Any, Callable, Optional

from betrayer.application import BetrayerApplication
from betrayer.core.config import Config
from betrayer.core.environment import Environment
from betrayer.core.exceptions import BootstrapError, BetrayerError
from betrayer.core.lifecycle import LifecycleState

__all__ = ["Bootstrap"]

# Modules that must be importable for the foundation to work.  This is the
# real dependency check stage - an empty placeholder would be a lie.
REQUIRED_MODULES = (
    "betrayer",
    "betrayer.application",
    "betrayer.bootstrap",
    "betrayer.core.config",
    "betrayer.core.environment",
    "betrayer.core.exceptions",
    "betrayer.core.lifecycle",
    "betrayer.core.registry",
    "betrayer.runtime.context",
    "betrayer.runtime.state",
    "betrayer.diagnostics.inspector",
    "betrayer.cli.main",
)


class Bootstrap:
    """Deterministic boot sequence for a :class:`BetrayerApplication`."""

    def __init__(
        self,
        application: Optional[BetrayerApplication] = None,
        *,
        name: str = "betrayer",
        config: Optional[Config] = None,
        environment: Optional[Environment] = None,
    ) -> None:
        self._application = application
        self._name = name
        self._config = config
        self._environment = environment
        self._stages: list[dict] = []
        self._completed = False
        self._extra_stages: list[tuple[str, Callable[[BetrayerApplication], Any]]] = []

    # ── extension point ──────────────────────────────────────────

    def add_stage(self, name: str, handler: Callable[[BetrayerApplication], Any]) -> "Bootstrap":
        """Register an extra stage (e.g. a future dependency installer).

        The handler is called with the application *before* the application
        is initialised, so it can still mutate configuration.  Adding a
        stage never requires changing ``Application`` itself.
        """
        self._extra_stages.append((name, handler))
        return self

    # ── inspection ───────────────────────────────────────────────

    @property
    def stages(self) -> list[dict]:
        return list(self._stages)

    @property
    def completed(self) -> bool:
        return self._completed

    @property
    def application(self) -> Optional[BetrayerApplication]:
        return self._application

    def report(self) -> dict:
        return {
            "completed": self._completed,
            "application": self._application.name if self._application else None,
            "state": self._application.state.value if self._application else None,
            "stages": self.stages,
        }

    # ── execution ────────────────────────────────────────────────

    def build(self) -> BetrayerApplication:
        """Run bootstrap + initialize and return the READY application."""
        app = self._application
        if app is None:
            app = BetrayerApplication(
                name=self._name,
                config=self._config,
                environment=self._environment,
            )
            self._application = app

        self._stages = []
        self._run_stage("environment", lambda: self._stage_environment(app))
        self._run_stage("configuration", lambda: self._stage_configuration(app))
        self._run_stage("dependencies", lambda: self._stage_dependencies(app))
        for name, handler in self._extra_stages:
            self._run_stage(name, lambda handler=handler: handler(app))
        self._run_stage("runtime", lambda: self._stage_runtime(app))
        self._run_stage("application", lambda: self._stage_application(app))
        self._completed = True
        return app

    # Backwards-compatible explicit name for the common case.
    def to_ready(self) -> BetrayerApplication:
        return self.build()

    def run(self) -> BetrayerApplication:
        """``build()`` then move the application to RUNNING."""
        app = self.build()
        app.run()
        return app

    # ── internals ────────────────────────────────────────────────

    def _run_stage(self, name: str, handler: Callable[[], str]) -> None:
        started = time.perf_counter()
        try:
            detail = handler() or ""
        except BetrayerError as exc:
            self._record(name, "fail", exc.message, started)
            raise
        except Exception as exc:  # wrap anything unexpected
            self._record(name, "fail", repr(exc), started)
            raise BootstrapError(
                message=f"Bootstrap stage '{name}' failed: {exc}",
                stage=name,
                cause=exc,
                code="BOOTSTRAP_STAGE_FAILED",
                context={"application": self._application.name if self._application else None},
            ) from exc
        self._record(name, "ok", detail, started)

    def _record(self, name: str, status: str, detail: str, started: float) -> None:
        self._stages.append(
            {
                "stage": name,
                "status": status,
                "detail": detail,
                "duration_ms": round((time.perf_counter() - started) * 1000, 3),
            }
        )

    def _stage_environment(self, app: BetrayerApplication) -> str:
        env = app.environment
        if env.project_root is None or not env.project_root.exists():
            raise BootstrapError(
                message="Project root does not exist",
                stage="environment",
                code="BOOTSTRAP_ENVIRONMENT_INVALID",
                context={"project_root": str(env.project_root)},
            )
        return f"{env.os_name} {env.os_release} | python {env.python_version} | mode={env.mode}"

    def _stage_configuration(self, app: BetrayerApplication) -> str:
        config = app.config
        config.load_env()
        if config.get("app.name") is None:
            config.ensure("app.name", app.name)
        config.finalise()
        return f"{len(config.keys(safe=True))} safe keys | finalised={config.is_finalised()}"

    def _stage_dependencies(self, app: BetrayerApplication) -> str:
        missing = []
        for module in REQUIRED_MODULES:
            try:
                importlib.import_module(module)
            except Exception as exc:  # pragma: no cover - defensive
                missing.append(f"{module} ({exc})")
        if missing:
            raise BootstrapError(
                message="Required modules could not be imported: " + ", ".join(missing),
                stage="dependencies",
                code="BOOTSTRAP_MISSING_DEPENDENCY",
                context={"missing": missing},
            )
        return f"{len(REQUIRED_MODULES)} modules importable"

    def _stage_runtime(self, app: BetrayerApplication) -> str:
        ctx = app.runtime_context
        status = ctx.status()
        return f"context bound to {status['application']} | state={status['lifecycle_state']}"

    def _stage_application(self, app: BetrayerApplication) -> str:
        if app.state is LifecycleState.CREATED:
            app.bootstrap()
        if app.state is LifecycleState.BOOTSTRAPPING:
            app.initialize()
        if app.state is LifecycleState.READY:
            app.ready()
        return f"application state={app.state.value}"
