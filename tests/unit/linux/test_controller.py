from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import pytest

from herdr_core.animation import Animator
from herdr_core.faces import EmptyFace, ExitFace, KeyLayout, LauncherFace, OfflineFace
from herdr_core.models import AgentStatus
from herdr_core.presenter import DeckPresenter
from herdr_core.render import KeyRenderer
from herdr_core.session import HerdrSession
from linux.config import HomeKey
from linux.controller import DockController, Mode
from linux.device import ButtonPressed, KeyPressed
from tests.fakes.in_memory import InMemoryHerdr, RecordingRaiser
from tests.fakes.surface import FakeClock, FakeSurface

RENDERER = KeyRenderer()
HOME = (
    HomeKey(1, "herdr", herdr=True, symbol="◐"),
    HomeKey(2, "Firefox", app="firefox"),
    HomeKey(3, "Build", run="make"),
    HomeKey(4, "Browser", app="chromium", focus="^chromium$"),
    HomeKey(5, "Logs", run="foot journalctl -f", focus="^logs$"),
    HomeKey(6, "Zed", focus="zed"),
)


@dataclass
class FakeFocuser:
    existing: set[str] = field(default_factory=set)
    asked: list[str] = field(default_factory=list)

    async def focus_matching(self, pattern: str) -> bool:
        self.asked.append(pattern)
        return pattern in self.existing


@dataclass
class FakeLauncher:
    runs: list[str] = field(default_factory=list)
    apps: list[str] = field(default_factory=list)

    def run(self, command: str) -> None:
        self.runs.append(command)

    def app(self, app: str) -> None:
        self.apps.append(app)


@dataclass
class Rig:
    surface: FakeSurface
    herdr: InMemoryHerdr
    launcher: FakeLauncher
    raiser: RecordingRaiser
    session: HerdrSession
    presenter: DeckPresenter
    controller: DockController
    focuser: FakeFocuser

    async def settle(self) -> None:
        """Let the session and presenter tasks run until the keys stop changing."""
        import asyncio

        for _ in range(50):
            await asyncio.sleep(0)
        await self.presenter.push()


@pytest.fixture
async def rig() -> AsyncIterator[Rig]:
    surface, herdr = FakeSurface(), InMemoryHerdr()
    launcher, raiser, focuser = FakeLauncher(), RecordingRaiser(), FakeFocuser({"^chromium$"})
    layout = KeyLayout(exit_key=True)

    async def no_sleep(_: float) -> None:
        import asyncio

        await asyncio.Event().wait()

    presenter = DeckPresenter(
        surface, RENDERER, Animator(), layout=layout, clock=FakeClock(), sleep=no_sleep
    )
    session = HerdrSession(herdr, herdr, raiser, capacity=14, on_view=presenter.update)
    controller = DockController(
        surface,
        RENDERER,
        HOME,
        launcher,
        session,
        presenter,
        layout=layout,
        buttons={"left": "herdr", "middle": "none", "right": "page"},
        focuser=focuser,
    )
    yield Rig(surface, herdr, launcher, raiser, session, presenter, controller, focuser)
    await controller.shutdown()


def png(face: object) -> bytes:
    return RENDERER.render(face)  # type: ignore[arg-type]


async def test_home_page(rig: Rig) -> None:
    await rig.controller.draw_home()
    assert rig.surface.shown[0] == png(LauncherFace("herdr", "◐"))
    assert rig.surface.shown[1] == png(LauncherFace("Firefox"))
    assert rig.surface.shown[14] == png(EmptyFace())
    rig.surface.calls.clear()
    await rig.controller.draw_home()
    assert rig.surface.calls == []  # unchanged keys are not resent
    await rig.controller.redraw()
    assert len(rig.surface.calls) == 15


async def test_home_keys_launch(rig: Rig) -> None:
    await rig.controller.handle(KeyPressed(1))
    await rig.controller.handle(KeyPressed(2))
    await rig.controller.handle(KeyPressed(9))  # unassigned
    assert rig.launcher.apps == ["firefox"]
    assert rig.launcher.runs == ["make"]
    assert rig.controller.mode is Mode.HOME


async def test_focus_existing_window_or_launch(rig: Rig) -> None:
    await rig.controller.handle(KeyPressed(3))  # chromium window exists → focused
    assert rig.launcher.apps == []
    await rig.controller.handle(KeyPressed(4))  # no logs window → run
    assert rig.launcher.runs == ["foot journalctl -f"]
    await rig.controller.handle(KeyPressed(5))  # focus-only key without a window → nothing
    assert rig.focuser.asked == ["^chromium$", "^logs$", "zed"]
    assert rig.launcher.apps == [] and rig.launcher.runs == ["foot journalctl -f"]
    rig.focuser.existing.clear()
    await rig.controller.handle(KeyPressed(3))  # no chromium window → launch
    assert rig.launcher.apps == ["chromium"]


async def test_enter_and_exit_herdr_mode(rig: Rig) -> None:
    rig.herdr.add("w1:p1", AgentStatus.BLOCKED)
    await rig.controller.draw_home()
    await rig.controller.handle(KeyPressed(0))
    assert rig.controller.mode is Mode.HERDR
    await rig.settle()
    assert rig.surface.shown[0] == png(ExitFace((AgentStatus.BLOCKED,)))

    await rig.controller.handle(KeyPressed(1))  # first agent key
    assert rig.herdr.focus_calls == ["w1:p1"]
    assert rig.raiser.raised == ["w1:p1"]

    await rig.controller.handle(KeyPressed(0))  # Exit
    assert rig.controller.mode is Mode.HOME
    assert not rig.session.running
    assert rig.surface.shown[0] == png(LauncherFace("herdr", "◐"))
    assert rig.surface.shown[1] == png(LauncherFace("Firefox"))


async def test_exit_never_shows_offline_faces(rig: Rig) -> None:
    rig.herdr.add("w1:p1")
    await rig.controller.enter_herdr()
    await rig.settle()
    rig.surface.shown.clear()
    await rig.controller.exit_herdr()
    assert png(OfflineFace()) not in rig.surface.shown.values()


async def test_enter_and_exit_are_idempotent(rig: Rig) -> None:
    await rig.controller.exit_herdr()
    assert rig.surface.calls == []
    await rig.controller.enter_herdr()
    await rig.controller.enter_herdr()
    assert len(rig.herdr.streams) <= 1


async def test_buttons(rig: Rig) -> None:
    for n in range(1, 17):
        rig.herdr.add(f"w{n}:p1")
    await rig.controller.handle(ButtonPressed("right"))  # page does nothing on home
    await rig.controller.handle(ButtonPressed("middle"))  # none
    assert rig.controller.mode is Mode.HOME
    await rig.controller.handle(ButtonPressed("left"))
    assert rig.controller.mode is Mode.HERDR
    await rig.settle()
    assert rig.session.view.page.page == 0
    await rig.controller.handle(ButtonPressed("right"))
    assert rig.session.view.page.page == 1
    await rig.controller.handle(ButtonPressed("unknown"))
    await rig.controller.handle(ButtonPressed("left"))
    assert rig.controller.mode is Mode.HOME


async def test_redraw_in_herdr_mode_invalidates(rig: Rig) -> None:
    rig.herdr.add("w1:p1")
    await rig.controller.enter_herdr()
    await rig.settle()
    rig.surface.calls.clear()
    await rig.controller.redraw()
    await rig.presenter.push()
    assert len(rig.surface.calls) == 15


async def test_entering_herdr_mode_raises_the_herdr_window(rig: Rig) -> None:
    raised: list[str] = []

    async def raise_herdr() -> None:
        raised.append("herdr")
        if len(raised) == 2:
            raise RuntimeError("hyprctl gone")

    rig.controller._on_enter = raise_herdr
    await rig.controller.handle(KeyPressed(0))
    assert raised == ["herdr"]
    await rig.controller.handle(KeyPressed(0))  # exit
    await rig.controller.handle(ButtonPressed("left"))  # enter again; raiser fails, mode still on
    assert raised == ["herdr", "herdr"]
    assert rig.controller.mode is Mode.HERDR


async def test_failing_focus_check_still_launches(rig: Rig) -> None:
    async def broken(pattern: str) -> bool:
        raise RuntimeError("hyprctl exploded")

    rig.focuser.focus_matching = broken  # type: ignore[method-assign]
    await rig.controller.handle(KeyPressed(3))
    assert rig.launcher.apps == ["chromium"]


async def test_widget_keys_and_tick(rig: Rig) -> None:
    from herdr_core.faces import ClockFace

    class Clock:
        text = "14:07"

        def face(self) -> ClockFace:
            return ClockFace(self.text)

        def press(self) -> bool:
            return False

        def advance(self) -> None:
            pass

    clock = Clock()
    rig.controller._widgets = {4: clock}
    await rig.controller.draw_home()
    assert rig.surface.shown[4] == png(ClockFace("14:07"))
    rig.surface.calls.clear()
    await rig.controller.tick()
    assert rig.surface.calls == []  # unchanged: nothing sent
    clock.text = "14:08"
    await rig.controller.tick()
    assert rig.surface.calls == [4]  # only the clock key
    await rig.controller.enter_herdr()
    rig.surface.calls.clear()
    clock.text = "14:09"
    await rig.controller.tick()  # Herdr mode: the home page isn't visible
    assert 4 not in rig.surface.calls


async def test_blank_turns_off_ignores_presses_and_restores(rig: Rig) -> None:
    screen: list[bool] = []

    class Screen:
        async def set_screen(self, on: bool) -> None:
            screen.append(on)

    rig.controller._screen = Screen()
    await rig.controller.draw_home()
    await rig.controller.set_blank(True)
    await rig.controller.set_blank(True)  # no change: nothing happens
    assert screen == [False] and rig.controller.blank
    rig.surface.calls.clear()
    await rig.controller.handle(KeyPressed(2))  # stray press while locked
    await rig.controller.tick()
    await rig.controller.redraw()
    assert rig.launcher.runs == [] and rig.surface.calls == []
    await rig.controller.set_blank(False)
    assert screen == [False, True]
    assert len(rig.surface.calls) == 15  # home page fully redrawn


async def test_blank_in_herdr_mode_pauses_animation(rig: Rig) -> None:
    rig.herdr.add("w1:p1", AgentStatus.WORKING)
    await rig.controller.enter_herdr()
    await rig.settle()
    await rig.controller.set_blank(True)  # no screen port: still pauses the presenter
    assert rig.presenter._task is None
    await rig.controller.set_blank(False)
    assert rig.presenter._task is not None


async def test_pressable_widgets_toggle_and_redraw_immediately(rig: Rig) -> None:
    from herdr_core.faces import TimerFace
    from linux.widgets import TimerWidget

    now = [100.0]
    timer = TimerWidget(clock=lambda: now[0])
    rig.controller._widgets = {9: timer}
    await rig.controller.draw_home()
    assert rig.surface.shown[9] == png(TimerFace())
    await rig.controller.handle(KeyPressed(9))
    assert timer.running
    assert rig.surface.shown[9] == png(TimerFace("0:00", pulse=True))  # drawn right away
    now[0] += 61
    await rig.controller.tick()
    assert rig.surface.shown[9] == png(TimerFace("1:01", pulse=False))
    await rig.controller.handle(KeyPressed(9))
    assert not timer.running and rig.surface.shown[9] == png(TimerFace())
    assert rig.launcher.runs == [] and rig.launcher.apps == []


async def test_widgets_advance_in_herdr_mode_and_failures_are_contained(
    rig: Rig, caplog: pytest.LogCaptureFixture
) -> None:
    advanced: list[str] = []

    class Ticking:
        def face(self) -> EmptyFace:
            return EmptyFace()

        def press(self) -> bool:
            return False

        def advance(self) -> None:
            advanced.append("x")
            raise RuntimeError("boom")

    rig.controller._widgets = {9: Ticking()}
    await rig.controller.enter_herdr()
    await rig.controller.tick()
    assert advanced == ["x"]  # pomodoro notifications keep coming in Herdr mode
    assert "advancing a widget failed" in caplog.text
