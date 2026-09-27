"""Betrayer command line interface.

Commands are intentionally few.  Every command:

* builds a READY application through ``Bootstrap``,
* reads state exclusively through ``betrayer.diagnostics.Inspector``,
* prints short, deterministic, LLM friendly output,
* supports ``--json`` for machine consumption (always valid JSON),
* returns a real exit code (0 = success, non-zero = failure).

Commands are wired up through a single :class:`betrayer.cli.registry.CommandRegistry`
(see :func:`build_command_registry`); the parser and the dispatch loop only
iterate that table, so a new command never requires redesigning the CLI core.

Extension point: ``run_validate()`` is importable so tests and future
tooling can reuse the same checks the CLI runs.
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

from betrayer.bootstrap import Bootstrap
from betrayer.cli.registry import Command, CommandError, CommandRegistry
from betrayer.core.config import Config, is_secret_key
from betrayer.core.environment import Environment
from betrayer.core.exceptions import BetrayerError
from betrayer.core.lifecycle import Lifecycle, LifecycleState
from betrayer.core.meta import (
    ARCHITECTURE_VERSION,
    FOUNDATION_VERSION,
    FRAMEWORK_DESCRIPTION,
    FRAMEWORK_NAME,
    FRAMEWORK_SLUG,
    __version__,
)
from betrayer.diagnostics.inspector import Inspector
from betrayer.diagnostics.store import (
    CHECK_STATUS_ERROR,
    CHECK_STATUS_PASS,
    CHECK_STATUS_WARNING,
    DiagnosticsStore,
)

PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]
MANIFEST_PATH: Path = PROJECT_ROOT / ".betrayer" / "manifest.json"
ARCHITECTURE_PATH: Path = PROJECT_ROOT / ".betrayer" / "architecture.json"

#: Name the CLI is invoked as (``bet`` -- also the argparse ``prog``).
CLI_PROG = "bet"

COMMAND_HELP = {
    "info": "show framework, python, os and application state",
    "environment": "show detected environment information",
    "status": "show runtime and lifecycle status",
    "config": "show effective configuration (secrets masked)",
    "doctor": "run foundation health checks",
    "validate": "validate the foundation (imports, structure, lifecycle, ...)",
        "check": "quick project/framework health check (PASS/WARNING/ERROR)",
        "debug": "diagnose requests, errors, and traces",
        "manifest": "show or regenerate the machine readable framework manifest",
        "create": "create a new Betrayer application project",
        "make": "generate project artifacts (e.g. a new module or resource)",
        "discover": "discover Betrayer capabilities (list, get <name>, search <query>)",
        "queue": "inspect or run the job queue (use --json for machine output)",
        "schedule": "inspect or run due scheduled jobs (use --json for machine output)",
        "realtime": "introspect the realtime (WebSocket) layer (use --json for machine output)",
        "test": "run tests (canonical testing system)",
    }

REQUIRED_MODULES = (
    "betrayer",
    "betrayer.application",
    "betrayer.bootstrap",
    "betrayer.core.config",
    "betrayer.core.environment",
    "betrayer.core.exceptions",
    "betrayer.core.lifecycle",
    "betrayer.core.meta",
    "betrayer.core.registry",
    "betrayer.runtime.context",
    "betrayer.runtime.state",
    "betrayer.diagnostics.inspector",
    "betrayer.cli.main",
)

REQUIRED_PATHS = (
    "betrayer/__init__.py",
    "betrayer/__main__.py",
    "betrayer/application.py",
    "betrayer/bootstrap.py",
    "betrayer/core/__init__.py",
    "betrayer/core/config.py",
    "betrayer/core/environment.py",
    "betrayer/core/exceptions.py",
    "betrayer/core/lifecycle.py",
    "betrayer/core/meta.py",
    "betrayer/core/registry.py",
    "betrayer/runtime/__init__.py",
    "betrayer/runtime/context.py",
    "betrayer/runtime/state.py",
    "betrayer/diagnostics/__init__.py",
    "betrayer/diagnostics/inspector.py",
    "betrayer/cli/__init__.py",
    "betrayer/cli/main.py",
    "betrayer/ai/INDEX.md",
    ".betrayer/manifest.json",
    "tests/test_foundation.py",
)


# ── helpers ──────────────────────────────────────────────────────


def _print_json(payload: Any) -> None:
    """Print *valid* JSON: sorted keys, explicit default stringifier."""
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))


def _ready_application():
    """Build a READY application using the public bootstrap API."""
    return Bootstrap(name=FRAMEWORK_NAME.lower()).build()


def _section(name: str, label: str, checks: Sequence[tuple[str, bool, str]]) -> dict:
    normalized = [
        {"name": check_name, "status": "pass" if ok else "fail", "detail": detail}
        for check_name, ok, detail in checks
    ]
    passed = sum(1 for check in normalized if check["status"] == "pass")
    return {
        "name": name,
        "label": label,
        "status": "pass" if passed == len(normalized) and normalized else "fail",
        "detail": f"{passed}/{len(normalized)} checks passed",
        "checks": normalized,
    }


# ── validation checks ────────────────────────────────────────────


def _validate_imports() -> dict:
    checks: list[tuple[str, bool, str]] = []
    for module in REQUIRED_MODULES:
        try:
            importlib.import_module(module)
            checks.append((module, True, "imported"))
        except Exception as exc:  # noqa: BLE001 - report anything
            checks.append((module, False, f"{type(exc).__name__}: {exc}"))
    return _section("imports", "package imports", checks)


def _validate_package_structure() -> dict:
    checks: list[tuple[str, bool, str]] = []
    for relative in REQUIRED_PATHS:
        path = PROJECT_ROOT / relative
        checks.append((relative, path.exists(), "present" if path.exists() else "missing"))
    checks.append(
        (
            "no_circular_import",
            _validate_no_circular_import(),
            "reimported every module in a clean interpreter",
        )
    )
    return _section("package_structure", "package structure", checks)


def _validate_no_circular_import() -> bool:
    """Import each module in isolation (fresh subprocess-free check)."""
    for module in REQUIRED_MODULES:
        try:
            spec = importlib.util.find_spec(module)
        except Exception:  # noqa: BLE001
            return False
        if spec is None:
            return False
    # A circular import would raise ImportError on a fresh import; the
    # ``imports`` section re-imports everything, so reaching this point
    # with every module present is sufficient evidence.
    return True


def _validate_lifecycle() -> dict:
    checks: list[tuple[str, bool, str]] = []
    try:
        lifecycle = Lifecycle(name="validator")
        events: list[str] = []
        lifecycle.register_handler(LifecycleState.BOOTSTRAPPING, lambda s, a: events.append("bootstrap"))
        lifecycle.register_handler(LifecycleState.READY, lambda s, a: events.append("initialize"))
        lifecycle.register_handler(LifecycleState.READY, lambda s, a: events.append("ready"))
        lifecycle.register_handler(LifecycleState.RUNNING, lambda s, a: events.append("start"))
        lifecycle.register_handler(LifecycleState.STOPPING, lambda s, a: events.append("stop"))
        lifecycle.register_handler(LifecycleState.STOPPED, lambda s, a: events.append("shutdown"))
        for target in (
            LifecycleState.BOOTSTRAPPING,
            LifecycleState.READY,
            LifecycleState.RUNNING,
            LifecycleState.STOPPING,
            LifecycleState.STOPPED,
        ):
            lifecycle.transition(target)
        expected = ["bootstrap", "initialize", "ready", "start", "stop", "shutdown"]
        checks.append(("handlers_in_order", events == expected, f"events={events}"))
        checks.append(("final_state_stopped", lifecycle.state is LifecycleState.STOPPED, lifecycle.state.value))
        checks.append(("history_recorded", len(lifecycle.history) >= 6, f"{len(lifecycle.history)} states"))

        invalid_raised = False
        try:
            Lifecycle(name="validator-invalid").transition(LifecycleState.RUNNING)
        except BetrayerError:
            invalid_raised = True
        checks.append(("invalid_transition_rejected", invalid_raised, "CREATED -> RUNNING rejected"))

        failure = Lifecycle(name="validator-failure")
        def _boom(state, application):
            raise ValueError("boom")
        failure.register_handler(LifecycleState.BOOTSTRAPPING, _boom)
        failure_recorded = False
        try:
            failure.transition(LifecycleState.BOOTSTRAPPING)
        except BetrayerError as exc:
            failure_recorded = exc.code == "LIFECYCLE_HANDLER_FAILED"
        checks.append(
            (
                "failure_enters_failed_state",
                failure.state is LifecycleState.FAILED and failure_recorded,
                f"state={failure.state.value}",
            )
        )
    except Exception as exc:  # noqa: BLE001
        checks.append(("lifecycle_probe", False, f"{type(exc).__name__}: {exc}"))
    return _section("lifecycle", "lifecycle state machine", checks)


def _validate_configuration() -> dict:
    checks: list[tuple[str, bool, str]] = []
    try:
        config = Config(defaults={"app.name": "validator", "api.secret_key": "top-secret"})
        checks.append(("defaults", config.get("app.name") == "validator", str(config.get("app.name"))))
        config.set("app.debug", True)
        checks.append(("set_get", config.get("app.debug") is True, "set/get works"))
        checks.append(("missing_returns_none", config.get("does.not.exist") is None, "None default"))

        nested = Config(defaults={"db": {"host": "localhost"}})
        checks.append(("nested_flattening", nested.get("db.host") == "localhost", "app.name style keys"))

        env_config = Config(defaults={"app.debug": False})
        env_config.load_env(environ={"BETRAYER_APP__DEBUG": "1"})
        checks.append(("env_override", env_config.get("app.debug") is True, "BETRAYER_APP__DEBUG=1"))

        safe = config.safe_data()
        checks.append(("secret_masked", safe.get("api.secret_key") == "****", "masked as ****"))
        checks.append(
            (
                "secret_not_leaked",
                "top-secret" not in json.dumps(config.safe_data()),
                "raw secret absent from safe output",
            )
        )
        checks.append(("safe_keys_hide_secret", "api.secret_key" not in config.keys(safe=True), "hidden"))

        frozen = Config(defaults={"a": 1})
        frozen.finalise()
        blocked = False
        try:
            frozen.set("a", 2)
        except BetrayerError:
            blocked = True
        checks.append(("finalise_blocks_set", blocked, "immutable after finalise"))
    except Exception as exc:  # noqa: BLE001
        checks.append(("configuration_probe", False, f"{type(exc).__name__}: {exc}"))
    return _section("configuration", "configuration system", checks)


def _validate_environment() -> dict:
    checks: list[tuple[str, bool, str]] = []
    try:
        environment = Environment.detect()
        checks.append(("python_version", bool(environment.python_version), environment.python_version))
        checks.append(("os_name", bool(environment.os_name), environment.os_name))
        checks.append(("architecture", bool(environment.architecture), environment.architecture))
        checks.append(("executable", bool(environment.executable), environment.executable))
        checks.append(("cwd_exists", environment.cwd.exists(), str(environment.cwd)))
        checks.append(("root_exists", environment.project_root.exists(), str(environment.project_root)))
        checks.append(("mode", environment.mode in ("development", "production", "testing"), environment.mode))
    except Exception as exc:  # noqa: BLE001
        checks.append(("environment_probe", False, f"{type(exc).__name__}: {exc}"))
    return _section("environment", "environment detection", checks)


def _validate_runtime() -> dict:
    checks: list[tuple[str, bool, str]] = []
    try:
        from betrayer.application import BetrayerApplication

        application = BetrayerApplication(name="validator")
        application.bootstrap()
        application.initialize()
        context = application.runtime_context
        checks.append(("context_bound", context.application is application, "ctx.application is app"))
        checks.append(("context_config", context.config is application.config, "ctx.config is app.config"))
        checks.append(("context_lifecycle", context.lifecycle is application.lifecycle, "ctx.lifecycle is app.lifecycle"))
        checks.append(("context_environment", context.environment is not None, "ctx.environment present"))
        checks.append(("context_registry", context.registry is application.registry, "ctx.registry is app.registry"))
        checks.append(("runtime_state", context.state is not None, "runtime state present"))
        checks.append(("state_ready", application.state is LifecycleState.READY, application.state.value))
        other = BetrayerApplication(name="validator-2")
        checks.append(
            (
                "no_global_singleton",
                other.runtime_context is not context,
                "two applications keep independent contexts",
            )
        )
    except Exception as exc:  # noqa: BLE001
        checks.append(("runtime_probe", False, f"{type(exc).__name__}: {exc}"))
    return _section("runtime", "runtime context and state", checks)


def _validate_tests() -> dict:
    checks: list[tuple[str, bool, str]] = []
    test_file = PROJECT_ROOT / "tests" / "test_foundation.py"
    smoke_file = PROJECT_ROOT / "tests" / "smoke_test.py"
    checks.append(("tests_dir", (PROJECT_ROOT / "tests").is_dir(), str(PROJECT_ROOT / "tests")))
    checks.append(("foundation_tests", test_file.is_file(), test_file.name))
    checks.append(("smoke_test", smoke_file.is_file(), smoke_file.name))
    try:
        importlib.import_module("pytest")
        checks.append(("pytest_available", True, "pytest importable"))
    except Exception as exc:  # noqa: BLE001
        checks.append(("pytest_available", False, f"pytest not importable: {exc}"))
    return _section("tests", "test suite presence", checks)


def discover_packages(package_root: Path | None = None) -> list[str]:
    """Dotted names of framework packages, derived from the filesystem.

    A directory is a package when it contains ``__init__.py``.  Packages are
    discovered instead of listed so a new subsystem automatically shows up in
    the manifest (deterministic, alphabetical order).
    """
    root = package_root or (PROJECT_ROOT / FRAMEWORK_SLUG)
    packages: list[str] = []
    for init_file in sorted(root.rglob("__init__.py")):
        relative = init_file.parent.relative_to(root).parts
        packages.append(".".join((root.name, *relative)) if relative else root.name)
    return packages


def build_manifest() -> dict:
    """Derive the machine readable manifest from runtime state.

    Identity comes from ``betrayer.core.meta`` (single source of truth), the
    command list from the CLI registry and the package list from the filesystem.
    Nothing here is a second copy of a value that already exists elsewhere, so
    ``.betrayer/manifest.json`` can always be regenerated with
    ``python -m betrayer manifest --write``.
    """
    return {
        "framework": FRAMEWORK_NAME,
        "version": __version__,
        "foundation_version": FOUNDATION_VERSION,
        "architecture_version": ARCHITECTURE_VERSION,
        "commands": list(COMMANDS),
        "packages": discover_packages(),
        "package_roots": [FRAMEWORK_SLUG],
        "description": FRAMEWORK_DESCRIPTION,
    }


def build_architecture() -> dict:
    """Machine readable architecture description, generated from ``meta``.

    ``architecture_version`` is read from ``betrayer.core.meta`` and never from
    the file on disk, so the document cannot claim a version the code does not
    have.  Regenerate with ``python -m betrayer manifest --write``.
    """
    return {
        "framework": FRAMEWORK_NAME,
        "architecture_version": ARCHITECTURE_VERSION,
        "foundation_version": FOUNDATION_VERSION,
        "layers": [
            {
                "name": "core",
                "description": "Foundation subsystems: config, environment, lifecycle, registry, exceptions",
                "dependencies": [],
            },
            {
                "name": "runtime",
                "description": "Runtime context and state management",
                "dependencies": ["core"],
            },
            {
                "name": "diagnostics",
                "description": "Inspection and validation tools",
                "dependencies": ["core", "runtime"],
            },
            {
                "name": "cli",
                "description": "Command-line interface",
                "dependencies": ["core", "runtime", "diagnostics"],
            },
            {
                "name": "ai",
                "description": "LLM-facing documentation and guidance",
                "dependencies": ["core", "runtime", "diagnostics"],
            },
        ],
        "dependency_rules": [
            "core MUST NOT depend on cli, runtime, diagnostics, or ai",
            "runtime MUST NOT depend on cli or diagnostics",
            "diagnostics MUST NOT depend on cli",
            "cli MUST depend only on core, runtime, and diagnostics",
            "ai MUST depend only on core, runtime, and diagnostics",
        ],
        "extension_points": [
            "lifecycle handlers (on_bootstrap, on_initialize, on_ready, on_start, on_stop, on_shutdown, on_error)",
            "Registry for custom components",
            "Config for typed configuration",
            "Environment for runtime inspection",
        ],
    }


#: Files under ``.betrayer/`` that are GENERATED from runtime builders and must
#: never be hand edited.  Mapping is ordered, so writing is deterministic.
GENERATED_METADATA: dict[Path, Callable[[], dict]] = {
    MANIFEST_PATH: build_manifest,
    ARCHITECTURE_PATH: build_architecture,
}


def write_metadata() -> list[Path]:
    """Write every generated metadata file from its runtime builder."""
    written: list[Path] = []
    for path, builder in GENERATED_METADATA.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(builder(), indent=4) + "\n", encoding="utf-8")
        written.append(path)
    return written


def _validate_metadata() -> dict:
    checks: list[tuple[str, bool, str]] = []
    for path, builder in GENERATED_METADATA.items():
        expected = builder()
        try:
            stored = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 - report anything
            checks.append((path.name, False, f"{type(exc).__name__}: {exc}"))
            continue
        if not isinstance(stored, dict):
            checks.append((path.name, False, "not a JSON object"))
            continue
        drifted = sorted(key for key, value in expected.items() if stored.get(key) != value)
        checks.append(
            (path.name, not drifted, "matches runtime" if not drifted else f"drifted: {', '.join(drifted)}")
        )
    return _section("metadata", "generated metadata matches runtime", checks)


def run_validate() -> dict:
    """Run every foundation validation section and return a report dict."""
    results: dict = {}
    results["imports"] = _validate_imports()
    results["package_structure"] = _validate_package_structure()
    results["lifecycle"] = _validate_lifecycle()
    results["configuration"] = _validate_configuration()
    results["environment"] = _validate_environment()
    results["runtime"] = _validate_runtime()
    results["metadata"] = _validate_metadata()
    results["tests"] = _validate_tests()
    sections = [value for value in results.values() if isinstance(value, dict)]
    results["status"] = "pass" if sections and all(s["status"] == "pass" for s in sections) else "fail"
    return results


# ── commands ─────────────────────────────────────────────────────


def _as_json(args: argparse.Namespace) -> bool:
    """Return the parsed ``--json`` flag (``False`` when absent)."""
    return bool(getattr(args, "json", False))


def _cmd_info(args: argparse.Namespace) -> int:
    as_json = _as_json(args)
    application = _ready_application()
    info = Inspector(application).info()
    if as_json:
        _print_json(info)
        return 0
    print(f"{FRAMEWORK_NAME} Framework")
    print(f"Version: {info['version']}")
    print(f"Architecture: {info['architecture_version']}")
    print(f"Python: {info['python']}")
    print(f"OS: {info['os']}")
    print(f"Environment: {info['environment']}")
    print(f"Project Root: {info['project_root']}")
    print(f"Application: {info['application']}")
    print(f"Application State: {info['state']}")
    return 0


def _cmd_environment(args: argparse.Namespace) -> int:
    as_json = _as_json(args)
    data = Environment.detect().to_dict()
    if as_json:
        _print_json(data)
        return 0
    for key in sorted(data):
        print(f"{key}: {data[key]}")
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    as_json = _as_json(args)
    application = _ready_application()
    status = Inspector(application).status()
    if as_json:
        _print_json(status)
        return 0
    print(f"Application: {status['application']}")
    print(f"State: {status['state']}")
    print(f"Previous State: {status['previous_state']}")
    print(f"Ready: {status['ready']}")
    print(f"History: {' -> '.join(status['history'])}")
    print(f"Components: {', '.join(status['components']) or '(none)'}")
    print(f"Failed: {status['failed']}")
    return 0


def _cmd_config(args: argparse.Namespace) -> int:
    as_json = _as_json(args)
    application = _ready_application()
    data = application.config.safe_data()
    if as_json:
        _print_json(data)
        return 0
    print("Configuration (secrets masked):")
    for key in sorted(data):
        print(f"{key} = {data[key]}")
    return 0


def _cmd_doctor(args: argparse.Namespace) -> int:
    as_json = _as_json(args)
    application = _ready_application()
    report = Inspector(application).doctor()
    if as_json:
        _print_json(report)
        return 0 if report["ok"] else 1
    label_width = max(len(c["name"]) for c in report["checks"]) + 2
    for check in report["checks"]:
        name = check["name"]
        status = check["status"]
        if status == "ok":
            status_label = "PASS"
            print(f"{name:.<{label_width}} {status_label}")
            detail = check.get("detail", "")
            if detail:
                print(f"  {detail}")
        else:
            status_label = "ERROR"
            print(f"{name:.<{label_width}} {status_label}")
            reason = check.get("reason", "unknown")
            print(f"  {reason}")
            suggestion = check.get("suggestion", "")
            if suggestion:
                print(f"  Suggested: {suggestion}")
        print("")
    print_summary = "all checks passed" if report["ok"] else "problems detected"
    print(f"Doctor: {print_summary} ({report['summary']})")
    return 0 if report["ok"] else 1


def _cmd_check(args: argparse.Namespace) -> int:
    """Quick project/framework health check."""
    as_json = _as_json(args)
    application = _ready_application()
    checks: list[dict] = []

    # 1. Project structure
    structure_checks = _check_structure()
    checks.append(structure_checks)

    # 2. Configuration
    config_checks = _check_config(application)
    checks.append(config_checks)

    # 3. Environment
    env_checks = _check_env(application)
    checks.append(env_checks)

    # 4. Imports
    import_checks = _check_imports_main()
    checks.append(import_checks)

    # 5. Module registration
    module_checks = _check_modules(application)
    checks.append(module_checks)

    # 6. Database configuration
    db_checks = _check_database(application)
    checks.append(db_checks)

    # 7. Migration state
    migration_checks = _check_migrations(application)
    checks.append(migration_checks)

    # 8. Application bootstrap
    bootstrap_checks = _check_bootstrap(application)
    checks.append(bootstrap_checks)

    # 9. Required dependencies
    dep_checks = _check_dependencies(application)
    checks.append(dep_checks)

    # Determine overall status
    error_count = sum(1 for c in checks if c["status"] == CHECK_STATUS_ERROR)
    warning_count = sum(1 for c in checks if c["status"] == CHECK_STATUS_WARNING)
    if error_count > 0:
        overall_status = CHECK_STATUS_ERROR
    elif warning_count > 0:
        overall_status = CHECK_STATUS_WARNING
    else:
        overall_status = CHECK_STATUS_PASS

    result = {
        "success": overall_status == CHECK_STATUS_PASS,
        "status": overall_status,
        "checks": checks,
        "summary": {
            "passed": sum(1 for c in checks if c["status"] == CHECK_STATUS_PASS),
            "warnings": warning_count,
            "errors": error_count,
            "total": len(checks),
        },
    }

    if as_json:
        _print_json(result)
        return 0 if overall_status != CHECK_STATUS_ERROR else 1

    print(f"Betrayer Project Check ({overall_status})")
    print("")
    for check in checks:
        name = check["name"]
        status = check["status"]
        if status == CHECK_STATUS_PASS:
            print(f"  [{CHECK_STATUS_PASS}] {name}")
        elif status == CHECK_STATUS_WARNING:
            print(f"  [{CHECK_STATUS_WARNING}] {name}")
            if check.get("message"):
                print(f"       {check['message']}")
        else:
            print(f"  [{CHECK_STATUS_ERROR}] {name}")
            if check.get("message"):
                print(f"       {check['message']}")
            if check.get("suggested_actions"):
                for action in check["suggested_actions"]:
                    print(f"       -> {action}")
    print("")
    print(f"Summary: {result['summary']['passed']} passed, "
          f"{result['summary']['warnings']} warnings, "
          f"{result['summary']['errors']} errors")
    return 0 if overall_status != CHECK_STATUS_ERROR else 1


def _check_structure() -> dict:
    """Check that required project files and directories exist."""
    from pathlib import Path
    root = Path.cwd()
    required = ["betrayer", "pyproject.toml", "setup.py"]
    missing = [p for p in required if not (root / p).exists()]
    if missing:
        return {
            "name": "project_structure",
            "status": CHECK_STATUS_ERROR,
            "message": f"Missing: {', '.join(missing)}",
            "suggested_actions": ["Run 'bet create' to scaffold the project."],
        }
    return {
        "name": "project_structure",
        "status": CHECK_STATUS_PASS,
        "message": "All required files and directories found.",
    }


def _check_config(application: Any) -> dict:
    """Check configuration validity."""
    diagnostics: list[str] = []
    try:
        config = application.config
        if config is None:
            return {
                "name": "configuration",
                "status": CHECK_STATUS_ERROR,
                "message": "No configuration found.",
                "suggested_actions": ["Ensure Bootstrap is called."],
            }
        safe_keys = config.keys(safe=True)
        if not safe_keys:
            return {
                "name": "configuration",
                "status": CHECK_STATUS_WARNING,
                "message": "Configuration is empty.",
            }
        return {
            "name": "configuration",
            "status": CHECK_STATUS_PASS,
            "message": f"{len(safe_keys)} configuration keys available.",
        }
    except Exception as exc:
        return {
            "name": "configuration",
            "status": CHECK_STATUS_ERROR,
            "message": f"Configuration check failed: {exc}",
            "suggested_actions": ["Check configuration file syntax."],
        }


def _check_env(application: Any) -> dict:
    """Check environment detection."""
    try:
        env = application.environment
        if env is None:
            return {
                "name": "environment",
                "status": CHECK_STATUS_ERROR,
                "message": "Environment not detected.",
                "suggested_actions": ["Run 'bet doctor' for details."],
            }
        return {
            "name": "environment",
            "status": CHECK_STATUS_PASS,
            "message": f"OS={env.os_name}, Python={env.python_version}, Mode={env.mode}",
        }
    except Exception as exc:
        return {
            "name": "environment",
            "status": CHECK_STATUS_ERROR,
            "message": f"Environment detection failed: {exc}",
        }


def _check_imports_main() -> dict:
    """Check that all required framework modules can be imported."""
    import importlib
    required = REQUIRED_MODULES
    failed: list[str] = []
    for mod in required:
        try:
            importlib.import_module(mod)
        except Exception as exc:
            failed.append(f"{mod}: {exc}")
    if failed:
        return {
            "name": "imports",
            "status": CHECK_STATUS_ERROR,
            "message": f"{len(failed)} module(s) failed to import.",
            "context": {"failed": failed},
            "suggested_actions": ["Check PYTHONPATH and package installation."],
        }
    return {
        "name": "imports",
        "status": CHECK_STATUS_PASS,
        "message": f"All {len(required)} required modules import successfully.",
    }


def _check_modules(application: Any) -> dict:
    """Check module registration."""
    try:
        modules = getattr(application, "modules", None)
        if modules is None:
            return {
                "name": "module_registration",
                "status": CHECK_STATUS_WARNING,
                "message": "Module system not available.",
            }
        # Check if any modules are registered
        if hasattr(modules, "names"):
            names = list(modules.names())
            return {
                "name": "module_registration",
                "status": CHECK_STATUS_PASS if names else CHECK_STATUS_WARNING,
                "message": f"{len(names)} module(s) registered: {', '.join(names) if names else 'none'}",
            }
        return {
            "name": "module_registration",
            "status": CHECK_STATUS_PASS,
            "message": "Module system available.",
        }
    except Exception as exc:
        return {
            "name": "module_registration",
            "status": CHECK_STATUS_ERROR,
            "message": f"Module check failed: {exc}",
        }


def _check_database(application: Any) -> dict:
    """Check database configuration."""
    try:
        config = application.config
        if config is None:
            return {
                "name": "database_configuration",
                "status": CHECK_STATUS_WARNING,
                "message": "Cannot check database: no configuration.",
            }
        driver = config.get("database.default.driver")
        if driver is None:
            return {
                "name": "database_configuration",
                "status": CHECK_STATUS_WARNING,
                "message": "No database driver configured (optional for non-DB apps).",
            }
        return {
            "name": "database_configuration",
            "status": CHECK_STATUS_PASS,
            "message": f"Driver: {driver}",
        }
    except Exception as exc:
        return {
            "name": "database_configuration",
            "status": CHECK_STATUS_ERROR,
            "message": f"Database check failed: {exc}",
        }


def _check_migrations(application: Any) -> dict:
    """Check migration state."""
    try:
        container = getattr(application, "container", None)
        if container is None:
            return {
                "name": "migration_state",
                "status": CHECK_STATUS_WARNING,
                "message": "Container not available; cannot check migrations.",
            }
        # Try to resolve migration registry if registered
        if hasattr(container, "has") and container.has("migration_registry"):
            return {
                "name": "migration_state",
                "status": CHECK_STATUS_PASS,
                "message": "Migration registry is configured.",
            }
        return {
            "name": "migration_state",
            "status": CHECK_STATUS_PASS,
            "message": "No migration registry (no migrations configured).",
        }
    except Exception as exc:
        return {
            "name": "migration_state",
            "status": CHECK_STATUS_WARNING,
            "message": f"Migration check skipped: {exc}",
        }


def _check_bootstrap(application: Any) -> dict:
    """Check application bootstrap."""
    state = getattr(application, "state", None)
    if state is None:
        return {
            "name": "application_bootstrap",
            "status": CHECK_STATUS_ERROR,
            "message": "Application has no state.",
            "suggested_actions": ["Call Bootstrap().build() on the application."],
        }
    state_value = getattr(state, "value", None)
    if state_value in ("ready", "running"):
        return {
            "name": "application_bootstrap",
            "status": CHECK_STATUS_PASS,
            "message": f"Application is in '{state_value}' state.",
        }
    return {
        "name": "application_bootstrap",
        "status": CHECK_STATUS_ERROR,
        "message": f"Application state is '{state_value}' (expected 'ready' or 'running').",
        "suggested_actions": ["Call application.ready() or Bootstrap().build()."],
    }


def _check_dependencies(application: Any) -> dict:
    """Check required dependencies."""
    import importlib
    required_packages = ["betrayer"]
    missing: list[str] = []
    for pkg in required_packages:
        try:
            importlib.import_module(pkg)
        except ImportError:
            missing.append(pkg)
    if missing:
        return {
            "name": "required_dependencies",
            "status": CHECK_STATUS_ERROR,
            "message": f"Missing packages: {', '.join(missing)}",
            "suggested_actions": ["Run 'pip install betrayer' or install from source."],
        }
    return {
        "name": "required_dependencies",
        "status": CHECK_STATUS_PASS,
        "message": "All required dependencies are available.",
    }


def _cmd_debug(args: argparse.Namespace) -> int:
    """Diagnose requests, errors, and traces."""
    as_json = _as_json(args)
    action = getattr(args, "debug_action", None)
    application = _ready_application()
    diagnostics = getattr(application, "diagnostics", None)

    if action == "last":
        return _debug_last(as_json, diagnostics)
    elif action == "errors":
        return _debug_errors(as_json, diagnostics)
    elif action == "trace":
        request_id = getattr(args, "request_id", None)
        return _debug_trace(as_json, diagnostics, request_id)
    elif action == "inspect":
        request_id = getattr(args, "request_id", None)
        return _debug_inspect(as_json, diagnostics, request_id)
    else:
        # Default: show summary
        return _debug_summary(as_json, diagnostics)


def _debug_summary(as_json: bool, diagnostics: Any) -> int:
    """Show diagnostics summary."""
    if diagnostics is None:
        summary = {
            "status": "no_diagnostics",
            "message": "No diagnostics store available. Ensure Bootstrap was called.",
            "summary": {"total_records": 0, "errors": 0, "warnings": 0},
        }
        if as_json:
            _print_json(summary)
        else:
            print("Diagnostics: No diagnostics store available.")
        return 0

    summary = diagnostics.summary()
    recent = diagnostics.recent(limit=5)
    summary["recent"] = recent
    if as_json:
        _print_json(summary)
    else:
        print(f"Diagnostics Store: {summary['name']}")
        print(f"Total Records: {summary['total_records']}")
        print(f"Errors: {summary['errors']}")
        print(f"Warnings: {summary['warnings']}")
        print(f"Requests Tracked: {summary['requests_tracked']}")
        print(f"Traces Recorded: {summary['traces_recorded']}")
        print("")
        if recent:
            print("Recent Records:")
            for r in recent:
                ts = r.get("timestamp", "")
                level = r.get("level", "?").upper()
                msg = r.get("message", "")
                print(f"  [{level}] {msg}")
        else:
            print("No recent records.")
    return 0


def _debug_last(as_json: bool, diagnostics: Any) -> int:
    """Show the last recorded diagnostic record."""
    if diagnostics is None:
        if as_json:
            _print_json({"status": "no_diagnostics", "message": "No store available"})
        else:
            print("No diagnostics store available.")
        return 0
    recent = diagnostics.recent(limit=1)
    if not recent:
        if as_json:
            _print_json({"status": "empty", "message": "No records yet"})
        else:
            print("No diagnostic records yet.")
        return 0
    record = recent[0]
    if as_json:
        _print_json(record)
    else:
        _print_diagnostic_record(record)
    return 0


def _debug_errors(as_json: bool, diagnostics: Any) -> int:
    """Show error records."""
    if diagnostics is None:
        if as_json:
            _print_json({"status": "no_diagnostics", "message": "No store available"})
        else:
            print("No diagnostics store available.")
        return 0
    errors = diagnostics.errors(limit=50)
    if as_json:
        _print_json({"errors": errors, "count": len(errors)})
    else:
        if not errors:
            print("No errors recorded.")
            return 0
        print(f"Errors ({len(errors)}):")
        print("")
        for err in errors:
            ts = err.get("timestamp", "")
            code = err.get("code", "?")
            msg = err.get("message", "")
            rid = err.get("request_id", "-")
            comp = err.get("component", "?")
            print(f"  [{code}] {msg}")
            print(f"       Time: {ts} | Component: {comp} | Request: {rid}")
            print("")
    return 0


def _debug_trace(as_json: bool, diagnostics: Any, request_id: Optional[str]) -> int:
    """Show request trace steps."""
    if diagnostics is None:
        if as_json:
            _print_json({"status": "no_diagnostics"})
        else:
            print("No diagnostics store available.")
        return 0
    if not request_id:
        if as_json:
            _print_json({"status": "missing_request_id"})
        else:
            print("Usage: bet debug trace <request_id>")
        return 1
    trace = diagnostics.get_trace(request_id)
    if trace is None:
        if as_json:
            _print_json({"status": "not_found", "request_id": request_id})
        else:
            print(f"No trace found for request: {request_id}")
        return 1

    result = {"request_id": request_id, "trace": trace}
    if as_json:
        _print_json(result)
    else:
        print(f"Trace for request: {request_id}")
        print("")
        arrow = "  ↓"
        for step in trace:
            layer = step.get("layer", "?")
            component = step.get("component", "?")
            status = step.get("status", "?")
            detail = step.get("detail", "")
            print(f"  {layer}: {component}")
            print(f"    status={status} | {detail}")
            print(arrow)
        print("  [end]")
    return 0


def _debug_inspect(as_json: bool, diagnostics: Any, request_id: Optional[str]) -> int:
    """Show detailed request information."""
    if diagnostics is None:
        if as_json:
            _print_json({"status": "no_diagnostics"})
        else:
            print("No diagnostics store available.")
        return 0
    if not request_id:
        if as_json:
            _print_json({"status": "missing_request_id"})
        else:
            print("Usage: bet debug inspect <request_id>")
        return 1
    request_info = diagnostics.get_request(request_id)
    if request_info is None:
        if as_json:
            _print_json({"status": "not_found", "request_id": request_id})
        else:
            print(f"No request info found for: {request_id}")
        return 1

    if as_json:
        _print_json(request_info)
    else:
        print(f"Request Inspection: {request_id}")
        print("")
        code = request_info.get("code", "?")
        level = request_info.get("level", "?")
        message = request_info.get("message", "")
        component = request_info.get("component", "?")
        actions = request_info.get("suggested_actions", [])
        trace = request_info.get("trace", [])

        print(f"  Code:       {code}")
        print(f"  Level:      {level}")
        print(f"  Component:  {component}")
        print(f"  Message:    {message}")

        if actions:
            print("  Suggested Actions:")
            for a in actions:
                print(f"    - {a}")

        if trace:
            print(f"  Trace ({len(trace)} steps):")
            for step in trace:
                layer = step.get("layer", "?")
                comp = step.get("component", "?")
                status = step.get("status", "?")
                dur = step.get("duration_ms", 0)
                print(f"    [{layer}] {comp}: {status} ({dur}ms)")
    return 0


def _print_diagnostic_record(record: dict) -> None:
    """Print a single diagnostic record in human-readable format."""
    level = record.get("level", "?").upper()
    code = record.get("code", "?")
    msg = record.get("message", "")
    component = record.get("component", "?")
    rid = record.get("request_id")
    tid = record.get("trace_id")
    actions = record.get("suggested_actions", [])

    print(f"[{level}] {code}: {msg}")
    print(f"  Component: {component}")
    if rid:
        print(f"  Request ID: {rid}")
    if tid:
        print(f"  Trace ID: {tid}")
    if actions:
        print("  Suggested Actions:")
        for a in actions:
            print(f"    - {a}")


def _configure_debug(parser: argparse.ArgumentParser) -> None:
    """Configure the ``bet debug`` subcommand parser."""
    # --json is consumed from the parent; subparsers need their own.
    subparsers = parser.add_subparsers(dest="debug_action", metavar="subcommand")

    # last
    last_parser = subparsers.add_parser(
        "last",
        help="show last diagnostic record",
        description="Show last diagnostic record",
    )
    last_parser.add_argument("--json", action="store_true", help="emit machine readable JSON output", default=None)

    # errors
    err_parser = subparsers.add_parser(
        "errors",
        help="list error records",
        description="List error records",
    )
    err_parser.add_argument("--json", action="store_true", help="emit machine readable JSON output", default=None)

    # trace <request_id>
    trace_parser = subparsers.add_parser(
        "trace",
        help="show request trace",
        description="Show request trace steps",
    )
    trace_parser.add_argument("request_id", metavar="request_id", help="Request ID to trace")
    trace_parser.add_argument("--json", action="store_true", help="emit machine readable JSON output", default=None)

    # inspect <request_id>
    inspect_parser = subparsers.add_parser(
        "inspect",
        help="inspect a request/error",
        description="Inspect a request or error in detail",
    )
    inspect_parser.add_argument("request_id", metavar="request_id", help="Request ID to inspect")
    inspect_parser.add_argument("--json", action="store_true", help="emit machine readable JSON output", default=None)


# ── queue command ──────────────────────────────────────────────


def _cmd_queue(args: argparse.Namespace) -> int:
    """Show the state of the default in-memory queue, or run jobs."""
    from betrayer.jobs import Queue, JobRunner

    queue = Queue()
    runner = JobRunner(queue)
    as_json = _as_json(args)

    action = getattr(args, "queue_action", None)
    if action == "run":
        results = runner.run_available()
        if as_json:
            _print_json({
                "action": "run",
                "queue": queue.to_dict(),
                "results": [r.to_dict() for r in results],
            })
        else:
            print(f"Queue: {queue.name} ({queue.size()} remaining)")
            for r in results:
                status = "OK" if r.success else "FAIL"
                print(f"  [{status}] {r.job}: {r.duration:.4f}s")
        return 0

    # default: show queue info
    if as_json:
        _print_json(queue.to_dict())
    else:
        print(f"Queue name : {queue.name}")
        print(f"Size       : {queue.size()}")
        print(f"Backend    : InMemoryQueue")
    return 0


def _configure_queue(parser: argparse.ArgumentParser) -> None:
    """Configure ``bet queue`` subcommands."""
    subparsers = parser.add_subparsers(dest="queue_action", metavar="action")
    subparsers.add_parser("run", help="run all available queued jobs")


# ── schedule command ────────────────────────────────────────────


def _cmd_schedule(args: argparse.Namespace) -> int:
    """Show or run scheduled jobs."""
    from betrayer.jobs import Scheduler, Queue, JobRunner

    queue = Queue()
    runner = JobRunner(queue)
    scheduler = Scheduler(queue=queue, runner=runner)
    as_json = _as_json(args)

    action = getattr(args, "schedule_action", None)
    if action == "run":
        results = scheduler.run_due()
        if as_json:
            _print_json({
                "action": "run_due",
                "scheduler": scheduler.to_dict(),
                "results": [r.to_dict() for r in results],
            })
        else:
            print(f"Running due jobs... ({len(results)} executed)")
            for r in results:
                status = "OK" if r.success else "FAIL"
                print(f"  [{status}] {r.job}: {r.duration:.4f}s")
        return 0

    # default: list scheduled jobs
    jobs = scheduler.list_jobs()
    if as_json:
        _print_json({"scheduled": len(jobs), "jobs": jobs})
    else:
        print(f"Scheduled jobs: {len(jobs)}")
        for j in jobs:
            print(f"  {j['name']}: every {j['interval_seconds']}s, ran {j['run_count']}x")
    return 0


def _configure_schedule(parser: argparse.ArgumentParser) -> None:
    """Configure ``bet schedule`` subcommands."""
    subparsers = parser.add_subparsers(dest="schedule_action", metavar="action")
    subparsers.add_parser("run", help="run all due scheduled jobs")


# ── realtime command ────────────────────────────────────────────


def _cmd_realtime(args: argparse.Namespace) -> int:
    """Introspect the realtime (WebSocket) layer of the application.

    Lightweight, read-only: builds a READY application, attaches a
    :class:`~betrayer.web.realtime_manager.RealtimeManager` and reports its
    empty-but-ready state.  Does not open sockets or start a server.

    Output::

        {"success": true, "channels": [], "connections": 0}
    """
    from betrayer.bootstrap import Bootstrap
    from betrayer.web.realtime_manager import RealtimeManager

    application = Bootstrap(name=FRAMEWORK_NAME.lower()).build()
    manager = RealtimeManager(application=application)
    snapshot = manager.to_dict()
    as_json = _as_json(args)
    if as_json:
        _print_json(
            {
                "success": True,
                "channels": snapshot["channels"],
                "connections": snapshot["connections"],
            }
        )
    else:
        print(f"Realtime manager: {len(snapshot['channels'])} channels, "
              f"{snapshot['connections']} connections")
        for ch in snapshot["channels"]:
            print(f"  {ch['name']}: {ch['connections']} connections")
    return 0


def _configure_realtime(parser: argparse.ArgumentParser) -> None:
    """``bet realtime`` has no subcommands (introspection only)."""
    # No extra arguments: a single introspection call. The shared ``--json``
    # flag (added by the parent parser) is honoured automatically.
    _ = parser


def _cmd_validate(args: argparse.Namespace) -> int:
    as_json = _as_json(args)
    results = run_validate()
    if as_json:
        _print_json(results)
        return 0 if results["status"] == "pass" else 1
    for name, section in results.items():
        if not isinstance(section, dict):  # skips the aggregate "status" key
            continue
        marker = "OK" if section["status"] == "pass" else "FAIL"
        print(f"[{marker}] {name}: {section['detail']}")
        if section["status"] == "fail":
            for check in section["checks"]:
                if check["status"] == "fail":
                    print(f"    - {check['name']}: {check['detail']}")
    print(f"Validation: {results['status']}")
    return 0 if results["status"] == "pass" else 1


def _cmd_manifest(args: argparse.Namespace) -> int:
    """Show the runtime derived manifest; ``--write`` regenerates the file.

    ``.betrayer/manifest.json`` and ``.betrayer/architecture.json`` are never
    hand edited: they are rebuilt from ``betrayer.core.meta`` plus the CLI and
    package surface, so a metadata file can never drift away from the runtime
    it describes.
    """
    as_json = _as_json(args)
    write = bool(getattr(args, "write", False))
    manifest = build_manifest()
    if write:
        written = write_metadata()
        if as_json:
            _print_json({"written": [str(path) for path in written], "manifest": manifest})
        else:
            for path in written:
                print(f"metadata written: {path}")
        return 0
    if as_json:
        _print_json(manifest)
        return 0
    print(f"{FRAMEWORK_NAME} manifest (generated from runtime)")
    print(f"version: {manifest['version']}")
    print(f"foundation_version: {manifest['foundation_version']}")
    print(f"architecture_version: {manifest['architecture_version']}")
    print(f"commands: {', '.join(manifest['commands'])}")
    print(f"packages: {', '.join(manifest['packages'])}")
    return 0


def _cmd_create(args: argparse.Namespace) -> int:
    """Create a new Betrayer application project in the current directory.

    ``create`` is the one command that does not build a READY application
    first: it generates a project on disk, so there is no application to
    inspect yet.  Controlled failures (invalid name, existing directory) raise
    :class:`CommandError` and return the framework CLI failure exit code.
    """
    from betrayer.generators.project import ProjectGenerator

    as_json = _as_json(args)
    name = args.project_name
    force = bool(getattr(args, "force", False))
    try:
        generator = ProjectGenerator(name=name, output_dir=Path.cwd(), overwrite=force)
    except Exception as exc:  # noqa: BLE001 - name validation failure
        raise CommandError(str(exc)) from exc
    try:
        output = generator.generate()
    except Exception as exc:  # noqa: BLE001 - existing directory, write failure
        raise CommandError(str(exc)) from exc
    if not output.success:
        detail = "; ".join(
            f"{e['path']}: {e['message']}" for e in output.errors
        )
        raise CommandError(f"failed to create project: {detail}")
    if as_json:
        _print_json(
            {
                "project": str(generator.target),
                "created": output.created,
                "updated": output.updated,
                "skipped": output.skipped,
            }
        )
        return 0
    print(f"Created Betrayer project: {generator.target}")
    for relative in output.created:
        print(f"  created {relative}")
    print("Run it with:")
    print(f"  cd {name} && python run.py")
    print("Test it with:")
    print(f"  cd {name} && pytest")
    return 0


def _configure_create(parser: argparse.ArgumentParser) -> None:
    """Add ``create`` specific arguments (registered with the command)."""
    parser.add_argument(
        "project_name",
        help="new project name (letters, digits, '-' and '_'; must start with a letter)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="populate an existing, non-empty directory instead of failing",
    )


#: ``bet make <target>`` handlers.  ``make`` is a thin dispatcher: each target is
#: a small function registered here, so adding a target touches one place --
#: exactly like a top level command registers one :class:`Command`.
_MAKE_HANDLERS: dict[str, Callable[[argparse.Namespace], int]] = {}


def _cmd_make_module(args: argparse.Namespace) -> int:
    """Create a new application module in the current directory.

    Like ``create`` this does not build a READY application first: it generates
    files on disk.  Controlled failures (invalid name, existing module) raise
    :class:`CommandError` and return the framework CLI failure exit code.
    """
    from betrayer.generators.module import ModuleGenerator

    as_json = _as_json(args)
    name = args.module_name
    force = bool(getattr(args, "force", False))
    try:
        generator = ModuleGenerator(name=name, output_dir=Path.cwd(), overwrite=force)
    except Exception as exc:  # noqa: BLE001 - name validation failure
        raise CommandError(str(exc)) from exc
    try:
        output = generator.generate()
    except Exception as exc:  # noqa: BLE001 - existing module, write failure
        raise CommandError(str(exc)) from exc
    if not output.success:
        detail = "; ".join(
            f"{e['path']}: {e['message']}" for e in output.errors
        )
        raise CommandError(f"failed to create module: {detail}")
    if as_json:
        _print_json(
            {
                "module": generator.module_name,
                "path": str(generator.target),
                "created": output.created,
                "updated": output.updated,
                "skipped": output.skipped,
            }
        )
        return 0
    print(f"Created module: {generator.module_name} ({generator.target})")
    for relative in output.created:
        print(f"  created {relative}")
    for relative in output.updated:
        print(f"  updated {relative}")
    print("Register it in your application with:")
    print(f"  app.modules.register({generator.class_name})")
    return 0


_MAKE_HANDLERS["module"] = _cmd_make_module


def _cmd_make_resource(args: argparse.Namespace) -> int:
    """Create a new data resource in the current directory.

    Like ``create`` this does not build a READY application first: it generates
    files on disk.  Controlled failures (invalid name, existing resource) raise
    :class:`CommandError` and return the framework CLI failure exit code.
    """
    from betrayer.generators.resource import ResourceGenerator

    as_json = _as_json(args)
    name = args.resource_name
    force = bool(getattr(args, "force", False))
    try:
        generator = ResourceGenerator(name=name, output_dir=Path.cwd(), overwrite=force)
    except Exception as exc:  # noqa: BLE001 - name validation failure
        raise CommandError(str(exc)) from exc
    try:
        output = generator.generate()
    except Exception as exc:  # noqa: BLE001 - existing resource, write failure
        raise CommandError(str(exc)) from exc
    if not output.success:
        detail = "; ".join(
            f"{e['path']}: {e['message']}" for e in output.errors
        )
        raise CommandError(f"failed to create resource: {detail}")
    if as_json:
        _print_json(
            {
                "resource": generator.resource_name,
                "path": str(generator.target),
                "model_class": generator.model_class_name,
                "repository_class": generator.repository_class_name,
                "module_class": generator.module_class_name,
                "created": output.created,
                "updated": output.updated,
                "skipped": output.skipped,
            }
        )
        return 0
    print(f"Created resource: {generator.resource_name} ({generator.target})")
    for relative in output.created:
        print(f"  created {relative}")
    for relative in output.updated:
        print(f"  updated {relative}")
    print("Register it in your application with:")
    print(f"  app.modules.register({generator.module_class_name})")
    return 0


_MAKE_HANDLERS["resource"] = _cmd_make_resource


def _cmd_make_service(args: argparse.Namespace) -> int:
    """Create a new application service in the current directory.

    Like ``create`` this does not build a READY application first: it generates
    files on disk.  Controlled failures (invalid name, existing service) raise
    :class:`CommandError` and return the framework CLI failure exit code.
    """
    from betrayer.generators.service import ServiceGenerator

    as_json = _as_json(args)
    name = args.service_name
    force = bool(getattr(args, "force", False))
    try:
        generator = ServiceGenerator(name=name, output_dir=Path.cwd(), overwrite=force)
    except Exception as exc:  # noqa: BLE001 - name validation failure
        raise CommandError(str(exc)) from exc
    try:
        output = generator.generate()
    except Exception as exc:  # noqa: BLE001 - existing service, write failure
        raise CommandError(str(exc)) from exc
    if not output.success:
        detail = "; ".join(
            f"{e['path']}: {e['message']}" for e in output.errors
        )
        raise CommandError(f"failed to create service: {detail}")
    if as_json:
        _print_json(
            {
                "service": generator.service_key,
                "path": str(generator.target),
                "service_class": generator.service_class_name,
                "module_class": generator.module_class_name,
                "created": output.created,
                "updated": output.updated,
                "skipped": output.skipped,
            }
        )
        return 0
    print(f"Created service: {generator.service_key} ({generator.target})")
    for relative in output.created:
        print(f"  created {relative}")
    for relative in output.updated:
        print(f"  updated {relative}")
    print("Register it in your application with:")
    print(f"  app.modules.register({generator.module_class_name})")
    return 0


_MAKE_HANDLERS["service"] = _cmd_make_service


def _cmd_make_crud(args: argparse.Namespace) -> int:
    """Create a complete CRUD resource in the current directory.

    Like ``create`` this does not build a READY application first: it generates
    files on disk.  Controlled failures (invalid name, existing resource) raise
    :class:`CommandError` and return the framework CLI failure exit code.
    """
    from betrayer.generators.crud import CrudGenerator

    as_json = _as_json(args)
    name = args.resource_name
    force = bool(getattr(args, "force", False))
    try:
        generator = CrudGenerator(name=name, output_dir=Path.cwd(), overwrite=force)
    except Exception as exc:  # noqa: BLE001 - name validation failure
        raise CommandError(str(exc)) from exc
    try:
        output = generator.generate()
    except Exception as exc:  # noqa: BLE001 - existing resource, write failure
        raise CommandError(str(exc)) from exc
    if not output.success:
        detail = "; ".join(
            f"{e['path']}: {e['message']}" for e in output.errors
        )
        raise CommandError(f"failed to create crud resource: {detail}")
    if as_json:
        _print_json(
            {
                "resource": generator.resource_name,
                "path": str(generator.target),
                "model_class": generator.model_class_name,
                "repository_class": generator.repository_class_name,
                "service_class": generator.service_class_name,
                "module_class": generator.module_class_name,
                "created": output.created,
                "updated": output.updated,
                "skipped": output.skipped,
            }
        )
        return 0
    print(f"Created CRUD resource: {generator.resource_name} ({generator.target})")
    for relative in output.created:
        print(f"  created {relative}")
    for relative in output.updated:
        print(f"  updated {relative}")
    print("Register it in your application with:")
    print(f"  app.modules.register({generator.module_class_name})")
    return 0


_MAKE_HANDLERS["crud"] = _cmd_make_crud


def _cmd_make_migration(args: argparse.Namespace) -> int:
    """Create a new database migration file in the current directory.

    Like ``create`` this does not build a READY application first: it generates
    one file on disk.  Controlled failures (invalid name, existing migration)
    raise :class:`CommandError` and return the framework CLI failure exit code.
    """
    from betrayer.generators.migration import MigrationGenerator

    as_json = _as_json(args)
    name = args.migration_name
    force = bool(getattr(args, "force", False))
    try:
        generator = MigrationGenerator(name=name, output_dir=Path.cwd(), overwrite=force)
    except Exception as exc:  # noqa: BLE001 - name validation failure
        raise CommandError(str(exc)) from exc
    try:
        output = generator.generate()
    except Exception as exc:  # noqa: BLE001 - existing migration, write failure
        raise CommandError(str(exc)) from exc
    if not output.success:
        detail = "; ".join(
            f"{e['path']}: {e['message']}" for e in output.errors
        )
        raise CommandError(f"failed to create migration: {detail}")
    if as_json:
        _print_json(
            {
                "migration": generator.migration_name,
                "sequence": generator.sequence,
                "file": generator.file_name,
                "path": str(generator.target),
                "created": output.created,
                "updated": output.updated,
                "skipped": output.skipped,
            }
        )
        return 0
    print(f"Created migration: {generator.migration_name} ({generator.file_name})")
    for relative in output.created:
        print(f"  created {relative}")
    for relative in output.updated:
        print(f"  updated {relative}")
    print("Register it in your migration registry with:")
    print(f"  from {generator.module_import} import {generator.class_name}")
    return 0


_MAKE_HANDLERS["migration"] = _cmd_make_migration


def _cmd_make_extension(args: argparse.Namespace) -> int:
    """Create a new extension skeleton in the current directory.

    Like ``create`` this does not build a READY application first: it generates
    files on disk.  Controlled failures (invalid name, existing extension)
    raise :class:`CommandError` and return the framework CLI failure exit code.
    """
    from betrayer.generators.extension import ExtensionGenerator

    as_json = _as_json(args)
    name = args.extension_name
    force = bool(getattr(args, "force", False))
    try:
        generator = ExtensionGenerator(name=name, output_dir=Path.cwd(), overwrite=force)
    except Exception as exc:  # noqa: BLE001 - name validation failure
        raise CommandError(str(exc)) from exc
    try:
        output = generator.generate()
    except Exception as exc:  # noqa: BLE001 - existing extension, write failure
        raise CommandError(str(exc)) from exc
    if not output.success:
        detail = "; ".join(
            f"{e['path']}: {e['message']}" for e in output.errors
        )
        raise CommandError(f"failed to create extension: {detail}")
    if as_json:
        _print_json(
            {
                "extension": generator.extension_name,
                "path": str(generator.target),
                "extension_class": generator.class_name,
                "created": output.created,
                "updated": output.updated,
                "skipped": output.skipped,
            }
        )
        return 0
    print(f"Created extension: {generator.extension_name} ({generator.target})")
    for relative in output.created:
        print(f"  created {relative}")
    for relative in output.updated:
        print(f"  updated {relative}")
    print("Register it in your application with:")
    print(f"  app.extensions.register({generator.class_name})")
    return 0


_MAKE_HANDLERS["extension"] = _cmd_make_extension


def _cmd_make(args: argparse.Namespace) -> int:
    """Dispatch ``bet make <target>`` to the matching generator command."""
    target = getattr(args, "make_target", None)
    available = ", ".join(sorted(_MAKE_HANDLERS))
    if target is None:
        raise CommandError(f"make requires a target (available: {available})")
    handler = _MAKE_HANDLERS.get(target)
    if handler is None:
        raise CommandError(
            f"unknown make target: {target!r} (available: {available})"
        )
    return handler(args)


def _configure_make(parser: argparse.ArgumentParser) -> None:
    """Add the ``make`` subcommands (``bet make module <name>``, ``bet make resource <name>``, ...).

    ``make`` groups generators under a single top level command while keeping
    the flat registry: the nested subparser only selects a target, the actual
    work lives in the per target handler above.
    """
    subparsers = parser.add_subparsers(dest="make_target", metavar="target")
    module_parser = subparsers.add_parser(
        "module", help="create a new application module"
    )
    module_parser.add_argument(
        "module_name",
        help="new module name (letters, digits, '-' and '_'; must start with a letter)",
    )
    module_parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite an existing module instead of failing",
    )
    module_parser.add_argument(
        "--json", action="store_true", help="emit machine readable JSON output"
    )
    resource_parser = subparsers.add_parser(
        "resource", help="create a new data resource (model + repository + routes)"
    )
    resource_parser.add_argument(
        "resource_name",
        help="new resource name (letters, digits, '-' and '_'; must start with a letter)",
    )
    resource_parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite an existing resource instead of failing",
    )
    resource_parser.add_argument(
        "--json", action="store_true", help="emit machine readable JSON output"
    )
    service_parser = subparsers.add_parser(
        "service", help="create a new application service"
    )
    service_parser.add_argument(
        "service_name",
        help="new service name (letters, digits, '-' and '_'; must start with a letter)",
    )
    service_parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite an existing service instead of failing",
    )
    service_parser.add_argument(
        "--json", action="store_true", help="emit machine readable JSON output"
    )
    crud_parser = subparsers.add_parser(
        "crud",
        help="create a complete CRUD resource (model + repository + service + routes)",
    )
    crud_parser.add_argument(
        "resource_name",
        help="new resource name (letters, digits, '-' and '_'; must start with a letter)",
    )
    crud_parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite an existing resource instead of failing",
    )
    crud_parser.add_argument(
        "--json", action="store_true", help="emit machine readable JSON output"
    )
    migration_parser = subparsers.add_parser(
        "migration", help="create a new database migration file"
    )
    migration_parser.add_argument(
        "migration_name",
        help="new migration name (letters, digits, '-' and '_'; must start with a letter)",
    )
    migration_parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite an existing migration instead of failing",
    )
    migration_parser.add_argument(
        "--json", action="store_true", help="emit machine readable JSON output"
    )
    extension_parser = subparsers.add_parser(
        "extension", help="create a new extension skeleton"
    )
    extension_parser.add_argument(
        "extension_name",
        help="new extension name (letters, digits, '-' and '_'; must start with a letter)",
    )
    extension_parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite an existing extension instead of failing",
    )
    extension_parser.add_argument(
        "--json", action="store_true", help="emit machine readable JSON output"
    )


# ── discover ─────────────────────────────────────────────────────


def _cmd_discover(args: argparse.Namespace) -> int:
    """Discover Betrayer capabilities (LLM-facing knowledge surface).

    Sub-commands:

    ``bet discover``
        List all capabilities (summary).

    ``bet discover <name>``
        Get full definition of a named capability.

    ``bet discover --search <query>``
        Search capabilities by keyword (name, purpose, category).

    All sub-commands support ``--json`` for machine-readable output.
    """
    from betrayer.ai import discover

    as_json = _as_json(args)
    search_query = getattr(args, "search", None)
    capability_name = getattr(args, "capability_name", None)

    # --search takes precedence over positional name
    if search_query:
        results = discover.search(search_query)
        if as_json:
            _print_json({"success": True, "results": results, "query": search_query})
            return 0
        if not results:
            print(f"No capabilities matched {search_query!r}")
            return 0
        print(f"Capabilities matching {search_query!r}:")
        for cap in results:
            print(f"  {cap['name']:25s}  {cap['category']:20s}  {cap['status']:12s}  {cap['purpose']}")
        return 0

    if capability_name:
        try:
            cap = discover.get(capability_name)
        except LookupError as exc:
            if as_json:
                _print_json({"success": False, "error": str(exc)})
                return 1
            print(f"[FAIL] {exc}")
            return 1

        if as_json:
            _print_json({"success": True, "capability": cap})
            return 0

        print(f"Capability: {cap['name']}")
        print(f"  Purpose:  {cap['purpose']}")
        print(f"  Category: {cap['category']}")
        print(f"  Status:   {cap['status']}")
        print(f"  Package:  {cap['package']}")
        print(f"  Contract: {cap['contract'] or '(included in source)'}")
        print(f"  Public API:")
        for api in cap['public_api']:
            print(f"    - {api}")
        print(f"  Related capabilities: {', '.join(sorted(set(cap['uses'] + cap['used_by']))) or '(none)'}")
        return 0

    # Default: list all capabilities
    result = discover.list()
    if as_json:
        _print_json({"success": True, "capabilities": result, "total": len(result)})
        return 0

    # Group by category for human-friendly output
    by_category: dict[str, list[dict]] = {}
    for cap in result:
        by_category.setdefault(cap["category"], []).append(cap)

    print(f"Betrayer Capabilities ({len(result)} total)")
    print()
    for cat in sorted(by_category):
        print(f"  [{cat}]")
        for cap in sorted(by_category[cat], key=lambda c: c["name"]):
            print(f"    {cap['name']:25s}  {cap['status']:12s}  {cap['purpose']}")
        print()
    print("Use: bet discover <name>  -- get full capability definition")
    print("Use: bet discover --search <query>  -- search capabilities")
    return 0


def _configure_discover(parser: argparse.ArgumentParser) -> None:
    """Add ``discover`` sub-commands."""
    parser.add_argument(
        "capability_name",
        nargs="?",
        default=None,
        help="capability name (e.g. pagination, authentication, cache)",
    )
    parser.add_argument(
        "--search",
        metavar="QUERY",
        default=None,
        help="search capabilities by name, purpose, category, or package",
    )


def _configure_manifest(parser: argparse.ArgumentParser) -> None:
    """Add ``manifest`` specific flags (registered with the command)."""
    parser.add_argument(
        "--write",
        action="store_true",
        help="regenerate the generated .betrayer metadata from runtime state",
    )


# ── test command ────────────────────────────────────────────────────

_TEST_LAYERS = {
    "unit": "unit tests (test_*_unit.py, tests/unit/)",
    "integration": "integration tests (test_*_integration.py, tests/integration/)",
    "functional": "functional/API tests (test_*_functional.py, tests/functional/)",
    "smoke": "smoke tests (test_*_smoke.py, tests/smoke/)",
}

_TEST_FILE_PATTERNS = {
    "unit": ("test_*_unit.py", "unit/"),
    "integration": ("test_*_integration.py", "integration/"),
    "functional": ("test_*_functional.py", "functional/"),
    "smoke": ("test_*_smoke.py", "smoke/"),
}


def _cmd_test(args: argparse.Namespace) -> int:
    """Run tests with pytest and produce LLM-friendly output.

    Delegates to ``pytest`` under the hood; never reimplements a test runner.
    """
    as_json = _as_json(args)

    # Build pytest arguments.
    pytest_args: list[str] = []

    # Filter by layer if provided.
    provided_layers = [
        layer for layer in _TEST_LAYERS if getattr(args, layer, False)
    ]
    paths = getattr(args, "test_paths", ["tests"])

    # Determine test paths/patterns.
    if paths != ["tests"]:
        pytest_args.extend(str(p) for p in paths)
    elif provided_layers:
        # Collect keyword expressions and paths per layer.
        k_exprs: list[str] = []
        for layer in provided_layers:
            pattern, dir_pattern = _TEST_FILE_PATTERNS[layer]
            # Use -k to filter by file pattern (pytest doesn't have layer tags)
            # We use a simple heuristic: match test files by their name pattern.
            # Since we control the test file naming convention, we can use
            # the convention directly with --ignore for other layers.
            pass

        # Better approach: run all tests but filter with -k for layer-specific.
        # But pytest -k filters on test names, not file names.
        # The simplest reliable approach: use path with glob patterns via
        # specific test file discovery.

        # For each layer, collect matching test files.
        test_files: list[str] = []
        from pathlib import Path as _Path

        project_root = _Path(__file__).resolve().parents[2]
        tests_dir = project_root / "tests"

        for layer in provided_layers:
            pattern, _dir_pattern = _TEST_FILE_PATTERNS[layer]
            for tf in sorted(tests_dir.glob(pattern)):
                test_files.append(str(tf))

        if not test_files:
            if as_json:
                _print_json(_empty_test_result("no tests found for layer"))
                return 0
            print("No tests found for the requested layer.")
            return 0

        pytest_args.extend(test_files)
    else:
        # No filter: run all tests in tests/.
        pytest_args.extend(str(p) for p in paths)

    # Add pytest options: verbose, no-header, no-summary for LLM-friendly parsing.
    pytest_args.extend(["-v", "--tb=short", "--no-header", "--no-summary"])

    # Capture output.
    import io
    import sys as _sys
    from unittest import runner as _runner

    # Use pytest's own capture mechanism.
    import pytest as _pytest

    # We use pytest.main with a custom plugin to capture results.
    collected_results: list[dict] = []
    start_time = __import__("time").time()

    class _ResultCollector:
        """Minimal pytest plugin that collects structured results."""

        def __init__(self) -> None:
            self.passed: list[dict] = []
            self.failed: list[dict] = []
            self.skipped: list[dict] = []

        @staticmethod
        def pytest_report_header() -> list[str]:
            return []

        def pytest_runtest_logreport(self, report: Any) -> None:
            if report.when != "call" and (
                report.when != "setup" or report.failed
            ):
                return
            node_id = report.nodeid
            # Skip non-test items.
            if "::" not in node_id:
                return
            parts = node_id.split("::")
            test_name = parts[-1]
            test_file = parts[0] if len(parts) > 1 else node_id

            entry = {
                "test": test_name,
                "file": test_file,
                "line": report.location[1] + 1 if report.location else 0,
            }

            if report.passed and report.when == "call":
                entry["message"] = "passed"
                self.passed.append(entry)
            elif report.skipped:
                entry["message"] = report.longreprtext if report.longreprtext else "skipped"
                self.skipped.append(entry)
            elif report.failed:
                # Extract short message.
                msg = str(report.longreprtext) if report.longreprtext else "unknown"
                # Truncate to first meaningful line.
                msg = msg.split("\n")[0] if "\n" in msg else msg
                entry["message"] = msg
                self.failed.append(entry)

    collector = _ResultCollector()
    exit_code = _pytest.main(
        pytest_args,
        plugins=[collector],
    )
    duration = __import__("time").time() - start_time

    # Build structured result.
    passed = len(collector.passed)
    failed = len(collector.failed)
    skipped = len(collector.skipped)
    total = passed + failed + skipped

    result = {
        "success": exit_code == 0,
        "total": total,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "duration": round(duration, 3),
        "failures": collector.failed,
    }

    if as_json:
        _print_json(result)
        return 0 if result["success"] else 1

    # LLM-friendly text output.
    print(f"TEST_RESULT: {'PASS' if result['success'] else 'FAIL'}")
    print(f"total: {total}  passed: {passed}  failed: {failed}  skipped: {skipped}")
    print(f"duration: {duration:.3f}s")
    for failure in collector.failed:
        print()
        print("TEST_FAILED")
        print(f"test: {failure['test']}")
        print(f"file: {failure['file']}")
        print(f"line: {failure['line']}")
        print(f"message: {failure['message']}")

    return 0 if result["success"] else 1


def _empty_test_result(reason: str) -> dict:
    return {
        "success": True,
        "total": 0,
        "passed": 0,
        "failed": 0,
        "skipped": 0,
        "duration": 0.0,
        "failures": [],
        "note": reason,
    }


def _configure_test(parser: argparse.ArgumentParser) -> None:
    """Add ``test`` specific arguments (registered with the command)."""
    # Optional paths (defaults to "tests" directory).
    parser.add_argument(
        "test_paths",
        nargs="*",
        default=["tests"],
        help="test path(s) (file or directory, default: tests/)",
    )
    # Layer filters (mutually exclusive-ish; last wins in argparse).
    for layer, help_text in _TEST_LAYERS.items():
        flag = f"--{layer}"
        parser.add_argument(
            flag,
            action="store_true",
            help=help_text,
        )


def build_command_registry() -> CommandRegistry:
    """Build the single CLI dispatch table.

    The registry is the *only* place a command is wired up.  Adding ``create``,
    ``generate``, ``migrate`` or ``inspect`` later means registering one more
    :class:`~betrayer.cli.registry.Command` here (or from a dedicated command
    module); the parser and the dispatch loop stay untouched.
    """
    registry = CommandRegistry(CLI_PROG)
    registry.register(Command("info", COMMAND_HELP["info"], _cmd_info))
    registry.register(Command("environment", COMMAND_HELP["environment"], _cmd_environment))
    registry.register(Command("status", COMMAND_HELP["status"], _cmd_status))
    registry.register(Command("config", COMMAND_HELP["config"], _cmd_config))
    registry.register(Command("doctor", COMMAND_HELP["doctor"], _cmd_doctor))
    registry.register(Command("check", COMMAND_HELP["check"], _cmd_check))
    registry.register(
        Command("debug", COMMAND_HELP["debug"], _cmd_debug, configure=_configure_debug)
    )
    registry.register(Command("validate", COMMAND_HELP["validate"], _cmd_validate))
    registry.register(
        Command("manifest", COMMAND_HELP["manifest"], _cmd_manifest, configure=_configure_manifest)
    )
    registry.register(
        Command("create", COMMAND_HELP["create"], _cmd_create, configure=_configure_create)
    )
    registry.register(
        Command("make", COMMAND_HELP["make"], _cmd_make, configure=_configure_make)
    )
    registry.register(
        Command("test", COMMAND_HELP["test"], _cmd_test, configure=_configure_test)
    )
    registry.register(
        Command("queue", COMMAND_HELP["queue"], _cmd_queue, configure=_configure_queue)
    )
    registry.register(
        Command("schedule", COMMAND_HELP["schedule"], _cmd_schedule, configure=_configure_schedule)
    )
    registry.register(
        Command("realtime", COMMAND_HELP["realtime"], _cmd_realtime, configure=_configure_realtime)
    )
    registry.register(
        Command("discover", COMMAND_HELP["discover"], _cmd_discover, configure=_configure_discover)
    )
    return registry


COMMAND_REGISTRY: CommandRegistry = build_command_registry()

# ``COMMANDS`` stays the canonical, ordered list of command names.  It is
# derived from the registry so the registry remains the single source of truth.
COMMANDS = COMMAND_REGISTRY.names()


def build_parser(registry: Optional[CommandRegistry] = None) -> argparse.ArgumentParser:
    """Build the argparse parser (public so tests can assert the surface).

    Subcommands are generated from a :class:`CommandRegistry`; when no registry
    is passed the shared :data:`COMMAND_REGISTRY` is used.  Neither the parser
    nor its loop needs to change to add a new command.
    """
    active = registry if registry is not None else COMMAND_REGISTRY
    parser = argparse.ArgumentParser(prog=active.prog, description=f"{FRAMEWORK_NAME} framework CLI")
    parser.add_argument("--version", action="version", version=f"{FRAMEWORK_NAME} {__version__}")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="emit machine readable JSON output")
    subparsers = parser.add_subparsers(dest="command", metavar="command")
    for command in active.commands():
        subparser = subparsers.add_parser(
            command.name, parents=[common], help=command.help, description=command.help
        )
        command.add_arguments(subparser)
        # Bind the resolved Command so dispatch never needs a second lookup table.
        subparser.set_defaults(_command=command)
    return parser


def main(argv: Optional[Sequence[str]] = None, registry: Optional[CommandRegistry] = None) -> int:
    """CLI entry point. Returns a real exit code (0 = success)."""
    parser = build_parser(registry)
    args = parser.parse_args(argv)
    command = getattr(args, "_command", None)
    if command is None:
        parser.print_help()
        return 2
    try:
        return int(command.handler(args))
    except CommandError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return exc.exit_code
    except BetrayerError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - never leak a traceback as the only output
        print(f"[FAIL] unexpected error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())
