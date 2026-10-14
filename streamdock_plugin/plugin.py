"""The herdr plugin for StreamDock-style apps: routes the app's events to the shared core."""

from __future__ import annotations

import asyncio
import logging
from typing import Protocol

from herdr_core.faces import KeyLayout
from streamdock_plugin.grid import Grid
from streamdock_plugin.lifecycle import VisibilityLifecycle
from streamdock_plugin.protocol import (
    Appeared,
    DeviceConnected,
    DeviceDisconnected,
    Disappeared,
    KeyReleased,
    parse_event,
)
from streamdock_plugin.surface import StreamDockSurface

log = logging.getLogger(__name__)


class Redrawable(Protocol):
    def invalidate(self) -> None: ...


class Pressable(Protocol):
    async def press(self, key_index: int) -> None: ...


class HerdrPlugin:
    """Turns app events into surface updates, lifecycle changes and session presses."""

    def __init__(
        self,
        surface: StreamDockSurface,
        lifecycle: VisibilityLifecycle,
        presenter: Redrawable,
        session: Pressable,
        layout: KeyLayout,
        grid: Grid,
        action_uuid: str,
    ) -> None:
        self._surface = surface
        self._lifecycle = lifecycle
        self._presenter = presenter
        self._session = session
        self._layout = layout
        self._grid = grid
        self._action_uuid = action_uuid
        self._sizes: dict[str, tuple[int, int]] = {}
        self._device: str | None = None
        self._tasks: set[asyncio.Task[None]] = set()
        self._warned: set[str] = set()
        self._visible: dict[str, Appeared] = {}
        """Keys on screen. The app won't repeat `willAppear` for them, so a new grid needs this."""

    def handle(self, raw: str) -> None:
        """One message from the app. Never raises."""
        event = parse_event(raw)
        if isinstance(event, DeviceConnected):
            self._sizes[event.device] = (event.columns, event.rows)
        elif isinstance(event, DeviceDisconnected):
            self._sizes.pop(event.device, None)
            if event.device == self._device:
                self._device = None
        elif isinstance(event, Appeared):
            self._appeared(event)
        elif isinstance(event, Disappeared):
            key = self._surface.key_of(event.context)
            if key is not None:
                log.info("key %s disappeared", key + 1)
            self._surface.detach(event.context)
            self._lifecycle.disappeared(event.context)
            self._visible.pop(event.context, None)
        elif isinstance(event, KeyReleased):
            self._released(event)

    def set_grid(self, grid: Grid) -> None:
        """Number the keys with a different grid, including the keys already on screen."""
        self._grid = grid
        for event in list(self._visible.values()):
            self._appeared(event)

    async def close(self) -> None:
        await self._lifecycle.close()
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    def _appeared(self, event: Appeared) -> None:
        self._visible[event.context] = event
        key = self._key(event.action, event.device, event.column, event.row)
        if key is None:
            # A key we don't use (the back key, off the grid): if this context was attached
            # to another key before, it must not keep drawing or keep herdr running.
            self._surface.detach(event.context)
            self._lifecycle.disappeared(event.context)
            return
        log.info("key %s appeared (column %s, row %s)", key + 1, event.column, event.row)
        self._surface.attach(event.context, key)
        self._lifecycle.appeared(event.context)
        self._presenter.invalidate()  # this key has never been drawn

    def _released(self, event: KeyReleased) -> None:
        key = self._key(event.action, event.device, event.column, event.row)
        if key is None:
            return
        log.info("key %s pressed", key + 1)
        task = asyncio.create_task(self._press(self._layout.session_index(key)), name="press")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _press(self, index: int) -> None:
        try:
            await self._session.press(index)
        except Exception:
            log.exception("press on slot %s failed", index)

    def _key(self, action: str, device: str, column: int, row: int) -> int | None:
        """The key index for one of our actions on the dock we drive, else None."""
        if action != self._action_uuid or not self._allowed(device):
            return None
        key = self._grid.key_index(column, row)
        if key is None:
            return None
        if self._layout.is_exit(key):
            self._warn_once("exit", "key 1 is reserved for Exit; the action is ignored there")
            return None
        self._device = device  # only a key we really draw on latches the dock
        return key

    def _allowed(self, device: str) -> bool:
        reason = self._grid.rejects(self._sizes.get(device))
        if reason is not None:
            self._warn_once(device, f"device {device}: {reason}")
            return False
        if self._device is not None and self._device != device:
            self._warn_once(device, f"ignoring a second dock ({device}); one dock at a time")
            return False
        return True

    def _warn_once(self, key: str, message: str) -> None:
        if key not in self._warned:
            self._warned.add(key)
            log.warning("%s", message)
