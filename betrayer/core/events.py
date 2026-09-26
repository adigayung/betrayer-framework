"""Deterministic in-process event system.

The event bus is the framework notification mechanism.  It is synchronous
and single threaded on purpose - there is no queue, no broker and no
background worker (those belong to a different task)::

    events.on("user.created", handler)      -> subscription
    events.emit("user.created", payload)    -> synchronous delivery
    events.off("user.created", handler)     -> unsubscription

Rules:
* handlers run in a deterministic order: ``priority`` descending, then
  registration order; ``emit`` therefore always behaves the same way
* every handler receives exactly one :class:`Event` object holding
  ``name``, ``payload``, ``sequence`` and ``bus``
* ``emit`` returns machine readable results ``[(handler_id, ok, error)]``
* a failing handler never disappears silently: the failure is reported in
  that result list and - with ``strict=True`` - re-raised as
  :class:`~betrayer.core.exceptions.EventError`
* event names are dotted lower case (``"user.created"``); an invalid name
  raises :class:`EventError` immediately
"""

from __future__ import annotations

import re
from typing import Any, Callable, Iterator, List, Optional, Tuple

from betrayer.core.exceptions import EventError

__all__ = ["EVENT_NAME_PATTERN", "Event", "EventHandler", "EventBus"]

EVENT_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$")

_EmitResult = Tuple[str, bool, Optional[str]]


def check_event_name(name: Any) -> str:
    """Return ``name`` if it is a valid event name, else raise ``EventError``."""
    if not isinstance(name, str) or not EVENT_NAME_PATTERN.match(name):
        raise EventError(
            message=(
                f"Invalid event name: {name!r} "
                "(expected dotted lower case, e.g. 'user.created')"
            ),
            code="EVENT_NAME_INVALID",
            context={"event": name},
        )
    return name


def _handler_name(handler: Any) -> str:
    """Return a stable, human/LLM readable name for a handler callable."""
    module = getattr(handler, "__module__", "")
    qualname = getattr(handler, "__qualname__", None) or getattr(
        handler, "__name__", type(handler).__name__
    )
    return f"{module}.{qualname}" if module and module != "__main__" else str(qualname)


class Event:
    """One emitted event: what happened, with which payload, in which order."""

    __slots__ = ("name", "payload", "sequence", "bus")

    def __init__(
        self,
        name: str,
        payload: Any = None,
        *,
        sequence: int = 0,
        bus: Any = None,
    ) -> None:
        self.name = name
        self.payload = payload
        self.sequence = sequence
        self.bus = bus

    def to_dict(self) -> dict:
        """Machine readable snapshot of the event."""
        return {
            "name": self.name,
            "payload": self.payload,
            "sequence": self.sequence,
            "bus": getattr(self.bus, "name", None),
        }

    describe = to_dict

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Event name={self.name!r} sequence={self.sequence}>"


class EventHandler:
    """A single subscription: handler, priority, order and owner."""

    __slots__ = ("event", "handler", "priority", "index", "once", "owner")

    def __init__(
        self,
        event: str,
        handler: Callable[[Event], Any],
        *,
        priority: int = 0,
        index: int = 0,
        once: bool = False,
        owner: str = "",
    ) -> None:
        self.event = event
        self.handler = handler
        self.priority = int(priority)
        self.index = int(index)
        self.once = bool(once)
        self.owner = owner

    @property
    def handler_id(self) -> str:
        """Stable id of this subscription inside its bus."""
        return f"{self.event}:{self.index}"

    @property
    def name(self) -> str:
        """Stable name of the handler callable."""
        return _handler_name(self.handler)

    def to_dict(self) -> dict:
        return {
            "id": self.handler_id,
            "event": self.event,
            "handler": self.name,
            "priority": self.priority,
            "order": self.index,
            "once": self.once,
            "owner": self.owner,
        }

    describe = to_dict

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<EventHandler {self.handler_id} handler={self.name}>"


class EventBus:
    """Synchronous, deterministic event bus owned by one application."""

    def __init__(self, name: str = "events") -> None:
        self.name = name
        self._handlers: dict[str, List[EventHandler]] = {}
        self._order = 0
        self._emitted = 0

    # -- registration -------------------------------------------------
    def on(
        self,
        event: str,
        handler: Callable[[Event], Any],
        *,
        priority: int = 0,
        once: bool = False,
        owner: str = "",
    ) -> EventHandler:
        """Subscribe ``handler`` to ``event`` and return the subscription."""
        check_event_name(event)
        if not callable(handler):
            raise EventError(
                message=f"Handler for event {event!r} is not callable: {handler!r}",
                code="EVENT_HANDLER_INVALID",
                context={"event": event},
            )
        self._order += 1
        entry = EventHandler(
            event,
            handler,
            priority=priority,
            index=self._order,
            once=once,
            owner=owner,
        )
        entries = self._handlers.setdefault(event, [])
        entries.append(entry)
        entries.sort(key=lambda item: (-item.priority, item.index))
        return entry

    def add_listener(
        self,
        event: str,
        handler: Callable[[Event], Any],
        *,
        priority: int = 0,
        once: bool = False,
        owner: str = "",
    ) -> EventHandler:
        """Alias of :meth:`on`; ``on`` is the canonical name."""
        return self.on(event, handler, priority=priority, once=once, owner=owner)

    def off(self, event: str, handler: Optional[Callable] = None) -> int:
        """Remove subscriptions.

        With ``handler`` only that callable is removed; without it every
        subscription of the event is removed.  Returns the removed count.
        """
        check_event_name(event)
        entries = self._handlers.get(event)
        if not entries:
            return 0
        if handler is None:
            removed = len(entries)
            self._handlers.pop(event, None)
            return removed
        kept = [entry for entry in entries if entry.handler is not handler]
        removed = len(entries) - len(kept)
        if kept:
            self._handlers[event] = kept
        else:
            self._handlers.pop(event, None)
        return removed

    def off_handler(self, entry: EventHandler) -> bool:
        """Remove one subscription returned by :meth:`on`."""
        if not isinstance(entry, EventHandler):
            raise EventError(
                message=f"off_handler expects an EventHandler, got {entry!r}",
                code="EVENT_HANDLER_INVALID",
                context={"handler": repr(entry)},
            )
        entries = self._handlers.get(entry.event)
        if not entries or entry not in entries:
            return False
        entries.remove(entry)
        if not entries:
            self._handlers.pop(entry.event, None)
        return True

    # -- emission -----------------------------------------------------
    def emit(
        self,
        event: str,
        payload: Any = None,
        *,
        strict: bool = False,
    ) -> List[_EmitResult]:
        """Deliver ``event`` to every handler, in deterministic order.

        Returns ``[(handler_id, ok, error)]``; with ``strict=True`` the first
        failing handler raises :class:`EventError` (handlers that already ran
        stay executed).
        """
        check_event_name(event)
        entries = list(self._handlers.get(event, ()))
        self._emitted += 1
        if not entries:
            return []
        event_object = Event(event, payload, sequence=self._emitted, bus=self)
        results: List[_EmitResult] = []
        for entry in entries:
            if entry.once:
                self._remove(entry)
            try:
                entry.handler(event_object)
            except Exception as exc:  # noqa: BLE001 - reported, not swallowed
                error = f"{type(exc).__name__}: {exc}"
                results.append((entry.handler_id, False, error))
                if strict:
                    raise EventError(
                        message=(
                            f"Handler for event {event!r} failed: {error}"
                        ),
                        code="EVENT_HANDLER_FAILED",
                        stage="emit",
                        cause=exc,
                        context={
                            "event": event,
                            "handler": entry.name,
                            "handler_id": entry.handler_id,
                            "sequence": event_object.sequence,
                        },
                    ) from exc
            else:
                results.append((entry.handler_id, True, None))
        return results

    def _remove(self, entry: EventHandler) -> bool:
        entries = self._handlers.get(entry.event)
        if not entries or entry not in entries:
            return False
        entries.remove(entry)
        if not entries:
            self._handlers.pop(entry.event, None)
        return True

    # -- introspection ------------------------------------------------
    def names(self) -> List[str]:
        """Event names that currently have handlers (registration order)."""
        return list(self._handlers)

    def handlers(self, event: str) -> List[EventHandler]:
        """Subscriptions of ``event`` in delivery order."""
        return list(self._handlers.get(event, ()))

    def count(self, event: str) -> int:
        return len(self._handlers.get(event, ()))

    def has_handlers(self, event: str) -> bool:
        return bool(self._handlers.get(event))

    def total_handlers(self) -> int:
        return sum(len(entries) for entries in self._handlers.values())

    def clear(self, event: Optional[str] = None) -> int:
        """Remove every subscription (or those of ``event``)."""
        if event is None:
            removed = self.total_handlers()
            self._handlers.clear()
            return removed
        check_event_name(event)
        entries = self._handlers.pop(event, [])
        return len(entries)

    def describe(self) -> dict:
        """Machine readable snapshot of the bus (deterministic keys)."""
        return {
            "name": self.name,
            "events": {
                event: [entry.to_dict() for entry in entries]
                for event, entries in self._handlers.items()
            },
            "event_count": len(self._handlers),
            "handler_count": self.total_handlers(),
            "emitted": self._emitted,
        }

    to_dict = describe
    inspect = describe

    # -- dunder -------------------------------------------------------
    def __contains__(self, event: object) -> bool:
        return bool(self._handlers.get(event)) if isinstance(event, str) else False

    def __iter__(self) -> Iterator[str]:
        return iter(self._handlers)

    def __len__(self) -> int:
        return len(self._handlers)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"EventBus(name={self.name!r}, events={len(self._handlers)}, "
            f"handlers={self.total_handlers()})"
        )
