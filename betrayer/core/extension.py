"""Extension system: extensions add capability without touching core.

An extension is *not* a module:

* module    - structural part of the application (``users``, ``orders``)
* extension - capability added to the framework/application
  (``admin-ui``, ``metrics-export``, ``task-queue``)

Every extension has a name, a version, metadata, dependency information and
optional hooks::

    class ExampleExtension(Extension):
        name = "example"
        version = "1.0.0"

        def register(self, context):      # installed into the registry
            ...

        def initialize(self, context):    # after Foundation bootstrap
            ...

        def shutdown(self, context):      # cleanup
            ...

Rules:
* deterministic: extensions run in registration order (shutdown reversed)
* enabled/disabled is explicit state, never an implicit responsibility
* dependency information names other extension names; unknown or circular
  dependencies are rejected
* a disabled extension is registered but never verified or initialized
* failing hooks raise :class:`~betrayer.core.exceptions.ExtensionError`
  carrying extension name, hook name and cause
* this is an architecture hook, not a plugin marketplace
"""

from __future__ import annotations

from typing import Any, Iterator, List, Optional, Tuple

from betrayer.core.exceptions import ExtensionError

__all__ = ["ExtensionState", "Extension", "ExtensionRegistry"]


class ExtensionState:
    """Explicit extension states - no boolean flags."""

    REGISTERED = "registered"
    DISABLED = "disabled"
    REGISTERING = "registering"
    VERIFYING = "verifying"
    INITIALIZING = "initializing"
    INITIALIZED = "initialized"
    SHUTTING_DOWN = "shutting_down"
    SHUTDOWN = "shutdown"
    FAILED = "failed"

    ALL: Tuple[str, ...] = (
        REGISTERED,
        DISABLED,
        REGISTERING,
        VERIFYING,
        INITIALIZING,
        INITIALIZED,
        SHUTTING_DOWN,
        SHUTDOWN,
        FAILED,
    )


class Extension:
    """Base class for extensions.

    ``enabled`` is a class level default that can be overridden per
    instance, so an application can ship an extension and turn it off by
    configuration without editing the extension itself.
    """

    name: str = ""
    version: str = "0.0.0"
    dependencies: Tuple[str, ...] = ()
    metadata: dict = {}
    enabled: bool = True

    def register(self, context: Any) -> None:
        """Install the extension: register components, providers, events."""

    def verify(self, context: Any) -> None:
        """Check preconditions (optional compatibility check)."""

    def initialize(self, context: Any) -> None:
        """Run after Foundation bootstrap."""

    def shutdown(self, context: Any) -> None:
        """Cleanup hook, runs in reverse registration order."""

    @classmethod
    def extension_name(cls) -> str:
        """Return the extension name (class attribute ``name``)."""
        return cls.name or cls.__name__.lower()

    def to_dict(self) -> dict:
        """Machine readable snapshot of the extension definition."""
        return {
            "name": self.extension_name(),
            "class": type(self).__name__,
            "version": self.version,
            "dependencies": list(self.dependencies),
            "metadata": dict(self.metadata),
            "enabled": bool(self.enabled),
        }

    describe = to_dict

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<{type(self).__name__} name={self.extension_name()!r}>"


class ExtensionRegistry:
    """Ordered, dependency aware registry of application extensions.

    The extension registry stores extension objects only; every other kind
    of component keeps using :class:`~betrayer.core.registry.Registry`.
    """

    def __init__(
        self,
        application: Any = None,
        *,
        registry: Any = None,
        container: Any = None,
        events: Any = None,
        name: str = "extensions",
    ) -> None:
        self.name = name
        self.application = application
        if registry is None and container is None and events is None:
            core = getattr(application, "core", None)
            registry = getattr(core, "registry", None)
            container = getattr(core, "container", None)
            events = getattr(core, "events", None)
        self.registry = registry
        self.container = container
        self.events = events
        self._extensions: dict[str, Extension] = {}
        self._states: dict[str, str] = {}

    # -- registration -------------------------------------------------
    def register(self, extension: Any, *, enabled: Optional[bool] = None) -> Extension:
        """Register ``extension`` (instance or class) and install it."""
        extension = self._as_extension(extension)
        name = extension.extension_name()
        if not name:
            raise ExtensionError(
                message="Extension must define a non-empty 'name'",
                code="EXTENSION_NAME_MISSING",
                context={"class": type(extension).__name__},
            )
        if name in self._extensions:
            raise ExtensionError(
                message=f"Extension already registered: {name}",
                code="EXTENSION_DUPLICATE",
                context={"extension": name, "available": self.names()},
            )
        if enabled is not None:
            extension.enabled = bool(enabled)
        self._extensions[name] = extension
        if not extension.enabled:
            self._states[name] = ExtensionState.DISABLED
            return extension
        self._states[name] = ExtensionState.REGISTERED
        self._call_hook(extension, "register", failure_code="EXTENSION_REGISTER_FAILED")
        return extension

    def _validate_dependencies(self, extension: Extension) -> None:
        name = extension.extension_name()
        for dependency in extension.dependencies:
            if dependency == name:
                raise ExtensionError(
                    message=f"Extension {name!r} depends on itself",
                    code="EXTENSION_DEPENDENCY_SELF",
                    context={"extension": name},
                )
            if dependency not in self._extensions:
                raise ExtensionError(
                    message=f"Unknown dependency {dependency!r} of extension {name!r}",
                    code="EXTENSION_DEPENDENCY_UNKNOWN",
                    context={"extension": name, "dependency": dependency},
                )
            if not self._extensions[dependency].enabled:
                raise ExtensionError(
                    message=(
                        f"Extension {name!r} requires disabled extension "
                        f"{dependency!r}"
                    ),
                    code="EXTENSION_DEPENDENCY_DISABLED",
                    context={"extension": name, "dependency": dependency},
                )

    def add(self, extension: Any, *, enabled: Optional[bool] = None) -> Extension:
        """Alias of :meth:`register`; ``register`` is the canonical name."""
        return self.register(extension, enabled=enabled)

    def unregister(self, name: str) -> Extension:
        """Remove an extension; returns the removed extension object."""
        extension = self._extensions.get(name)
        if extension is None:
            raise ExtensionError(
                message=f"Unknown extension: {name}",
                code="EXTENSION_NOT_FOUND",
                context={"extension": name, "available": self.names()},
            )
        self._extensions.pop(name, None)
        self._states.pop(name, None)
        return extension

    def enable(self, name: str, enabled: bool = True) -> Extension:
        """Enable/disable a registered extension explicitly."""
        extension = self.get(name)
        extension.enabled = bool(enabled)
        if not extension.enabled:
            self._states[name] = ExtensionState.DISABLED
        elif self._states[name] == ExtensionState.DISABLED:
            self._states[name] = ExtensionState.REGISTERED
        return extension

    def _as_extension(self, extension: Any) -> Extension:
        if isinstance(extension, type) and issubclass(extension, Extension):
            return extension()
        if isinstance(extension, Extension):
            return extension
        raise ExtensionError(
            message=(
                f"Expected an Extension instance or subclass, got {extension!r}"
            ),
            code="EXTENSION_INVALID",
            context={"value": repr(extension)},
        )

    def _call_hook(
        self,
        extension: Extension,
        hook: str,
        *,
        failure_code: str = "EXTENSION_REGISTER_FAILED",
    ) -> None:
        function = getattr(extension, hook, None)
        if not callable(function):
            raise ExtensionError(
                message=(
                    f"Extension {extension.extension_name()!r} has no {hook!r} hook"
                ),
                code="EXTENSION_HOOK_MISSING",
                context={"extension": extension.extension_name(), "hook": hook},
            )
        name = extension.extension_name()
        try:
            function(self._hook_context())
        except Exception as exc:
            self._states[name] = ExtensionState.FAILED
            raise ExtensionError(
                message=(
                    f"Extension {name!r} failed in '{hook}': "
                    f"{type(exc).__name__}: {exc}"
                ),
                code=failure_code,
                stage=hook,
                cause=exc,
                context={"extension": name, "hook": hook},
            ) from exc

    def _hook_context(self) -> Any:
        from betrayer.runtime.context import RuntimeContext

        application = self.application
        if application is not None:
            for attribute in ("runtime_context", "context"):
                candidate = getattr(application, attribute, None)
                if candidate is not None:
                    return candidate
        return RuntimeContext(
            application,
            registry=self.registry,
            state=None,
        )

    # -- dependency graph ---------------------------------------------
    def check_dependencies(self) -> dict:
        """Validate the extension graph: missing, disabled and cycles."""
        problems: List[dict] = []
        for name, extension in self._extensions.items():
            for dependency in extension.dependencies:
                if dependency == name:
                    problems.append(
                        {
                            "extension": name,
                            "dependency": dependency,
                            "reason": "self_dependency",
                        }
                    )
                elif dependency not in self._extensions:
                    problems.append(
                        {
                            "extension": name,
                            "dependency": dependency,
                            "reason": "unknown_dependency",
                        }
                    )
                elif not self._extensions[dependency].enabled:
                    problems.append(
                        {
                            "extension": name,
                            "dependency": dependency,
                            "reason": "disabled_dependency",
                        }
                    )
        for cycle in self._cycles():
            problems.append(
                {
                    "extension": cycle[0],
                    "dependency": cycle[-1],
                    "reason": "circular_dependency",
                    "chain": cycle,
                }
            )
        return {"ok": not problems, "problems": problems, "order": self.order()}

    def order(self) -> List[str]:
        """Enabled extension names in a dependency-first order."""
        order: List[str] = []
        visiting: List[str] = []
        visited: set[str] = set()

        def visit(name: str) -> None:
            if name in visited:
                return
            if name in visiting:
                chain = visiting[visiting.index(name):] + [name]
                raise ExtensionError(
                    message="Circular extension dependency: " + " -> ".join(chain),
                    code="EXTENSION_DEPENDENCY_CIRCULAR",
                    context={"extension": name, "chain": chain},
                )
            visiting.append(name)
            for dependency in self._extensions[name].dependencies:
                if dependency in self._extensions:
                    visit(dependency)
            visiting.pop()
            visited.add(name)
            order.append(name)

        for name, extension in self._extensions.items():
            if extension.enabled:
                visit(name)
        return order

    def _cycles(self) -> List[List[str]]:
        try:
            self.order()
        except ExtensionError as exc:
            chain = exc.context.get("chain")
            return [list(chain)] if chain else []
        return []

    # -- lifecycle ----------------------------------------------------
    def verify_all(self) -> List[str]:
        """Run ``verify`` on every enabled extension (registration order)."""
        verified: List[str] = []
        for name in self.order():
            extension = self._extensions[name]
            self._states[name] = ExtensionState.VERIFYING
            self._call_hook(extension, "verify", failure_code="EXTENSION_VERIFY_FAILED")
            self._states[name] = ExtensionState.REGISTERED
            verified.append(name)
        return verified

    def initialize_all(self) -> List[str]:
        """Run ``initialize`` on every enabled extension, dependency first."""
        initialized: List[str] = []
        for name in self.order():
            extension = self._extensions[name]
            self._validate_dependencies(extension)
            self._states[name] = ExtensionState.INITIALIZING
            self._call_hook(extension, "initialize", failure_code="EXTENSION_INITIALIZE_FAILED")
            self._states[name] = ExtensionState.INITIALIZED
            initialized.append(name)
        return initialized

    def shutdown_all(self) -> List[str]:
        """Run ``shutdown`` on every initialized extension, reverse order."""
        shut_down: List[str] = []
        for name in reversed(self.order()):
            extension = self._extensions[name]
            if self._states.get(name) != ExtensionState.INITIALIZED:
                continue
            self._states[name] = ExtensionState.SHUTTING_DOWN
            self._call_hook(extension, "shutdown", failure_code="EXTENSION_SHUTDOWN_FAILED")
            self._states[name] = ExtensionState.SHUTDOWN
            shut_down.append(name)
        return shut_down

    # -- introspection ------------------------------------------------
    def get(self, name: str) -> Extension:
        """Return an extension without triggering any hook."""
        extension = self._extensions.get(name)
        if extension is None:
            raise ExtensionError(
                message=f"Unknown extension: {name}",
                code="EXTENSION_NOT_FOUND",
                context={"extension": name, "available": self.names()},
            )
        return extension

    def has(self, name: str) -> bool:
        return name in self._extensions

    def names(self) -> List[str]:
        """Registered extension names, in registration order."""
        return list(self._extensions)

    def enabled(self) -> List[str]:
        """Names of extensions that are currently enabled."""
        return [name for name, extension in self._extensions.items() if extension.enabled]

    def state(self, name: str) -> str:
        """Current state of one extension."""
        self.get(name)
        return self._states[name]

    def describe(self) -> dict:
        """Machine readable snapshot of every extension (deterministic keys)."""
        return {
            "name": self.name,
            "count": len(self._extensions),
            "extensions": {
                name: {
                    **extension.to_dict(),
                    "state": self._states[name],
                    "order": index,
                }
                for index, (name, extension) in enumerate(self._extensions.items())
            },
            "enabled": self.enabled(),
            "order": [name for name in self.order()],
        }

    to_dict = describe
    inspect = describe

    def items(self) -> Iterator[Tuple[str, Extension]]:
        return iter(self._extensions.items())

    def __contains__(self, name: object) -> bool:
        return name in self._extensions

    def __iter__(self) -> Iterator[str]:
        return iter(self._extensions)

    def __len__(self) -> int:
        return len(self._extensions)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"ExtensionRegistry(name={self.name!r}, extensions={self.names()})"
