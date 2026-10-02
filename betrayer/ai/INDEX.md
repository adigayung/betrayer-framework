# Betrayer Framework — Index for LLM Agents

This document is written for LLM coding agents (like AETHER) that use
Betrayer as their framework. Read this first to understand Betrayer.

## What is Betrayer?

Betrayer is a Python framework designed for LLM coding agents. It is NOT
an AI agent itself. It provides structure, contracts, tools, validation,
and runtime hands — while the LLM remains the brain.

## Quick Start

```python
from betrayer import BetrayerApplication

app = BetrayerApplication(name="my-app")
app.bootstrap()
app.initialize()
app.ready()
app.start()
# ... do work ...
app.stop()
app.shutdown()
```

## Capability Discovery (LLM-First)

Before reading any source code, discover what Betrayer can do:

```python
from betrayer.ai import discover

# List all capabilities (summary)
discover.list()

# Get full definition of one capability
discover.get("pagination")

# Search by keyword
discover.search("authentication")

# Progressive summary (Level 1 — just enough to decide next step)
discover.summary("database")
```

Or from the CLI:

```
bet discover                    # list all capabilities (human readable)
bet discover --json             # machine-readable JSON
bet discover pagination         # get full definition
bet discover --json --search db # search + JSON
```

Every capability has: name, purpose, category, status, public API,
contract link, package, related capabilities, and a usage example.
No source code reading required to determine *what* is available.

## Package Structure

```
betrayer/
  __init__.py          # Public API exports
  __main__.py          # python -m betrayer entry point
  application.py       # Central Application object
  bootstrap.py         # Bootstrap system
  core/
    __init__.py
    config.py          # Configuration management
    environment.py     # Environment detection
    lifecycle.py       # Lifecycle state machine
    registry.py        # Component registry
    exceptions.py      # Exception hierarchy
  runtime/
    __init__.py
    context.py         # Runtime context
  diagnostics/
    __init__.py
    inspector.py       # Diagnostic inspector
  cli/
    __init__.py
    main.py            # CLI commands
  ai/                  # LLM-facing documentation + capability discovery
  data/                # Database abstraction + ORM (betrayer.data)
    engines/           # Concrete engines: SQLiteEngine, DuckDBEngine (09.4)
  infrastructure/      # HTTP, queue, scheduler, retry, email, health
  jobs/                # Canonical Job, Queue, JobRunner, Scheduler
  web/                 # Web/REST runtime (WebRouter, ApiResource, FlaskAdapter)
                       # + validation pipeline (Schema, Field, ValidationResult)
                       # + realtime/WebSocket (web.realtime: Channel, Connection,
                       #   Message, RealtimeManager, FlaskRealtimeAdapter)
  auth/                # Authentication + authorization (identity, middleware)
  cache/               # Backend-agnostic cache + web middleware
  ratelimit/           # Fixed-window rate limiting + middleware
  architecture/        # Architecture Guard (bet validate architecture section)
  generators/          # bet make ... code generators
```

## Data Layer & ORM

The Data Layer (`betrayer.data`) provides the database contract (Stage 09.1),
the Query Builder + ORM (Stage 09.2), and the Repository + Relationships layer
(Stage 09.3):

```python
from betrayer.data import ORMModel, ORMField, BaseRepository, HasMany, BelongsTo

class User(ORMModel):
    __table__ = "users"
    __connection__ = manager          # DatabaseManager/Engine/provider

    id = ORMField(int, primary_key=True)
    name = ORMField(str, required=True)
    posts = HasMany("Post")           # relationship (declared like a field)

user = User.query().where("email", email).first()
user = User.create(name="John", email="john@example.com")
user.save()
user.posts().get()                     # relationship -> Query
User.repository().find(user.id)        # canonical Repository CRUD
User.meta()                            # metadata + relationships, no source read
```

Read `betrayer/data/ORM_CONTRACT.md` for the Query Builder & ORM API
(define model, query, create/update/delete, transaction, metadata, errors) and
`betrayer/data/REPOSITORY_CONTRACT.md` for the Repository & relationship API
(`BaseRepository`, `Model.repository()`, `belongs_to`/`has_one`/`has_many`/
`many_to_many`, metadata, error contract).

Concrete engines live in `betrayer.data.engines` (Stage 09.4) and are wired in
through the same registry extension point — the ORM/Repository never know
which database is behind it:

```python
from betrayer.core.config import Config
from betrayer.data import DatabaseRegistry, DatabaseManager
from betrayer.data.engines import register_builtin_engines

registry = DatabaseRegistry(Config({
    "database.default.driver": "sqlite",   # or "duckdb"
    "database.default.database": "app.db",
}))
register_builtin_engines(registry)          # sqlite (stdlib) + duckdb (optional)
manager = DatabaseManager(registry.engine("default"))
manager.connect()                          # schema -> ORM -> Repository -> DB
```

`sqlite` uses the standard library; `duckdb` is an optional dependency imported
lazily (connecting without it raises `UnsupportedDatabaseError`).  See
`betrayer/data/DATABASE_CONTRACT.md` for config, dialects, and the E2E flow.

## Golden Path (canonical end-to-end)

The canonical application flow, with a runnable example in
`example/product_catalog/` (see its `README.md` for commands)::

    Project -> Module -> Model -> Migration -> Database
        -> Repository -> Service -> Resource/API -> Run -> Test -> Debug

Wire it in order (composition root):

```python
from betrayer import BetrayerApplication, Bootstrap, Config
from betrayer.data import MigrationRegistry, create_table_sql, install_database

app = BetrayerApplication(name="catalog", config=Config({
    "database.default.driver": "sqlite",
    "database.default.database": "catalog.db",
}))
Bootstrap(app).build()
install_database(app)                 # connect + container service "database"

Product.__connection__ = app.container.resolve("database")
app.modules.register(ProductCatalogModule)   # registers repo + service
app.modules.initialize_all()

registry = MigrationRegistry()
registry.register(CreateProductsTableMigration())
registry.apply(app.container.resolve("database"))   # runs up() by sequence
```

Wiring helpers (all reuse the existing registry / engines / ORM, no new
subsystem): `betrayer.data.install_database`, `build_database_manager`,
`create_table_sql(model, dialect)` / `drop_table_sql` (schema DDL from an ORM
model), and `MigrationRegistry.apply(database)` / `.rollback(database)`.
The HTTP layer is the shared `betrayer.web.CrudApiResource` served by
`FlaskAdapter`; the flow is `HTTP -> Resource -> Service -> Repository -> ORM`.

## Key Principles

1. **LLM is the brain.** Betrayer provides structure, not decisions.
2. **Predictable structure.** Package layout and naming are consistent.
3. **Deterministic bootstrap.** Same steps, same order, every time.
4. **Explicit lifecycle.** States are named, not boolean flags.
5. **Inspectable state.** Every component can be queried.
6. **No global mutable singletons.** RuntimeContext is passed around.
7. **No secret leakage.** Config never prints secrets.
8. **Windows is first-class.** No Unix-only assumptions.

## Dependency Direction

```
core (no dependencies on other betrayer packages)
  ↑
runtime (depends on core)
  ↑
diagnostics (depends on core, runtime)
  ↑
cli (depends on core, runtime, diagnostics)
  ↑
ai (depends on core, runtime, diagnostics)
```

**Rule:** Lower layers never depend on higher layers.

## Lifecycle Flow

```
CREATED → BOOTSTRAPPING → READY → RUNNING → STOPPING → STOPPED
                                                    ↓
                                                  FAILED (if error)
```

### Lifecycle Events

| Event           | When                          |
|-----------------|-------------------------------|
| on_bootstrap    | During bootstrap phase        |
| on_initialize   | After bootstrap, before ready |
| on_ready        | When application is ready     |
| on_start        | When application starts       |
| on_stop         | When application stops        |
| on_shutdown     | After stop, before destroyed  |
| on_error        | When any stage fails          |

## Configuration

```python
config = Config(defaults={"app.name": "my-app"})
config.set("app.debug", True)
config.get("app.name")        # → "my-app"
config.get("app.debug")       # → True
```

- Config supports nested keys with dot notation (`"app.name"`).
- Environment variables can override values (`BETRAYER_APP__DEBUG=1`).
- Config is immutable after `finalise()`.
- Secret keys (containing `secret`, `key`, `token`, `password`) are masked in output.

## Environment Detection

```python
env = Environment.detect()
env.python_version      # e.g. "3.11.5"
env.os_name             # e.g. "Windows"
env.architecture        # e.g. "AMD64"
env.is_virtualenv       # True/False
env.cwd                 # Path object
env.project_root        # Path object
env.development_mode    # True/False
```

## Runtime Context

RuntimeContext holds references to the application, environment, config,
lifecycle, and registry. It is passed to subsystems — not a global singleton.

## CLI Commands

| Command                    | Description                          |
|----------------------------|--------------------------------------|
| `python -m betrayer info`  | Framework information                |
| `python -m betrayer environment` | Environment details              |
| `python -m betrayer status`| Runtime/framework status             |
| `python -m betrayer doctor`| Foundation health checks (PASS/WARNING/ERROR) |
| `python -m betrayer check` | Quick project health check (PASS/WARNING/ERROR) |
| `python -m betrayer debug` | Diagnostics summary (also: `last`, `errors`, `trace <id>`, `inspect <id>`) |
| `python -m betrayer validate` | Validate framework integrity     |
| `python -m betrayer config` | Show configuration (secrets masked)|
| `python -m betrayer manifest` | Show generated metadata; `--write` regenerates it |
| `python -m betrayer test`     | Run tests (canonical testing system); `--unit`, `--integration`, `--functional`, `--smoke`, `--json` |
| `python -m betrayer discover` | Discover Betrayer capabilities (`<name>`, `--search <query>`, `--json`) |
| `python -m betrayer queue`    | Inspect or run the job queue (`--json` for machine output) |
| `python -m betrayer schedule` | Inspect or run due scheduled jobs (`--json` for machine output) |
| `python -m betrayer realtime` | Introspect the realtime (WebSocket) layer (`--json` for machine output) |

Every command supports `--json` (valid JSON, sorted keys) and returns a real
exit code: `0` = success, non-zero = failure.

## Diagnostics & Developer Tools

Betrayer provides a canonical diagnostics subsystem for inspection, tracing,
and debugging.  See `betrayer/ai/DIAGNOSTICS_CONTRACT.md` for the full contract.

### `bet check`

Quick project/framework health check covering: project structure, configuration,
environment, imports, module registration, database configuration, migration
state, application bootstrap, and required dependencies.

```
bet check                    Human-readable output
bet check --json             Machine readable JSON
```

### `bet doctor`

In-depth diagnostics that performs real checks (probe applications, imports,
lifecycle transitions).  Uses the existing `Inspector` API.

```
bet doctor                   Human-readable output
bet doctor --json            Machine readable JSON
```

### `bet debug`

Request/error inspection and trace:

```
bet debug                    Diagnostics summary
bet debug last               Last recorded diagnostic record
bet debug errors             Error records
bet debug trace <id>         Request trace by request ID
bet debug inspect <id>       Detailed request inspection
```

### Request / Trace ID

Every HTTP request receives two identifiers:

- `request_id` — short (12 hex chars), generated per request
- `trace_id` — longer (16 hex chars), stable across retries

Access from anywhere:

```python
from betrayer.diagnostics import get_current_request_id, get_current_trace_id

request_id = get_current_request_id()
trace_id = get_current_trace_id()
```

Incoming headers: `X-Request-Id` and `X-Trace-Id` (auto-generated if absent).

### Structured Diagnostic Record

All diagnostics use the same canonical JSON format:

```json
{
  "success": false,
  "status": "error",
  "checks": [
    {
      "name": "database_connection",
      "status": "error",
      "message": "Database connection failed.",
      "context": {"driver": "sqlite"},
      "suggested_actions": ["Check database configuration."]
    }
  ]
}
```

### DiagnosticsStore

The in-memory `DiagnosticsStore` records structured diagnostic events.
It is attached to the application during bootstrap and reachable via
`app.diagnostics`.

### Secret Masking

Secrets are never exposed in diagnostics output. Configuration values for
secret keys (`password`, `token`, `api_key`, ...) are replaced with `"****"`.

## Resource / API Runtime

A resource is a thin, declarative endpoint collection backed by the existing
Betrayer web abstractions (`WebRouter`, `WebContext`, `Request`, `Response`,
`ApiResponse`).  The runtime layer mounts routes on Flask through
`FlaskAdapter`; it never introduces a second API framework.

```python
from betrayer.web import ApiResource, ApiResponse, CrudApiResource, FlaskAdapter

class ProductResource(CrudApiResource):
    name = "product"
    prefix = "/api/v1"

# serve a router (e.g. one created by `bet make resource` / `bet make crud`)
from betrayer.application import BetrayerApplication
adapter = FlaskAdapter(BetrayerApplication(name="app"), ProductResource(service=service).resource_router())
flask_app = adapter.build()          # a real Flask app
```

The flow is always `HTTP Request -> Resource -> Service -> Repository/Data`:
resources delegate to a service resolved from the container
(`context.resolve("<name>_service")`) and never take over business logic.

**Generated resource compatibility** — `bet make resource <name>` and
`bet make crud <name>` produce a `routes.py` with `register_routes(router)`;
call that to populate the router, then mount it with `FlaskAdapter`.

**Error handling** — every error becomes a controlled JSON response using the
Betrayer envelope `{"success", "data", "error"}`; raised `WebError` subclasses
map to their documented status (`BadRequestError`→400,
`NotFoundError`→404, `ValidationError`→422, `InternalServerError`→500) and
unexpected exceptions never leak a traceback.

## Validation & Request Pipeline

The canonical pipeline is `Request → Routing → Request Parsing → Validation →
Resource → Service → Response/Error`.  Declare a `Schema` (fields + types +
constraints) and attach it to a resource; the body is parsed once, validated
*before* the service, and a structured result is put on the `WebContext`:

```python
from betrayer.web import CrudApiResource, Field, Schema

class ProductSchema(Schema):
    name  = Field(str, required=True)
    price = Field(float, required=True, min=0)
    stock = Field(int, default=0, min=0)

class ProductResource(CrudApiResource):
    name = "products"
    schema = ProductSchema()      # POST/PUT validate before the service
```

A validation failure is a `ValidationError` (422 `VALIDATION_FAILED`) carrying
`error.details.fields` (`{"name": ["This field is required."]}`).  Dependency
injection uses the existing container (`context.resolve("<name>_service")`) —
there is no second DI/validation/error system.  See `betrayer/ai/VALIDATION.md`.

## Generated Metadata

`.betrayer/manifest.json` and `.betrayer/architecture.json` are GENERATED,
never hand edited. They are rebuilt from `betrayer.core.meta` plus the CLI and
package surface:

```
python -m betrayer manifest --write
```

`python -m betrayer validate` fails (`metadata` section) if a generated file
drifts from the runtime it describes. Source of truth is always code.

## Making a Subsystem

1. Create a new package under `betrayer/`.
2. Import only from `core`, `runtime`, or `diagnostics`.
3. Register components via `Application.registry`.
4. Hook into lifecycle via `Application.lifecycle.register_handler` (never edit
   the core lifecycle to add a subsystem).
5. Add a CLI command in `betrayer/cli/main.py`: register it in `COMMANDS`,
   `COMMAND_HELP` and `_COMM
… [dipadatkan] 300 karakter dipotong …


## Testing System

Betrayer provides a canonical testing system built on pytest. See `betrayer/ai/TESTING_CONTRACT.md` for the full contract.

## Events / Jobs / Queue / Scheduler

Betrayer provides a canonical system for event dispatch, background jobs,
queue execution, and scheduled tasks. See `betrayer/ai/EVENTS_JOBS_CONTRACT.md`
for the full contract.

**Event system** (`betrayer.core.events`):
- `EventBus` — synchronous, deterministic, in-process
- `Event(name, payload)` — structured event objects
- Handlers registered via `.on(event, handler)` / removed via `.off(event, handler)`

**Job system** (`betrayer.jobs`):
- `Job` — abstract base class with `handle() -> JobResult`
- `JobResult` — structured success/failure with metadata

**Queue** (`betrayer.jobs.Queue`):
- `queue.push(job)` / `queue.pop()` / `queue.size()` / `queue.clear()`
- In-memory backend by default (for dev/test)

**JobRunner** (`betrayer.jobs.JobRunner`):
- `runner.run_once()` / `runner.run_available()` / `runner.execute(job)`

**Scheduler** (`betrayer.jobs.Scheduler`):
- `scheduler.every(60).seconds.do(MyJob())` — fluent API
- `scheduler.schedule(job, interval_seconds)` — explicit API
- `scheduler.run_due()` — execute all due jobs

**CLI:**
```
bet queue           # show queue state
bet queue run       # run all available jobs
bet schedule        # list scheduled jobs
bet schedule run    # run all due jobs
```

Key commands: `bet test` — run full suite; `bet test --unit` — unit tests only; etc.

Key commands:

```bash
bet test              # run all tests (delegates to pytest)
bet test --unit       # unit tests only
bet test --integration
bet test --functional
bet test --smoke
bet test --json       # structured JSON output
```

Test layers (by file naming convention):

| Layer | Pattern |
|-------|---------|
| Unit | `test_*_unit.py` |
| Integration | `test_*_integration.py` |
| Functional | `test_*_functional.py` |
| Smoke | `test_*_smoke.py` |

## Realtime (WebSocket)

Betrayer provides a canonical realtime (WebSocket) capability. It is
**transport-aware but business-logic agnostic**: a WebSocket channel calls the
*same* Service the HTTP resource uses — no duplicated business logic, no second
event/tracing system. See `betrayer/ai/REALTIME_CONTRACT.md` for the full contract.

**Core building blocks** (`betrayer.web.realtime`):

* `Message` — one machine-readable realtime message (reuses `request_id` / `trace_id`).
* `Connection` — one client session (transport agnostic).
* `Channel` — a named realtime room (`/products`, `/chat`); `connect` / `send` / `broadcast` / `broadcast_except` / `disconnect`.
* `RealtimeManager` — channel/connection registry + EventBus integration.
* `FlaskRealtimeAdapter` — optional `flask_sock` transport edge (mounts on the same Flask app).

**Typical flow** (Service reuse + Event → Realtime):

```python
manager = RealtimeManager(application=app)
manager.on_event("product.created", "/products")
app.events.on("product.created", manager.handle_event)
# Service.create() -> app.events.emit("product.created", payload)
# -> RealtimeManager.handle_event -> Channel.broadcast -> all connected clients
```

**CLI:** `bet realtime` / `bet realtime --json` (introspect channels & connections).

The in-process `Channel` / `Connection` / `Message` / `RealtimeManager` work without
any extra dependency; only the live WebSocket transport needs `flask_sock`.

| Layer | Pattern |
|-------|---------|
| Unit | `test_*_unit.py` |
| Integration | `test_*_integration.py` |
| Functional | `test_*_functional.py` |
| Smoke | `test_*_smoke.py` |

Available fixtures: `application`, `database_path`, `database_config`, `database_manager` (defined in `tests/conftest.py`).

## Authentication (Task 16.1)

Authentication determines **who** the request is (identity), not **what** the
user may do (authorization).  See `betrayer/ai/AUTHENTICATION_CONTRACT.md` for
the full contract.

**Canonical API:**

```python
from betrayer.auth import Identity, AnonymousIdentity

request.user                # Identity or AnonymousIdentity
request.user.is_authenticated  # True / False
request.user.is_anonymous      # True / False
request.user.id             # stable identifier
```

**Authenticator** resolves a request to an identity:

```python
from betrayer.auth import Authenticator, HeaderTokenAuthenticator

class MyAuth(Authenticator):
    def authenticate(self, request) -> Identity | None: ...

# Built-in Bearer token support:
auth = HeaderTokenAuthenticator(resolver=my_token_resolver)
```

**Middleware** sets `request.user` on every request:

```python
from betrayer.auth import AuthenticationMiddleware

mw = AuthenticationMiddleware(authenticator=auth)
app.registry.get("web.middleware").add(mw)  # or app.container.singleton("authenticator", auth)
```

**Protected endpoints:**

```python
class ProductResource(CrudApiResource):
    authentication_required = True    # 401 UNAUTHENTICATED for anonymous
```

**Errors:**

```python
from betrayer.auth import UnauthenticatedError  # 401 UNAUTHENTICATED
from betrayer.auth import AuthenticationError    # base auth error
```

All errors use the existing `BetrayerError` hierarchy and the standard JSON
error envelope.

**What is NOT included:** JWT, OAuth, sessions, user management, RBAC, ACL.

---

## Authorization (Task 16.2)

Authorization answers **"may this identity perform this action?"** — separate
from and layered **after** Authentication.  See
`betrayer/ai/AUTHORIZATION_CONTRACT.md` for the full contract.

**Canonical API:**

```python
from betrayer.auth import Authorizer, authorize, CallbackAuthorizer

class MyAuthorizer(Authorizer):
    def authorize(self, identity, action, resource=None, context=None) -> bool: ...

# Deterministic result:
authorize(request.user, action="update", resource=product, context=context)
#   allowed → continues
#   denied  → ForbiddenError (403 FORBIDDEN, existing error envelope)
```

**DI (canonical key):**

```python
app.container.instance("authorizer", MyAuthorizer())
```

**Protect a Resource (declarative):**

```python
class ProductResource(CrudApiResource):
    authorization_required = True          # 403 FORBIDDEN when denied
    authorization_actions = {"POST": "create", "PUT": "update"}
```

**Pipeline middleware (after Authentication):**

```python
from betrayer.auth import AuthorizationMiddleware

app.registry.get("web.middleware").add(AuthorizationMiddleware())  # priority 10 > 0
```

**Errors:** `ForbiddenError` (403 `FORBIDDEN`) — from the existing
`betrayer.web.exceptions` hierarchy.  `401` remains the Authentication layer's
answer (`UNAUTHENTICATED`); `403` is Authorization's (`FORBIDDEN`).

**What is NOT included:** RBAC, ACL, role hierarchy, permission database,
policy DSL, admin UI, external identity providers.

---

## Pagination (Task 16.3)

Pagination is a canonical page-based API for collection endpoints.  See
`betrayer/ai/PAGINATION_CONTRACT.md` for the full contract.

**Canonical API** (`from betrayer.web import ...`, also re-exported from
`betrayer`):

```python
from betrayer.web import (
    PaginationParams,          # validated page/per_page (immutable)
    PaginationMetadata,        # page, per_page, total, total_pages
    PaginatedResult,           # items + metadata
    parse_pagination,          # request -> PaginationParams (validates)
    paginate_sequence,         # in-memory slice fallback
    paginate_query,            # data-layer pagination (Query/Repository)
)
```

**Defaults & limits:** `page` defaults to `1` (must be >= 1); `per_page`
defaults to `20` and is capped at `MAX_PER_PAGE = 100`.  Invalid values raise
the existing `ValidationError` (422 `VALIDATION_FAILED`) with the standard
structured field view — no second error envelope.

**Resource integration (opt-in):**

```python
class ProductResource(CrudApiResource):
    name = "products"
    prefix = "/api"
    pagination = True        # GET /api/products?page=2&per_page=20
```

The collection handler reads `page`/`per_page`, asks the service for one page
(canonical `service.paginate(page=, per_page=)`, or `list()` fallback sliced
in memory) and returns the standard collection envelope with
`meta.pagination`:

```json
{"success": true, "data": [...],
 "meta": {"resource": "products", "count": 20,
          "pagination": {"page": 2, "per_page": 20, "total": 135, "total_pages": 7}}}
```

**Data layer:** `Query` gained a minimal `query.paginate(page=, per_page=)`
returning `{"items": [...], "total": int}` built on the existing
`limit`/`offset`/`count` — no new query/ORM abstraction.  Unpaginated
resources are completely untouched.

---

## Rate Limiting (Task 16.4)

Rate limiting membatasi jumlah request berdasarkan **identity atau request key**
dalam periode tertentu.  Implementasi adalah **fixed-window**.  Lihat
`betrayer/ai/RATE_LIMITING_CONTRACT.md` untuk kontrak lengkap.

**Canonical API (`from betrayer.ratelimit import ...`):**

```python
from betrayer.ratelimit import (
    RateLimit,              # RateLimit(limit=100, window=60)
    RateLimitResult,        # result.allowed, .remaining, .reset_at
    RateLimitMiddleware,    # Web middleware (priority=5)
    FixedWindowRateLimiter, # Core limiter
    MemoryRateLimitStore,   # Default in-memory store
)
```

**Middleware integration (after Authentication, before Authorization):**

```python
from betrayer.ratelimit import RateLimitMiddleware

app.registry.get("web.middleware").add(
    RateLimitMiddleware(default=RateLimit(100, 60))
)
```

**Resource integration (opt-in):**

```python
class ProductResource(CrudApiResource):
    name = "products"
    rate_limit = RateLimit(limit=100, window=60)
```

**Response when exceeded:** HTTP 429 `RATE_LIMIT_EXCEEDED` — existing error
envelope.  Headers: `X-RateLimit-Limit`, `X-RateLimit-Remaining`,
`X-RateLimit-Reset`.

---

## Cache (Task 16.5)

Cache menyediakan canonical cache API yang backend-agnostic.  Lihat
`betrayer/ai/CACHE_CONTRACT.md` untuk kontrak lengkap.

**Canonical API (`from betrayer.data import ...`):**

```python
from betrayer.data import CacheManager, MemoryCacheBackend

cache = CacheManager()                     # in-memory by default
cache.set("key", value, ttl=60)
cache.get("key")                           # MISSING sentinel on miss
cache.get("key", default=None)             # None on miss
cache.exists("key")
cache.delete("key")
cache.clear()
cache.get_or_set("key", factory, ttl=60)
```

**Web middleware integration (opt-in per resource):**

```python
from betrayer.cache import WebCacheMiddleware, CacheManager

app.registry.get("web.middleware").add(
    WebCacheMiddleware(cache=CacheManager())
)

class ProductResource(CrudApiResource):
    name = "products"
    cache_ttl = 60   # cache GET responses for 60 seconds
```

**Response headers:** `X-Cache: HIT` / `X-Cache: MISS` on cached responses.

---


## Application Essentials Integration (Task 16.6)

The Application Essentials compose into a single deterministic request pipeline:

```
Request
  ↓
Authentication          (priority=0)
  ↓
Rate Limiting           (priority=5)
  ↓
Authorization           (priority=10)
  ↓
Validation
  ↓
Resource (handler)
  ↓
Pagination              (opt-in, inside Resource)
  ↓
Cache (after_response)  (priority=20)
  ↓
Response
```

### Middleware Ordering

| Middleware                | Priority | Responsibility                              |
|--------------------------|----------|---------------------------------------------|
| `AuthenticationMiddleware` | 0        | Resolves `request.user` (Identity / AnonymousIdentity) |
| `RateLimitMiddleware`      | 5        | Enforces rate limit using identity-based keys |
| `AuthorizationMiddleware`  | 10       | Checks permission against the Authorizer     |
| `WebCacheMiddleware`       | 20       | Caches GET/HEAD responses (after security)   |

The cache middleware runs **after all security middleware** (priority 20 > 10 > 5 > 0)
so that a cached response is **never served before authentication, rate limiting,
or authorization have run** on every request.

### Security Semantics

| Condition                     | HTTP  | Error Code              |
|-------------------------------|-------|-------------------------|
| Authentication required + missing | 401 | `UNAUTHENTICATED`       |
| Authorized required + denied  | 403 | `FORBIDDEN`             |
| Rate limit exceeded           | 429 | `RATE_LIMIT_EXCEEDED`   |
| Invalid pagination            | 422 | `VALIDATION_FAILED`     |

### Cache Identity Isolation

The HTTP response cache (`WebCacheMiddleware`) includes the authenticated user
identity in the **cache key** when present:

- `user:42:GET:/api/products?page=2&per_page=20` for authenticated user id=42
- `GET:/api/products?page=2&per_page=20` for anonymous requests (no prefix)

This ensures **no cross-user response leakage**: User A never receives User B's
cached response.  Raw authorization tokens are never used as cache keys.

### Resource Declaration

```python
from betrayer.ratelimit import RateLimit

class ProductResource(CrudApiResource):
    name = "products"
    authentication_required = True     # 401 for anonymous
    authorization_required = True       # 403 for unauthorized
    authorization_action = "view"       # default action
    pagination = True                   # paginated GET collection
    rate_limit = RateLimit(limit=100, window=60)   # rate limited
    cache_ttl = 60                      # GET responses cached 60s
```

All flags are independent — a resource may opt into any subset.

### Key Contracts

- `betrayer/ai/AUTHENTICATION_CONTRACT.md` — Identity, Authenticator, middleware
- `betrayer/ai/AUTHORIZATION_CONTRACT.md` — Authorizer, `authorize()`, policies
- `betrayer/ai/PAGINATION_CONTRACT.md` — PaginationParams, paginate helpers
- `betrayer/ai/RATE_LIMITING_CONTRACT.md` — RateLimit, store, middleware
- `betrayer/ai/CACHE_CONTRACT.md` — CacheManager, CachePolicy, WebCacheMiddleware

### Integration Tests

`tests/test_application_essentials_integration.py` contains 41 tests covering:

1. Authentication + Authorization integration (separate responsibilities)
2. Authentication + Rate Limiting (identity-based keys, no leak)
3. Rate Limiting + Authorization (blocked request never reaches authz)
4. Authentication + Cache (user-specific cache keys, no bypass)
5. Authorization + Cache (authorization runs before cache)
6. Pagination + Cache (per-page keys, canonical ordering)
7. Rate Limiting + Cache (cached requests still counted)
8. Full protected paginated cached endpoint (MISS → HIT round-trip)
9. Error consistency
10. Resource contract independence
11. Unconfigured resource regression
12. DI / Container integration

---

- Do not make Betrayer an AI agent.
- Do not put business logic in Application.
- Do not create global mutable singletons.
- Do not make core depend on CLI or future layers.
- Do not assume Unix/Linux shell behavior.
- Do not hardcode path separators.
- Do not print secrets in any output.
- Do not create abstraction layers just to look sophisticated.

## Error Handling

All Betrayer exceptions inherit from `BetrayerError` and carry:
- `code` — machine-readable error code
- `component` — which subsystem raised it
- `stage` — lifecycle stage when it occurred
- `cause` — original exception (if any)

## Validation

Run `python -m betrayer validate` to check:
- Imports
- Package structure
- Lifecycle
- Configuration
- Environment
- Runtime
- Tests (if available)

## Diagnosis

Run `python -m betrayer doctor` for real health checks.
The doctor inspects actual runtime state, not guesses.
