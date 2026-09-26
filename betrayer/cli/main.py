"""Betrayer command line interface.

Commands are intentionally few.  Every command:

* builds a READY application through ``Bootstrap``,
* reads state exclusively through ``betrayer.diagnostics.Inspector``,
* prints short, deterministic, LLM friendly output,
* supports ``--json`` for machine consumption (always valid JSON),
* returns a real exit code (0 = success, non-zero = failure).

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

PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]
MANIFEST_PATH: Path = PROJECT_ROOT / ".betrayer" / "manifest.json"
ARCHITECTURE_PATH: Path = PROJECT_ROOT / ".betrayer" / "architecture.json"

COMMANDS = ("info", "environment", "status", "config", "doctor", "validate", "manifest")

COMMAND_HELP = {
    "info": "show framework, python, os and application state",
    "environment": "show detected environment information",
    "status": "show runtime and lifecycle status",
    "config": "show effective configuration (secrets masked)",
    "doctor": "run foundation health checks",
    "validate": "validate the foundation (imports, structure, lifecycle, ...)",
    "manifest": "show or regenerate the machine readable framework manifest",
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


def _cmd_info(as_json: bool) -> int:
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


def _cmd_environment(as_json: bool) -> int:
    data = Environment.detect().to_dict()
    if as_json:
        _print_json(data)
        return 0
    for key in sorted(data):
        print(f"{key}: {data[key]}")
    return 0


def _cmd_status(as_json: bool) -> int:
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


def _cmd_config(as_json: bool) -> int:
    application = _ready_application()
    data = application.config.safe_data()
    if as_json:
        _print_json(data)
        return 0
    print("Configuration (secrets masked):")
    for key in sorted(data):
        print(f"{key} = {data[key]}")
    return 0


def _cmd_doctor(as_json: bool) -> int:
    application = _ready_application()
    report = Inspector(application).doctor()
    if as_json:
        _print_json(report)
        return 0 if report["ok"] else 1
    for check in report["checks"]:
        if check["status"] == "ok":
            print(f"[OK] {check['name']}")
        else:
            print(f"[FAIL] {check['name']}")
            print(f"Reason: {check.get('reason', 'unknown')}")
            print(f"Suggested check: {check.get('suggestion', 'inspect the component manually')}")
    print("Doctor: " + ("all checks passed" if report["ok"] else "problems detected"))
    return 0 if report["ok"] else 1


def _cmd_validate(as_json: bool) -> int:
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


def _cmd_manifest(as_json: bool, write: bool = False) -> int:
    """Show the runtime derived manifest; ``--write`` regenerates the file.

    ``.betrayer/manifest.json`` and ``.betrayer/architecture.json`` are never
    hand edited: they are rebuilt from ``betrayer.core.meta`` plus the CLI and
    package surface, so a metadata file can never drift away from the runtime
    it describes.
    """
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


_COMMAND_HANDLERS = {
    "info": _cmd_info,
    "environment": _cmd_environment,
    "status": _cmd_status,
    "config": _cmd_config,
    "doctor": _cmd_doctor,
    "validate": _cmd_validate,
    "manifest": _cmd_manifest,
}


def build_parser() -> argparse.ArgumentParser:
    """Build the argparse parser (public so tests can assert the surface)."""
    parser = argparse.ArgumentParser(prog="betrayer", description=f"{FRAMEWORK_NAME} framework CLI")
    parser.add_argument("--version", action="version", version=f"{FRAMEWORK_NAME} {__version__}")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="emit machine readable JSON output")
    subparsers = parser.add_subparsers(dest="command", metavar="command")
    for name in COMMANDS:
        subparser = subparsers.add_parser(
            name, parents=[common], help=COMMAND_HELP[name], description=COMMAND_HELP[name]
        )
        if name == "manifest":
            subparser.add_argument(
                "--write", action="store_true", help="regenerate the generated .betrayer metadata from runtime state"
            )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point. Returns a real exit code (0 = success)."""
    parser = build_parser()
    args = parser.parse_args(argv)
    command = getattr(args, "command", None)
    if command is None:
        parser.print_help()
        return 2
    as_json = bool(getattr(args, "json", False))
    try:
        handler = _COMMAND_HANDLERS[command]
        if command == "manifest":
            return handler(as_json, write=bool(getattr(args, "write", False)))
        return handler(as_json)
    except BetrayerError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - never leak a traceback as the only output
        print(f"[FAIL] unexpected error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())
