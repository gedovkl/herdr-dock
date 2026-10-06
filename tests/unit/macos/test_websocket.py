from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any

import pytest
import websocket

from macos.websocket import WebSocketTransport


class FakeApp:
    """Stands in for websocket.WebSocketApp: replays a scripted session on `run_forever`."""

    def __init__(self, url: str, **callbacks: Callable[..., None]) -> None:
        self.url = url
        self.callbacks = callbacks
        self.sent: list[str] = []
        self.script: list[str] = []
        self.closed = False
        self.send_error: Exception | None = None

    def run_forever(self) -> None:
        self.callbacks["on_open"](self)
        for message in self.script:
            self.callbacks["on_message"](self, message)
        self.callbacks["on_close"](self, 1000, "bye")

    def send(self, message: str) -> None:
        if self.send_error is not None:
            raise self.send_error
        self.sent.append(message)

    def close(self) -> None:
        self.closed = True


class Rig:
    def __init__(self, script: list[str]) -> None:
        self.messages: list[str] = []
        self.closed = asyncio.Event()
        self.apps: list[FakeApp] = []
        self.script = script

    def factory(self, url: str, **callbacks: Callable[..., None]) -> Any:
        app = FakeApp(url, **callbacks)
        app.script = self.script
        self.apps.append(app)
        return app

    def transport(self) -> WebSocketTransport:
        return WebSocketTransport(
            18618,
            "registerPlugin",
            "UUID1",
            asyncio.get_running_loop(),
            on_message=self.messages.append,
            on_close=self.closed.set,
            app_factory=self.factory,
        )


async def test_registers_then_delivers_messages_on_the_loop_and_reports_close() -> None:
    rig = Rig(["m1", "m2"])
    transport = rig.transport()
    transport.start()
    await asyncio.wait_for(rig.closed.wait(), 2)
    app = rig.apps[0]
    assert app.url == "ws://127.0.0.1:18618"
    assert [json.loads(m) for m in app.sent] == [{"event": "registerPlugin", "uuid": "UUID1"}]
    assert rig.messages == ["m1", "m2"]


async def test_send_before_start_is_a_connection_error() -> None:
    transport = Rig([]).transport()
    with pytest.raises(ConnectionError):
        transport.send("hi")


async def test_send_passes_messages_through() -> None:
    rig = Rig([])
    transport = rig.transport()
    transport.start()
    await asyncio.wait_for(rig.closed.wait(), 2)
    transport.send("hello")
    assert rig.apps[0].sent[-1] == "hello"


async def test_send_failures_become_connection_errors() -> None:
    rig = Rig([])
    transport = rig.transport()
    transport.start()
    await asyncio.wait_for(rig.closed.wait(), 2)
    rig.apps[0].send_error = websocket.WebSocketConnectionClosedException("gone")
    with pytest.raises(ConnectionError):
        transport.send("hello")
    rig.apps[0].send_error = BrokenPipeError("pipe")
    with pytest.raises(ConnectionError):
        transport.send("hello")


async def test_close_closes_the_socket() -> None:
    rig = Rig([])
    transport = rig.transport()
    transport.start()
    await asyncio.wait_for(rig.closed.wait(), 2)
    transport.close()
    assert rig.apps[0].closed
