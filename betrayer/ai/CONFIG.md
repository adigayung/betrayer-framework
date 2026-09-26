# Betrayer Framework — Configuration

## Config Class

`Config` is the central configuration container for Betrayer.

## Features

- **Default values** — Set at construction time.
- **Environment variable overrides** — `BETRAYER_<SECTION>__<KEY>=value`.
- **Explicit overrides** — Set values programmatically.
- **Typed access** — Get values with type conversion.
- **Nested keys** — Dot notation for nested configuration (`"app.name"`).
- **Immutable after finalisation** — Once finalised, values cannot change.
- **Secret masking** — Keys containing `secret`, `key`, `token`, `password` are masked in output.

## Usage

```python
from betrayer.core.config import Config

config = Config(defaults={
    "app.name": "my-app",
    "app.debug": False,
    "database.host": "localhost",
    "database.port": 5432,
})

# Get values
name = config.get("app.name")        # → "my-app"
debug = config.get("app.debug")      # → False
port = config.get("database.port")   # → 5432

# Set values (before finalisation)
config.set("app.debug", True)

# Finalise (make immutable)
config.finalise()

# Check if key exists
"app.name" in config                  # → True

# Get all keys (non-secret only for safe display)
config.keys(safe=True)                # → ["app.name", "app.debug", ...]
```

## Environment Variable Overrides

Set environment variables with double underscores for nested keys:

```bash
# Windows CMD
set BETRAYER_APP__DEBUG=1

# PowerShell
$env:BETRAYER_APP__DEBUG=1
```

This overrides `config.get("app.debug")` with `True`.

## Secret Masking

Keys containing these words (case-insensitive) are masked:
- `secret`
- `key`
- `token`
- `password`

Example:
```python
config.set("api.secret_key", "super-secret")
config.get("api.secret_key")         # → "super-secret" (access works)
config.safe_data()                    # → {"api.secret_key": "****"}
```

## Inspection

```python
# Safe inspection (no secrets)
config.safe_data()

# Full inspection (all values, including secrets)
# Only use in trusted contexts
config.data()
```

## Error Handling

- `ConfigurationError` — Raised for invalid configuration operations.
- Missing keys raise `KeyError` (standard Python behavior).
- Type mismatches raise `TypeError`.
