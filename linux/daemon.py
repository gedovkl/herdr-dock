"""herdr-dock Linux daemon: `python -m linux.daemon`. Composition root for the M18 front end."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import os
import signal
import sys
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path

from herdr_core.animation import Animator
from herdr_core.client import HerdrSocketClient
from herdr_core.config import Config, ConfigError, RaiseConfig, load_config
from herdr_core.faces import KeyLayout
from herdr_core.ports import Raiser, Sleep
from herdr_core.presenter import DeckPresenter
from herdr_core.raise_window import raiser_from_config
from herdr_core.render import KeyRenderer, Palette
from herdr_core.session import HerdrSession
from herdr_core.socket_path import resolve_socket_path
from linux.config import HERDR_WINDOW, KEY_COUNT, HomeKey, LinuxConfig, load_linux_config
from linux.controller import DockController
from linux.device import DeviceInput, M18Device, StreamDockSdk
from linux.hyprland import HerdrWindowRaiser, WindowFocuser
from linux.launcher import ShellLauncher
from linux.power import LockMonitor, SleepMonitor
from linux.widgets import (
    ClockWidget,
    PomodoroWidget,
    TimerWidget,
    WeatherWidget,
    Widget,
    desktop_notify,
)

log = logging.getLogger("herdr_dock")


class _Redraw:
    """Queue item: repaint the dock (after a replug), in order with key presses."""


_REDRAW = _Redraw()


class _Tick:
    """Queue item: refresh live home keys (clock, weather)."""


_TICK = _Tick()


class _Blank:
    """Queue item: turn the dock off (True) or on (False); `done` resolves once applied."""

    def __init__(self, blank: bool, done: asyncio.Future[None] | None = None) -> None:
        self.blank = blank
        self.done = done

    def __repr__(self) -> str:
        return f"_Blank({self.blank})"


def default_workdir(env: dict[str, str] | os._Environ[str] = os.environ) -> Path:
    base = env.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()
    return Path(base) / "herdr-dock"


def build_widgets(home: tuple[HomeKey, ...]) -> dict[int, Widget]:
    widgets: dict[int, Widget] = {}
    for key in home:
        if key.widget == "clock":
            widgets[key.index] = ClockWidget(key.time_format, key.date_format)
        elif key.widget == "pomodoro":
            widgets[key.index] = PomodoroWidget(
                key.work_minutes * 60,
                key.rest_minutes * 60,
                notify=desktop_notify if key.notify else None,
            )
        elif key.widget == "timer":
            widgets[key.index] = TimerWidget()
        elif key.widget == "weather":
            assert key.latitude is not None and key.longitude is not None  # validated by config
            widgets[key.index] = WeatherWidget(
                key.latitude,
                key.longitude,
                units=key.units,
                place=key.place,
                refresh_seconds=key.refresh_minutes * 60,
            )
    return widgets


def linux_raiser(config: RaiseConfig) -> Raiser:
    """`herdr-window` (or nothing configured) focuses the herdr client's window on Hyprland."""
    if config.enabled and config.linux.strip() in ("", HERDR_WINDOW):
        return HerdrWindowRaiser()
    return raiser_from_config(config, platform="linux")


class Daemon:
    """Wires device ↔ controller and keeps the device connected across replugs."""

    def __init__(
        self,
        device: M18Device,
        controller: DockController,
        *,
        poll_seconds: float,
        alive_seconds: float = 0.25,
        widgets: dict[int, Widget] | None = None,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._device = device
        self._controller = controller
        self._poll = poll_seconds
        self._alive = alive_seconds
        self._widgets = dict(widgets or {})
        self._sleep = sleep
        # Key presses and redraws share one queue so they never run concurrently.
        self._inputs: asyncio.Queue[DeviceInput | _Redraw | _Tick | _Blank] = asyncio.Queue()
        self._monitors: list[LockMonitor | SleepMonitor] = []
        self._locked = self._asleep = False
        self._blank_when_locked = self._blank_on_sleep = False
        self._last_error = ""
        self._announced_wait = False

    def watch_power(
        self,
        *,
        blank_when_locked: bool,
        blank_on_sleep: bool,
        lock_poll_seconds: float = 1.0,
        lock: LockMonitor | None = None,
        sleep: SleepMonitor | None = None,
    ) -> None:
        """Turn the dock off while the session is locked and/or the machine sleeps."""
        self._blank_when_locked, self._blank_on_sleep = blank_when_locked, blank_on_sleep
        if blank_when_locked:
            self._monitors.append(lock or LockMonitor(self._on_locked, interval=lock_poll_seconds))
        if blank_on_sleep:
            self._monitors.append(sleep or SleepMonitor(self._on_asleep))

    def _on_locked(self, locked: bool) -> None:
        self._locked = locked
        self._queue_blank()

    async def _on_asleep(self, asleep: bool) -> None:
        """Returns once the dock state is applied, so the sleep monitor can release suspend."""
        self._asleep = asleep
        done: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self._queue_blank(done)
        await done

    def _queue_blank(self, done: asyncio.Future[None] | None = None) -> None:
        blank = (self._locked and self._blank_when_locked) or (
            self._asleep and self._blank_on_sleep
        )
        self._inputs.put_nowait(_Blank(blank, done))

    def on_input(self, event: DeviceInput) -> None:
        """Device callback (already on the event loop)."""
        self._inputs.put_nowait(event)

    async def run(self, stop: asyncio.Event) -> None:
        tasks = [
            asyncio.create_task(self._handle_inputs(), name="inputs"),
            asyncio.create_task(self._watch_device(), name="device-watch"),
        ]
        if self._widgets:
            tasks.append(asyncio.create_task(self._tick_widgets(), name="widget-tick"))
        for monitor in self._monitors:
            tasks.append(asyncio.create_task(monitor.run(), name=type(monitor).__name__))
        for widget in self._widgets.values():
            if isinstance(widget, WeatherWidget):
                tasks.append(asyncio.create_task(self._refresh_weather(widget), name="weather"))
        try:
            await stop.wait()
        finally:
            for task in tasks:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            with contextlib.suppress(Exception):
                await self._controller.shutdown()
            with contextlib.suppress(Exception):
                await self._device.clear()
            await self._device.shutdown()

    async def _handle_inputs(self) -> None:
        while True:
            event = await self._inputs.get()
            try:
                if isinstance(event, _Redraw):
                    await self._controller.redraw()
                elif isinstance(event, _Tick):
                    await self._controller.tick()
                elif isinstance(event, _Blank):
                    try:
                        await self._controller.set_blank(event.blank)
                    finally:
                        if event.done is not None and not event.done.done():
                            event.done.set_result(None)  # sleep may proceed now
                else:
                    await self._controller.handle(event)
            except Exception:
                log.exception("handling %s failed", event)

    async def _tick_widgets(self) -> None:
        """Once a second; the controller only sends keys whose text actually changed."""
        while True:
            self._inputs.put_nowait(_TICK)
            await self._sleep(1.0)

    async def _refresh_weather(self, widget: WeatherWidget) -> None:
        """Never raises: a failed fetch keeps the last reading and retries sooner."""
        while True:
            ok = await widget.refresh()
            if ok:
                self._inputs.put_nowait(_TICK)
            await self._sleep(widget.refresh_seconds if ok else widget.RETRY_SECONDS)

    async def _watch_device(self) -> None:
        """Connect when the M18 appears; notice an unplug within `alive_seconds`.

        Never raises: a missing, unplugged or inaccessible dock is a normal state, logged once.
        """
        while True:
            try:
                if self._device.connected:
                    await self._check_alive()
                    await self._sleep(self._alive)
                    continue
                await self._try_connect()
            except Exception as exc:  # keep watching whatever the SDK throws
                self._log_once(f"M18: {exc}")
            await self._sleep(self._poll)

    async def _check_alive(self) -> None:
        if not self._device.alive():
            await self._device.disconnect(removed=True)

    async def _try_connect(self) -> None:
        if await self._device.connect():
            self._last_error, self._announced_wait = "", False
            self._inputs.put_nowait(_REDRAW)
        elif not self._announced_wait:
            log.info("waiting for the M18 to be plugged in")
            self._announced_wait = True

    def _log_once(self, message: str) -> None:
        if message != self._last_error:
            log.error("%s", message)
            self._last_error = message


def build(
    config: Config, linux: LinuxConfig, socket: Path, workdir: Path
) -> tuple[Daemon, DockController]:
    renderer = KeyRenderer(Palette().with_status_colors(config.colors), size=64)
    widgets = build_widgets(linux.home)
    layout = KeyLayout(exit_key=True)
    holder: list[Callable[[DeviceInput], None]] = []
    device = M18Device(
        StreamDockSdk(),
        linux.device_ids,
        workdir,
        lambda event: holder[0](event),
        brightness=linux.brightness,
    )
    presenter = DeckPresenter(
        device, renderer, Animator(config.animation), layout=layout, label=config.label
    )
    client = HerdrSocketClient(socket)
    session = HerdrSession(
        client,
        client,
        linux_raiser(config.raise_window),
        capacity=layout.session_capacity(KEY_COUNT),
        on_view=presenter.update,
        resync_interval=config.resync_seconds,
    )
    controller = DockController(
        device,
        renderer,
        linux.home,
        ShellLauncher(linux.app_launcher),
        session,
        presenter,
        layout=layout,
        buttons=dict(linux.buttons),
        focuser=WindowFocuser(),
        on_enter=HerdrWindowRaiser().raise_herdr_window if linux.focus_herdr_on_enter else None,
        widgets=widgets,
        screen=device,
    )
    daemon = Daemon(device, controller, poll_seconds=linux.poll_seconds, widgets=widgets)
    daemon.watch_power(
        blank_when_locked=linux.blank_when_locked,
        blank_on_sleep=linux.blank_on_sleep,
        lock_poll_seconds=linux.lock_poll_seconds,
    )
    holder.append(daemon.on_input)
    return daemon, controller


async def serve(daemon: Daemon) -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    await daemon.run(stop)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="herdr-dock", description="herdr agents on a StreamDock M18"
    )
    parser.add_argument("--config", type=Path, help="config file (default: ~/.config/herdr-dock)")
    parser.add_argument("--socket", help="herdr socket path (default: auto-detect)")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("PIL").setLevel(logging.INFO)  # chunk-level PNG debug noise
    try:
        config = load_config(args.config)
        linux = load_linux_config(args.config)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    # Absolute now: the device later changes the working directory for the SDK.
    socket = resolve_socket_path(
        args.socket or config.herdr_socket, os.environ, Path.home()
    ).absolute()
    log.info("herdr socket: %s", socket)
    daemon, _ = build(config, linux, socket, default_workdir())
    asyncio.run(serve(daemon))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
