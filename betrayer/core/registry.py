"""Component registry.

The registry is a plain, instance scoped container.  Subsystems register
themselves here so the framework (and an LLM) can enumerate what is
available at runtime without guessing import paths.

Rules:
* No global mutable state - a registry belongs to one application.
* Duplicate registration raises ``RegistryError`` unless ``replace=True``.
* Lookups of unknown names raise ``RegistryError`` (never return ``None``).
"""

from __future__ import annotations

from typing import Any, Iterator, Optional

from betrayer.core.exceptions import RegistryError

__all__ = [
    "CATEGORIES",
    "CATEGORY_COMPONENT",
    "CATEGORY_EXTENSIONS",
    "CATEGORY_EVENTS",
    "CATEGORY_MODULES",
    "CATEGORY_SERVICES",
    "Registry",
    "check_category",
]

#: Recognised registry categories.  Categories keep one flat namespace
#: readable ("what is this component?") without a second registry.
CATEGORY_COMPONENT = "component"
CATEGORY_SERVICES = "services"
CATEGORY_MODULES = "modules"
CATEGORY_EXTENSIONS = "extensions"
CATEGORY_EVENTS = "events"

CATEGORIES = (
    CATEGORY_COMPONENT,
    CATEGORY_SERVICES,
    CATEGORY_MODULES,
    CATEGORY_EXTENSIONS,
    CATEGORY_EVENTS,
)


def check_category(category: str) -> str:
    """Return ``category`` if it is known, otherwise raise ``RegistryError``."""
    if category not in CATEGORIES:
        raise RegistryError(
            message=f"Unknown registry category: {category!r}",
            code="REGISTRY_CATEGORY_INVALID",
            context={"category": category, "categories": list(CATEGORIES)},
        )
    return category


class Registry:
    """Instance scoped component registry."""

    def __init__(self, name: str = "registry") -> None:
        self.name = name
        self._components: dict[str, Any] = {}
        self._metadata: dict[str, dict] = {}
        self._categories: dict[str, str] = {}

    # -- mutation -------------------------------------------------
    def register(
        self,
        name: str,
        component: Any,
        *,
        replace: bool = False,
        metadata: Optional[dict] = None,
        category: str = CATEGORY_COMPONENT,
    ) -> Any:
        """Register ``component`` under ``name`` and return it.

        ``category`` groups the introspection surface (``services``,
        ``modules``, ``extensions``, ``events`` or the default
        ``component``); an unknown category is rejected instead of being
        stored silently.  Re-registering an existing name still raises
        ``RegistryError`` unless ``replace=True``.
        """
        check_category(category)
        if name in self._components and not replace:
            raise RegistryError(
                message=f"Component already registered: {name}",
                code="REGISTRY_DUPLICATE",
                context={"name": name},
            )
        self._components[name] = component
        self._metadata[name] = dict(metadata or {})
        self._categories[name] = category
        return component

    def unregister(self, name: str) -> Any:
        if name not in self._components:
            raise RegistryError(
                message=f"Unknown component: {name}",
                code="REGISTRY_NOT_FOUND",
                context={"name": name},
            )
        self._metadata.pop(name, None)
        self._categories.pop(name, None)
        return self._components.pop(name)

    # -- access ---------------------------------------------------
    def get(self, name: str) -> Any:
        if name not in self._components:
            raise RegistryError(
                message=f"Unknown component: {name}",
                code="REGISTRY_NOT_FOUND",
                context={"name": name, "available": self.list_all()},
            )
        return self._components[name]

    def has(self, name: str) -> bool:
        return name in self._components

    def list_all(self) -> list[str]:
        """Return every registered component name (insertion order)."""
        return list(self._components)

    # ``names`` is an explicit alias so both spellings stay discoverable.
    def names(self) -> list[str]:
        return self.list_all()

    def metadata(self, name: str) -> dict:
        if name not in self._metadata:
            raise RegistryError(
                message=f"Unknown component: {name}",
                code="REGISTRY_NOT_FOUND",
                context={"name": name},
            )
        return dict(self._metadata[name])

    # -- inspection -----------------------------------------------
    def describe(self) -> dict:
        return {
            "name": self.name,
            "count": len(self._components),
            "components": [
                {
                    "name": name,
                    "type": type(component).__name__,
                    "metadata": dict(self._metadata.get(name, {})),
                }
                for name, component in self._components.items()
            ],
        }

    # -- categories / introspection -------------------------------
    def category_of(self, name: str) -> str:
        """Return the category ``name`` was registered under."""
        if name not in self._components:
            raise RegistryError(
                message=f"Unknown component: {name}",
                code="REGISTRY_NOT_FOUND",
                context={"name": name},
            )
        return self._categories.get(name, CATEGORY_COMPONENT)

    def sorted_names(self) -> list[str]:
        """Return every component name sorted alphabetically (stable)."""
        return sorted(self._components)

    def categories(self) -> dict[str, list[str]]:
        """Return ``{category: [names]}`` for every known category."""
        summary: dict[str, list[str]] = {category: [] for category in CATEGORIES}
        for name in self._components:
            category = self._categories.get(name, CATEGORY_COMPONENT)
            summary.setdefault(category, []).append(name)
        return summary

    def list_by_category(self, category: str) -> list[str]:
        """Return the names registered under ``category`` (insertion order)."""
        check_category(category)
        return [
            name
            for name in self._components
            if self._categories.get(name, CATEGORY_COMPONENT) == category
        ]

    def list_components(self) -> list[str]:
        return self.list_by_category(CATEGORY_COMPONENT)

    def list_services(self) -> list[str]:
        """Registered services (usually mirrored from the DI container)."""
        return self.list_by_category(CATEGORY_SERVICES)

    def list_modules(self) -> list[str]:
        return self.list_by_category(CATEGORY_MODULES)

    def list_extensions(self) -> list[str]:
        return self.list_by_category(CATEGORY_EXTENSIONS)

    def list_events(self) -> list[str]:
        """Event names *declared* in the registry.

        Live subscriptions are owned by
        :class:`~betrayer.core.events.EventBus` (``app.core.events``).
        """
        return self.list_by_category(CATEGORY_EVENTS)

    def describe_categories(self) -> dict:
        return {
            "name": self.name,
            "count": len(self._components),
            "categories": self.categories(),
        }

    # -- dunder ---------------------------------------------------
    def __contains__(self, name: object) -> bool:
        return name in self._components

    def __iter__(self) -> Iterator[str]:
        return iter(self._components)

    def __len__(self) -> int:
        return len(self._components)

    def __repr__(self) -> str:
        return f"Registry(name={self.name!r}, count={len(self._components)})"
