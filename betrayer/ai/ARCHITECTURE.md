# Betrayer Framework — Architecture

## Overview

Betrayer is an LLM-first Python framework. It provides structure, contracts,
tools, validation, and runtime hands for coding agents.

## Layers

### Core (foundation)
- **Config**: Typed, inspectable configuration with env var overrides.
- **Environment**: Runtime environment detection (OS, Python, paths, etc.).
- **Lifecycle**: Deterministic state machine (CREATED → BOOTSTRAPPING → READY → RUNNING → STOPPING → STOPPED / FAILED).
- **Registry**: Component registry for loose coupling.
- **Exceptions**: Hierarchical error system with code, component, stage, cause.

### Runtime
- **RuntimeContext**: Container holding references to core subsystems.
  Not a global singleton — passed explicitly.

### Diagnostics
- **Inspector**: Inspection and validation tools.
  Provides `info`, `environment`, `status`, `doctor`, `validate` commands.

### CLI
- **main**: Command-line interface using argparse.
  Delegates to framework public APIs only.

### AI Surface
- **ai/**: LLM-facing documentation in markdown (contracts, patterns, this map)
  **and** the capability discovery package — `betrayer.ai.capabilities` (the
  canonical capability registry) and `betrayer.ai.discover` (the LLM entry point
  `list` / `get` / `search` / `summary`). `betrayer/ai` is importable and depends
  only on the standard library.

## Dependency Rules

1. `core` has NO Betrayer dependencies.
2. `runtime` depends only on `core`.
3. `diagnostics` depends on `core` and `runtime`.
4. `cli` depends on `core`, `runtime`, and `diagnostics`.
5. `ai` depends on `core`, `runtime`, and `diagnostics`.

## Extension Points

- **Lifecycle handlers**: Subsystems can register callbacks for lifecycle events.
- **Registry**: Subsystems can register custom components.
- **Config**: Typed configuration with validation.
- **Environment**: Runtime inspection.

## Generated Metadata

`.betrayer/manifest.json` and `.betrayer/architecture.json` are GENERATED from
runtime state (`betrayer.core.meta` plus the package and CLI surface) by the
builders in `betrayer/cli/main.py` (`build_manifest`, `build_architecture`).

- Never hand edit them; run `python -m betrayer manifest --write`.
- `python -m betrayer validate` reports drift in its `metadata` section.
- `version` and `architecture_version` are read from `betrayer/core/meta.py`,
  so a metadata file can never claim a version the code does not have.

## State Machine

```
CREATED
  ↓ bootstrap()
BOOTSTRAPPING
  ↓ initialize()
READY
  ↓ start()
RUNNING
  ↓ stop()
STOPPING
  ↓ shutdown()
STOPPED

Any state → on_error() → FAILED
```

## Key Design Decisions

1. **No boolean state flags.** Use `LifecycleState` enum.
2. **No global mutable singletons.** RuntimeContext is explicit.
3. **No secret leakage.** Config masks secret keys in output.
4. **Windows first-class.** All path handling uses pathlib.
5. **Deterministic bootstrap.** Same steps, same order.
6. **No future subsystems as placeholders.** Only build what exists now.
