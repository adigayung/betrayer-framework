"""Minimal example application built on the Betrayer foundation.

It shows the whole foundation lifecycle end to end and is a good first
place to look when learning the framework::

    BOOTSTRAP
    INITIALIZE
    READY
    RUNNING
    STOPPING
    STOPPED

Run it with ``python example/run.py``.
"""

from __future__ import annotations

from typing import Optional, Sequence

from betrayer import BetrayerApplication, Bootstrap, Config

EXAMPLE_CONFIG = {
    "app.name": "betrayer-example",
    "app.debug": True,
    "example.greeting": "hello from the example application",
    "example.api_key": "not-a-real-secret",
}


def register_lifecycle_logging(app: BetrayerApplication) -> None:
    """Attach print handlers so the lifecycle is observable."""
    lifecycle = app.lifecycle
    lifecycle.on_bootstrap(lambda state, application: print("BOOTSTRAP"))
    lifecycle.on_initialize(lambda state, application: print("INITIALIZE"))
    lifecycle.on_ready(lambda state, application: print("READY"))
    lifecycle.on_start(lambda state, application: print("RUNNING"))
    lifecycle.on_stop(lambda state, application: print("STOPPING"))
    lifecycle.on_shutdown(lambda state, application: print("STOPPED"))
    lifecycle.on_error(lambda state, application: print("FAILED"))


def build_application() -> BetrayerApplication:
    """Create the example application without running it."""
    app = BetrayerApplication(name="betrayer-example", config=Config(defaults=EXAMPLE_CONFIG))
    register_lifecycle_logging(app)
    return app


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Bootstrap, run and shut down the example application."""
    app = build_application()

    Bootstrap(app).build()  # BOOTSTRAP -> INITIALIZE -> READY
    app.start()             # READY -> RUNNING

    print(f"greeting: {app.config.get('example.greeting')}")
    print(f"state: {app.state.value}")

    app.stop()              # RUNNING -> STOPPING
    app.shutdown()          # STOPPING -> STOPPED

    print(f"final state: {app.state.value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
