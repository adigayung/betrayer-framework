"""Diagnostics: read-only inspection of a Betrayer application.

Why this module exists
----------------------
AETHER (or any other LLM coding agent) needs a *single* deterministic
place to ask "what is the state of this framework right now?".  That
place is :class:`Inspector`.

Rules enforced here (mirrored in ``betrayer/ai/ARCHITECTURE.md``):

* The inspector **never mutates** the application it inspects.  The
  ``doctor`` check drives a throwaway *probe* application instead.
* Every public method returns plain ``dict``/``list``/``str``/``bool``
  values, so results can be dumped as JSON and read by an LLM.
* ``doctor()`` performs real checks (imports, lifecycle transitions on a
  probe application), never heuristic guesses.
* Secrets are always masked: the inspector hands out
  ``Config.safe_data()``, never ``Config.data()``.

Public API (stable for this architecture version)::

    Inspector(app).info()            # identity / versions / paths
    Inspector(app).environment()     # Environment.to_dict()
    Inspector(app).config()          # safe (masked) configuration
    Inspector(app).status()          # lifecycle + registry status
    Inspector(app).lifecycle_info()  # Lifecycle.describe()
    Inspector(app).runtime_info()    # RuntimeContext.status()
    Inspector(app).inspect()         # everything above, one dict
    Inspector(app).doctor()          # foundation health report
"""

from __future__ import annotations

import importlib
import platform
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from betrayer.core.config import Config, is_secret_key
from betrayer.core.environment import Environment
from betrayer.core.lifecycle import Lifecycle, LifecycleState
from betrayer.core.meta import (
    ARCHITECTURE_VERSION,
    FOUNDATION_VERSION,
    FRAMEWORK_NAME,
    __version__,
)

#: Modules that must import cleanly for the foundation to be sound.
FOUNDATION_MODULES: tuple = (
    "betrayer",
    "betrayer.application",
    "betrayer.bootstrap",
    "betrayer.core",
    "betrayer.core.config",
    "betrayer.core.environment",
    "betrayer.core.exceptions",
    "betrayer.core.lifecycle",
    "betrayer.core.meta",
    "betrayer.core.registry",
    "betrayer.runtime",
    "betrayer.runtime.context",
    "betrayer.runtime.state",
    "betrayer.diagnostics",
    "betrayer.diagnostics.inspector",
    "betrayer.cli",
    "betrayer.cli.main",
)

#: Minimum interpreter supported by the foundation.
MINIMUM_PYTHON: tuple = (3, 9)

#: Deterministic ``doctor`` check order.
DOCTOR_CHECK_NAMES: tuple = (
    "Python",
    "Environment",
    "Configuration",
    "Package imports",
    "Application lifecycle",
    "Runtime state",
)

OK: str = "ok"
FAIL: str = "fail"


class Inspector:
    """Read-only diagnostics facade over an application (or bare environment).

    All collaborators are optional so an inspector can be built around a
    free standing ``Environment``/``Config`` for tests, but in normal use
    it is constructed with a single application::

        Inspector(application)
    """

    def __init__(
        self,
        application: Any = None,
        *,
        environment: Optional[Environment] = None,
        config: Optional[Config] = None,
        lifecycle: Optional[Lifecycle] = None,
        registry: Any = None,
    ) -> None:
        self._application = application
        self._environment = environment
        self._config = config
        self._lifecycle = lifecycle
        self._registry = registry

    # -- collaborators (live lookups when an application is attached) --
    @property
    def application(self) -> Any:
        return self._application

    @property
    def name(self) -> Optional[str]:
        name = getattr(self._application, "name", None)
        return name if name else None

    def _resolve_environment(self) -> Environment:
        environment = self._environment
        if environment is None:
            environment = getattr(self._application, "environment", None)
        if environment is None:
            environment = Environment.detect()
        return environment

    def _resolve_config(self) -> Optional[Config]:
        config = self._config
        if config is None:
            config = getattr(self._application, "config", None)
        return config

    def _resolve_lifecycle(self) -> Optional[Lifecycle]:
        lifecycle = self._lifecycle
        if lifecycle is None:
            lifecycle = getattr(self._application, "lifecycle", None)
        return lifecycle

    def _resolve_registry(self) -> Any:
        registry = self._registry
        if registry is None:
            registry = getattr(self._application, "registry", None)
        return registry

    # -- snapshots -----------------------------------------------------
    def info(self) -> dict:
        """Framework identity, versions and paths (safe to print)."""
        environment = self._resolve_environment()
        return {
            "framework": FRAMEWORK_NAME,
            "version": __version__,
            "foundation_version": FOUNDATION_VERSION,
            "architecture_version": ARCHITECTURE_VERSION,
            "python": environment.python_version,
            "python_implementation": environment.python_implementation,
            "os": environment.os_name,
            "os_release": environment.os_release,
            "architecture": environment.architecture,
            "environment": environment.mode,
            "shell": environment.shell,
            "executable": environment.executable,
            "project_root": str(environment.project_root),
            "cwd": str(environment.cwd),
            "application": self.name,
            "state": self._state_value(),
        }

    def environment(self) -> dict:
        """Full environment snapshot (``Environment.to_dict()``)."""
        return self._resolve_environment().to_dict()

    def config(self) -> dict:
        """Safe (secret masked) configuration; never raw values."""
        config = self._resolve_config()
        if config is None:
            return {}
        if hasattr(config, "safe_data"):
            return config.safe_data()
        return {}

    def lifecycle_info(self) -> dict:
        """Lifecycle snapshot (``Lifecycle.describe()`` when available)."""
        lifecycle = self._resolve_lifecycle()
        if lifecycle is None:
            return {
                "name": None,
                "state": None,
                "previous_state": None,
                "history": [],
                "failed": False,
                "error": None,
                "handlers": {},
            }
        if hasattr(lifecycle, "describe"):
            return lifecycle.describe()
        state = getattr(lifecycle, "state", None)
        return {
            "name": getattr(lifecycle, "name", None),
            "state": getattr(state, "value", None),
            "previous_state": None,
            "history": [],
            "failed": bool(getattr(lifecycle, "is_failed", False)),
            "error": None,
            "handlers": {},
        }

    def registry_info(self) -> dict:
        """Registered components (names + kinds)."""
        registry = self._resolve_registry()
        components: List[str] = []
        metadata: Dict[str, Any] = {}
        if registry is not None:
            if hasattr(registry, "list_all"):
                components = list(registry.list_all())
            elif hasattr(registry, "names"):
                components = list(registry.names())
            if hasattr(registry, "metadata"):
                try:
                    metadata = registry.metadata()
                except Exception:  # pragma: no cover - defensive
                    metadata = {}
        return {
            "components": components,
            "count": len(components),
            "metadata": metadata,
        }

    def runtime_info(self) -> Optional[dict]:
        """Runtime context snapshot, or ``None`` when detached."""
        application = self._application
        if application is None:
            return None
        context = getattr(application, "runtime_context", None)
        if context is None or not hasattr(context, "status"):
            return None
        return context.status()

    def status(self) -> dict:
        """Lifecycle/registry status used by ``python -m betrayer status``."""
        lifecycle = self.lifecycle_info()
        registry = self.registry_info()
        error = lifecycle.get("error") or None
        failed_stage = None
        if isinstance(error, dict):
            failed_stage = error.get("stage")
        if failed_stage is None:
            failed_stage = getattr(self._resolve_lifecycle(), "failed_stage", None)
        return {
            "framework": FRAMEWORK_NAME,
            "version": __version__,
            "application": self.name,
            "application_type": type(self._application).__name__ if self._application else None,
            "state": lifecycle.get("state"),
            "previous_state": lifecycle.get("previous_state"),
            "ready": lifecycle.get("state") in ("ready", "running"),
            "running": lifecycle.get("state") == "running",
            "failed": bool(lifecycle.get("failed")),
            "failed_stage": failed_stage,
            "error": error,
            "history": list(lifecycle.get("history") or []),
            "handlers": lifecycle.get("handlers") or {},
            "components": list(registry["components"]),
            "environment": self._resolve_environment().mode,
            "project_root": str(self._resolve_environment().project_root),
            "runtime": self.runtime_info(),
        }

    def inspect(self) -> dict:
        """Everything the inspector knows, in one JSON friendly dict."""
        environment = self._resolve_environment()
        return {
            "framework": {
                "name": FRAMEWORK_NAME,
                "version": __version__,
                "foundation_version": FOUNDATION_VERSION,
                "architecture_version": ARCHITECTURE_VERSION,
                "python_version": environment.python_version,
                "python_implementation": environment.python_implementation,
                "os_name": environment.os_name,
                "architecture": environment.architecture,
                "is_windows": environment.is_windows,
            },
            "environment": environment.to_dict(),
            "configuration": self.config(),
            "lifecycle": self.lifecycle_info(),
            "registry": self.registry_info(),
            "application": {
                "name": self.name,
                "type": type(self._application).__name__ if self._application else None,
                "state": self._state_value(),
            },
            "runtime": self.runtime_info(),
        }

    # -- doctor --------------------------------------------------------
    def doctor(self) -> dict:
        """Run real foundation checks and return a report.

        Every check returns ``{"name", "status", "reason", "suggestion",
        "detail"}`` with ``status`` in ``{"ok", "fail"}``.
        """
        checks = [
            self._check("Python", self._check_python),
            self._check("Environment", self._check_environment),
            self._check("Configuration", self._check_configuration),
            self._check("Package imports", self._check_imports),
            self._check("Application lifecycle", self._check_lifecycle),
            self._check("Runtime state", self._check_runtime_state),
        ]
        ok = all(check["status"] == OK for check in checks)
        passed = sum(1 for check in checks if check["status"] == OK)
        return {
            "framework": FRAMEWORK_NAME,
            "version": __version__,
            "ok": ok,
            "status": "pass" if ok else "fail",
            "checks": checks,
            "summary": f"{passed}/{len(checks)} checks passed",
        }

    def _check(self, name: str, checker: Callable[[], dict]) -> dict:
        try:
            result = checker()
        except Exception as exc:  # pragma: no cover - guard rail
            return self._result(
                name,
                FAIL,
                reason=f"{type(exc).__name__}: {exc}",
                suggestion="inspect the component manually, then re-run 'python -m betrayer doctor'",
            )
        result["name"] = name
        return result

    @staticmethod
    def _result(
        name: str,
        status: str,
        reason: str = "",
        suggestion: str = "",
        detail: str = "",
    ) -> dict:
        return {
            "name": name,
            "status": status,
            "reason": reason,
            "suggestion": suggestion,
            "detail": detail,
        }

    # -- individual checks --------------------------------------------
    def _check_python(self) -> dict:
        current = sys.version_info[:3]
        detail = (
            f"{platform.python_version()} ({platform.python_implementation()}) "
            f"on {platform.system()} {platform.release()}"
        )
        if current < MINIMUM_PYTHON:
            required = ".".join(str(part) for part in MINIMUM_PYTHON)
            return self._result(
                "Python",
                FAIL,
                reason=f"python {platform.python_version()} < required {required}",
                suggestion=f"use Python {required}+ (see betrayer/ai/ENVIRONMENT.md)",
            )
        return self._result("Python", OK, detail=detail)

    def _check_environment(self) -> dict:
        environment = self._resolve_environment()
        problems: List[str] = []
        if not environment.python_version:
            problems.append("python_version is empty")
        if not environment.os_name:
            problems.append("os_name is empty")
        root = Path(environment.project_root)
        if not root.is_dir():
            problems.append(f"project_root does not exist: {root}")
        if problems:
            return self._result(
                "Environment",
                FAIL,
                reason="; ".join(problems),
                suggestion="re-run environment detection; see betrayer/ai/ENVIRONMENT.md",
            )
        detail = (
            f"{environment.os_name} {environment.os_release} {environment.architecture} | "
            f"mode={environment.mode} | python={environment.python_version} | root={root}"
        )
        return self._result("Environment", OK, detail=detail)

    def _check_configuration(self) -> dict:
        config = self._resolve_config()
        if config is None:
            return self._result(
                "Configuration",
                FAIL,
                reason="configuration is unavailable (no application bound)",
                suggestion="build an application with Bootstrap before running doctor",
            )
        raw = config.data() if hasattr(config, "data") else {}
        safe = self.config()
        leaked = [
            key
            for key, value in raw.items()
            if is_secret_key(key) and str(value) and str(safe.get(key, "")) == str(value)
        ]
        if leaked:
            return self._result(
                "Configuration",
                FAIL,
                reason=f"secret values are not masked: {', '.join(sorted(leaked))}",
                suggestion="check Config.safe_data() masking in betrayer/core/config.py",
            )
        finalised = bool(getattr(config, "is_finalised", False))
        return self._result(
            "Configuration",
            OK,
            detail=f"{len(raw)} keys, secrets masked, finalised={finalised}",
        )

    def _check_imports(self) -> dict:
        failures: List[str] = []
        for module in FOUNDATION_MODULES:
            try:
                importlib.import_module(module)
            except Exception as exc:
                failures.append(f"{module}: {type(exc).__name__}: {exc}")
        if failures:
            return self._result(
                "Package imports",
                FAIL,
                reason="; ".join(failures),
                suggestion="look for circular imports, then run 'python -m betrayer validate'",
            )
        return self._result(
            "Package imports",
            OK,
            detail=f"{len(FOUNDATION_MODULES)} foundation modules imported",
        )

    def _check_lifecycle(self) -> dict:
        from betrayer.application import BetrayerApplication

        try:
            probe = BetrayerApplication(name="doctor-probe")
            probe.bootstrap()
            probe.initialize()
            probe.ready()
            probe.start()
            probe.stop()
            probe.shutdown()
        except Exception as exc:
            return self._result(
                "Application lifecycle",
                FAIL,
                reason=f"{type(exc).__name__}: {exc}",
                suggestion="run 'python -m betrayer validate' and inspect the lifecycle history",
            )
        final = getattr(probe.state, "value", None)
        if final != LifecycleState.STOPPED.value:
            return self._result(
                "Application lifecycle",
                FAIL,
                reason=f"probe ended in state {final!r}, expected {LifecycleState.STOPPED.value!r}",
                suggestion="check VALID_TRANSITIONS in betrayer/core/lifecycle.py",
            )
        history = " -> ".join(
            str(getattr(state, "value", state)) for state in probe.lifecycle.history
        )
        return self._result(
            "Application lifecycle",
            OK,
            detail=f"probe transitioned {history}",
        )

    def _check_runtime_state(self) -> dict:
        from betrayer.application import BetrayerApplication

        first = BetrayerApplication(name="runtime-probe-a")
        second = BetrayerApplication(name="runtime-probe-b")
        if first.runtime_context is second.runtime_context:
            return self._result(
                "Runtime state",
                FAIL,
                reason="runtime context is shared between applications (global singleton)",
                suggestion="RuntimeContext must be per application; see betrayer/runtime/context.py",
            )
        runtime = first.runtime_context
        if not hasattr(runtime, "status"):
            return self._result(
                "Runtime state",
                FAIL,
                reason="RuntimeContext has no status() snapshot method",
                suggestion="restore RuntimeContext.status() in betrayer/runtime/context.py",
            )
        snapshot = runtime.status()
        if not isinstance(snapshot, dict) or "lifecycle_state" not in snapshot:
            return self._result(
                "Runtime state",
                FAIL,
                reason="RuntimeContext.status() did not return a lifecycle snapshot",
                suggestion="check RuntimeContext.status() in betrayer/runtime/context.py",
            )
        bound = self._application is not None
        return self._result(
            "Runtime state",
            OK,
            detail=(
                f"independent contexts | probe state={snapshot['lifecycle_state']} | "
                f"application bound={bound}"
            ),
        )

    # -- helpers -------------------------------------------------------
    def _state_value(self) -> Optional[str]:
        lifecycle = self._resolve_lifecycle()
        state = getattr(lifecycle, "state", None)
        if state is None:
            return None
        return getattr(state, "value", state)


__all__ = ["Inspector", "DOCTOR_CHECK_NAMES", "FOUNDATION_MODULES", "MINIMUM_PYTHON"]
