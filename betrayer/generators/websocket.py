"""WebSocket / realtime feature generator for the Betrayer Framework.

Creates a complete realtime feature package that integrates the existing
Betrayer realtime layer (:class:`betrayer.web.realtime_manager.RealtimeManager`,
:class:`~betrayer.web.channel.Channel`, :class:`~betrayer.web.message.Message`)
with the event bus and a business service.  No second realtime/event system is
introduced -- it reuses what the framework already provides.

A generated websocket feature contains::

    __init__.py       public API
    channels.py       channel name constants + event routing definitions
    service.py        a thin service that broadcasts through the manager
    module.py         Module that wires events -> realtime (handle_event)
    tests/...         unit + integration placeholders

The module registers a ``<name>_realtime`` manager on the container and, when
the application exposes an event bus, subscribes ``handle_event`` so business
events fan out to their channel (`Service -> Event -> Realtime -> Channel`).

Example usage::

    bet make websocket chat
    bet make websocket notifications --event notifications.created
    bet make websocket presence --json
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Tuple

from betrayer.generators.base import (
    BaseGenerator,
    GeneratorError,
    GeneratorOutput,
    package_name,
    title_case,
    validate_project_name,
)

__all__ = ["WebsocketGenerator", "validate_websocket_name", "WEBSOCKET_VERSION"]

#: Initial version assigned to a freshly generated websocket feature.
WEBSOCKET_VERSION = "0.1.0"


def validate_websocket_name(name: str) -> str | None:
    """Return a human readable error message, or ``None`` when ``name`` is OK.

    Websocket feature names follow the same convention as project names
    (letters, digits, ``-`` and ``_``; must start with a letter) so the CLI
    surface stays consistent.  The message is phrased in terms of a *websocket
    feature* though.
    """
    error = validate_project_name(name)
    if error:
        return error.replace("project name", "websocket name")
    return None


class WebsocketGenerator(BaseGenerator):
    """Generate a new realtime (WebSocket) feature package.

    ``name`` is the name chosen on the command line; the importable package is
    the ``snake_case`` form of ``name`` (so ``bet make websocket chat-rooms``
    produces ``chat_rooms/``).  Generated names follow the existing
    convention::

        <TitleCase>RealtimeService   the service that broadcasts messages
        <TitleCase>RealtimeModule    the module wiring events -> realtime

    The channel name follows ``/<snake_case>`` (``chat`` -> ``/chat``).
    """

    name = "websocket"
    description = "Create a realtime (WebSocket) feature (channel + service + event wiring) in the current project"

    def __init__(
        self,
        name: str,
        output_dir: Path,
        overwrite: bool = False,
        *,
        events: Tuple[str, ...] | None = None,
    ) -> None:
        error = validate_websocket_name(name)
        if error:
            raise GeneratorError(f"invalid websocket name: {error}")
        self.requested_name = name
        self.package = package_name(name)
        # Events that should be routed to this channel.  When none are supplied
        # a single conventional event ``<package>.created`` is used.
        if events:
            self.events = tuple(e for e in events if e)
        else:
            self.events = (f"{self.package}.created",)
        super().__init__(output_dir=Path(output_dir) / self.package, overwrite=overwrite)

    @property
    def target(self) -> Path:
        """The directory the new websocket package is created in."""
        return self.output_dir

    @property
    def feature_name(self) -> str:
        """The feature's package name (snake_case)."""
        return self.package

    @property
    def channel_name(self) -> str:
        """The realtime channel name (``/chat`` -> ``/chat``)."""
        return f"/{self.package}"

    @property
    def service_class_name(self) -> str:
        """Name of the generated realtime service class."""
        return f"{title_case(self.package)}RealtimeService"

    @property
    def service_key(self) -> str:
        """The container service name for the realtime service."""
        return f"{self.package}_realtime"

    @property
    def module_class_name(self) -> str:
        """Name of the generated :class:`~betrayer.core.module.Module` subclass."""
        return f"{title_case(self.package)}RealtimeModule"

    # ── structure ──────────────────────────────────────────────────────

    def _files(self) -> Dict[str, str]:
        """Deterministic mapping of relative path -> file content."""
        return {
            "__init__.py": self._init_py(),
            "channels.py": self._channels_py(),
            "service.py": self._service_py(),
            "module.py": self._module_py(),
            "tests/__init__.py": '"""Tests for this realtime feature package."""\n',
            f"tests/test_{self.package}_unit.py": self._tests_unit_py(),
        }

    def _init_py(self) -> str:
        return f'''"""The ``{self.feature_name}`` realtime (WebSocket) feature package.

Generated by ``bet make websocket {self.requested_name}``.

Public API::

    CHANNEL               the channel name (``{self.channel_name}``)
    EVENT_ROUTES          event name -> channel mapping
    {self.service_class_name}    the service that broadcasts messages
    {self.module_class_name}     the module wiring events -> realtime

Register it on an application::

    from {self.feature_name} import {self.module_class_name}

    app.modules.register({self.module_class_name})
"""

from __future__ import annotations

from {self.feature_name}.channels import CHANNEL, EVENT_ROUTES
from {self.feature_name}.service import {self.service_class_name}
from {self.feature_name}.module import {self.module_class_name}

__all__ = [
    "CHANNEL",
    "EVENT_ROUTES",
    "{self.service_class_name}",
    "{self.module_class_name}",
]
'''

    def _channels_py(self) -> str:
        event_lines = "\n".join(
            f'    "{event}": CHANNEL,' for event in self.events
        )
        events_repr = ",\n".join(f'    "{event}"' for event in self.events)
        return f'''"""Channel and event routing for the ``{self.feature_name}`` realtime feature.

Generated by ``bet make websocket {self.requested_name}``.

A channel is a named realtime room owned by the framework's
:class:`~betrayer.web.realtime_manager.RealtimeManager`.  Business events are
routed to a channel by (event name -> channel name); the ``RealtimeManager``
does the broadcasting, this module only declares the mapping.
"""

from __future__ import annotations

from typing import Dict, Tuple

__all__ = ["CHANNEL", "EVENT_ROUTES", "EVENTS"]

#: The realtime channel this feature owns.
CHANNEL = "{self.channel_name}"

#: Business events that should fan out to :data:`CHANNEL`.
EVENTS: Tuple[str, ...] = (
{events_repr},
)

#: Event name -> channel name mapping consumed by the module.
EVENT_ROUTES: Dict[str, str] = {{
{event_lines}
}}
'''

    def _service_py(self) -> str:
        return f'''"""Realtime service for the ``{self.feature_name}`` feature.

Generated by ``bet make websocket {self.requested_name}``.

The service is a thin, business-agnostic bridge over the framework's
:class:`~betrayer.web.realtime_manager.RealtimeManager`: it publishes messages
to the feature's channel.  It never reimplements broadcast logic -- the
manager and :class:`~betrayer.web.channel.Channel` own that.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from betrayer.web.realtime_manager import RealtimeManager

from {self.feature_name}.channels import CHANNEL

__all__ = ["{self.service_class_name}"]


class {self.service_class_name}:
    """Publishes realtime messages to the ``{self.channel_name}`` channel."""

    name = "{self.service_key}"
    channel_name = CHANNEL

    def __init__(self, manager: RealtimeManager) -> None:
        self._manager = manager

    @property
    def manager(self) -> RealtimeManager:
        """The underlying realtime manager."""
        return self._manager

    def broadcast(self, event: str, data: Optional[Dict[str, Any]] = None) -> int:
        """Broadcast ``event`` to every connection on the channel.

        Returns the number of connections that received the message.
        """
        channel = self._manager.channel(self.channel_name)
        return channel.broadcast({{"event": event, "data": data or {{}}}})

    def connect(self, connection_id: Optional[str] = None, **metadata: Any):
        """Open a connection on the channel and return it."""
        return self._manager.connect(
            self.channel_name, connection_id, metadata=metadata or None
        )

    def connection_count(self) -> int:
        """Number of live connections on the channel."""
        return self._manager.channel(self.channel_name).connection_count()

    def introspect(self) -> Dict[str, Any]:
        """Machine readable metadata."""
        return {{
            "type": "realtime_service",
            "name": self.name,
            "class": type(self).__name__,
            "channel": self.channel_name,
        }}
'''

    def _module_py(self) -> str:
        return f'''"""Realtime module for ``{self.feature_name}``.

Generated by ``bet make websocket {self.requested_name}``.

The module registers a :class:`~betrayer.web.realtime_manager.RealtimeManager`
on the container (key ``realtime_manager``) and a service
(:class:`{self.service_class_name}`) under ``{self.service_key}``.  When the
application exposes an event bus, it subscribes :meth:`handle_event` so that
business events described in :data:`{self.feature_name}.channels.EVENT_ROUTES`
fan out to their channel -- reusing the framework EventBus, never a second one.
"""

from __future__ import annotations

from typing import Any, Tuple

from betrayer.core.module import Module
from betrayer.web.realtime_manager import RealtimeManager

from {self.feature_name}.channels import EVENT_ROUTES
from {self.feature_name}.service import {self.service_class_name}

__all__ = ["{self.module_class_name}"]


class {self.module_class_name}(Module):
    """Betrayer module wiring the ``{self.feature_name}`` realtime feature."""

    name = "{self.package}_realtime"
    version = "{WEBSOCKET_VERSION}"
    dependencies: Tuple[str, ...] = ()
    services: Tuple[str, ...] = ("realtime_manager", "{self.service_key}")
    metadata = {{
        "description": "the {self.feature_name} realtime (websocket) feature",
        "channel": "{self.channel_name}",
        "events": {list(self.events)!r},
    }}

    def register(self, context: Any) -> None:
        """Register the realtime manager and service on the container."""
        container = context.container
        application = getattr(context, "application", None)

        # A single, shared RealtimeManager per application.  It is registered
        # once: if the application already provided one (e.g. realtime feature
        # modules coexist), reuse it instead of building a duplicate.
        if not container.has("realtime_manager"):
            manager = RealtimeManager(application=application)
            container.instance("realtime_manager", manager)

        def _build_service() -> {self.service_class_name}:
            manager = container.resolve("realtime_manager")
            return {self.service_class_name}(manager=manager)

        container.singleton("{self.service_key}", _build_service)

    def initialize(self, context: Any) -> None:
        """Subscribe to the event bus so business events reach the channel."""
        application = getattr(context, "application", None)
        events = getattr(application, "events", None)
        if events is None:
            return
        try:
            events.on("*", self.handle_event)
        except Exception:  # noqa: BLE001 - event bus without wildcard support
            for event_name in EVENT_ROUTES:
                events.on(event_name, self.handle_event)

    def handle_event(self, event: Any) -> None:
        """Route a business event to the feature channel via the manager."""
        name = getattr(event, "name", None) or (
            event.get("event") if isinstance(event, dict) else None
        )
        if name not in EVENT_ROUTES:
            return
        payload = getattr(event, "payload", None)
        if payload is None and isinstance(event, dict):
            payload = event.get("payload") or event.get("data")
        container = getattr(getattr(self, "_context", None), "container", None)
        if container is None:
            return
        service = container.resolve("{self.service_key}")
        service.broadcast(name, payload or {{}})

    def shutdown(self, context: Any) -> None:
        """Unsubscribe from the event bus."""
        application = getattr(context, "application", None)
        events = getattr(application, "events", None)
        if events is None:
            return
        try:
            events.off("*", self.handle_event)
        except Exception:  # noqa: BLE001 - best effort
            for event_name in EVENT_ROUTES:
                try:
                    events.off(event_name, self.handle_event)
                except Exception:  # noqa: BLE001
                    pass
'''

    def _tests_unit_py(self) -> str:
        return f'''"""Unit tests for the ``{self.feature_name}`` realtime feature.

Generated by ``bet make websocket {self.requested_name}``.
"""

from {self.feature_name}.channels import CHANNEL, EVENT_ROUTES


class Test{title_case(self.package)}RealtimeUnit:
    """Unit tests for {self.feature_name} realtime components."""

    def test_channel_defined(self) -> None:
        assert CHANNEL == "{self.channel_name}"

    def test_events_route_to_channel(self) -> None:
        assert EVENT_ROUTES
        assert all(channel == CHANNEL for channel in EVENT_ROUTES.values())
'''

    # ── generation ──────────────────────────────────────────────────────

    def generate(self) -> GeneratorOutput:
        """Create the realtime feature package and every generated file.

        Raises :class:`GeneratorError` when the target already exists and is
        not empty and ``overwrite`` is False, so an existing feature is never
        overwritten silently.
        """
        if not self.overwrite and self._target_occupied():
            raise GeneratorError(
                "websocket feature already exists (use --force to overwrite): "
                f"{self.output_dir}"
            )
        self._ensure_directory(self.output_dir)
        for relative, content in self._files().items():
            try:
                self._write(relative, content)
            except GeneratorError as exc:  # pragma: no cover - defensive
                self.output.add_error(relative, exc)
        return self.output

    def _target_occupied(self) -> bool:
        """True when the target directory exists and is not empty."""
        if not self.output_dir.exists():
            return False
        try:
            return any(self.output_dir.iterdir())
        except OSError:
            return True
