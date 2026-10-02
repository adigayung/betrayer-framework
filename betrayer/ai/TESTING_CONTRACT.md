# Betrayer Testing System — Contract for LLM Agents

This document describes the canonical testing system for Betrayer applications.

## TL;DR

```
bet test                 # run all tests
bet test --unit          # run only unit tests
bet test --integration   # run only integration tests
bet test --functional    # run only functional/API tests
bet test --smoke         # run only smoke tests
bet test --json          # structured JSON output for LLM processing
bet test tests/test_foo.py  # run a specific file
```

Exit code: `0` = all passed, non-zero = some failed.

## Principles

1. **pytest is the test runner.** Betrayer does not replace pytest. The `bet test` CLI delegates to pytest under the hood.
2. **Convention over configuration.** Test file names determine test layer (unit/integration/functional/smoke).
3. **One canonical workflow.** Every Betrayer project uses the same test structure and CLI.
4. **LLM-friendly output.** `--json` produces structured output the LLM can parse without reading pytest output.

## Test Layers

Tests are categorised into four layers by file naming convention:

| Layer | File Pattern | Purpose |
|-------|-------------|---------|
| Unit | `test_*_unit.py` | Pure logic, no database/IO. Mock dependencies. |
| Integration | `test_*_integration.py` | Database + ORM + Repository. Real SQLite. |
| Functional | `test_*_functional.py` | HTTP API via Flask test client. Full stack. |
| Smoke | `test_*_smoke.py` | Full bootstrap + one critical path. |

Each layer builds on the layers below it:

```
Unit → Integration → Functional → Smoke
```

A unit test failure blocks nothing else; a smoke test failure means the application is fundamentally broken.

## Test Discovery

Test files live in the `tests/` directory and follow these conventions:

```
tests/
  conftest.py                 # shared fixtures (framework provided)
  test_products_unit.py       # unit tests
  test_products_integration.py# integration tests
  test_products_functional.py # functional tests
  test_products_smoke.py      # smoke tests
  test_foundation.py          # existing tests (not layer-tagged)
  ...
```

The layer flags (`--unit`, `--integration`, etc.) discover tests by matching the file name patterns above. Tests that do not follow the naming convention are run by `bet test` without flags but are excluded from layer-specific runs.

## `bet test` CLI

### Usage

```
bet test [test_path] [--unit] [--integration] [--functional] [--smoke] [--json]
```

```
bet test affected [--run] [--list] [--json] [test_path...]
```

### Examples

```bash
# Run every test in tests/
bet test

# Run only unit tests
bet test --unit

# Run integration and functional together
bet test --integration --functional

# Run a specific test file
bet test tests/test_products_functional.py

# Structured JSON output
bet test --json

# Structured JSON for a layer
bet test --smoke --json

# Affected tests: detect git-changed files, map to tests, run them
bet test affected              # auto-detect changes, run affected tests
bet test affected --list       # list affected tests only (no run)
bet test affected --run        # same as default (explicit)
bet test affected --json       # structured JSON (no run, inspect first)
bet test affected tests/test_foo.py  # override detection, run specific test
```

### Exit codes

| Exit code | Meaning |
|-----------|---------|
| 0 | All tests passed |
| 1 | One or more tests failed |
| Other | pytest internal error (syntax error, missing dependency, etc.) |

### Affected Tests Output (JSON)

```json
{
  "success": true,
  "changed_files": ["betrayer/cache/policy.py"],
  "affected_tests": ["tests/test_cache.py"],
  "affected_count": 1,
  "determined": true,
  "reasons": {
    "tests/test_cache.py": ["imports/is betrayer.cache.policy"]
  },
  "note": null
}
```

When no affected test can be determined:

```json
{
  "success": true,
  "changed_files": [],
  "affected_tests": [],
  "affected_count": 0,
  "determined": false,
  "note": "no affected tests could be determined"
}
```

### Exit codes

| Exit code | Meaning |
|-----------|---------|
| 0 | All tests passed |
| 1 | One or more tests failed |
| Other | pytest internal error (syntax error, missing dependency, etc.) |

## Fixtures

Shared fixtures are provided in `tests/conftest.py`. These are the *only* framework-provided fixtures; project-specific fixtures go in their own conftest.

| Fixture | Scope | Returns |
|---------|-------|---------|
| `application` | function | A READY `BetrayerApplication` (no database) |
| `database_path` | function | `Path` to a temporary SQLite file (cleaned up) |
| `database_config` | function | `Config` pointing to the temporary SQLite |
| `database_manager` | function | Connected `DatabaseManager` over temporary SQLite |

Example usage:

```python
def test_something(database_manager):
    database_manager.execute("CREATE TABLE test (id INT)")
    rows = database_manager.execute("SELECT 1 AS x").get("rows")
    assert rows[0]["x"] == 1
```

## JSON Result Format

```json
{
  "success": false,
  "total": 609,
  "passed": 556,
  "failed": 53,
  "skipped": 0,
  "duration": 39.272,
  "failures": [
    {
      "test": "test_create_product",
      "file": "tests/test_products_functional.py",
      "line": 42,
      "message": "expected 201, got 422"
    }
  ]
}
```

### Fields

| Field | Type | Description |
|-------|------|-------------|
| `success` | bool | `true` when exit code is 0 |
| `total` | int | Total number of collected tests |
| `passed` | int | Number of passed tests |
| `failed` | int | Number of failed tests |
| `skipped` | int | Number of skipped tests |
| `duration` | float | Wall-clock seconds |
| `failures` | list | Array of failure objects (empty on success) |

### Failure object

| Field | Type | Description |
|-------|------|-------------|
| `test` | str | Test method/function name |
| `file` | str | File path (relative to project root) |
| `line` | int | Line number of the assertion |
| `message` | str | Short failure message (first line) |

### Human-readable output (without `--json`)

```text
TEST_RESULT: FAIL
total: 3  passed: 2  failed: 1  skipped: 0
duration: 1.234s

TEST_FAILED
test: test_create_product
file: tests/test_products_functional.py
line: 42
message: expected 201, got 422
```

## Adding Tests to a Project

1. Create test files in `tests/` following the naming convention.
2. Use the shared fixtures from `tests/conftest.py` when appropriate.
3. Add project-specific fixtures in a local `conftest.py`.
4. Run with `bet test`.

Example project structure:

```
my-project/
  betrayer/               # framework
  my_app/                 # your application
  tests/
    conftest.py           # shared fixtures
    test_app_unit.py      # unit tests
    test_app_integration.py  # integration tests
    test_app_functional.py   # functional tests
    test_app_smoke.py        # smoke tests
```

## Writing Tests by Layer

### Unit Tests

- Pure logic only: no database, no network, no filesystem.
- Mock external dependencies with `unittest.mock`.
- Test one class/method at a time.

```python
from unittest.mock import MagicMock
from my_app.service import MyService

def test_service_computes_value():
    repo = MagicMock()
    repo.all.return_value = [{"value": 10}]
    service = MyService(repo)
    assert service.compute_total() == 10
```

### Integration Tests

- Use a real SQLite database (temporary, per-function scope).
- Use `database_path`, `database_config`, or `database_manager` fixtures.
- Test repository + ORM interactions.

```python
def test_repository_crud(database_manager):
    from my_app.models import Product
    Product.__connection__ = database_manager
    # ... test create, find, update, delete
```

### Functional Tests

- Use Flask test client.
- Test HTTP endpoints end-to-end.
- Use real database (temporary SQLite).

```python
def test_api_create(client):
    resp = client.post("/api/products", json={"name": "Widget", "price": 1.0})
    assert resp.status_code == 201
    assert resp.get_json()["data"]["name"] == "Widget"
```

### Smoke Tests

- Boot the full application from scratch.
- Execute one critical path (create → read).
- Verify persistence across connections.

```python
def test_smoke(tmp_path):
    app = build_application(database_path=tmp_path / "smoke.db")
    client = create_flask_app(app).test_client()
    resp = client.post("/api/products", json={"name": "Smoke", "price": 1.0, "stock": 1})
    assert resp.status_code == 201
```

## Test Isolation

Integration and functional tests use temporary SQLite databases created per-test-function:

1. `database_path` creates a unique temporary file.
2. Each test gets a fresh database (fresh schema applied).
3. The file is deleted after the test (best-effort).

This means:
- Tests never modify the development database.
- Tests are fully isolated from each other.
- Tests can run in parallel (in theory; pytest-xdist is not required).

## Limitations

- Layer filtering (`--unit`, `--integration`, etc.) works by file name pattern matching, not pytest markers.
- Tests that don't follow the naming convention are run by `bet test` but excluded from layer-specific runs.
- The testing system does not replace pytest plugins. Use `pytest.ini` / `pyproject.toml` for advanced configuration.
- No built-in code coverage (use `pytest-cov` separately).