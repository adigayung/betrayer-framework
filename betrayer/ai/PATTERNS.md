# Betrayer Framework — Patterns and Conventions

## Naming Conventions

- **Package names**: lowercase, `snake_case` (`betrayer.core`, `betrayer.runtime`).
- **Module names**: lowercase, `snake_case` (`config.py`, `environment.py`).
- **Class names**: `PascalCase` (`BetrayerApplication`, `Lifecycle`).
- **Function/method names**: `snake_case` (`bootstrap`, `get_config`).
- **Constants**: `UPPER_SNAKE_CASE` (`LifecycleState.CREATED`).
- **Private members**: leading underscore (`_components`).
- **Public API**: no leading underscore, type hints required.

## Type Hints

All public APIs must use type hints:

```python
def bootstrap(self) -> None: ...
def get(self, key: str, default: T | None = None) -> T | None: ...
```

## Import Order

1. Standard library imports
2. Third-party imports (none in foundation)
3. Local imports (`from betrayer.xxx import ...`)

## Path Handling

- Always use `pathlib.Path` for file paths.
- Never hardcode path separators (`/` or `\`).
- Use `.resolve()` for absolute paths.
- Use `.exists()` and `.is_dir()` for checks.

## No Global Mutable State

- `RuntimeContext` is not a singleton — it is passed explicitly.
- `Config` is immutable after finalisation.
- `EnvironmentInfo` is frozen (immutable dataclass).
- `Registry` is per-Application, not global.

## Extension Points

- **Lifecycle handlers**: Register callbacks for state changes.
- **Registry**: Register custom components by name.
- **Config**: Add new configuration keys.
- **Environment**: Add new detection fields.

## Adding a CLI Command

1. Implement `_cmd_<name>(args: argparse.Namespace) -> int` in
   `betrayer/cli/main.py`. Return a real exit code, print short deterministic
   output, and honour `--json` through `_print_json`.
2. Register the name in `COMMANDS`, add help text in `COMMAND_HELP`, and map it
   in `_COMMAND_HANDLERS`.
3. The command must build a READY application through `Bootstrap` and read
   state through `betrayer.diagnostics.Inspector`.
4. Add a test in `tests/test_foundation.py` that parses it with
   `build_parser()`.

## Regenerating Generated Metadata

After changing `betrayer/core/meta.py`, the package list, or the CLI surface:

```
python -m betrayer manifest --write
```

`.betrayer/manifest.json` and `.betrayer/architecture.json` are GENERATED
files — never hand edit them. `python -m betrayer validate` reports drift in
its `metadata` section.

## What NOT to Create

- Do not create abstraction layers just to look sophisticated.
- Do not create placeholder subsystems (database, auth, cache) that are empty.
- Do not create global singletons that are hard to test.
- Do not create circular imports between packages.

## Testing Conventions

- Tests live in `tests/` directory.
- Test files mirror source structure (`tests/test_lifecycle.py` for `core/lifecycle.py`).
- Tests do not modify framework source.
- Tests use pytest.
- Test names are descriptive (`test_lifecycle_transition_ready_to_running`).

## Documentation Conventions

- AI documentation in `betrayer/ai/` (markdown).
- Machine-readable metadata in `.betrayer/` (JSON).
- Documentation is written for LLM agents, not humans.
- Every public API has a docstring.
