"""Module system: modules are the structural units of an application.

A module is a small, explicit unit with a name, metadata, declared
dependencies and at most three hooks::

    class UsersModule(Module):
        name = "users"
        dependencies = ("storage",)     # module names, not import paths

        def register(self, context):    # discovery + provider registration
            context.container.singleton("user_service", build_user_service)

        def initialize(self, context):  # after Foundation bootstrap
            context.events.on("user.created", notify)

        def shutdown(self, context):    # reverse order, before stop
            ...

Module lifecycle is *not* a second lifecycle: modules use the Foundation
lifecycle stages (bootstrap / initialize / shutdown) and are driven by the
application through :class:`ModuleRegistry`.

Rules:
* explicit: a module never builds its own dependencies, it declares them
* deterministic: modules register, initialize and shut down in registration
  order (shutdown in reverse order)
* failing hooks raise :class:`~betrayer.core.exceptions.ModuleError`
  carrying module name, hook name and cause
* unknown or circular module dependencies are rejected
* metadata is a plain dict so an LLM can introspect it without importing
  application code
"""

from __future__ import annotations

from typing import Any, Iterator, List, Optional, Tuple

from betrayer.core.exceptions import ModuleError

__all__ = ["ModuleState", "Module", "ModuleRegistry"]


class ModuleState:
    """Explicit module states - no boolean flags."""

    REGISTERED = "registered"
    REGISTERING = "registering"
    INITIALIZING = "initializing"
    INITIALIZED = "initialized"
    SHUTTING_DOWN = "shutting_down"
    SHUTDOWN = "shutdown"
    FAILED = "failed"

    ALL: Tuple[str, ...] = (
        REGISTERED,
        REGISTERING,
        INITIALIZING,
        INITIALIZED,
        SHUTTING_DOWN,
        SHUTDOWN,
        FAILED,
    )


class Module:
    """Base class for application modules.

    Subclasses may override any hook; all of them are optional and default
    to a no-op so a module only contains what it really needs.
    """

    name: str = ""
    version: str = "0.0.0"
    dependencies: Tuple[str, ...] = ()
    metadata: dict = {}
    services: Tuple[str, ...] = ()

    def register(self, context: Any) -> None:
        """Declare the module: register providers, components and events."""

    def initialize(self, context: Any) -> None:
        """Run after Foundation bootstrap; may use already built services."""

    def shutdown(self, context: Any) -> None:
        """Release module resources; runs in reverse registration order."""

    @classmethod
    def module_name(cls) -> str:
        """Return the module name (class attribute ``name``)."""
        return cls.name or cls.__name__.lower()

    def to_dict(self) -> dict:
        """Machine readable snapshot of the module definition."""
        return {
            "name": self.module_name(),
            "class": type(self).__name__,
            "version": self.version,
            "dependencies": list(self.dependencies),
            "services": list(self.services),
            "metadata": dict(self.metadata),
        }

    describe = to_dict

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<{type(self).__name__} name={self.module_name()!r}>"


class ModuleRegistry:
    """Ordered, dependency aware registry of the application modules.

    The module registry is *not* a second component registry: it stores
    module objects only.  Services, extensions and event handlers keep using
    :class:`~betrayer.core.registry.Registry`, :class:`~betrayer.core.extension.ExtensionRegistry`
    and :class:`~betrayer.core.events.EventBus`.
    """

    def __init__(
        self,
        application: Any = None,
        *,
        registry: Any = None,
        container: Any = None,
        events: Any = None,
        name: str = "modules",
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
        self._modules: dict[str, Module] = {}
        self._states: dict[str, str] = {}

    # -- registration -------------------------------------------------
    def register(self, module: Any) -> Module:
        """Register ``module`` (instance or class) and call its ``register`` hook."""
        module = self._as_module(module)
        name = module.module_name()
        if not name:
            raise ModuleError(
                message="Module must define a non-empty 'name'",
                code="MODULE_NAME_MISSING",
                context={"class": type(module).__name__},
            )
        if name in self._modules:
            raise ModuleError(
                message=f"Module already registered: {name}",
                code="MODULE_DUPLICATE",
                context={"module": name, "available": self.names()},
            )
        self._modules[name] = module
        self._states[name] = ModuleState.REGISTERED
        # Validate declared dependencies for their side effect (unknown /
        # self dependency raises here); the *hook context* must be the runtime
        # context, never the module itself, so ``context.container`` works.
        self._validate_dependencies(module)
        self._call_hook(module, "register", None)
        return module

    def _validate_dependencies(self, module: Module) -> Module:
        name = module.module_name()
        for dependency in module.dependencies:
            if dependency == name:
                raise ModuleError(
                    message=f"Module {name!r} depends on itself",
                    code="MODULE_DEPENDENCY_SELF",
                    context={"module": name},
                )
            if dependency not in self._modules:
                raise ModuleError(
                    message=f"Unknown dependency {dependency!r} of module {name!r}",
                    code="MODULE_DEPENDENCY_UNKNOWN",
                    context={"module": name, "dependency": dependency},
                )
        return module

    def add(self, module: Any) -> Module:
        """Alias of :meth:`register`; ``register`` is the canonical name."""
        return self.register(module)

    def unregister(self, name: str) -> Module:
        """Remove a module; returns the removed module object."""
        module = self._modules.get(name)
        if module is None:
            raise ModuleError(
                message=f"Unknown module: {name}",
                code="MODULE_NOT_FOUND",
                context={"module": name, "available": self.names()},
            )
        self._modules.pop(name, None)
        self._states.pop(name, None)
        return module

    def _as_module(self, module: Any) -> Module:
        if isinstance(module, type) and issubclass(module, Module):
            return module()
        if isinstance(module, Module):
            return module
        raise ModuleError(
            message=(
                f"Expected a Module instance or subclass, got {module!r}"
            ),
            code="MODULE_INVALID",
            context={"value": repr(module)},
        )

    # -- lifecycle ----------------------------------------------------
    def check_dependencies(self) -> dict:
        """Validate the module graph: missing names and cycles."""
        problems: List[dict] = []
        for name, module in self._modules.items():
            for dependency in module.dependencies:
                if dependency == name:
                    problems.append(
                        {
                            "module": name,
                            "dependency": dependency,
                            "reason": "self_dependency",
                        }
                    )
                elif dependency not in self._modules:
                    problems.append(
                        {
                            "module": name,
                            "dependency": dependency,
                            "reason": "unknown_dependency",
                        }
                    )
        for cycle in self._cycles():
            problems.append(
                {"module": cycle[0], "dependency": cycle[-1], "reason": "circular_dependency", "chain": cycle}
            )
        return {"ok": not problems, "problems": problems, "order": self.order()}

    def order(self) -> List[str]:
        """Module names in a deterministic dependency-first order."""
        order: List[str] = []
        visiting: List[str] = []
        visited: set[str] = set()

        def visit(name: str) -> None:
            if name in visited:
                return
            if name in visiting:
                chain = visiting[visiting.index(name):] + [name]
                raise ModuleError(
                    message="Circular module dependency: " + " -> ".join(chain),
                    code="MODULE_DEPENDENCY_CIRCULAR",
                    context={"module": name, "chain": chain},
                )
            visiting.append(name)
            for dependency in self._modules[name].dependencies:
                if dependency in self._modules:
                    visit(dependency)
            visiting.pop()
            visited.add(name)
            order.append(name)

        for name in self._modules:
            visit(name)
        return order

    def _cycles(self) -> List[List[str]]:
        try:
            self.order()
        except ModuleError as exc:
            chain = exc.context.get("chain")
            return [list(chain)] if chain else []
        return []

    def initialize_all(self) -> List[str]:
        """Call ``initialize`` on every module in dependency-first order."""
        initialized: List[str] = []
        for name in self.order():
            module = self._modules[name]
            self._states[name] = ModuleState.INITIALIZING
            try:
                self._call_hook(module, "initialize", None, failure_code="MODULE_INITIALIZE_FAILED")
            except ModuleError:
                raise
            self._states[name] = ModuleState.INITIALIZED
            initialized.append(name)
        return initialized

    def shutdown_all(self) -> List[str]:
        """Call ``shutdown`` on every initialized module in reverse order."""
        shut_down: List[str] = []
        for name in reversed(self.order()):
            module = self._modules[name]
            state = self._states.get(name)
            if state not in (ModuleState.INITIALIZED, ModuleState.FAILED):
                continue
            self._states[name] = ModuleState.SHUTTING_DOWN
            self._call_hook(module, "shutdown", None, failure_code="MODULE_SHUTDOWN_FAILED")
            self._states[name] = ModuleState.SHUTDOWN
            shut_down.append(name)
        return shut_down

    def _call_hook(
        self,
        module: Module,
        hook: str,
        context: Any,
        *,
        failure_code: str = "MODULE_REGISTER_FAILED",
    ) -> None:
        function = getattr(module, hook, None)
        if not callable(function):
            raise ModuleError(
                message=f"Module {module.module_name()!r} has no {hook!r} hook",
                code="MODULE_HOOK_MISSING",
                context={"module": module.module_name(), "hook": hook},
            )
        name = module.module_name()
        if hook == "register":
            self._states[name] = ModuleState.REGISTERING
        try:
            function(self._hook_context(context))
        except Exception as exc:
            self._states[name] = ModuleState.FAILED
            raise ModuleError(
                message=(
                    f"Module {name!r} failed in '{hook}': "
                    f"{type(exc).__name__}: {exc}"
                ),
                code=failure_code,
                stage=hook,
                cause=exc,
                context={"module": name, "hook": hook},
            ) from exc
        if hook == "register":
            self._states[name] = ModuleState.REGISTERED

    def _hook_context(self, context: Any) -> Any:
        if context is not None:
            return context
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

    # -- introspection ------------------------------------------------
    def get(self, name: str) -> Module:
        """Return a module without triggering any hook."""
        module = self._modules.get(name)
        if module is None:
            raise ModuleError(
                message=f"Unknown module: {name}",
                code="MODULE_NOT_FOUND",
                context={"module": name, "available": self.names()},
            )
        return module

    def has(self, name: str) -> bool:
        return name in self._modules

    def names(self) -> List[str]:
        """Registered module names, in registration order."""
        return list(self._modules)

    def state(self, name: str) -> str:
        """Current state of one module."""
        self.get(name)
        return self._states[name]

    def shape(self) -> dict:
        """The ``module -> dependency`` graph an LLM can follow."""
        return {
            name: {
                "dependencies": list(module.dependencies),
                "services": list(module.services),
            }
            for name, module in self._modules.items()
        }

    def describe(self) -> dict:
        """Machine readable snapshot of every module (deterministic keys)."""
        return {
            "name": self.name,
            "count": len(self._modules),
            "modules": {
                name: {
                    **module.to_dict(),
                    "state": self._states[name],
                    "order": index,
                }
                for index, (name, module) in enumerate(self._modules.items())
            },
            "order": [name for name in self.order()],
        }

    to_dict = describe
    inspect = describe

    def items(self) -> Iterator[Tuple[str, Module]]:
        return iter(self._modules.items())

    def __contains__(self, name: object) -> bool:
        return name in self._modules

    def __iter__(self) -> Iterator[str]:
        return iter(self._modules)

    def __len__(self) -> int:
        return len(self._modules)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"ModuleRegistry(name={self.name!r}, modules={self.names()})"
