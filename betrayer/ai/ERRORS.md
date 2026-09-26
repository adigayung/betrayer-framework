# Betrayer Framework — Error System

## Exception Hierarchy

```
BetrayerError (Base)
├── BootstrapError
├── ConfigurationError
├── EnvironmentError
├── LifecycleError
├── RuntimeError
├── RegistryError
└── InspectionError
```

## BetrayerError

Base class for all Betrayer errors. Every exception carries:

| Field     | Description                          |
|-----------|--------------------------------------|
| `message` | Human-readable error message         |
| `code`    | Machine-readable error code          |
| `component` | Which subsystem raised it          |
| `stage`   | Lifecycle stage when error occurred  |
| `cause`   | Original exception (if wrapped)      |

## Usage

```python
from betrayer.core.exceptions import LifecycleError

raise LifecycleError(
    message="Failed to transition to READY",
    code="LIFECYCLE_INVALID_TRANSITION",
    component="lifecycle",
    stage="bootstrapping",
    cause=original_exception,
)
```

## Error Codes

Error codes follow the pattern `{COMPONENT}_{ERROR_TYPE}`:

- `BOOTSTRAP_FAILED` — Bootstrap process failed.
- `CONFIG_INVALID_KEY` — Configuration key not found or invalid.
- `CONFIG_FINALISED` — Attempted to modify finalised config.
- `ENVIRONMENT_DETECTION_FAILED` — Environment detection failed.
- `LIFECYCLE_INVALID_TRANSITION` — Invalid state transition.
- `LIFECYCLE_ALREADY_IN_STATE` — Already in target state.
- `RUNTIME_CONTEXT_MISSING` — Required runtime context is missing.
- `REGISTRY_COMPONENT_NOT_FOUND` — Component not registered.
- `INSPECTION_FAILED` — Inspection/diagnostic failed.

## Error Handling in Lifecycle

When a lifecycle stage fails:
1. The error is caught and recorded.
2. Lifecycle transitions to FAILED.
3. `on_error` handlers are invoked.
4. The error is re-raised as the appropriate `BetrayerError` subclass.

## LLM-Friendly Errors

Errors are designed to be easily parsed by LLMs:
- Structured fields (code, component, stage) — not buried in message text.
- Cause chain preserved — original exception accessible.
- No noisy formatting — just the facts.
- Machine-readable error codes for programmatic handling.
