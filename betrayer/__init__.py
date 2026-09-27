"""Betrayer Framework - an LLM-first Python framework.

Betrayer provides structure, contracts, tools and validation around the
decisions made by an LLM.  The framework is deliberately explicit,
predictable and inspectable: every subsystem can be found, described and
checked without guessing.

Public API (stable for the whole 0.x foundation line)::

    BetrayerApplication  framework composition root
    Bootstrap            deterministic start-up orchestration
    Config               dotted-key configuration, secret aware
    Environment          frozen environment snapshot
    Lifecycle            lifecycle state machine + handlers
    LifecycleState       CREATED/BOOTSTRAPPING/READY/... enum
    Registry             instance scoped component registry
    RuntimeContext       per-application runtime access point
    RuntimeState         per-run runtime value object
"""

from __future__ import annotations

from betrayer.core.meta import (
    ARCHITECTURE_VERSION,
    FOUNDATION_VERSION,
    FRAMEWORK_NAME,
    FRAMEWORK_SLUG,
    __version__,
)
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
    RuntimeError,
)
from betrayer.core.config import Config
from betrayer.core.environment import Environment
from betrayer.core.container import LIFETIMES, SINGLETON, TRANSIENT, Container
from betrayer.core.events import Event, EventBus, EventHandler
from betrayer.core.extension import Extension, ExtensionRegistry, ExtensionState
from betrayer.core.module import Module, ModuleRegistry, ModuleState
from betrayer.core.system import CoreSystem
from betrayer.core.lifecycle import Lifecycle, LifecycleState
from betrayer.core.registry import Registry
from betrayer.runtime.context import RuntimeContext
from betrayer.runtime.state import RuntimeState
from betrayer.application import BetrayerApplication
from betrayer.bootstrap import Bootstrap
from betrayer.web.pagination import (
    PAGE_PARAM,
    PER_PAGE_PARAM,
    DEFAULT_PAGE,
    DEFAULT_PER_PAGE,
    MAX_PER_PAGE,
    PaginationParams,
    PaginationMetadata,
    PaginatedResult,
    parse_pagination,
    paginate_sequence,
    paginate_query,
)

__all__ = [
    "FRAMEWORK_NAME",
    "FRAMEWORK_SLUG",
    "ARCHITECTURE_VERSION",
    "FOUNDATION_VERSION",
    "__version__",
    "BetrayerError",
    "BootstrapError",
    "ConfigurationError",
    "EnvironmentError",
    "LifecycleError",
    "RegistryError",
    "RuntimeError",
    "DependencyError",
    "EventError",
    "ExtensionError",
    "ModuleError",
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
    "RuntimeContext",
    "RuntimeState",
    "BetrayerApplication",
    "Bootstrap",
    "PAGE_PARAM",
    "PER_PAGE_PARAM",
    "DEFAULT_PAGE",
    "DEFAULT_PER_PAGE",
    "MAX_PER_PAGE",
    "PaginationParams",
    "PaginationMetadata",
    "PaginatedResult",
    "parse_pagination",
    "paginate_sequence",
    "paginate_query",
]
