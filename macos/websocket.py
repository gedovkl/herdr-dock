"""WebSocket link to the StreamDock app (websocket-client, on its own thread)."""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Callable
from typing import Any

import websocket

from macos.protocol import register_message

log = logging.getLogger(__name__)


class WebSocketTransport:
    """Runs the socket on a background thread and hands everything to the asyncio loop.

    `on_message` and `on_close` are called on the loop, never on the socket thread.
    """

    def __init__(
        self,
        port: int,
        register_event: str,
        plugin_uuid: str,
        loop: asyncio.AbstractEventLoop,
        *,
        on_message: Callable[[str], None],
        on_close: Callable[[], None],
        app_factory: Callable[..., Any] = websocket.WebSocketApp,
    ) -> None:
        self._url = f"ws://127.0.0.1:{port}"
        self._register = register_message(register_event, plugin_uuid)
        self._loop = loop
        self._on_message = on_message
        self._on_close = on_close
        self._app_factory = app_factory
        self._app: Any = None

    def start(self) -> None:
        app = self._app_factory(
            self._url,
            on_open=lambda ws: ws.send(self._register),
            on_message=lambda _ws, message: self._loop.call_soon_threadsafe(
                self._on_message, message
            ),
            on_error=lambda _ws, error: log.warning("websocket error: %s", error),
            on_close=lambda _ws, _code, _reason: self._loop.call_soon_threadsafe(self._on_close),
        )
        self._app = app
        threading.Thread(target=app.run_forever, name="streamdock-ws", daemon=True).start()

    def send(self, message: str) -> None:
        if self._app is None:
            raise ConnectionError("not connected to the StreamDock app")
        try:
            self._app.send(message)
        except (websocket.WebSocketException, OSError) as exc:
            raise ConnectionError(f"sending to the StreamDock app failed: {exc}") from exc

    def close(self) -> None:
        if self._app is not None:
            self._app.close()
