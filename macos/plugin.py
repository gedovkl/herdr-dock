"""The herdr plugin for the StreamDock app: routes the app's events to the shared core."""

from __future__ import annotations

import asyncio
import logging
from typing import Protocol

from herdr_core.faces import KeyLayout
from macos.lifecycle import VisibilityLifecycle
from macos.protocol import (
    Appeared,
    DeviceConnected,
    DeviceDisconnected,
    Disappeared,
    KeyReleased,
    parse_event,
)
from macos.surface import StreamDockSurface

log = logging.getLogger(__name__)

ACTION_UUID = "com.herdr.dock.agent"
"""The one action. Put it on keys 2-15 of a folder; the core decides what each key shows."""
COLUMNS, ROWS = 5, 3
"""The M18's key grid. Other docks aren't supported."""


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
    ) -> None:
        self._surface = surface
        self._lifecycle = lifecycle
        self._presenter = presenter
        self._session = session
        self._layout = layout
        self._sizes: dict[str, tuple[int, int]] = {}
        self._device: str | None = None
        self._tasks: set[asyncio.Task[None]] = set()
        self._warned: set[str] = set()

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
        elif isinstance(event, KeyReleased):
            self._released(event)

    async def close(self) -> None:
        await self._lifecycle.close()
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    def _appeared(self, event: Appeared) -> None:
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
        if action != ACTION_UUID or not self._allowed(device):
            return None
        if not (0 <= column < COLUMNS and 0 <= row < ROWS):
            return None
        # The app numbers the M18's rows from the bottom: its folder back key (top-left) is stored
        # at column 0, row 2. Key indexes count from the top-left like everywhere else here.
        key = (ROWS - 1 - row) * COLUMNS + column
        if self._layout.is_exit(key):
            self._warn_once(
                "back", "key 1 is the app's folder back key; the action is ignored there"
            )
            return None
        self._device = device  # only a key we really draw on latches the dock
        return key

    def _allowed(self, device: str) -> bool:
        size = self._sizes.get(device)
        if size is not None and size != (COLUMNS, ROWS):
            self._warn_once(
                device, f"device {device} is {size[0]}x{size[1]}; only the 5x3 M18 works"
            )
            return False
        if self._device is not None and self._device != device:
            self._warn_once(device, f"ignoring a second dock ({device}); one dock at a time")
            return False
        return True

    def _warn_once(self, key: str, message: str) -> None:
        if key not in self._warned:
            self._warned.add(key)
            log.warning("%s", message)
