"""Home page and Herdr mode on the M18."""

from __future__ import annotations

import enum
import logging
from collections.abc import Awaitable, Callable, Sequence
from typing import Protocol

from herdr_core.faces import EmptyFace, Face, KeyLayout, LauncherFace
from herdr_core.ports import KeySurface
from herdr_core.render import KeyRenderer
from linux.config import KEY_COUNT, HomeKey
from linux.device import ButtonPressed, DeviceInput, KeyPressed

log = logging.getLogger(__name__)


class Launcher(Protocol):
    def run(self, command: str) -> None: ...
    def app(self, app: str) -> None: ...


class Focuser(Protocol):
    async def focus_matching(self, pattern: str) -> bool: ...


class Session(Protocol):
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def press(self, key_index: int) -> None: ...
    def next_page(self) -> None: ...


class Presenter(Protocol):
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    def invalidate(self) -> None: ...


class Mode(enum.Enum):
    HOME = "home"
    HERDR = "herdr"


class DockController:
    """Routes presses by mode. HOME shows launcher keys; HERDR shows agents with Exit on key 0."""

    def __init__(
        self,
        surface: KeySurface,
        renderer: KeyRenderer,
        home: Sequence[HomeKey],
        launcher: Launcher,
        session: Session,
        presenter: Presenter,
        *,
        layout: KeyLayout,
        buttons: dict[str, str],
        focuser: Focuser,
        on_enter: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self._surface = surface
        self._renderer = renderer
        self._home = {key.index: key for key in home}
        self._launcher = launcher
        self._session = session
        self._presenter = presenter
        self._layout = layout
        self._buttons = buttons
        self._focuser = focuser
        self._on_enter = on_enter
        self._mode = Mode.HOME
        self._home_shown: dict[int, Face] = {}

    @property
    def mode(self) -> Mode:
        return self._mode

    async def handle(self, event: DeviceInput) -> None:
        if isinstance(event, ButtonPressed):
            await self._button(self._buttons.get(event.name, "none"))
        elif self._mode is Mode.HOME:
            await self._home_press(event)
        elif self._layout.is_exit(event.index):
            await self.exit_herdr()
        else:
            await self._session.press(self._layout.session_index(event.index))

    async def enter_herdr(self) -> None:
        if self._mode is Mode.HERDR:
            return
        self._mode = Mode.HERDR
        self._home_shown.clear()
        self._presenter.invalidate()
        await self._presenter.start()
        await self._session.start()
        if self._on_enter is not None:
            try:
                await self._on_enter()
            except Exception:
                log.warning("bringing the herdr window to the front failed", exc_info=True)

    async def exit_herdr(self) -> None:
        if self._mode is Mode.HOME:
            return
        # Stop drawing first so the session's final "offline" view never reaches the keys.
        await self._presenter.stop()
        await self._session.stop()
        self._mode = Mode.HOME
        await self.draw_home(force=True)

    async def redraw(self) -> None:
        """Repaint everything, e.g. after the device was replugged."""
        if self._mode is Mode.HOME:
            await self.draw_home(force=True)
        else:
            self._presenter.invalidate()

    async def draw_home(self, *, force: bool = False) -> None:
        if force:
            self._home_shown.clear()
        for index in range(KEY_COUNT):
            face = self._home_face(index)
            if self._home_shown.get(index) == face:
                continue
            await self._surface.show(index, self._renderer.render(face))
            self._home_shown[index] = face

    async def shutdown(self) -> None:
        await self.exit_herdr()

    def _home_face(self, index: int) -> Face:
        key = self._home.get(index)
        if key is None:
            return EmptyFace()
        return LauncherFace(key.label, key.symbol, key.icon)

    async def _home_press(self, event: KeyPressed) -> None:
        key = self._home.get(event.index)
        if key is None:
            return
        if key.herdr:
            await self.enter_herdr()
        elif key.focus and await self._focus(key.focus):
            return
        elif key.run:
            self._launcher.run(key.run)
        elif key.app:
            self._launcher.app(key.app)

    async def _focus(self, pattern: str) -> bool:
        """Focus a matching window; any failure means "no window", so the key launches instead."""
        try:
            return await self._focuser.focus_matching(pattern)
        except Exception:
            log.warning("focusing a %r window failed", pattern, exc_info=True)
            return False

    async def _button(self, action: str) -> None:
        if action == "herdr":
            if self._mode is Mode.HOME:
                await self.enter_herdr()
            else:
                await self.exit_herdr()
        elif action == "page" and self._mode is Mode.HERDR:
            self._session.next_page()
