from __future__ import annotations

import asyncio

from macos.lifecycle import VisibilityLifecycle

GRACE = 0.3


class Rig:
    def __init__(self, *, fail_start: bool = False) -> None:
        self.calls: list[str] = []
        self.sleeps: asyncio.Queue[float] = asyncio.Queue()
        self.release = asyncio.Event()
        self.fail_start = fail_start
        self.lifecycle = VisibilityLifecycle(self.start, self.stop, grace=GRACE, sleep=self.sleep)

    async def start(self) -> None:
        self.calls.append("start")
        if self.fail_start:
            raise RuntimeError("boom")

    async def stop(self) -> None:
        self.calls.append("stop")

    async def sleep(self, seconds: float) -> None:
        self.sleeps.put_nowait(seconds)
        await self.release.wait()  # the test decides when the grace period ends


async def settle() -> None:
    for _ in range(10):
        await asyncio.sleep(0)


async def test_first_appearance_starts_once() -> None:
    rig = Rig()
    rig.lifecycle.appeared("a")
    rig.lifecycle.appeared("b")
    await settle()
    assert rig.calls == ["start"]
    await rig.lifecycle.close()


async def test_stops_only_after_the_last_context_and_the_grace_delay() -> None:
    rig = Rig()
    rig.lifecycle.appeared("a")
    rig.lifecycle.appeared("b")
    await settle()
    rig.lifecycle.disappeared("a")
    await settle()
    assert rig.calls == ["start"]  # b is still visible
    rig.lifecycle.disappeared("b")
    await settle()
    assert await rig.sleeps.get() == GRACE
    assert rig.calls == ["start"]  # still inside the grace period
    rig.release.set()
    await settle()
    assert rig.calls == ["start", "stop"]
    await rig.lifecycle.close()


async def test_a_page_switch_inside_the_grace_period_keeps_running() -> None:
    """The app sends every willDisappear before the new page's willAppear."""
    rig = Rig()
    rig.lifecycle.appeared("a")
    await settle()
    rig.lifecycle.disappeared("a")
    await settle()
    rig.lifecycle.appeared("b")  # new context on the new page
    await settle()
    rig.release.set()
    await settle()
    assert rig.calls == ["start"]
    await rig.lifecycle.close()


async def test_restarts_after_a_real_stop() -> None:
    rig = Rig()
    rig.lifecycle.appeared("a")
    await settle()
    rig.lifecycle.disappeared("a")
    rig.release.set()
    await settle()
    assert rig.calls == ["start", "stop"]
    rig.lifecycle.appeared("c")
    await settle()
    assert rig.calls == ["start", "stop", "start"]
    await rig.lifecycle.close()


async def test_flicker_restarts_the_grace_period() -> None:
    """Empty only briefly before the second disappearance must not stop immediately."""
    rig = Rig()
    rig.lifecycle.appeared("a")
    await settle()
    rig.lifecycle.disappeared("a")
    await settle()
    rig.lifecycle.appeared("b")
    rig.lifecycle.disappeared("b")
    rig.release.set()
    await settle()
    assert rig.sleeps.qsize() >= 2  # a fresh grace period began for the second emptiness
    await rig.lifecycle.close()


async def test_a_failing_start_is_logged_and_does_not_kill_the_lifecycle() -> None:
    rig = Rig(fail_start=True)
    rig.lifecycle.appeared("a")
    await settle()
    rig.fail_start = False
    rig.lifecycle.disappeared("a")
    rig.lifecycle.appeared("b")
    await settle()
    assert rig.calls.count("start") >= 1
    await rig.lifecycle.close()


async def test_close_stops_a_running_session() -> None:
    rig = Rig()
    rig.lifecycle.appeared("a")
    await settle()
    await rig.lifecycle.close()
    assert rig.calls == ["start", "stop"]


async def test_close_without_ever_starting_does_nothing() -> None:
    rig = Rig()
    await rig.lifecycle.close()
    assert rig.calls == []


async def test_events_after_close_do_nothing() -> None:
    rig = Rig()
    rig.lifecycle.appeared("a")
    await settle()
    await rig.lifecycle.close()
    rig.lifecycle.appeared("late")
    rig.lifecycle.disappeared("late")
    await settle()
    assert rig.calls == ["start", "stop"]
    assert rig.lifecycle._task is None
