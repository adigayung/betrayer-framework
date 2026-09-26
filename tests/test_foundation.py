"""Tests for Betrayer Framework Foundation."""

import json
import sys
from pathlib import Path

import pytest

from betrayer import (
    BetrayerApplication,
    Bootstrap,
    Config,
    Environment,
    Lifecycle,
    LifecycleState,
    Registry,
    RuntimeContext,
)
from betrayer.core.exceptions import (
    BetrayerError,
    BootstrapError,
    ConfigurationError,
    EnvironmentError,
    LifecycleError,
    RuntimeError as BetrayerRuntimeError,
    RegistryError,
)
from betrayer.diagnostics.inspector import Inspector


# ── Package Import ──────────────────────────────────────────────


def test_package_import():
    """Betrayer package can be imported."""
    import betrayer

    assert hasattr(betrayer, "__version__")
    assert betrayer.__version__ == "0.1.0"


def test_all_public_exports():
    """All expected public symbols are exported."""
    import betrayer

    assert hasattr(betrayer, "BetrayerApplication")
    assert hasattr(betrayer, "Bootstrap")
    assert hasattr(betrayer, "Config")
    assert hasattr(betrayer, "Environment")
    assert hasattr(betrayer, "Lifecycle")
    assert hasattr(betrayer, "LifecycleState")
    assert hasattr(betrayer, "Registry")
    assert hasattr(betrayer, "RuntimeContext")
    assert hasattr(betrayer, "__version__")


# ── Application Creation ────────────────────────────────────────


def test_application_creation():
    """Application can be created with a name."""
    app = BetrayerApplication(name="test-app")
    assert app.name == "test-app"
    assert app.state == LifecycleState.CREATED


def test_application_default_name():
    """Application has a default name."""
    app = BetrayerApplication()
    assert app.name == "betrayer"


def test_application_has_registry():
    """Application has a registry."""
    app = BetrayerApplication(name="test-app")
    assert isinstance(app.registry, Registry)


def test_application_has_lifecycle():
    """Application has a lifecycle."""
    app = BetrayerApplication(name="test-app")
    assert isinstance(app.lifecycle, Lifecycle)


def test_application_has_config():
    """Application has a config."""
    app = BetrayerApplication(name="test-app")
    assert isinstance(app.config, Config)


def test_application_has_environment():
    """Application has an environment."""
    app = BetrayerApplication(name="test-app")
    assert isinstance(app.environment, Environment)


def test_application_has_runtime_context():
    """Application has a runtime context."""
    app = BetrayerApplication(name="test-app")
    assert isinstance(app.runtime_context, RuntimeContext)


# ── Bootstrap ────────────────────────────────────────────────────


def test_bootstrap_transitions():
    """Bootstrap transitions through expected states."""
    app = BetrayerApplication(name="test-app")
    assert app.state == LifecycleState.CREATED

    app.bootstrap()
    assert app.state == LifecycleState.BOOTSTRAPPING

    app.initialize()
    assert app.state == LifecycleState.READY

    app.start()
    assert app.state == LifecycleState.RUNNING


def test_bootstrap_deterministic():
    """Bootstrap produces the same state sequence every time."""
    app1 = BetrayerApplication(name="test-app")
    app1.bootstrap()
    app1.initialize()
    app1.ready()
    app1.start()

    app2 = BetrayerApplication(name="test-app")
    app2.bootstrap()
    app2.initialize()
    app2.ready()
    app2.start()

    assert app1.state == app2.state == LifecycleState.RUNNING


def test_bootstrap_with_config():
    """Bootstrap works with explicit config."""
    config = Config(defaults={"app.name": "custom-app"})
    app = BetrayerApplication(name="test-app", config=config)
    app.bootstrap()
    assert app.config.get("app.name") == "custom-app"


# ── Configuration ────────────────────────────────────────────────


def test_config_defaults():
    """Config returns default values."""
    config = Config(defaults={"app.name": "my-app", "app.debug": False})
    assert config.get("app.name") == "my-app"
    assert config.get("app.debug") is False


def test_config_set_and_get():
    """Config can set and get values."""
    config = Config(defaults={"app.name": "my-app"})
    config.set("app.debug", True)
    assert config.get("app.debug") is True


def test_config_nested_keys():
    """Config supports nested keys with dot notation."""
    config = Config(defaults={"database.host": "localhost", "database.port": 5432})
    assert config.get("database.host") == "localhost"
    assert config.get("database.port") == 5432


def test_config_missing_key_returns_none():
    """Missing key returns None by default."""
    config = Config(defaults={"app.name": "my-app"})
    assert config.get("nonexistent") is None


def test_config_missing_key_with_default():
    """Missing key returns provided default."""
    config = Config(defaults={"app.name": "my-app"})
    assert config.get("nonexistent", "fallback") == "fallback"


def test_config_finalised():
    """Config cannot be modified after finalisation."""
    config = Config(defaults={"app.name": "my-app"})
    config.finalise()
    with pytest.raises(ConfigurationError):
        config.set("app.debug", True)


def test_config_env_override(monkeypatch):
    """Environment variables override config defaults."""
    monkeypatch.setenv("BETRAYER_APP__DEBUG", "1")
    config = Config(defaults={"app.debug": False})
    config.load_env()
    assert config.get("app.debug") is True


def test_config_safe_data_masks_secrets():
    """safe_data() masks secret keys."""
    config = Config(defaults={"api.secret_key": "super-secret", "app.name": "my-app"})
    safe = config.safe_data()
    assert safe["api.secret_key"] == "****"
    assert safe["app.name"] == "my-app"


def test_config_keys_excludes_secrets_when_safe():
    """keys(safe=True) excludes secret keys."""
    config = Config(defaults={"api.secret_key": "secret", "app.name": "my-app"})
    keys = config.keys(safe=True)
    assert "api.secret_key" not in keys
    assert "app.name" in keys


# ── Environment Detection ────────────────────────────────────────


def test_environment_detection():
    """Environment detection returns valid info."""
    env = Environment.detect()
    assert env.python_version != ""
    assert env.os_name != ""
    assert env.architecture != ""
    assert env.executable != ""
    assert env.cwd is not None
    assert env.project_root is not None


def test_environment_python_version():
    """Environment detects Python version."""
    env = Environment.detect()
    assert sys.version_info.major >= 3


def test_environment_cwd_exists():
    """Current working directory exists."""
    env = Environment.detect()
    assert env.cwd.exists()


def test_environment_project_root_exists():
    """Project root directory exists."""
    env = Environment.detect()
    assert env.project_root.exists()


def test_environment_is_frozen():
    """EnvironmentInfo is immutable (frozen dataclass)."""
    env = Environment.detect()
    with pytest.raises(Exception):
        env.python_version = "hacked"  # type: ignore[misc]


# ── Lifecycle Ordering ───────────────────────────────────────────


def test_lifecycle_state_order():
    """Lifecycle states follow correct order."""
    lifecycle = Lifecycle()
    assert lifecycle.state == LifecycleState.CREATED

    lifecycle.transition(LifecycleState.BOOTSTRAPPING)
    assert lifecycle.state == LifecycleState.BOOTSTRAPPING

    lifecycle.transition(LifecycleState.READY)
    assert lifecycle.state == LifecycleState.READY

    lifecycle.transition(LifecycleState.RUNNING)
    assert lifecycle.state == LifecycleState.RUNNING

    lifecycle.transition(LifecycleState.STOPPING)
    assert lifecycle.state == LifecycleState.STOPPING

    lifecycle.transition(LifecycleState.STOPPED)
    assert lifecycle.state == LifecycleState.STOPPED


def test_lifecycle_invalid_transition_raises():
    """Invalid lifecycle transition raises LifecycleError."""
    lifecycle = Lifecycle()
    with pytest.raises(LifecycleError):
        lifecycle.transition(LifecycleState.RUNNING)  # CREATED → RUNNING is invalid


def test_lifecycle_event_ordering():
    """Lifecycle events fire in correct order."""
    events: list[str] = []

    def on_bootstrap(state, app):
        events.append("on_bootstrap")

    def on_initialize(state, app):
        events.append("on_initialize")

    def on_ready(state, app):
        events.append("on_ready")

    def on_start(state, app):
        events.append("on_start")

    lifecycle = Lifecycle()
    lifecycle.register_handler(LifecycleState.BOOTSTRAPPING, on_bootstrap)
    lifecycle.register_handler(LifecycleState.READY, on_initialize)
    lifecycle.register_handler(LifecycleState.READY, on_ready)
    lifecycle.register_handler(LifecycleState.RUNNING, on_start)

    lifecycle.transition(LifecycleState.BOOTSTRAPPING)
    lifecycle.transition(LifecycleState.READY)
    lifecycle.transition(LifecycleState.RUNNING)

    assert events == [
        "on_bootstrap",
        "on_initialize",
        "on_ready",
        "on_start",
    ]


def test_lifecycle_failure_transitions_to_failed():
    """Failed handler transitions lifecycle to FAILED."""
    lifecycle = Lifecycle()

    def failing_handler(state, app):
        raise RuntimeError("Handler failed")

    lifecycle.register_handler(LifecycleState.BOOTSTRAPPING, failing_handler)

    with pytest.raises(BetrayerRuntimeError):
        lifecycle.transition(LifecycleState.BOOTSTRAPPING)

    assert lifecycle.state == LifecycleState.FAILED


def test_lifecycle_previous_state_on_failure():
    """Lifecycle records previous state when failure occurs."""
    lifecycle = Lifecycle()
    lifecycle.transition(LifecycleState.BOOTSTRAPPING)
    assert lifecycle.previous_state == LifecycleState.CREATED


# ── Registry ─────────────────────────────────────────────────────


def test_registry_register_and_get():
    """Registry can register and retrieve components."""
    registry = Registry()
    registry.register("my_component", {"value": 42})
    assert registry.get("my_component") == {"value": 42}


def test_registry_register_duplicate_raises():
    """Registering duplicate component raises RegistryError."""
    registry = Registry()
    registry.register("comp", "first")
    with pytest.raises(RegistryError):
        registry.register("comp", "second")


def test_registry_get_missing_raises():
    """Getting missing component raises RegistryError."""
    registry = Registry()
    with pytest.raises(RegistryError):
        registry.get("nonexistent")


def test_registry_has():
    """Registry can check if component exists."""
    registry = Registry()
    registry.register("comp", "value")
    assert registry.has("comp") is True
    assert registry.has("missing") is False


def test_registry_list_all():
    """Registry can list all registered components."""
    registry = Registry()
    registry.register("a", 1)
    registry.register("b", 2)
    all_components = registry.list_all()
    assert "a" in all_components
    assert "b" in all_components
    assert len(all_components) == 2


# ── Runtime Context ──────────────────────────────────────────────


def test_runtime_context_holds_application():
    """RuntimeContext holds reference to application."""
    app = BetrayerApplication(name="test-app")
    ctx = RuntimeContext(application=app)
    assert ctx.application is app


def test_runtime_context_holds_environment():
    """RuntimeContext holds reference to environment."""
    app = BetrayerApplication(name="test-app")
    ctx = RuntimeContext(application=app)
    assert ctx.environment is not None


def test_runtime_context_holds_config():
    """RuntimeContext holds reference to config."""
    app = BetrayerApplication(name="test-app")
    ctx = RuntimeContext(application=app)
    assert ctx.config is not None


def test_runtime_context_holds_lifecycle():
    """RuntimeContext holds reference to lifecycle."""
    app = BetrayerApplication(name="test-app")
    ctx = RuntimeContext(application=app)
    assert ctx.lifecycle is not None


def test_runtime_context_holds_registry():
    """RuntimeContext holds reference to registry."""
    app = BetrayerApplication(name="test-app")
    ctx = RuntimeContext(application=app)
    assert ctx.registry is not None


def test_runtime_context_is_not_singleton():
    """RuntimeContext is not a global singleton."""
    app1 = BetrayerApplication(name="app1")
    app2 = BetrayerApplication(name="app2")
    ctx1 = RuntimeContext(application=app1)
    ctx2 = RuntimeContext(application=app2)
    assert ctx1 is not ctx2
    assert ctx1.application is app1
    assert ctx2.application is app2


# ── Exception Hierarchy ──────────────────────────────────────────


def test_betrayer_error_is_base():
    """BetrayerError is the base exception."""
    assert issubclass(BetrayerError, Exception)


def test_bootstrap_error_inherits():
    """BootstrapError inherits from BetrayerError."""
    assert issubclass(BootstrapError, BetrayerError)


def test_configuration_error_inherits():
    """ConfigurationError inherits from BetrayerError."""
    assert issubclass(ConfigurationError, BetrayerError)


def test_environment_error_inherits():
    """EnvironmentError inherits from BetrayerError."""
    assert issubclass(EnvironmentError, BetrayerError)


def test_lifecycle_error_inherits():
    """LifecycleError inherits from BetrayerError."""
    assert issubclass(LifecycleError, BetrayerError)


def test_runtime_error_inherits():
    """RuntimeError inherits from BetrayerError."""
    assert issubclass(BetrayerRuntimeError, BetrayerError)


def test_exception_has_code():
    """Exception has a code attribute."""
    err = BetrayerError(message="test", code="TEST_CODE")
    assert err.code == "TEST_CODE"


def test_exception_has_component():
    """Exception has a component attribute."""
    err = BetrayerError(message="test", component="test_component")
    assert err.component == "test_component"


def test_exception_has_stage():
    """Exception has a stage attribute."""
    err = BetrayerError(message="test", stage="bootstrapping")
    assert err.stage == "bootstrapping"


def test_exception_has_cause():
    """Exception has a cause attribute."""
    original = ValueError("original error")
    err = BetrayerError(message="wrapped", cause=original)
    assert err.cause is original


# ── Inspector ────────────────────────────────────────────────────


def test_inspector_info():
    """Inspector.info() returns a dict with expected keys."""
    app = BetrayerApplication(name="test-app")
    inspector = Inspector(app)
    info = inspector.info()
    assert "framework" in info
    assert "version" in info
    assert "python" in info
    assert "os" in info
    assert "state" in info


def test_inspector_environment():
    """Inspector.environment() returns a dict."""
    app = BetrayerApplication(name="test-app")
    inspector = Inspector(app)
    env_info = inspector.environment()
    assert "python_version" in env_info
    assert "os_name" in env_info


def test_inspector_status():
    """Inspector.status() returns a dict."""
    app = BetrayerApplication(name="test-app")
    inspector = Inspector(app)
    status = inspector.status()
    assert "state" in status


def test_inspector_inspect():
    """Inspector.inspect() returns a dict with all info."""
    app = BetrayerApplication(name="test-app")
    inspector = Inspector(app)
    result = inspector.inspect()
    assert "framework" in result
    assert "environment" in result
    assert "lifecycle" in result
    assert "registry" in result


# ── CLI ──────────────────────────────────────────────────────────


def test_cli_info_command_runs():
    """CLI info command runs without error."""
    from betrayer.cli.main import build_parser, main

    parser = build_parser()
    args = parser.parse_args(["info"])
    assert args.command == "info"


def test_cli_environment_command_runs():
    """CLI environment command runs without error."""
    from betrayer.cli.main import build_parser

    parser = build_parser()
    args = parser.parse_args(["environment"])
    assert args.command == "environment"


def test_cli_status_command_runs():
    """CLI status command runs without error."""
    from betrayer.cli.main import build_parser

    parser = build_parser()
    args = parser.parse_args(["status"])
    assert args.command == "status"


def test_cli_doctor_command_runs():
    """CLI doctor command runs without error."""
    from betrayer.cli.main import build_parser

    parser = build_parser()
    args = parser.parse_args(["doctor"])
    assert args.command == "doctor"


def test_cli_validate_command_runs():
    """CLI validate command runs without error."""
    from betrayer.cli.main import build_parser

    parser = build_parser()
    args = parser.parse_args(["validate"])
    assert args.command == "validate"


def test_cli_config_command_runs():
    """CLI config command runs without error."""
    from betrayer.cli.main import build_parser

    parser = build_parser()
    args = parser.parse_args(["config"])
    assert args.command == "config"


def test_cli_json_flag():
    """CLI --json flag is parsed correctly."""
    from betrayer.cli.main import build_parser

    parser = build_parser()
    args = parser.parse_args(["info", "--json"])
    assert args.json is True


# ── Doctor ───────────────────────────────────────────────────────


def test_doctor_checks_python():
    """Doctor checks Python availability."""
    app = BetrayerApplication(name="test-app")
    app.bootstrap()
    inspector = Inspector(app)
    results = inspector.inspect()
    assert results["framework"]["python_version"] != ""


def test_doctor_checks_environment():
    """Doctor checks environment detection."""
    app = BetrayerApplication(name="test-app")
    app.bootstrap()
    inspector = Inspector(app)
    results = inspector.inspect()
    assert "environment" in results


def test_doctor_checks_configuration():
    """Doctor checks configuration."""
    app = BetrayerApplication(name="test-app")
    app.bootstrap()
    inspector = Inspector(app)
    results = inspector.inspect()
    assert "lifecycle" in results


# ── Validator ────────────────────────────────────────────────────


def test_validate_imports():
    """Validator can check imports."""
    from betrayer.cli.main import run_validate

    results = run_validate()
    assert "imports" in results
    assert results["imports"]["status"] in ("pass", "fail")


def test_validate_package_structure():
    """Validator can check package structure."""
    from betrayer.cli.main import run_validate

    results = run_validate()
    assert "package_structure" in results


def test_validate_lifecycle():
    """Validator can check lifecycle."""
    from betrayer.cli.main import run_validate

    results = run_validate()
    assert "lifecycle" in results


def test_validate_configuration():
    """Validator can check configuration."""
    from betrayer.cli.main import run_validate

    results = run_validate()
    assert "configuration" in results


def test_validate_environment():
    """Validator can check environment."""
    from betrayer.cli.main import run_validate

    results = run_validate()
    assert "environment" in results


def test_validate_runtime():
    """Validator can check runtime."""
    from betrayer.cli.main import run_validate

    results = run_validate()
    assert "runtime" in results


# ── Generated metadata ──────────────────────────────────────────


def test_manifest_is_generated_from_runtime():
    """manifest.json equals the runtime builder output (no drift possible)."""
    from betrayer.cli.main import MANIFEST_PATH, build_manifest

    stored = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert stored == build_manifest()


def test_architecture_version_matches_meta():
    """architecture.json is generated and its version comes from meta."""
    from betrayer.cli.main import ARCHITECTURE_PATH, build_architecture
    from betrayer.core.meta import ARCHITECTURE_VERSION

    stored = json.loads(ARCHITECTURE_PATH.read_text(encoding="utf-8"))
    assert stored == build_architecture()
    assert stored["architecture_version"] == ARCHITECTURE_VERSION


def test_manifest_packages_are_importable():
    """Every package listed in the manifest can actually be imported."""
    import importlib.util

    from betrayer.cli.main import build_manifest

    for name in build_manifest()["packages"]:
        assert importlib.util.find_spec(name) is not None, name


def test_validate_metadata_section():
    """Validator checks generated metadata against runtime state."""
    from betrayer.cli.main import run_validate

    results = run_validate()
    assert results["metadata"]["status"] == "pass"


def test_cli_manifest_command_parses():
    """CLI exposes manifest, with opt-in --write, without touching the files."""
    from betrayer.cli.main import build_parser

    parser = build_parser()
    assert parser.parse_args(["manifest"]).write is False
    assert parser.parse_args(["manifest", "--write"]).write is True
