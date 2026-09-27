# Diagnostics Contract

**Version:** 1.0  
**Applies to:** Betrayer `>= 0.1.0`

---

## 1. Overview

Betrayer provides a canonical diagnostics subsystem for checking,
tracing, and debugging applications.

```text
Problem
  ↓
Check         (bet check)   — quick health check
Doctor        (bet doctor)  — in-depth diagnostics
Debug         (bet debug)   — request/error inspection
```

All diagnostics commands produce **structured JSON output** with
`--json`.  Human-readable output follows the same format.

---

## 2. `bet check`

Quick project/framework health check.

### Usage

```
bet check              Human-readable output (exit 0 = pass, 1 = errors)
bet check --json       Machine readable JSON
```

### JSON Contract

```json
{
  "success": true,
  "status": "PASS",
  "checks": [
    {
      "name": "project_structure",
      "status": "PASS",
      "message": "All required files and directories found."
    },
    {
      "name": "configuration",
      "status": "PASS",
      "message": "2 configuration keys available."
    },
    {
      "name": "database_configuration",
      "status": "WARNING",
      "message": "No database driver configured (optional for non-DB apps)."
    }
  ],
  "summary": {
    "passed": 8,
    "warnings": 1,
    "errors": 0,
    "total": 9
  }
}
```

### Check categories

| Check | Status | Description |
|-------|--------|-------------|
| `project_structure` | PASS/WARNING/ERROR | Required files and directories |
| `configuration` | PASS/WARNING/ERROR | Configuration validity |
| `environment` | PASS/WARNING/ERROR | Environment detection |
| `imports` | PASS/WARNING/ERROR | Module importability |
| `module_registration` | PASS/WARNING | Module system state |
| `database_configuration` | PASS/WARNING | Database driver/config |
| `migration_state` | PASS/WARNING | Migration registry |
| `application_bootstrap` | PASS/WARNING/ERROR | Application lifecycle |
| `required_dependencies` | PASS/WARNING/ERROR | Package availability |

### Exit codes

- `0` — all checks passed or only warnings
- `1` — at least one ERROR

---

## 3. `bet doctor`

In-depth diagnostics.  May run more intrusive checks (probe applications,
connection tests).

### Usage

```
bet doctor             Human-readable output
bet doctor --json      Machine readable JSON
```

### JSON Contract

```json
{
  "framework": "Betrayer",
  "version": "0.1.0",
  "ok": true,
  "status": "pass",
  "checks": [
    {
      "name": "Python",
      "status": "ok",
      "reason": "",
      "suggestion": "",
      "detail": "3.11.5 (CPython) on Windows 10"
    },
    {
      "name": "Database",
      "status": "ok",
      "detail": "driver=sqlite, database=app.db"
    }
  ],
  "summary": "9/9 checks passed"
}
```

### Doctor checks

| Check | Description |
|-------|-------------|
| `Python` | Python version >= 3.9 |
| `Environment` | OS, mode, project root |
| `Configuration` | Keys, secret masking |
| `Package imports` | Foundation module imports |
| `Application lifecycle` | Full lifecycle transition on probe |
| `Runtime state` | Runtime context independence |
| `Database` | Database driver/configuration |
| `Migration` | Migration registry state |
| `Application bootstrap` | Application state |

---

## 4. `bet debug`

Request/error inspection and trace.

### Usage

```
bet debug                      Diagnostics summary
bet debug --json               Diagnostics summary (JSON)
bet debug last                 Last recorded record
bet debug last --json          Last record (JSON)
bet debug errors               Error records
bet debug errors --json        Error records (JSON)
bet debug trace <request_id>   Request trace by ID
bet debug inspect <request_id> Detailed request inspection
```

### JSON Contract (summary)

```json
{
  "name": "myapp.diagnostics",
  "total_records": 42,
  "errors": 3,
  "warnings": 5,
  "requests_tracked": 10,
  "traces_recorded": 10,
  "recent": [
    {
      "code": "REQUEST_ERROR",
      "component": "web",
      "level": "error",
      "message": "NotFoundError: Product not found",
      "request_id": "a1b2c3d4e5f6",
      "trace_id": "g7h8i9j0k1l2m3n4",
      "context": {},
      "suggested_actions": ["Check the product ID."],
      "timestamp": 1700000000.0
    }
  ]
}
```

### JSON Contract (trace)

```json
{
  "request_id": "a1b2c3d4e5f6",
  "trace": [
    {"layer": "http", "component": "TraceMiddleware", "status": "ok",
     "duration_ms": 0.0, "detail": "GET /api/products", "error": null},
    {"layer": "resource", "component": "ProductResource.list_handler",
     "status": "ok", "duration_ms": 1.2, "detail": "", "error": null},
    {"layer": "service", "component": "ProductService.list",
     "status": "ok", "duration_ms": 0.8, "detail": "", "error": null},
    {"layer": "repository", "component": "ProductRepository.find",
     "status": "ok", "duration_ms": 0.5, "detail": "", "error": null},
    {"layer": "orm", "component": "Model.query", "status": "ok",
     "duration_ms": 0.3, "detail": "", "error": null},
    {"layer": "database", "component": "DatabaseManager.execute",
     "status": "ok", "duration_ms": 2.1, "detail": "", "error": null}
  ]
}
```

---

## 5. Request / Trace ID

Every HTTP request receives two identifiers:

- `request_id` — short (12 hex chars), generated per request
- `trace_id` — longer (16 hex chars), stable across retries

Both are set as thread-local values and attached to the `WebContext`
so handlers and middleware can access them:

```python
from betrayer.diagnostics import get_current_request_id, get_current_trace_id

request_id = get_current_request_id()
trace_id = get_current_trace_id()
```

From an incoming request the IDs can be injected via headers:

- `X-Request-Id` — request ID (auto-generated if absent)
- `X-Trace-Id` — trace ID (auto-generated if absent)

---

## 6. Structured Diagnostic Record

Every diagnostic record follows this contract:

```json
{
  "timestamp": 1700000000.0,
  "code": "ERROR_CODE",
  "component": "subsystem_name",
  "level": "error",
  "message": "Human readable description",
  "request_id": "a1b2c3d4e5f6",
  "trace_id": "g7h8i9j0k1l2m3n4",
  "context": {
    "key": "value"
  },
  "suggested_actions": [
    "Step 1: ...",
    "Step 2: ..."
  ],
  "trace": [
    {"layer": "http", "component": "...", "status": "ok", "duration_ms": 0.0}
  ]
}
```

### Fields

| Field | Type | Description |
|-------|------|-------------|
| `timestamp` | `float` | Unix timestamp of the record |
| `code` | `string` | Stable error code (e.g. `BOOTSTRAP_COMPLETE`, `REQUEST_ERROR`) |
| `component` | `string` | Subsystem that generated the record |
| `level` | `string` | One of `info`, `warning`, `error`, `debug` |
| `message` | `string` | Single-line human readable description |
| `request_id` | `string\|null` | Request identifier |
| `trace_id` | `string\|null` | Trace identifier |
| `context` | `object` | Structured details (safe, no secrets) |
| `suggested_actions` | `string[]` | Actionable steps to resolve |
| `trace` | `object[]` | Request trace steps |

### Levels

| Level | Meaning |
|-------|---------|
| `info` | Normal operation, bootstrapping |
| `warning` | Potential problem, non critical |
| `error` | Failure, requires intervention |
| `debug` | Detailed diagnostic (future use) |

---

## 7. Error Codes

| Code | Component | Description |
|------|-----------|-------------|
| `BOOTSTRAP_COMPLETE` | bootstrap | Application bootstrapped successfully |
| `REQUEST_ERROR` | web | Unhandled request error |
| `DATABASE_CONNECTION` | database | Database connection issue |
| `MIGRATION_FAILED` | migration | Schema migration failure |
| `VALIDATION_ERROR` | web | Request validation failed |

---

## 8. Secret Masking

Secrets are never exposed in diagnostic output:

- Configuration values for secret keys (`password`, `token`, `api_key`, ...)
  are replaced with `"****"` in the diagnostics store.
- The `Inspector.config()` method returns `Config.safe_data()` which
  masks secrets automatically.
- Context dictionary values for secret keys are masked before storage.

---

## 9. JSON Output

All diagnostics commands support `--json` for machine consumption.

The output is always valid JSON with:
- Sorted keys
- `indent=2` formatting
- Non-serializable values converted via `str()`

---

## 10. Exit Codes

| Exit Code | Meaning |
|-----------|---------|
| `0` | Success / all checks passed |
| `1` | Failure / errors detected |
| `2` | Command usage error |