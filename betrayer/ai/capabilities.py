"""Canonical capability definitions for the Betrayer framework.

This module is the **single source of truth** for Betrayer capabilities.
Every capability has a structured definition consumed by:

- ``discover.list()`` / ``discover.get()`` / ``discover.search()``
- ``bet discover`` CLI command
- ``bet discover --json`` machine-readable output

Adding a new capability means adding one entry to ``CAPABILITIES``.
There is no second registry, no hardcoded dictionary elsewhere to drift.
"""

from __future__ import annotations

from typing import Any


# ── Capability record ────────────────────────────────────────────

CAPABILITY_CATEGORIES = {
    "core": "Foundation: lifecycle, config, environment, events, DI",
    "web": "Web/REST: routing, resource, middleware, error handling, realtime",
    "web/data": "Web/Data: pagination, validation",
    "data": "Data: ORM, repository, migration, cache",
    "infrastructure": "Infrastructure: queue, scheduler, retry, email, health",
    "security": "Security: authentication, authorization, rate limiting",
    "testing": "Testing: test runner, layers, fixtures",
    "cli": "CLI & developer tools: generator, diagnostics, introspection",
    "generator": "Code generation: module, resource, service, CRUD, migration",
}

CapabilityDef = dict[str, Any]
"""
Structure of a single capability definition::

    {
        "name": str,           # unique canonical name
        "purpose": str,         # single-line what/why
        "description": str,     # longer description (one paragraph)
        "category": str,        # one of CAPABILITY_CATEGORIES keys
        "status": str,          # "stable" | "beta" | "experimental"
        "public_api": [str],   # canonical importable symbols
        "contract": str | None, # path relative to betrayer/ai/ or None
        "package": str,         # betrayer sub-package
        "uses": [str],         # capabilities this capability depends on
        "used_by": [str],      # capabilities that depend on this one
        "cli_commands": [str], # relevant CLI commands
        "example": str,         # minimal usage snippet
    }
"""


# ── Canonical capability definitions ────────────────────────────

CAPABILITIES: list[CapabilityDef] = [
    # ── core ────────────────────────────────────────────────────
    {
        "name": "application",
        "purpose": "Framework composition root: bootstrap, lifecycle, registry, and container.",
        "description": (
            "``BetrayerApplication`` is the single entry point for every Betrayer app. "
            "It owns the lifecycle state machine, the component registry, the DI container, "
            "the event bus, and the module system.  Use it to wire together every other "
            "capability."
        ),
        "category": "core",
        "status": "stable",
        "public_api": [
            "BetrayerApplication",
            "Bootstrap",
            "from betrayer import BetrayerApplication, Bootstrap",
        ],
        "contract": None,
        "package": "betrayer",
        "uses": ["configuration", "environment", "lifecycle", "events", "container"],
        "used_by": ["module", "resource", "service", "database", "authentication",
                     "authorization", "testing"],
        "cli_commands": ["info", "status", "validate"],
        "example": (
            "app = BetrayerApplication(name=\"my-app\")\n"
            "Bootstrap(app).build()\n"
            "app.initialize()\n"
            "app.ready()\n"
            "app.start()\n"
        ),
    },
    {
        "name": "configuration",
        "purpose": "Dotted-key configuration with environment override, secret masking, and freeze support.",
        "description": (
            "``Config`` provides a hierarchical dictionary accessed by dotted keys "
            "(``app.name``, ``database.default.driver``).  Values can be overridden by "
            "environment variables (``BETRAYER_APP__DEBUG=1``).  Once ``finalise()`` is "
            "called the config is immutable.  Secret values (keys containing ``secret``, "
            "``key``, ``token``, ``password``) are masked in output."
        ),
        "category": "core",
        "status": "stable",
        "public_api": [
            "Config",
            "is_secret_key",
        ],
        "contract": "CONFIG.md",
        "package": "betrayer.core",
        "uses": [],
        "used_by": ["application", "database", "module"],
        "cli_commands": ["config"],
        "example": (
            'config = Config(defaults={"app.name": "my-app", "app.debug": False})\n'
            'config.set("app.debug", True)\n'
            'config.get("app.name")  # -> "my-app"\n'
            'config.finalise()       # immutable after this'
        ),
    },
    {
        "name": "environment",
        "purpose": "Detect runtime environment: Python, OS, virtualenv, project root.",
        "description": (
            "``Environment.detect()`` captures a frozen snapshot of the runtime environment: "
            "Python version, OS name, architecture, virtualenv status, current working "
            "directory, and project root.  Also provides ``development_mode`` hint based on "
            "environment variables."
        ),
        "category": "core",
        "status": "stable",
        "public_api": [
            "Environment",
        ],
        "contract": "ENVIRONMENT.md",
        "package": "betrayer.core",
        "uses": [],
        "used_by": ["application", "diagnostics"],
        "cli_commands": ["environment"],
        "example": (
            "env = Environment.detect()\n"
            'env.python_version   # -> "3.11.5"\n'
            'env.is_virtualenv    # -> True'
        ),
    },
    {
        "name": "lifecycle",
        "purpose": "Deterministic state machine: CREATED -> BOOTSTRAPPING -> READY -> RUNNING -> STOPPING -> STOPPED.",
        "description": (
            "Every Betrayer application follows a lifecycle state machine.  Transitions are "
            "guarded and reversible only along defined edges.  Handlers can be attached to "
            "each transition (``on_bootstrap``, ``on_initialize``, ``on_ready``, ``on_start``, "
            "``on_stop``, ``on_shutdown``, ``on_error``)."
        ),
        "category": "core",
        "status": "stable",
        "public_api": [
            "Lifecycle",
            "LifecycleState",
        ],
        "contract": "LIFECYCLE.md",
        "package": "betrayer.core",
        "uses": [],
        "used_by": ["application", "module"],
        "cli_commands": ["status"],
        "example": (
            "lifecycle = Lifecycle()\n"
            "lifecycle.transition(LifecycleState.READY)\n"
            'lifecycle.current  # -> LifecycleState.READY'
        ),
    },
    {
        "name": "events",
        "purpose": "Synchronous, deterministic, in-process event bus.",
        "description": (
            "The ``EventBus`` is the canonical event system — there is exactly one bus per "
            "application.  Handlers are registered with ``.on(event, handler)`` and removed "
            "with ``.off(event)``.  Events are structured ``Event(name, payload)`` objects. "
            "The bus supports priority ordering, one-shot listeners, and owner-scoped handlers."
        ),
        "category": "core",
        "status": "stable",
        "public_api": [
            "EventBus",
            "Event",
            "EventHandler",
            "from betrayer.core import EventBus, Event, EventHandler",
        ],
        "contract": "EVENTS_JOBS_CONTRACT.md",
        "package": "betrayer.core",
        "uses": [],
        "used_by": ["application", "jobs", "realtime", "cache"],
        "cli_commands": [],
        "example": (
            "bus = EventBus()\n"
            "bus.on(\"user.created\", lambda e: print(e.payload))\n"
            'bus.emit("user.created", {"id": 1})'
        ),
    },
    {
        "name": "container",
        "purpose": "Dependency injection container with singleton and transient lifetimes.",
        "description": (
            "The DI container resolves named services.  Supports ``singleton`` (one instance "
            "shared across the application) and ``transient`` (new instance per resolution) "
            "lifetimes.  Services are registered by name (``\"products_service\"``) and resolved "
            "via ``container.resolve(name)``.  Used by web resources (``context.resolve(...)``)."
        ),
        "category": "core",
        "status": "stable",
        "public_api": [
            "Container",
            "SINGLETON",
            "TRANSIENT",
            "LIFETIMES",
            "from betrayer.core import Container",
        ],
        "contract": None,
        "package": "betrayer.core",
        "uses": [],
        "used_by": ["application", "module", "service", "resource"],
        "cli_commands": [],
        "example": (
            "container = Container()\n"
            'container.singleton("products_service", ProductService())\n'
            'service = container.resolve("products_service")'
        ),
    },
    # ── web ──────────────────────────────────────────────────────
    {
        "name": "resource",
        "purpose": "Declarative endpoint collections backed by service + validation + pagination.",
        "description": (
            "A resource is a thin, declarative endpoint collection.  ``ApiResource`` provides "
            "the base class; ``CrudApiResource`` adds canonical CRUD endpoints (list, get, "
            "create, update, delete).  Resources can opt into authentication, authorization, "
            "rate limiting, pagination, and caching via class attributes.  The flow is always "
            "HTTP → Resource → Service → Repository/Data."
        ),
        "category": "web",
        "status": "stable",
        "public_api": [
            "ApiResource",
            "CrudApiResource",
            "ApiResponse",
            "FlaskAdapter",
            "from betrayer.web import ApiResource, CrudApiResource, ApiResponse",
        ],
        "contract": None,
        "package": "betrayer.web",
        "uses": ["validation", "pagination", "service", "container"],
        "used_by": ["authentication", "authorization", "rate_limiting", "cache"],
        "cli_commands": ["make resource", "make crud"],
        "example": (
            "class ProductResource(CrudApiResource):\n"
            '    name = "products"\n'
            "    prefix = \"/api/v1\"\n"
            "    pagination = True",
        ),
    },
    {
        "name": "validation",
        "purpose": "Declarative request schema validation with typed fields and constraints.",
        "description": (
            "Validation uses ``Schema`` + ``Field`` to parse and validate request bodies "
            "before the service runs.  Fields support type checking, required/optional, "
            "defaults, min/max, length constraints, choices, and regex patterns.  A "
            "``ValidationError`` (422) with field-level detail is raised on failure."
        ),
        "category": "web",
        "status": "stable",
        "public_api": [
            "Schema",
            "Field",
            "ValidationResult",
            "from betrayer.web import Schema, Field",
        ],
        "contract": "VALIDATION.md",
        "package": "betrayer.web",
        "uses": ["resource"],
        "used_by": [],
        "cli_commands": [],
        "example": (
            "class ProductSchema(Schema):\n"
            "    name = Field(str, required=True)\n"
            "    price = Field(float, required=True, min=0)\n"
            "\n"
            "class ProductResource(CrudApiResource):\n"
            "    schema = ProductSchema()",
        ),
    },
    {
        "name": "pagination",
        "purpose": "Page-based pagination for collection endpoints.",
        "description": (
            "Pagination is opt-in per resource via ``pagination = True`` on "
            "``CrudApiResource``.  Query parameters ``page`` (default 1) and ``per_page`` "
            "(default 20, max 100) are validated and parsed into ``PaginationParams``.  "
            "Responses include ``meta.pagination`` with page, per_page, total, and total_pages.  "
            "Out-of-range pages return an empty ``data`` array with truthful metadata."
        ),
        "category": "web/data",
        "status": "stable",
        "public_api": [
            "PaginationParams",
            "PaginationMetadata",
            "PaginatedResult",
            "parse_pagination",
            "paginate_sequence",
            "paginate_query",
            "from betrayer.web import PaginationParams, PaginatedResult, parse_pagination",
        ],
        "contract": "PAGINATION_CONTRACT.md",
        "package": "betrayer.web",
        "uses": ["resource", "validation"],
        "used_by": [],
        "cli_commands": [],
        "example": (
            "class ProductResource(CrudApiResource):\n"
            "    name = \"products\"\n"
            "    pagination = True",
        ),
    },
    {
        "name": "realtime",
        "purpose": "WebSocket/realtime channels using the same services as HTTP resources.",
        "description": (
            "Realtime channels reuse the same Service/Repository layer as HTTP — no duplicate "
            "business logic.  ``RealtimeManager`` owns channels and connections; messages are "
            "structured ``Message`` objects carrying request/trace IDs.  EventBus integration "
            "allows server-side events to be broadcast to WebSocket clients.  The optional "
            "``FlaskRealtimeAdapter`` mounts channels on the same Flask app via ``flask_sock``."
        ),
        "category": "web",
        "status": "stable",
        "public_api": [
            "RealtimeManager",
            "Channel",
            "Connection",
            "Message",
            "FlaskRealtimeAdapter",
            "from betrayer.web import RealtimeManager, Channel, Connection, Message",
        ],
        "contract": "REALTIME_CONTRACT.md",
        "package": "betrayer.web.realtime",
        "uses": ["events", "service", "diagnostics"],
        "used_by": [],
        "cli_commands": ["realtime"],
        "example": (
            "manager = RealtimeManager(application=app)\n"
            "manager.on_event(\"product.created\", \"/products\")\n"
            "app.events.on(\"product.created\", manager.handle_event)",
        ),
    },
    # ── security ─────────────────────────────────────────────────
    {
        "name": "authentication",
        "purpose": "Determines who made the request (identity resolution).",
        "description": (
            "Authentication answers \"who is this?\" — separate from \"what may they do?\" "
            "(authorization).  The ``Authenticator`` resolves a request to an ``Identity`` "
            "(or ``AnonymousIdentity``).  ``AuthenticationMiddleware`` sets ``request.user`` "
            "on every request.  Resources opt in with ``authentication_required = True`` "
            "(returns 401 UNAUTHENTICATED when anonymous)."
        ),
        "category": "security",
        "status": "stable",
        "public_api": [
            "Authenticator",
            "HeaderTokenAuthenticator",
            "Identity",
            "AnonymousIdentity",
            "AuthenticationMiddleware",
            "from betrayer.auth import Authenticator, Identity",
        ],
        "contract": "AUTHENTICATION_CONTRACT.md",
        "package": "betrayer.auth",
        "uses": ["resource", "middleware"],
        "used_by": ["authorization", "rate_limiting"],
        "cli_commands": [],
        "example": (
            "class MyAuth(Authenticator):\n"
            "    def authenticate(self, request) -> Identity | None: ...\n"
            "\n"
            "class ProductResource(CrudApiResource):\n"
            "    authentication_required = True",
        ),
    },
    {
        "name": "authorization",
        "purpose": "Determines whether an identity may perform an action (access control).",
        "description": (
            "Authorization answers \"may this identity perform this action?\" — layered "
            "after authentication.  The ``Authorizer`` returns ``True`` (allowed) or "
            "``False`` (denied).  ``AuthorizationMiddleware`` checks every request after "
            "rate limiting.  Resources opt in with ``authorization_required = True`` "
            "(returns 403 FORBIDDEN when denied)."
        ),
        "category": "security",
        "status": "stable",
        "public_api": [
            "Authorizer",
            "CallbackAuthorizer",
            "authorize",
            "AuthorizationMiddleware",
            "ForbiddenError",
            "from betrayer.auth import Authorizer, authorize",
        ],
        "contract": "AUTHORIZATION_CONTRACT.md",
        "package": "betrayer.auth",
        "uses": ["authentication", "resource", "middleware"],
        "used_by": [],
        "cli_commands": [],
        "example": (
            "class MyAuthorizer(Authorizer):\n"
            "    def authorize(self, identity, action, resource=None, context=None) -> bool: ...\n"
            "\n"
            "class ProductResource(CrudApiResource):\n"
            "    authorization_required = True",
        ),
    },
    {
        "name": "rate_limiting",
        "purpose": "Fixed-window rate limiting based on identity or request key.",
        "description": (
            "Rate limiting uses a fixed-window algorithm with configurable limit and "
            "window (default 100 requests / 60 seconds).  The ``RateLimitMiddleware`` "
            "runs after authentication (priority 5) and enforces limits using identity-based "
            "keys.  When exceeded, returns HTTP 429 with ``RATE_LIMIT_EXCEEDED``.  Resources "
            "opt in with ``rate_limit = RateLimit(limit=100, window=60)``."
        ),
        "category": "security",
        "status": "stable",
        "public_api": [
            "RateLimit",
            "RateLimitResult",
            "FixedWindowRateLimiter",
            "MemoryRateLimitStore",
            "RateLimitMiddleware",
            "from betrayer.ratelimit import RateLimit, RateLimitMiddleware",
        ],
        "contract": "RATE_LIMITING_CONTRACT.md",
        "package": "betrayer.ratelimit",
        "uses": ["authentication", "resource", "middleware"],
        "used_by": [],
        "cli_commands": [],
        "example": (
            "class ProductResource(CrudApiResource):\n"
            "    rate_limit = RateLimit(limit=100, window=60)",
        ),
    },
    # ── data ─────────────────────────────────────────────────────
    {
        "name": "database",
        "purpose": "Database abstraction: ORM, query builder, repository, migrations, and engine support.",
        "description": (
            "The data layer provides ``ORMModel`` with typed fields, relationships "
            "(``HasMany``, ``BelongsTo``, etc.), a query builder (``Query``) with where, "
            "order, limit/offset, and paginate support, a ``BaseRepository`` for CRUD, "
            "a ``MigrationRegistry`` for schema migrations, and concrete engines (SQLite, "
            "DuckDB).  The canonical wiring is ``install_database(app)``."
        ),
        "category": "data",
        "status": "stable",
        "public_api": [
            "ORMModel",
            "ORMField",
            "BaseRepository",
            "HasMany",
            "BelongsTo",
            "Query",
            "MigrationRegistry",
            "DatabaseManager",
            "install_database",
            "from betrayer.data import ORMModel, ORMField, BaseRepository",
        ],
        "contract": None,  # Several contract files exist
        "package": "betrayer.data",
        "uses": ["configuration", "application"],
        "used_by": ["cache", "migration"],
        "cli_commands": ["make migration"],
        "example": (
            "class User(ORMModel):\n"
            "    __table__ = \"users\"\n"
            "    id = ORMField(int, primary_key=True)\n"
            "    name = ORMField(str, required=True)\n"
            "    posts = HasMany(\"Post\")\n"
            "\n"
            "user = User.query().where(\"email\", email).first()",
        ),
    },
    {
        "name": "migration",
        "purpose": "Schema migration management with up/down steps.",
        "description": (
            "Migrations are declarative classes extending ``Migration`` with ``up()`` and "
            "``down()`` methods.  ``MigrationRegistry`` tracks applied migrations by sequence.  "
            "The ``bet make migration <name>`` CLI generates a skeleton migration file.  "
            "Migrations use the same engine as the application's database manager."
        ),
        "category": "data",
        "status": "stable",
        "public_api": [
            "Migration",
            "MigrationRegistry",
            "from betrayer.data import Migration, MigrationRegistry",
        ],
        "contract": None,
        "package": "betrayer.data",
        "uses": ["database", "configuration"],
        "used_by": [],
        "cli_commands": ["make migration"],
        "example": (
            "class CreateUsersTable(Migration):\n"
            "    def up(self, db):\n"
            "        db.execute(\"CREATE TABLE users (...)\")\n"
            "    def down(self, db):\n"
            "        db.execute(\"DROP TABLE users\")",
        ),
    },
    {
        "name": "cache",
        "purpose": "Backend-agnostic cache with TTL, sentinel-based miss detection, and web middleware.",
        "description": (
            "The cache subsystem provides ``CacheManager`` with ``get``, ``set``, ``delete``, "
            "``exists``, ``clear``, and ``get_or_set``.  A ``MISSING`` sentinel distinguishes "
            "cache miss from a cached ``None``.  ``WebCacheMiddleware`` caches GET/HEAD "
            "responses with TTL per resource (``cache_ttl``).  User identity is included in "
            "cache keys to prevent cross-user leakage."
        ),
        "category": "data",
        "status": "stable",
        "public_api": [
            "CacheManager",
            "MemoryCacheBackend",
            "CacheBackend",
            "WebCacheMiddleware",
            "from betrayer.data import CacheManager",
            "from betrayer.cache import WebCacheMiddleware",
        ],
        "contract": "CACHE_CONTRACT.md",
        "package": "betrayer.data",
        "uses": ["resource", "middleware", "authentication"],
        "used_by": [],
        "cli_commands": [],
        "example": (
            "cache = CacheManager()\n"
            "cache.set(\"key\", value, ttl=60)\n"
            "cache.get(\"key\")  # -> value or cache.MISSING",
        ),
    },
    # ── infrastructure ───────────────────────────────────────────
    {
        "name": "jobs",
        "purpose": "Background job system with queue, job runner, and scheduler.",
        "description": (
            "Jobs extend ``Job`` (abstract ``handle() -> JobResult``).  The in-memory "
            "``Queue`` supports push/pop/size/clear.  ``JobRunner`` executes available jobs.  "
            "The ``Scheduler`` provides a fluent API (``scheduler.every(60).seconds.do(MyJob())``) "
            "and ``run_due()`` for periodic execution.  CLI commands ``bet queue`` and "
            "``bet schedule`` provide introspection."
        ),
        "category": "infrastructure",
        "status": "stable",
        "public_api": [
            "Job",
            "JobResult",
            "Queue",
            "JobRunner",
            "Scheduler",
            "from betrayer.jobs import Job, Queue, JobRunner, Scheduler",
        ],
        "contract": "EVENTS_JOBS_CONTRACT.md",
        "package": "betrayer.jobs",
        "uses": ["events", "application"],
        "used_by": [],
        "cli_commands": ["queue", "schedule"],
        "example": (
            "class MyJob(Job):\n"
            "    def handle(self) -> JobResult:\n"
            "        ...\n"
            "\n"
            "queue.push(MyJob())\n"
            "runner.run_available()",
        ),
    },
    {
        "name": "testing",
        "purpose": "Canonical test system built on pytest with four layers (unit -> integration -> functional -> smoke).",
        "description": (
            "Tests follow file-naming conventions (``test_*_unit.py``, ``test_*_integration.py``, "
            "``test_*_functional.py``, ``test_*_smoke.py``).  The ``bet test`` CLI delegates "
            "to pytest with layer filters.  Output supports ``--json`` for machine-readable "
            "structured results.  Project-level fixtures (``application``, ``database_path``, "
            "``database_config``, ``database_manager``) are available in ``conftest.py``."
        ),
        "category": "testing",
        "status": "stable",
        "public_api": [
            "bet test",
            "bet test --unit",
            "bet test --integration",
            "bet test --functional",
            "bet test --smoke",
            "bet test --json",
        ],
        "contract": "TESTING_CONTRACT.md",
        "package": "betrayer (CLI)",
        "uses": ["application"],
        "used_by": [],
        "cli_commands": ["test"],
        "example": "bet test --unit --json",
    },
    {
        "name": "diagnostics",
        "purpose": "Inspection, tracing, and debugging: check, doctor, debug commands + DiagnosticsStore.",
        "description": (
            "The diagnostics subsystem provides ``Inspector`` for querying application state, "
            "``DiagnosticsStore`` for recording structured events, and CLI commands "
            "(``bet check`` for health check, ``bet doctor`` for deep inspection, "
            "``bet debug`` for request/error tracing).  Every request gets a ``request_id`` "
            "and ``trace_id``."
        ),
        "category": "cli",
        "status": "stable",
        "public_api": [
            "Inspector",
            "DiagnosticsStore",
            "get_current_request_id",
            "get_current_trace_id",
            "from betrayer.diagnostics import Inspector, get_current_request_id",
        ],
        "contract": "DIAGNOSTICS_CONTRACT.md",
        "package": "betrayer.diagnostics",
        "uses": ["application", "lifecycle", "environment"],
        "used_by": ["realtime", "testing"],
        "cli_commands": ["check", "doctor", "debug"],
        "example": "bet doctor --json",
    },
    {
        "name": "generator",
        "purpose": "Code generation for modules, resources, services, CRUD, migrations, and extensions.",
        "description": (
            "The ``bet make`` CLI command generates canonical project artifacts: "
            "``bet make module <name>``, ``bet make resource <name>``, "
            "``bet make service <name>``, ``bet make crud <name>`` (model + repo + service "
            "+ routes + module), ``bet make migration <name>``, and "
            "``bet make extension <name>``.  All generators support ``--json`` and ``--force``."
        ),
        "category": "generator",
        "status": "stable",
        "public_api": [
            "bet make module",
            "bet make resource",
            "bet make service",
            "bet make crud",
            "bet make migration",
            "bet make extension",
            "bet create",
        ],
        "contract": None,
        "package": "betrayer.generators",
        "uses": ["application", "resource", "database"],
        "used_by": [],
        "cli_commands": ["make", "create"],
        "example": "bet make crud product",
    },
    {
        "name": "module",
        "purpose": "Logical grouping of related components (services, routes, dependencies).",
        "description": (
            "A module groups related services, repositories, routes, and event handlers into "
            "one unit that can be registered with the application.  Modules are registered via "
            "``app.modules.register(MyModule)`` and initialized in order.  Each module is a "
            "class extending ``Module`` with ``name``, ``dependencies``, and lifecycle hooks."
        ),
        "category": "core",
        "status": "stable",
        "public_api": [
            "Module",
            "ModuleRegistry",
            "ModuleState",
            "from betrayer.core import Module, ModuleRegistry",
        ],
        "contract": None,
        "package": "betrayer.core",
        "uses": ["application", "container"],
        "used_by": ["resource", "service"],
        "cli_commands": ["make module"],
        "example": (
            "class ProductModule(Module):\n"
            '    name = "products"\n'
            "    dependencies = [\"database\"]",
        ),
    },
    {
        "name": "service",
        "purpose": "Business logic layer between resource and repository.",
        "description": (
            "Services contain the business logic of an application.  They are declared as "
            "plain classes and registered in the DI container.  Resources call services via "
            "``context.resolve(\"<name>_service\")``.  The generated service from "
            "``bet make service <name>`` includes CRUD methods delegating to the repository."
        ),
        "category": "core",
        "status": "stable",
        "public_api": [
            "bet make service",
            "DI key pattern: \"<name>_service\"",
        ],
        "contract": None,
        "package": "betrayer (generated)",
        "uses": ["container", "module"],
        "used_by": ["resource"],
        "cli_commands": ["make service"],
        "example": (
            "class ProductService:\n"
            "    def __init__(self, repository):\n"
            "        self._repository = repository\n"
            "    def list(self):\n"
            "        return self._repository.list()",
        ),
    },
    {
        "name": "middleware",
        "purpose": "Deterministic request processing pipeline with priority ordering.",
        "description": (
            "Middleware runs in priority order (lower number = earlier): "
            "Authentication (0) → Rate Limiting (5) → Authorization (10) → Cache (20). "
            "Each middleware has ``before_request`` and ``after_request`` hooks.  "
            "Middleware is registered via ``app.registry.get(\"web.middleware\").add(mw)``."
        ),
        "category": "web",
        "status": "stable",
        "public_api": [
            "Middleware",
            "WebMiddlewareRegistry",
            "from betrayer.web import Middleware",
        ],
        "contract": None,
        "package": "betrayer.web",
        "uses": ["resource"],
        "used_by": ["authentication", "authorization", "rate_limiting", "cache"],
        "cli_commands": [],
        "example": (
            "class MyMiddleware(Middleware):\n"
            "    priority = 15\n"
            "    def before_request(self, request, context):\n"
            "        ...",
        ),
    },
    {
        "name": "architecture_guard",
        "purpose": "Canonical architecture enforcement — detects violations that make the framework harder for LLM to understand, maintain, or use.",
        "description": (
            "Architecture Guard runs deterministic rules against the Betrayer framework "
            "to detect dependency direction violations (core→web, infrastructure→web, "
            "core→AI), duplicate subsystems, circular dependencies, AETHER isolation "
            "breaches, and Resource boundary violations.  Results are structured JSON "
            "and integrated into ``bet validate --json``.  Every violation carries a "
            "rule ID, severity, message, location, and actionable remediation."
        ),
        "category": "cli",
        "status": "stable",
        "public_api": [
            "from betrayer.architecture import guard",
            "guard.check()",
            "bet validate --json (includes 'architecture' section)",
        ],
        "contract": None,
        "package": "betrayer.architecture",
        "uses": ["diagnostics", "validation"],
        "used_by": [],
        "cli_commands": ["validate"],
        "example": (
            "from betrayer.architecture import guard\\n"
            "result = guard.check()\\n"
            "print(result.to_dict())\\n"
        ),
    },
]


# ── Index for fast lookup ────────────────────────────────────────

def _build_index() -> dict[str, CapabilityDef]:
    """Build name → capability index."""
    index: dict[str, CapabilityDef] = {}
    for cap in CAPABILITIES:
        name = cap["name"]
        if name in index:
            raise ValueError(f"Duplicate capability name: {name!r}")
        index[name] = cap
    return index


_CAPABILITY_INDEX: dict[str, CapabilityDef] | None = None


def _index() -> dict[str, CapabilityDef]:
    global _CAPABILITY_INDEX
    if _CAPABILITY_INDEX is None:
        _CAPABILITY_INDEX = _build_index()
    return _CAPABILITY_INDEX


# ── Error ────────────────────────────────────────────────────────


class CapabilityNotFoundError(LookupError):
    """Raised when a requested capability does not exist.

    Carries the requested name so the LLM can react and discover available
    capabilities.
    """

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"capability {name!r} not found")


# ── Public discovery API ─────────────────────────────────────────


def list_capabilities() -> list[CapabilityDef]:
    """Return all registered capabilities (summary level)."""
    return [
        {
            "name": cap["name"],
            "purpose": cap["purpose"],
            "category": cap["category"],
            "status": cap["status"],
            "package": cap["package"],
        }
        for cap in _index().values()
    ]


def get_capability(name: str) -> CapabilityDef:
    """Return a full capability definition by name.

    Raises ``CapabilityNotFoundError`` when the name is unknown.
    """
    index = _index()
    if name not in index:
        raise CapabilityNotFoundError(name)
    return dict(index[name])  # defensive copy


def search_capabilities(query: str) -> list[CapabilityDef]:
    """Search capabilities by name, purpose, category, or package.

    The search is case-insensitive and matches substrings.  Results are
    returned as summary level (same as ``list_capabilities``).
    """
    query_lower = query.lower()
    results: list[CapabilityDef] = []
    for cap in _index().values():
        if (query_lower in cap["name"].lower()
                or query_lower in cap["purpose"].lower()
                or query_lower in cap["category"].lower()
                or query_lower in cap["package"].lower()):
            results.append({
                "name": cap["name"],
                "purpose": cap["purpose"],
                "category": cap["category"],
                "status": cap["status"],
                "package": cap["package"],
            })
    return results


def capability_summary(cap: CapabilityDef) -> dict:
    """Extract a progressive-disclosure Level-1 summary from a full definition."""
    return {
        "name": cap["name"],
        "purpose": cap["purpose"],
        "category": cap["category"],
        "status": cap["status"],
        "public_api": cap["public_api"],
        "contract": cap["contract"],
        "package": cap["package"],
        "related_capabilities": sorted(set(cap["uses"] + cap["used_by"])),
    }


def categories() -> dict[str, str]:
    """Return the category index (name → description)."""
    return dict(CAPABILITY_CATEGORIES)