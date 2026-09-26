"""Betrayer core: configuration, environment, lifecycle, registry, errors.

Dependency direction (enforced by convention and validated by
``python -m betrayer validate``)::

    core  <-  runtime  <-  application  <-  bootstrap  <-  cli
    core  <-  diagnostics
    core  <-  ai (documentation only)

``core`` never imports the CLI, diagnostics, runtime or application layer.
"""

from __future__ import annotations

from betrayer.core.config import Config, is_secret_key
from betrayer.core.environment import Environment
from betrayer.core.exceptions import (
    BetrayerError,
    BootstrapError,
    ConfigurationError,
    DependencyError,
    EnvironmentError,
    EventError,
    ExtensionError,
    LifecycleError,
    ModuleError,
    RegistryError,
)
from betrayer.core.exceptions import RuntimeError as BetrayerRuntimeError
from betrayer.core.container import LIFETIMES, SINGLETON, TRANSIENT, Container
from betrayer.core.events import Event, EventBus, EventHandler
from betrayer.core.extension import Extension, ExtensionRegistry, ExtensionState
from betrayer.core.lifecycle import Lifecycle, LifecycleState
from betrayer.core.module import Module, ModuleRegistry, ModuleState
from betrayer.core.registry import (
    CATEGORIES,
    CATEGORY_COMPONENT,
    CATEGORY_EXTENSIONS,
    CATEGORY_EVENTS,
    CATEGORY_MODULES,
    CATEGORY_SERVICES,
    Registry,
)
from betrayer.core.system import CoreSystem

__all__ = [
    "Config",
    "Environment",
    "Lifecycle",
    "LifecycleState",
    "Registry",
    "Container",
    "CoreSystem",
    "Event",
    "EventBus",
    "EventHandler",
    "Extension",
    "ExtensionRegistry",
    "ExtensionState",
    "Module",
    "ModuleRegistry",
    "ModuleState",
    "LIFETIMES",
    "SINGLETON",
    "TRANSIENT",
    "CATEGORIES",
    "CATEGORY_COMPONENT",
    "CATEGORY_SERVICES",
    "CATEGORY_MODULES",
    "CATEGORY_EXTENSIONS",
    "CATEGORY_EVENTS",
    "BetrayerError",
    "BootstrapError",
    "ConfigurationError",
    "DependencyError",
    "EnvironmentError",
    "EventError",
    "ExtensionError",
    "LifecycleError",
    "ModuleError",
    "RegistryError",
    "BetrayerRuntimeError",
    "is_secret_key",
]
