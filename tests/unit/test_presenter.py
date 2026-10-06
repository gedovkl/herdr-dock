from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest

from herdr_core.animation import Animator, Effect
from herdr_core.faces import AgentFace, ExitFace, KeyLayout
from herdr_core.models import Agent, AgentStatus
from herdr_core.paging import paginate
from herdr_core.presenter import DeckPresenter
from herdr_core.render import KeyRenderer
from herdr_core.session import SessionView
from tests.fakes.surface import FakeClock, FakeSurface

S = AgentStatus
RENDERER = KeyRenderer()


def agent(n: int, status: AgentStatus) -> Agent:
    return Agent(f"w{n}:p1", f"w{n}", f"w{n}:t1", "claude", status, cwd=f"/p/a{n}")


def view(*statuses: AgentStatus, capacity: int = 3) -> SessionView:
    slots = [agent(n, s) for n, s in enumerate(statuses, start=1)]
    return SessionView(True, paginate(slots, capacity, 0), len(slots), frozenset(statuses))


@dataclass
class Rig:
    surface: FakeSurface
    clock: FakeClock
    presenter: DeckPresenter
    ticks: asyncio.Queue[float]


@pytest.fixture
async def rig() -> AsyncIterator[Rig]:
    surface, clock = FakeSurface(), FakeClock()
    ticks: asyncio.Queue[float] = asyncio.Queue()

    async def sleep(seconds: float) -> None:
        ticks.put_nowait(seconds)
        await asyncio.Event().wait()  # never fires; tests advance via presenter.push()

    presenter = DeckPresenter(
        surface, RENDERER, Animator(), layout=KeyLayout(), clock=clock, sleep=sleep
    )
    yield Rig(surface, clock, presenter, ticks)
    await presenter.stop()


async def test_push_sends_every_key_once(rig: Rig) -> None:
    rig.presenter.update(view(S.IDLE))
    assert not await rig.presenter.push()
    assert sorted(rig.surface.calls) == [0, 1, 2, 3]
    assert rig.surface.shown[1] == RENDERER.render(AgentFace("claude", "a1", S.IDLE))
    assert rig.presenter.faces[0] == ExitFace((S.IDLE,))
    rig.surface.calls.clear()
    await rig.presenter.push()
    assert rig.surface.calls == []


async def test_only_changed_keys_are_resent(rig: Rig) -> None:
    rig.presenter.update(view(S.IDLE, S.IDLE))
    await rig.presenter.push()
    rig.surface.calls.clear()
    rig.presenter.update(view(S.IDLE, S.DONE))
    await rig.presenter.push()
    assert sorted(rig.surface.calls) == [0, 2]  # exit summary + the changed agent


async def test_animation_advances_with_the_clock(rig: Rig) -> None:
    rig.presenter.update(view(S.BLOCKED, S.WORKING))
    assert await rig.presenter.push()
    blocked = AgentFace("claude", "a1", S.BLOCKED)
    assert rig.surface.shown[1] == RENDERER.render(blocked, Effect.BLINK, 0)
    rig.surface.calls.clear()
    rig.clock.now = 0.25
    await rig.presenter.push()
    assert sorted(rig.surface.calls) == [0, 1, 2]  # exit blinks with the blocked agent
    assert rig.surface.shown[1] == RENDERER.render(blocked, Effect.BLINK, 1)
    assert rig.surface.shown[2] == RENDERER.render(
        AgentFace("claude", "a2", S.WORKING), Effect.SPIN, 1
    )


async def test_invalidate_redraws_everything(rig: Rig) -> None:
    rig.presenter.update(view(S.IDLE))
    await rig.presenter.push()
    rig.surface.calls.clear()
    rig.presenter.invalidate()
    await rig.presenter.push()
    assert sorted(rig.surface.calls) == [0, 1, 2, 3]


async def test_failed_keys_are_retried(rig: Rig, caplog: pytest.LogCaptureFixture) -> None:
    rig.surface.fail_keys.add(1)
    rig.presenter.update(view(S.IDLE))
    await rig.presenter.push()
    assert "showing key 1 failed" in caplog.text
    rig.surface.fail_keys.clear()
    rig.surface.calls.clear()
    await rig.presenter.push()
    assert rig.surface.calls == [1]


async def _until(predicate: object) -> None:
    async def poll() -> None:
        while not predicate():  # type: ignore[operator]
            await asyncio.sleep(0)

    await asyncio.wait_for(poll(), 1.0)


async def test_run_loop_waits_for_updates_when_static(rig: Rig) -> None:
    await rig.presenter.start()
    await rig.presenter.start()  # idempotent
    rig.presenter.update(view(S.IDLE))
    await _until(lambda: len(rig.surface.shown) == 4)
    assert rig.ticks.empty()  # nothing animated: no ticker
    rig.presenter.update(view(S.DONE))
    await _until(lambda: rig.surface.shown[1] == RENDERER.render(AgentFace("claude", "a1", S.DONE)))


async def test_run_loop_ticks_while_animated(rig: Rig) -> None:
    await rig.presenter.start()
    rig.presenter.update(view(S.WORKING))
    assert await asyncio.wait_for(rig.ticks.get(), 1.0) == 0.25
    rig.presenter.update(view(S.IDLE))  # an update wakes the loop before the tick fires
    await _until(lambda: rig.surface.shown[1] == RENDERER.render(AgentFace("claude", "a1", S.IDLE)))


async def test_run_loop_real_tick() -> None:
    surface, clock = FakeSurface(), FakeClock()
    slept: list[float] = []

    async def sleep(seconds: float) -> None:
        slept.append(seconds)
        clock.now += seconds

    presenter = DeckPresenter(
        surface, RENDERER, Animator(), layout=KeyLayout(exit_key=False), clock=clock, sleep=sleep
    )
    presenter.update(view(S.WORKING))
    await presenter.start()
    face = AgentFace("claude", "a1", S.WORKING)
    await _until(lambda: surface.shown.get(0) == RENDERER.render(face, Effect.SPIN, 2))
    await presenter.stop()
    assert slept and set(slept) == {0.25}
