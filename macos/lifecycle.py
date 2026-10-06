"""Start herdr while any of our keys is visible, stop after they've all gone."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable

from herdr_core.ports import Sleep

log = logging.getLogger(__name__)


class VisibilityLifecycle:
    """Counts visible key contexts and runs `start`/`stop` as that count leaves and returns to 0.

    Opening a folder or switching pages sends every `willDisappear` before the new page's
    `willAppear`, so the count briefly hits 0. `stop` therefore waits `grace` seconds, and the
    wait begins again whenever the visible set changes. One task does all the starting and
    stopping, so `start` and `stop` never overlap.
    """

    def __init__(
        self,
        start: Callable[[], Awaitable[None]],
        stop: Callable[[], Awaitable[None]],
        *,
        grace: float = 0.3,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._start = start
        self._stop = stop
        self._grace = grace
        self._sleep = sleep
        self._visible: set[str] = set()
        self._running = False
        self._generation = 0
        self._changed = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    def appeared(self, context: str) -> None:
        self._visible.add(context)
        self._notify()

    def disappeared(self, context: str) -> None:
        self._visible.discard(context)
        self._notify()

    async def close(self) -> None:
        """Stop the worker, and herdr too if it is running."""
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        if self._running:
            await self._call(self._stop, "stopping")

    def _notify(self) -> None:
        self._generation += 1
        self._changed.set()
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name="herdr-visibility")

    async def _run(self) -> None:
        while True:
            await self._changed.wait()
            self._changed.clear()
            if self._visible and not self._running:
                self._running = True
                log.info("a herdr key is visible: starting")
                await self._call(self._start, "starting")
            elif not self._visible and self._running:
                generation = self._generation
                await self._sleep(self._grace)
                if self._visible or generation != self._generation:
                    continue  # came back, or changed again: re-evaluate with a fresh wait
                self._running = False
                log.info("no herdr key is visible: stopping")
                await self._call(self._stop, "stopping")

    async def _call(self, action: Callable[[], Awaitable[None]], what: str) -> None:
        try:
            await action()
        except Exception:
            log.exception("%s herdr failed", what)
