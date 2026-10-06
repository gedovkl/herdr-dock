from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from herdr_core.config import Config, RaiseConfig
from herdr_core.raise_window import CommandRaiser, NullRaiser
from linux import daemon as daemon_module
from linux.config import LinuxConfig
from linux.controller import Mode
from linux.daemon import Daemon, build, default_workdir, linux_raiser, main
from linux.device import ButtonPressed, DevicePermissionError, KeyPressed
from linux.hyprland import HerdrWindowRaiser
from tests.fakes.sdk import FakeSdk


def test_default_workdir() -> None:
    assert default_workdir({"XDG_RUNTIME_DIR": "/run/user/1"}) == Path("/run/user/1/herdr-dock")
    assert default_workdir({}).name == "herdr-dock"


def test_linux_raiser_choice() -> None:
    assert isinstance(linux_raiser(RaiseConfig()), HerdrWindowRaiser)
    assert isinstance(linux_raiser(RaiseConfig(linux="herdr-window")), HerdrWindowRaiser)
    assert isinstance(linux_raiser(RaiseConfig(linux="wmctrl -a foot")), CommandRaiser)
    assert isinstance(linux_raiser(RaiseConfig(enabled=False)), NullRaiser)


@pytest.fixture
def built(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Daemon, FakeSdk]:
    cwd = os.getcwd()
    sdk = FakeSdk()
    monkeypatch.setattr(daemon_module, "StreamDockSdk", lambda: sdk)
    monkeypatch.setattr("linux.device.os.access", lambda path, mode: True)
    linux = LinuxConfig(poll_seconds=0.01, blank_when_locked=False, blank_on_sleep=False)
    daemon, _ = build(Config(), linux, tmp_path / "h.sock", tmp_path)
    daemon._device._exists = lambda path: bool(sdk.devices)  # node exists while plugged in
    yield daemon, sdk
    os.chdir(cwd)


async def _until(predicate: object, timeout: float = 2.0) -> None:
    async def poll() -> None:
        while not predicate():  # type: ignore[operator]
            await asyncio.sleep(0.005)

    await asyncio.wait_for(poll(), timeout)


async def test_connects_draws_home_handles_presses_and_cleans_up(
    built: tuple[Daemon, FakeSdk], caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level("INFO")
    daemon, sdk = built
    sdk.plug(0x5548, 0x1000)
    stop = asyncio.Event()
    task = asyncio.create_task(daemon.run(stop))
    await _until(lambda: sdk.created and 1 in sdk.created[0].images)
    controller = daemon._controller
    daemon.on_input(KeyPressed(0))  # herdr key → Herdr mode (herdr is unreachable: offline)
    await _until(lambda: controller.mode is Mode.HERDR)
    daemon.on_input(ButtonPressed("left"))
    await _until(lambda: controller.mode is Mode.HOME)
    stop.set()
    await task
    assert sdk.created[0].calls[-3:] == [("clear",), ("refresh",), ("close",)]
    assert "waiting for the M18" not in caplog.text


async def test_replug_redraws(
    built: tuple[Daemon, FakeSdk], caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level("INFO")
    daemon, sdk = built
    sdk.plug(0x5548, 0x1000)
    stop = asyncio.Event()
    task = asyncio.create_task(daemon.run(stop))
    await _until(lambda: len(sdk.created) == 1 and sdk.created[0].images)
    sdk.unplug()
    await _until(lambda: ("close-removed",) in sdk.created[0].calls)  # no write to a removed device
    await _until(lambda: "waiting for the M18" in caplog.text)
    sdk.plug(0x5548, 0x1000)
    await _until(lambda: len(sdk.created) == 2 and len(sdk.created[1].images) == 15)
    stop.set()
    await task
    assert caplog.text.count("waiting for the M18") == 1  # one message per unplug


async def test_device_errors_are_logged_once(
    built: tuple[Daemon, FakeSdk], monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    daemon, sdk = built
    sdk.plug(0x5548, 0x1000)
    calls = []

    async def denied() -> bool:
        calls.append(1)
        raise DevicePermissionError("no access to /dev/hidraw7")

    monkeypatch.setattr(daemon._device, "connect", denied)
    stop = asyncio.Event()
    task = asyncio.create_task(daemon.run(stop))
    await _until(lambda: len(calls) >= 3)
    stop.set()
    await task
    assert caplog.text.count("no access to /dev/hidraw7") == 1


async def test_input_handler_errors_do_not_stop_the_daemon(
    built: tuple[Daemon, FakeSdk], monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    daemon, _ = built
    handled = []

    async def flaky(event: object) -> None:
        handled.append(event)
        if len(handled) == 1:
            raise RuntimeError("boom")

    monkeypatch.setattr(daemon._controller, "handle", flaky)
    stop = asyncio.Event()
    task = asyncio.create_task(daemon.run(stop))
    daemon.on_input(KeyPressed(1))
    daemon.on_input(KeyPressed(2))
    await _until(lambda: len(handled) == 2)
    stop.set()
    await task
    assert "handling KeyPressed(index=1) failed" in caplog.text


def test_main_rejects_bad_config(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config = tmp_path / "c.toml"
    config.write_text("[linux]\nbrightness = 900\n")
    assert main(["--config", str(config)]) == 2
    assert "brightness" in capsys.readouterr().err


def test_main_runs_until_stopped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    served = []

    async def fake_serve(daemon: Daemon) -> None:
        served.append(daemon)

    monkeypatch.setattr(daemon_module, "serve", fake_serve)
    monkeypatch.setattr(daemon_module, "default_workdir", lambda: tmp_path)
    config = tmp_path / "c.toml"
    config.write_text(
        "[linux]\nbrightness = 30\nblank_when_locked = false\nblank_on_sleep = false\n"
        '[[home]]\nkey = 1\nlabel = "h"\nherdr = true\n'
    )
    cwd = os.getcwd()
    try:
        assert main(["--config", str(config), "--socket", "rel/herdr.sock", "-v"]) == 0
    finally:
        os.chdir(cwd)
    assert len(served) == 1
    client = served[0]._controller._session._api  # type: ignore[attr-defined]
    assert client.socket_path == Path(cwd) / "rel/herdr.sock"  # absolute before any chdir


async def test_serve_stops_on_signal(built: tuple[Daemon, FakeSdk]) -> None:
    import signal

    daemon, _ = built
    task = asyncio.create_task(daemon_module.serve(daemon))
    await asyncio.sleep(0.02)
    os.kill(os.getpid(), signal.SIGTERM)
    await asyncio.wait_for(task, 2.0)


def test_focus_on_enter_wiring(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cwd = os.getcwd()
    try:
        _, on = build(Config(), LinuxConfig(), tmp_path / "h.sock", tmp_path)
        _, off = build(Config(), LinuxConfig(focus_herdr_on_enter=False), tmp_path / "h", tmp_path)
    finally:
        os.chdir(cwd)
    assert on._on_enter is not None
    assert off._on_enter is None


async def test_replug_redraw_never_interleaves_with_key_handling(
    built: tuple[Daemon, FakeSdk], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A home redraw and a herdr-key press must not run concurrently (keys would mix)."""
    daemon, sdk = built
    log: list[str] = []
    release = asyncio.Event()

    async def slow_redraw() -> None:
        log.append("redraw-start")
        await release.wait()
        log.append("redraw-end")

    async def handle(event: object) -> None:
        log.append("press")

    monkeypatch.setattr(daemon._controller, "redraw", slow_redraw)
    monkeypatch.setattr(daemon._controller, "handle", handle)
    sdk.plug(0x5548, 0x1000)
    stop = asyncio.Event()
    task = asyncio.create_task(daemon.run(stop))
    await _until(lambda: "redraw-start" in log)
    daemon.on_input(KeyPressed(0))
    for _ in range(20):
        await asyncio.sleep(0)
    assert log == ["redraw-start"]  # the press waits for the redraw
    release.set()
    await _until(lambda: log == ["redraw-start", "redraw-end", "press"])
    stop.set()
    await task


def test_build_widgets() -> None:
    from linux.config import HomeKey
    from linux.daemon import build_widgets
    from linux.widgets import ClockWidget, WeatherWidget

    widgets = build_widgets(
        (
            HomeKey(1, "h", herdr=True),
            HomeKey(5, "", widget="clock"),
            HomeKey(10, "", widget="weather", latitude=1.0, longitude=2.0, refresh_minutes=2),
            HomeKey(13, "", widget="pomodoro", work_minutes=50, rest_minutes=10),
            HomeKey(14, "", widget="pomodoro", notify=False),
            HomeKey(15, "", widget="timer"),
        )
    )
    assert set(widgets) == {4, 9, 12, 13, 14}
    from linux.widgets import PomodoroWidget, TimerWidget, desktop_notify

    assert isinstance(widgets[12], PomodoroWidget) and widgets[12]._work == 3000
    assert widgets[12]._notify is desktop_notify and widgets[13]._notify is None  # type: ignore[union-attr]
    assert isinstance(widgets[14], TimerWidget)
    assert isinstance(widgets[4], ClockWidget)
    assert isinstance(widgets[9], WeatherWidget) and widgets[9].refresh_seconds == 120


async def test_widget_tasks_tick_and_refresh_weather(built: tuple[Daemon, FakeSdk]) -> None:
    from linux.widgets import WeatherWidget

    daemon, _ = built
    sleeps: list[float] = []
    ticks: list[int] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        await asyncio.sleep(0)

    cloudy = {"current": {"temperature_2m": 10, "weather_code": 3}}
    responses: list[object] = [OSError("offline"), cloudy]

    async def fetch(url: str) -> object:
        response = responses.pop(0) if responses else cloudy
        if isinstance(response, Exception):
            raise response
        return response

    weather = WeatherWidget(1, 2, refresh_seconds=600, fetch=fetch)
    daemon._widgets = {0: weather}
    daemon._sleep = sleep

    async def tick() -> None:
        ticks.append(1)

    daemon._controller.tick = tick  # type: ignore[method-assign]
    stop = asyncio.Event()
    task = asyncio.create_task(daemon.run(stop))
    await _until(lambda: 600 in sleeps and 60 in sleeps and len(ticks) >= 2)
    stop.set()
    await task
    assert sleeps.index(60) < sleeps.index(600)  # failed fetch retries sooner
    assert weather.face().temperature == "10°C"  # type: ignore[union-attr]


async def test_lock_and_sleep_turn_the_dock_off_and_on(built: tuple[Daemon, FakeSdk]) -> None:
    daemon, _ = built
    blanks: list[bool] = []

    async def set_blank(blank: bool) -> None:
        blanks.append(blank)

    class Idle:
        async def run(self) -> None:
            await asyncio.Event().wait()

    daemon._controller.set_blank = set_blank  # type: ignore[method-assign]
    daemon.watch_power(
        blank_when_locked=True,
        blank_on_sleep=True,
        lock=Idle(),
        sleep=Idle(),  # type: ignore[arg-type]
    )
    stop = asyncio.Event()
    task = asyncio.create_task(daemon.run(stop))
    daemon._on_locked(True)
    await daemon._on_asleep(True)  # returns only once the blank was applied
    assert blanks == [True, True]
    daemon._on_locked(False)  # still asleep → stays off
    await daemon._on_asleep(False)  # awake and unlocked → on
    await _until(lambda: len(blanks) == 4)
    stop.set()
    await task
    assert blanks == [True, True, True, False]


async def test_blanking_options_can_be_switched_off(built: tuple[Daemon, FakeSdk]) -> None:
    daemon, _ = built
    daemon.watch_power(blank_when_locked=False, blank_on_sleep=True)
    assert [type(m).__name__ for m in daemon._monitors] == ["SleepMonitor"]
    daemon._on_locked(True)
    assert daemon._inputs.get_nowait().blank is False  # type: ignore[union-attr]


def test_build_wires_power_monitors_from_config(tmp_path: Path) -> None:
    cwd = os.getcwd()
    try:
        daemon, _ = build(Config(), LinuxConfig(lock_poll_seconds=2), tmp_path / "s", tmp_path)
    finally:
        os.chdir(cwd)
    assert sorted(type(m).__name__ for m in daemon._monitors) == ["LockMonitor", "SleepMonitor"]
