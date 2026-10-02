"""Focused tests for the Websocket Generator (realtime vertical slice).

Covers: websocket feature creation, the generated structure, channel/event
constants, the generated service & module classes, invalid name rejection,
overwrite protection and the ``bet make websocket`` CLI wiring.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Type

import pytest

from betrayer.cli.main import COMMANDS, build_parser, main
from betrayer.core.container import Container
from betrayer.core.module import Module
from betrayer.generators.base import GeneratorError
from betrayer.generators.websocket import (
    WEBSOCKET_VERSION,
    WebsocketGenerator,
    validate_websocket_name,
)

EXPECTED_WS_FILES = (
    "__init__.py",
    "channels.py",
    "service.py",
    "module.py",
    "tests/__init__.py",
    "tests/test_chat_unit.py",
)


def _generate(tmp_path: Path, name: str = "chat", overwrite: bool = False, **kwargs) -> WebsocketGenerator:
    return WebsocketGenerator(name=name, output_dir=tmp_path, overwrite=overwrite, **kwargs)


def _load_class(generator: WebsocketGenerator, attribute: str):
    package = generator.feature_name
    parent = str(generator.target.parent)

    def _purge() -> None:
        for mod in list(sys.modules):
            if mod == package or mod.startswith(package + "."):
                sys.modules.pop(mod, None)

    _purge()
    sys.path.insert(0, parent)
    try:
        module = __import__(package, fromlist=[attribute])
        return getattr(module, attribute)
    finally:
        sys.path.remove(parent)
        _purge()


# ── structure ───────────────────────────────────────────────────


def test_websocket_created_files(tmp_path: Path) -> None:
    generator = _generate(tmp_path)
    output = generator.generate()
    assert output.success, output.errors
    assert generator.target == tmp_path / "chat"
    for relative in EXPECTED_WS_FILES:
        assert (generator.target / relative).is_file(), f"missing {relative}"


def test_websocket_channel_and_events(tmp_path: Path) -> None:
    generator = _generate(tmp_path)
    assert generator.channel_name == "/chat"
    assert generator.events == ("chat.created",)
    generator.generate()
    channels = _load_class(generator, "CHANNEL")
    event_routes = _load_class(generator, "EVENT_ROUTES")
    assert channels == "/chat"
    assert event_routes == {"chat.created": "/chat"}


def test_websocket_custom_events(tmp_path: Path) -> None:
    generator = _generate(tmp_path, events=("messages.sent", "presence.updated"))
    assert generator.events == ("messages.sent", "presence.updated")
    generator.generate()
    event_routes = _load_class(generator, "EVENT_ROUTES")
    assert event_routes == {"messages.sent": "/chat", "presence.updated": "/chat"}


def test_generated_module_subclasses_module(tmp_path: Path) -> None:
    generator = _generate(tmp_path)
    generator.generate()
    module_class = _load_class(generator, generator.module_class_name)
    assert issubclass(module_class, Module)
    assert module_class.__name__ == "ChatRealtimeModule"
    assert module_class.module_name() == "chat_realtime"
    assert module_class.version == WEBSOCKET_VERSION
    assert module_class.services == ("realtime_manager", "chat_realtime")


def test_generated_module_registers_manager_and_service(tmp_path: Path) -> None:
    generator = _generate(tmp_path)
    generator.generate()
    module_class = _load_class(generator, generator.module_class_name)

    container = Container(name="demo")
    module_class().register(SimpleNamespace(container=container, application=None))
    assert "realtime_manager" in container
    assert "chat_realtime" in container
    service = container.resolve("chat_realtime")
    assert type(service).__name__ == "ChatRealtimeService"


def test_generated_service_broadcasts_to_channel(tmp_path: Path) -> None:
    generator = _generate(tmp_path)
    generator.generate()
    from betrayer.web.realtime_manager import RealtimeManager

    service_class = _load_class(generator, generator.service_class_name)
    manager = RealtimeManager()
    service = service_class(manager=manager)
    connection = manager.connect("/chat")
    count = service.broadcast("chat.created", {"text": "hi"})
    assert count == 1
    assert service.connection_count() == 1


# ── naming / validation ─────────────────────────────────────────


def test_hyphenated_name_creates_snake_case_package(tmp_path: Path) -> None:
    generator = WebsocketGenerator(name="message-room", output_dir=tmp_path)
    assert generator.feature_name == "message_room"
    assert generator.channel_name == "/message_room"
    assert generator.events == ("message_room.created",)
    generator.generate()
    assert (tmp_path / "message_room" / "channels.py").is_file()


@pytest.mark.parametrize(
    "name", ["", " ", "9start", "a b", "a.b", "a/b", "../x", "-lead", "a:b"]
)
def test_invalid_websocket_names_rejected(name: str) -> None:
    assert validate_websocket_name(name) is not None
    with pytest.raises(GeneratorError):
        WebsocketGenerator(name=name, output_dir=Path("."))


# ── overwrite protection ─────────────────────────────────────────


def test_existing_websocket_not_overwritten(tmp_path: Path) -> None:
    _generate(tmp_path).generate()
    with pytest.raises(GeneratorError):
        _generate(tmp_path).generate()


def test_existing_websocket_overwritten_with_force(tmp_path: Path) -> None:
    _generate(tmp_path).generate()
    output = _generate(tmp_path, overwrite=True).generate()
    assert output.success, output.errors


def test_generation_is_deterministic(tmp_path: Path) -> None:
    _generate(tmp_path).generate()
    first = {
        p.relative_to(tmp_path).as_posix(): p.read_text(encoding="utf-8")
        for p in (tmp_path / "chat").rglob("*.py")
    }
    _generate(tmp_path, overwrite=True).generate()
    second = {
        p.relative_to(tmp_path).as_posix(): p.read_text(encoding="utf-8")
        for p in (tmp_path / "chat").rglob("*.py")
    }
    assert first == second


# ── CLI wiring ──────────────────────────────────────────────────


def test_cli_make_command_registered() -> None:
    assert "make" in COMMANDS


def test_cli_make_websocket_parses() -> None:
    parser = build_parser()
    args = parser.parse_args(["make", "websocket", "chat"])
    assert args.command == "make"
    assert args.make_target == "websocket"
    assert args.websocket_name == "chat"
    assert args.force is False
    assert args.events == []


def test_cli_make_websocket_custom_events() -> None:
    parser = build_parser()
    args = parser.parse_args(
        ["make", "websocket", "chat", "--events", "msg.sent", "user.online"]
    )
    assert args.events == ["msg.sent", "user.online"]


def test_cli_make_websocket_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["make", "websocket", "chat"]) == 0
    assert (tmp_path / "chat" / "channels.py").is_file()
    assert (tmp_path / "chat" / "service.py").is_file()
    assert (tmp_path / "chat" / "module.py").is_file()


def test_cli_make_websocket_existing_returns_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["make", "websocket", "chat"]) == 0
    assert main(["make", "websocket", "chat"]) == 1


def test_cli_make_websocket_force_overwrites(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["make", "websocket", "chat"]) == 0
    assert main(["make", "websocket", "chat", "--force"]) == 0


def test_cli_make_websocket_invalid_name_returns_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["make", "websocket", "9bad"]) == 1


def test_cli_make_websocket_json_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["make", "websocket", "chat", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["websocket"] == "chat"
    assert payload["channel"] == "/chat"
    assert payload["events"] == ["chat.created"]
    assert payload["service_class"] == "ChatRealtimeService"
    assert payload["module_class"] == "ChatRealtimeModule"
    assert payload["created"]
