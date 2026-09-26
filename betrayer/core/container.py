"""Explicit dependency injection container.

The container answers one question in a traceable way::

    service -> provider -> lifetime

It is not a service locator with hidden magic: a service only exists after
somebody registered it, and a provider is only invoked when a dependency is
resolved.  Two concepts are kept apart on purpose:

* **container registration** - named providers, factories and instances
  (``container.singleton(...)``, ``container.resolve(...)``)
* **registry registration** - named components for discovery
  (``registry.register(...)``, ``registry.list_services()``)

Rules:
* deterministic: providers are kept in registration order
* duplicate names raise :class:`DependencyError` unless ``replace=True``
* unknown or ambiguous names raise :class:`DependencyError`
* circular dependencies are detected and rejected
* lifetimes: ``singleton`` (build once and cache), ``transient`` (build on
  every resolve), ``instance`` (registered object, singleton by definition)
* no global mutable state - one container belongs to one application
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

from betrayer.core.exceptions import DependencyError

__all__ = ["LIFETIMES", "SINGLETON", "TRANSIENT", "INSTANCE", "Provider", "Container"]

SINGLETON = "singleton"
TRANSIENT = "transient"
INSTANCE = "instance"
LIFETIMES: Tuple[str, ...] = (SINGLETON, TRANSIENT, INSTANCE)


class Provider:
    """A named way to obtain one service: provider, lifetime, dependencies."""

    __slots__ = (
        "name",
        "provider",
        "lifetime",
        "dependencies",
        "owner",
        "instance",
        "built",
        "resolution_count",
    )

    def __init__(
        self,
        name: str,
        provider: Any,
        *,
        lifetime: str = SINGLETON,
        dependencies: Tuple[str, ...] = (),
        owner: str = "",
        instance: Any = None,
    ) -> None:
        self.name = name
        self.provider = provider
        self.lifetime = lifetime
        self.dependencies = tuple(dependencies)
        self.owner = owner
        self.instance = instance
        self.built = lifetime == INSTANCE
        self.resolution_count = 0

    @property
    def provider_name(self) -> str:
        """Stable, LLM readable name of the provider callable."""
        target = self.provider
        if target is None:
            return f"{type(self.instance).__name__} (instance)"
        module = getattr(target, "__module__", "")
        qualname = getattr(target, "__qualname__", None) or getattr(
            target, "__name__", type(target).__name__
        )
        return f"{module}.{qualname}" if module and module != "__main__" else str(qualname)

    def to_dict(self) -> dict:
        """Machine readable snapshot of this provider."""
        return {
            "name": self.name,
            "provider": self.provider_name,
            "lifetime": self.lifetime,
            "dependencies": list(self.dependencies),
            "owner": self.owner,
            "resolved": self.built,
            "resolution_count": self.resolution_count,
        }

    describe = to_dict

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<Provider {self.name!r} lifetime={self.lifetime} "
            f"dependencies={list(self.dependencies)}>"
        )


class Container:
    """Instance scoped dependency injection container."""

    def __init__(self, name: str = "container") -> None:
        self.name = name
        self._providers: Dict[str, Provider] = {}
        self._resolve_stack: List[str] = []

    # -- registration -------------------------------------------------
    def singleton(
        self,
        name: str,
        provider: Any,
        *,
        depends_on: Tuple[str, ...] = (),
        owner: str = "",
        replace: bool = False,
    ) -> Provider:
        """Build the service once, then reuse the same object."""
        return self._add(name, provider, SINGLETON, depends_on, owner, replace)

    def transient(
        self,
        name: str,
        provider: Any,
        *,
        depends_on: Tuple[str, ...] = (),
        owner: str = "",
        replace: bool = False,
    ) -> Provider:
        """Build a new object on every resolve."""
        return self._add(name, provider, TRANSIENT, depends_on, owner, replace)

    def instance(
        self,
        name: str,
        value: Any,
        *,
        owner: str = "",
        replace: bool = False,
    ) -> Provider:
        """Register an already built object (singleton by definition)."""
        return self._add(
            name, None, INSTANCE, (), owner, replace, instance=value
        )

    def factory(
        self,
        name: str,
        factory: Callable[..., Any],
        *,
        lifetime: str = SINGLETON,
        depends_on: Tuple[str, ...] = (),
        owner: str = "",
        replace: bool = False,
    ) -> Provider:
        """Register a factory callable; ``lifetime`` defaults to singleton."""
        return self._add(name, factory, lifetime, depends_on, owner, replace)

    def provider(
        self,
        name: str,
        provider: Any,
        *,
        lifetime: str = SINGLETON,
        depends_on: Tuple[str, ...] = (),
        owner: str = "",
        replace: bool = False,
    ) -> Provider:
        """Register a provider callable or class (class = called when built)."""
        return self._add(name, provider, lifetime, depends_on, owner, replace)

    def _add(
        self,
        name: str,
        provider: Any,
        lifetime: str,
        depends_on: Tuple[str, ...],
        owner: str,
        replace: bool,
        *,
        instance: Any = None,
    ) -> Provider:
        if not isinstance(name, str) or not name:
            raise DependencyError(
                message=f"Service name must be a non-empty string, got {name!r}",
                code="DEPENDENCY_NAME_INVALID",
                context={"service": name},
            )
        if lifetime not in LIFETIMES:
            raise DependencyError(
                message=f"Unknown lifetime {lifetime!r} for {name!r}",
                code="DEPENDENCY_LIFETIME_UNKNOWN",
                context={"service": name, "lifetime": lifetime, "available": list(LIFETIMES)},
            )
        if name in self._providers and not replace:
            raise DependencyError(
                message=f"Service already registered: {name}",
                code="DEPENDENCY_DUPLICATE",
                context={"service": name, "available": self.list()},
            )
        if lifetime != INSTANCE and not callable(provider):
            raise DependencyError(
                message=f"Provider for {name!r} is not callable: {provider!r}",
                code="DEPENDENCY_PROVIDER_INVALID",
                context={"service": name},
            )
        entry = Provider(
            name,
            provider,
            lifetime=lifetime,
            dependencies=tuple(depends_on),
            owner=owner,
            instance=instance,
        )
        self._providers[name] = entry
        return entry

    def unregister(self, name: str) -> bool:
        """Remove a service definition; returns whether it existed."""
        return self._providers.pop(name, None) is not None

    # -- resolution ---------------------------------------------------
    def resolve(self, name: str) -> Any:
        """Return the service registered under ``name``."""
        entry = self._providers.get(name)
        if entry is None:
            raise DependencyError(
                message=f"Unknown service: {name}",
                code="DEPENDENCY_NOT_FOUND",
                context={"service": name, "available": self.list()},
            )
        if entry.lifetime == INSTANCE or (
            entry.lifetime == SINGLETON and entry.built
        ):
            entry.resolution_count += 1
            return entry.instance
        if name in self._resolve_stack:
            chain = self._resolve_stack + [name]
            raise DependencyError(
                message="Circular dependency detected: " + " -> ".join(chain),
                code="DEPENDENCY_CIRCULAR",
                context={"service": name, "chain": chain},
            )
        self._resolve_stack.append(name)
        try:
            dependencies = self._resolve_dependencies(entry)
            value = self._build(entry, dependencies)
        finally:
            self._resolve_stack.pop()
        entry.resolution_count += 1
        if entry.lifetime == SINGLETON:
            entry.instance = value
            entry.built = True
        return value

    def _resolve_dependencies(self, entry: Provider) -> Dict[str, Any]:
        resolved: Dict[str, Any] = {}
        for dependency in entry.dependencies:
            if dependency == entry.name:
                raise DependencyError(
                    message=(
                        f"Service {entry.name!r} declares itself as dependency"
                    ),
                    code="DEPENDENCY_CIRCULAR",
                    context={"service": entry.name, "dependency": dependency},
                )
            try:
                resolved[dependency] = self.resolve(dependency)
            except DependencyError as exc:
                raise DependencyError(
                    message=(
                        f"Dependency {dependency!r} of {entry.name!r} could not "
                        f"be resolved: {getattr(exc, 'message', exc)}"
                    ),
                    code="DEPENDENCY_UNRESOLVED",
                    cause=exc,
                    context={
                        "service": entry.name,
                        "dependency": dependency,
                        "provider": entry.provider_name,
                    },
                ) from exc
        return resolved

    def _build(self, entry: Provider, dependencies: Dict[str, Any]) -> Any:
        target = entry.provider
        try:
            if dependencies:
                return target(**dependencies)
            return target()
        except DependencyError:
            raise
        except Exception as exc:
            raise DependencyError(
                message=f"Provider for {entry.name!r} failed: {type(exc).__name__}: {exc}",
                code="DEPENDENCY_PROVIDER_FAILED",
                cause=exc,
                context={
                    "service": entry.name,
                    "provider": entry.provider_name,
                    "dependencies": sorted(dependencies),
                },
            ) from exc

    # -- introspection ------------------------------------------------
    def has(self, name: str) -> bool:
        """True when a provider (or a built instance) exists for ``name``."""
        return name in self._providers

    def get(self, name: str) -> Provider:
        """Return the provider definition of ``name`` (no build triggered)."""
        entry = self._providers.get(name)
        if entry is None:
            raise DependencyError(
                message=f"Unknown service: {name}",
                code="DEPENDENCY_NOT_FOUND",
                context={"service": name, "available": self.list()},
            )
        return entry

    def information(self, name: str) -> dict:
        """The ``service -> provider -> lifetime`` view of one service."""
        return self.get(name).to_dict()

    def list(self) -> List[str]:
        """Registered service names, in registration order."""
        return list(self._providers)

    names = list

    def resolved(self) -> List[str]:
        """Service names that already have a built instance."""
        return [name for name, entry in self._providers.items() if entry.built]

    def dependencies_of(self, name: str) -> List[str]:
        """Names this service depends on (declared, not resolved)."""
        return list(self.get(name).dependencies)

    def dependents_of(self, name: str) -> List[str]:
        """Service names that declare ``name`` as a dependency."""
        return [
            service
            for service, entry in self._providers.items()
            if name in entry.dependencies
        ]

    def graph(self) -> Dict[str, List[str]]:
        """Dependency graph: every service mapped to its declared dependencies."""
        return {name: list(entry.dependencies) for name, entry in self._providers.items()}

    def describe(self) -> dict:
        """Machine readable snapshot of the container (deterministic keys)."""
        return {
            "name": self.name,
            "count": len(self._providers),
            "services": {
                name: entry.to_dict() for name, entry in self._providers.items()
            },
            "lifetimes": {
                lifetime: [
                    name
                    for name, entry in self._providers.items()
                    if entry.lifetime == lifetime
                ]
                for lifetime in LIFETIMES
            },
            "resolved": self.resolved(),
        }

    to_dict = describe
    inspect = describe

    # -- dunder -------------------------------------------------------
    def __contains__(self, name: object) -> bool:
        return name in self._providers

    def __iter__(self) -> Iterator[str]:
        return iter(self._providers)

    def __len__(self) -> int:
        return len(self._providers)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"Container(name={self.name!r}, services={len(self._providers)}, "
            f"resolved={len(self.resolved())})"
        )
