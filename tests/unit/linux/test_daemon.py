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
    daemon, _ = build(Config(), LinuxConfig(poll_seconds=0.01), tmp_path / "h.sock", tmp_path)
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
    config.write_text('[linux]\nbrightness = 30\n[[home]]\nkey = 1\nlabel = "h"\nherdr = true\n')
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
