"""Foundation smoke test: run the framework from a cold start.

It can be executed directly (``python tests/smoke_test.py``) and is also
collected by pytest through :func:`test_foundation_smoke`.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from betrayer import BetrayerApplication, Bootstrap, LifecycleState  # noqa: E402
from betrayer.diagnostics.inspector import Inspector  # noqa: E402

EXPECTED_EVENTS = ["bootstrap", "initialize", "ready", "start", "stop", "shutdown"]


def _run_smoke() -> dict:
    """Drive a fresh application through the complete lifecycle."""
    app = BetrayerApplication(name="smoke")
    events: list[str] = []

    lifecycle = app.lifecycle
    lifecycle.register_handler(LifecycleState.BOOTSTRAPPING, lambda state, a: events.append("bootstrap"))
    lifecycle.register_handler(LifecycleState.READY, lambda state, a: events.append("initialize"))
    lifecycle.register_handler(LifecycleState.READY, lambda state, a: events.append("ready"))
    lifecycle.register_handler(LifecycleState.RUNNING, lambda state, a: events.append("start"))
    lifecycle.register_handler(LifecycleState.STOPPING, lambda state, a: events.append("stop"))
    lifecycle.register_handler(LifecycleState.STOPPED, lambda state, a: events.append("shutdown"))

    Bootstrap(app).build()
    assert app.state is LifecycleState.READY, app.state

    app.start()
    assert app.state is LifecycleState.RUNNING, app.state

    app.stop()
    assert app.state is LifecycleState.STOPPING, app.state

    app.shutdown()
    assert app.state is LifecycleState.STOPPED, app.state

    info = Inspector(app).info()
    assert info["framework"] == "Betrayer"
    assert info["state"] == "stopped"

    return {"events": events, "state": app.state.value}


def test_foundation_smoke() -> None:
    """The whole foundation lifecycle works from a cold start."""
    result = _run_smoke()
    assert result["events"] == EXPECTED_EVENTS
    assert result["state"] == "stopped"


def main() -> int:
    result = _run_smoke()
    print(f"events: {' -> '.join(result['events'])}")
    print(f"final state: {result['state']}")
    print("SMOKE: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
