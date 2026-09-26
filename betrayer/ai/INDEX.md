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
  ai/                  # LLM-facing documentation
```

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
| `python -m betrayer doctor`| Foundation health checks             |
| `python -m betrayer validate` | Validate framework integrity     |
| `python -m betrayer config` | Show configuration (secrets masked)|
| `python -m betrayer manifest` | Show generated metadata; `--write` regenerates it |

Every command supports `--json` (valid JSON, sorted keys) and returns a real
exit code: `0` = success, non-zero = failure.

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


## What NOT to Do

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
