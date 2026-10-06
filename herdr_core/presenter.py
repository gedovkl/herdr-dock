"""Push key images for a SessionView to a KeySurface, animating where needed."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time

from herdr_core.animation import Animator, Effect
from herdr_core.faces import Face, KeyLayout, faces_for
from herdr_core.models import LabelStyle
from herdr_core.ports import Clock, KeySurface, Sleep
from herdr_core.render import KeyRenderer
from herdr_core.session import SessionView

log = logging.getLogger(__name__)

_Shown = tuple[Face, Effect, int]


class DeckPresenter:
    """Feeds `update()` views to the surface.

    Only keys whose face, effect or frame changed are sent. While anything animates, a single
    ticker advances all frames from one clock, so blinking keys stay in phase.
    """

    def __init__(
        self,
        surface: KeySurface,
        renderer: KeyRenderer,
        animator: Animator,
        *,
        layout: KeyLayout,
        label: LabelStyle = "cwd",
        clock: Clock = time.monotonic,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._surface = surface
        self._renderer = renderer
        self._animator = animator
        self._layout = layout
        self._label = label
        self._clock = clock
        self._sleep = sleep
        self._faces: tuple[Face, ...] = ()
        self._shown: dict[int, _Shown] = {}
        self._dirty = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._failing = False

    @property
    def faces(self) -> tuple[Face, ...]:
        return self._faces

    def update(self, view: SessionView) -> None:
        """Session `on_view` callback."""
        self._faces = faces_for(view, self._label, self._layout)
        self._dirty.set()

    def invalidate(self) -> None:
        """Forget what the surface shows and redraw everything (e.g. after a device replug)."""
        self._shown.clear()
        self._dirty.set()

    async def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name="deck-presenter")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._shown.clear()

    async def push(self) -> bool:
        """Send changed keys for the current time.

        Returns True if another tick is needed: something animates, or a key failed to send
        and must be retried even if nothing else changes.
        """
        now = self._clock()
        effects = [self._animator.effect(face) for face in self._faces]
        animated = any(effect is not Effect.NONE for effect in effects)
        for key, (face, effect) in enumerate(zip(self._faces, effects, strict=True)):
            shown = (face, effect, self._animator.frame(effect, now))
            if self._shown.get(key) == shown:
                continue
            png = self._renderer.render(*shown)
            try:
                await self._surface.show(key, png)
            except Exception as exc:
                # Log once per failure streak; the remaining keys go out on the retry tick.
                if not self._failing:
                    log.warning("showing key %s failed: %s", key, exc)
                    self._failing = True
                return True
            self._failing = False
            self._shown[key] = shown
        return animated

    async def _run(self) -> None:
        while True:
            self._dirty.clear()
            if await self.push():
                await self._wait(self._animator.tick_interval)
            else:
                await self._dirty.wait()

    async def _wait(self, timeout: float) -> None:
        tick = asyncio.ensure_future(self._sleep(timeout))
        woken = asyncio.ensure_future(self._dirty.wait())
        try:
            await asyncio.wait({tick, woken}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in (tick, woken):
                task.cancel()
